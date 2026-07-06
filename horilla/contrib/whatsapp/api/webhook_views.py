"""
Meta WhatsApp Cloud API webhook receiver.
"""

# Standard library imports
import hmac
import json
import logging
import mimetypes

# Third-party imports (Django)
from django.core.files.base import ContentFile
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

# First party imports (Horilla)
from horilla.web import HttpResponse, JsonResponse

# Local imports
from ..bot import route_bot_message
from ..models import (
    MESSAGE_DIRECTION_IN,
    MESSAGE_DIRECTION_OUT,
    MESSAGE_STATUS_DELIVERED,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_READ,
    MESSAGE_STATUS_RECEIVED,
    MESSAGE_STATUS_SENT,
    MESSAGE_TYPE_CHOICES,
    WhatsAppAccount,
    WhatsAppAttachment,
    WhatsAppConversation,
    WhatsAppMessage,
)
from ..services import WhatsAppAPIError, WhatsAppCloudAPIClient

_VALID_MESSAGE_TYPES = {choice[0] for choice in MESSAGE_TYPE_CHOICES}

logger = logging.getLogger(__name__)

_STATUS_MAP = {
    "sent": MESSAGE_STATUS_SENT,
    "delivered": MESSAGE_STATUS_DELIVERED,
    "read": MESSAGE_STATUS_READ,
    "failed": MESSAGE_STATUS_FAILED,
}


@method_decorator(csrf_exempt, name="dispatch")
class WhatsAppWebhookView(View):
    """
    Receive Meta WhatsApp Cloud API webhook calls.

    GET handles the subscription verification handshake (hub.challenge).
    POST handles inbound messages and message status updates.

    No LoginRequiredMixin — this endpoint is called by Meta, not a user.
    """

    def get(self, request, *args, **kwargs):
        """Verify the webhook subscription against a connected account's verify token."""
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token", "")
        challenge = request.GET.get("hub.challenge", "")

        if mode != "subscribe":
            return HttpResponse(status=400)

        for account in WhatsAppAccount.objects.filter(is_active=True).exclude(
            webhook_verify_token__isnull=True
        ):
            stored_token = account.get_decrypted_webhook_verify_token() or ""
            if stored_token and hmac.compare_digest(stored_token, token):
                return HttpResponse(challenge, content_type="text/plain")

        logger.warning("WhatsApp webhook verification rejected: token mismatch")
        return HttpResponse(status=403)

    def post(self, request, *args, **kwargs):
        """Process inbound messages and status updates from Meta."""
        try:
            payload = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return HttpResponse(status=400)

        # TEMP-DEBUG-WEBHOOK: summary only (no message text); remove after diagnosing.
        try:
            summary = []
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    summary.append(
                        {
                            "field": change.get("field"),
                            "messages": [
                                m.get("type") for m in value.get("messages", [])
                            ],
                            "statuses": [
                                f"{st.get('status')}:{str(st.get('id'))[-8:]}"
                                for st in value.get("statuses", [])
                            ],
                            "phone_number_id": value.get("metadata", {}).get(
                                "phone_number_id"
                            ),
                        }
                    )
            with open(
                "/tmp/claude-1000/-home-cybrosys-Horilla-whatsapp/80b9e263-771f-4556-af48-53db23957cd8/scratchpad/webhook_debug.log",
                "a",
                encoding="utf-8",
            ) as debug_file:
                debug_file.write(
                    f"{timezone.now().isoformat()} {json.dumps(summary)}\n"
                )
        except Exception:  # pylint: disable=broad-except
            pass

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                phone_number_id = value.get("metadata", {}).get("phone_number_id")
                account = WhatsAppAccount.objects.filter(
                    phone_number_id=phone_number_id, is_active=True
                ).first()
                if not account:
                    logger.warning(
                        "WhatsApp webhook: no account found for phone_number_id=%s",
                        phone_number_id,
                    )
                    continue

                for message in value.get("messages", []):
                    self._handle_message(account, value, message)
                for status_update in value.get("statuses", []):
                    self._handle_status(status_update)

        return JsonResponse({"success": True})

    def _handle_message(self, account, value, message):
        """Store an inbound message and, if idle, hand it to the bot engine."""
        wa_message_id = message.get("id")
        if WhatsAppMessage.objects.filter(wa_message_id=wa_message_id).exists():
            return  # already processed (Meta retried the webhook)

        contact_number = message.get("from")
        contact_name = None
        for contact in value.get("contacts", []):
            if contact.get("wa_id") == contact_number:
                contact_name = contact.get("profile", {}).get("name")
                break

        conversation, _created = WhatsAppConversation.get_or_create_for(
            account, contact_number, contact_name
        )

        message_type = message.get("type", "text")
        body = None
        additional_info = None
        bot_reply_value = None
        flow_answers = None
        if message_type == "text":
            body = message.get("text", {}).get("body")
            bot_reply_value = body
        elif message_type in ("image", "document", "video", "audio"):
            body = message.get(message_type, {}).get("caption")
        elif message_type == "interactive":
            interactive = message.get("interactive", {})
            interactive_type = interactive.get("type")
            if interactive_type == "nfm_reply":
                body, additional_info = self._parse_nfm_reply(interactive)
                flow_answers = (
                    additional_info.get("flow_answers") if additional_info else None
                )
            elif interactive_type in ("button_reply", "list_reply"):
                selection = interactive.get(interactive_type, {})
                body = selection.get("title")
                bot_reply_value = selection.get("id") or body

        if flow_answers is not None and additional_info is not None:
            labels = self._flow_labels(account, conversation, flow_answers)
            if labels:
                additional_info["flow_labels"] = labels

        whatsapp_message = WhatsAppMessage.objects.create(
            conversation=conversation,
            direction=MESSAGE_DIRECTION_IN,
            message_type=(
                message_type if message_type in _VALID_MESSAGE_TYPES else "text"
            ),
            body=body,
            wa_message_id=wa_message_id,
            status=MESSAGE_STATUS_RECEIVED,
            additional_info=additional_info,
            company=account.company,
        )

        media_id = None
        if message_type in ("image", "document", "video", "audio"):
            media_id = message.get(message_type, {}).get("id")
        if media_id:
            mime_type = message.get(message_type, {}).get("mime_type")
            self._save_inbound_media(account, whatsapp_message, media_id, mime_type)

        if bot_reply_value:
            route_bot_message(account, conversation, bot_reply_value)
        elif flow_answers is not None:
            # A completed Meta WhatsApp Flow submission (nfm_reply) - route it
            # so a paused "send_meta_flow" Bot Rule node can resume with the
            # submitted answers. bot_reply_value stays unset here since a
            # Flow submission has no meaningful single "reply text/id".
            route_bot_message(account, conversation, body, flow_answers=flow_answers)

    def _save_inbound_media(self, account, whatsapp_message, media_id, mime_type):
        """
        Download an inbound attachment's bytes from the Cloud API and store
        it on a new WhatsAppAttachment, so it renders inline in the chat
        instead of just a media_id placeholder.
        """
        attachment = WhatsAppAttachment(
            message=whatsapp_message,
            media_id=media_id,
            mime_type=mime_type,
            company=account.company,
        )
        try:
            content = WhatsAppCloudAPIClient(account).download_media(media_id)
        except WhatsAppAPIError as exc:
            logger.error(
                "Failed to download WhatsApp media %s for message %s: %s",
                media_id,
                whatsapp_message.pk,
                exc,
            )
            return

        extension = mimetypes.guess_extension(mime_type or "") or ""
        filename = f"{media_id}{extension}"
        attachment.file.save(filename, ContentFile(content), save=False)
        attachment.file_size = len(content)
        attachment.save()

    def _flow_labels(self, account, conversation, answers):
        """Look up on-screen field labels for the Flow this reply answers."""
        from django.core.cache import cache

        token = (answers or {}).get("flow_token")
        if not token:
            return {}
        sent = (
            WhatsAppMessage.objects.filter(
                conversation=conversation,
                direction=MESSAGE_DIRECTION_OUT,
                additional_info__flow_token=token,
            )
            .order_by("-created_at")
            .first()
        )
        flow_id = (sent.additional_info or {}).get("flow_id") if sent else None
        if not flow_id:
            return {}
        cache_key = f"whatsapp_flow_labels_{flow_id}"
        labels = cache.get(cache_key)
        if labels is None:
            try:
                labels = WhatsAppCloudAPIClient(account).get_flow_field_labels(flow_id)
            except Exception:  # pylint: disable=broad-except
                logger.warning("Could not load labels for flow %s", flow_id)
                return {}
            cache.set(cache_key, labels, 3600)
        return labels

    def _parse_nfm_reply(self, interactive):
        """
        Parse a completed static WhatsApp Flow submission (an interactive
        message with type "nfm_reply") into (body, additional_info):
        - body: a human-readable rendering of the flat answers, so it
          displays reasonably in the existing chat bubble template.
        - additional_info: the raw decoded {"flow_answers": {...}} dict,
          stored on the WhatsAppMessage for anything that needs the raw data.
        """
        nfm_reply = interactive.get("nfm_reply", {})
        raw_response_json = nfm_reply.get("response_json") or "{}"
        try:
            answers = json.loads(raw_response_json)
        except json.JSONDecodeError:
            logger.warning("WhatsApp webhook: could not decode nfm_reply response_json")
            answers = {}

        # flow_token is Meta's own correlation id (see senders.py/inbox.py,
        # which stash it on the *outbound* message to resume the right
        # session/conversation) - it isn't one of the Flow's actual answers,
        # so it's excluded from the human-readable chat bubble text but kept
        # in additional_info below for anything that needs the raw payload.
        displayed_answers = {k: v for k, v in answers.items() if k != "flow_token"}
        body = "\n".join(
            f"{WhatsAppMessage.humanize_flow_field(key)}: {value}"
            for key, value in displayed_answers.items()
        )
        additional_info = {"flow_answers": answers}
        return body or nfm_reply.get("body"), additional_info

    def _handle_status(self, status_update):
        """Update a previously sent message's delivery/read/failed status."""
        wa_message_id = status_update.get("id")
        status_value = _STATUS_MAP.get(status_update.get("status"))
        logger.info(
            "WhatsApp webhook status update: %s for %s",
            status_update.get("status"),
            wa_message_id,
        )
        if not status_value:
            return

        message = WhatsAppMessage.objects.filter(
            wa_message_id=wa_message_id, direction=MESSAGE_DIRECTION_OUT
        ).first()
        if not message:
            logger.warning(
                "WhatsApp webhook status update for unknown message id %s",
                wa_message_id,
            )
            return

        message.status = status_value
        now = timezone.now()
        if status_value == MESSAGE_STATUS_DELIVERED:
            message.delivered_at = now
        elif status_value == MESSAGE_STATUS_READ:
            message.read_at = now
        elif status_value == MESSAGE_STATUS_FAILED:
            errors = status_update.get("errors", [])
            if errors:
                message.status_message = errors[0].get("title")
        message.save()
