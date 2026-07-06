"""
WhatsApp conversation panel and inbox views.
"""

# Standard library imports
import io
import logging
import os
import threading
import time
import uuid

# Third-party imports (Django)
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import OperationalError, close_old_connections
from django.db.models import Q
from django.utils import timezone
from django.utils.html import escape
from django.views.generic import DetailView, FormView, View

# First party imports (Horilla)
from horilla.apps import apps
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.views.details import (
    check_record_access,
    check_record_change_access,
)
from horilla.shortcuts import render
from horilla.urls import reverse
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.translation import gettext_lazy as _
from horilla.web import Http404, HttpResponse, JsonResponse

# Local imports
from ..forms import WhatsAppSendMessageForm
from ..models import (
    MESSAGE_DIRECTION_OUT,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_SENT,
    WhatsAppAccount,
    WhatsAppAttachment,
    WhatsAppBotRule,
    WhatsAppConversation,
    WhatsAppFlow,
    WhatsAppMessage,
    WhatsAppTemplate,
    normalize_whatsapp_number,
)
from ..services import WhatsAppAPIError, WhatsAppCloudAPIClient

logger = logging.getLogger(__name__)


_delivery_queues = {}
_delivery_lock = threading.Lock()


def _enqueue_delivery(conversation_id, message_id, attachment_id=None):
    """Queue a send so a conversation's messages go out one at a time, in order."""
    with _delivery_lock:
        pending = _delivery_queues.get(conversation_id)
        if pending is not None:
            pending.append((message_id, attachment_id))
            return
        _delivery_queues[conversation_id] = [(message_id, attachment_id)]

    def _worker():
        while True:
            with _delivery_lock:
                pending = _delivery_queues.get(conversation_id)
                if not pending:
                    _delivery_queues.pop(conversation_id, None)
                    return
                job = pending.pop(0)
            _deliver_message(*job)

    threading.Thread(target=_worker, daemon=True).start()


def _deliver_message(message_id, attachment_id=None):
    """Send a saved outbound message to Meta (runs in a background thread)."""
    try:
        message = None
        for attempt in range(5):
            try:
                message = WhatsAppMessage.objects.select_related(
                    "conversation", "conversation__account"
                ).get(pk=message_id)
                break
            except OperationalError:
                close_old_connections()
                time.sleep(0.2 * (attempt + 1))
        if message is None:
            return
        conversation = message.conversation
        client = WhatsAppCloudAPIClient(conversation.account)
        body = message.body
        try:
            if attachment_id:
                attachment = WhatsAppAttachment.objects.get(pk=attachment_id)
                with attachment.file.open("rb") as handle:
                    upload = io.BytesIO(handle.read())
                upload.name = os.path.basename(attachment.file.name)
                upload.content_type = attachment.mime_type
                media_id = client.upload_media(upload)
                attachment.media_id = media_id
                attachment.save(update_fields=["media_id"])
                result = client.send_media(
                    conversation.contact_number,
                    media_id,
                    attachment.mime_type,
                    caption=body,
                    filename=upload.name,
                )
            else:
                result = client.send_text(conversation.contact_number, body)
            message.wa_message_id = result.get("messages", [{}])[0].get("id")
            message.status = MESSAGE_STATUS_SENT
            message.sent_at = timezone.now()
            message.save(update_fields=["wa_message_id", "status", "sent_at"])
        except WhatsAppAPIError as exc:
            message.status = MESSAGE_STATUS_FAILED
            message.status_message = str(exc)
            message.save(update_fields=["status", "status_message"])
            logger.error(
                "Failed to send WhatsApp message for conversation %s: %s",
                conversation.pk,
                exc,
            )
    except Exception:  # pylint: disable=broad-except
        logger.exception("Background WhatsApp send failed for message %s", message_id)
    finally:
        close_old_connections()


def _resolve_phone_number(record):
    """Return the first usable phone number found on a CRM record."""
    for field_name in ("contact_number", "phone", "secondary_phone"):
        value = getattr(record, field_name, None)
        if value:
            return value
    return None


def _company_accounts(record):
    """Active WhatsApp accounts for the record's company, primary first."""
    return WhatsAppAccount.objects.filter(
        company=record.company, is_active=True
    ).order_by("-is_primary", "pk")


def _get_or_create_conversation(record, record_model, account_id=None):
    """
    Return the WhatsApp conversation for a CRM record, creating one if needed.
    Uses `account_id` if it names one of the company's active accounts,
    otherwise the company's primary account.
    """
    phone_number = _resolve_phone_number(record)
    if not phone_number:
        return None, None
    phone_number = normalize_whatsapp_number(phone_number)

    accounts = _company_accounts(record)
    account = None
    if account_id:
        account = accounts.filter(pk=account_id).first()
    if account is None:
        # No (valid) explicit choice: reopen the account this contact most
        # recently exchanged a message on, rather than always the primary one.
        latest = (
            WhatsAppConversation.objects.filter(
                contact_number=phone_number, account__in=accounts
            )
            .exclude(last_message_at__isnull=True)
            .order_by("-last_message_at")
            .first()
        )
        account = latest.account if latest else None
    account = account or accounts.first()
    if not account:
        return phone_number, None

    content_type = HorillaContentType.objects.get_for_model(record_model)
    conversation = WhatsAppConversation.objects.filter(
        account=account, contact_number=phone_number
    ).first()
    if not conversation:
        conversation = WhatsAppConversation.objects.create(
            account=account,
            contact_number=phone_number,
            contact_name=str(record),
            content_type=content_type,
            object_id=record.pk,
            company=record.company,
        )
    elif not conversation.content_type_id:
        conversation.content_type = content_type
        conversation.object_id = record.pk
        conversation.save(update_fields=["content_type", "object_id"])

    return phone_number, conversation


@method_decorator(htmx_required, name="dispatch")
class WhatsAppRecordTabView(LoginRequiredMixin, DetailView):
    """
    WhatsApp conversation tab for a CRM record's detail page.

    Subclasses (created dynamically by register_whatsapp_tab) set app_label
    and model_name to identify which model this tab belongs to. Follows the
    same DetailView + check_record_access shape as
    HorillaNotesAttachementSectionView / HorillaActivitySectionView.
    """

    template_name = "whatsapp_inbox/conversation_panel.html"
    context_object_name = "record"
    app_label = None
    model_name = None

    def get_queryset(self):
        model = apps.get_model(self.app_label, self.model_name)
        if not model:
            raise Http404(_("Invalid model for WhatsApp tab."))
        self.model = model
        return model.objects.all()

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if not check_record_access(request.user, self.object):
            return render(request, "403.html", status=403)
        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        record = self.object
        # An account picked in the switcher is remembered for this user's
        # session, so reopening the chat later doesn't reset to the first one.
        session_key = "whatsapp_active_account_id"
        picked = self.request.GET.get("account")
        if picked and picked.isdigit():
            self.request.session[session_key] = int(picked)
        account_id = picked or self.request.session.get(session_key)
        phone_number, conversation = _get_or_create_conversation(
            record, self.model, account_id
        )
        accounts = list(_company_accounts(record))
        context["accounts"] = accounts
        context["panel_url"] = self.request.path

        context["phone_number"] = phone_number
        context["conversation"] = conversation
        context["can_send_message"] = check_record_change_access(
            self.request.user, record
        )
        context["messages"] = (
            conversation.messages.select_related(
                "template", "sent_by"
            ).prefetch_related("attachments")
            if conversation
            else []
        )
        context["send_message_url"] = (
            reverse(
                "whatsapp:whatsapp_send_message_view", kwargs={"pk": conversation.pk}
            )
            if conversation
            else None
        )
        context["message_list_url"] = (
            reverse(
                "whatsapp:whatsapp_message_list_view", kwargs={"pk": conversation.pk}
            )
            if conversation
            else None
        )
        context["conversation_id"] = conversation.pk if conversation else None
        context["send_template_url"] = (
            reverse(
                "whatsapp:whatsapp_send_template_view", kwargs={"pk": conversation.pk}
            )
            if conversation
            else None
        )
        context["template_send_form_url"] = (
            reverse(
                "whatsapp:whatsapp_template_send_form_view",
                kwargs={"pk": conversation.pk},
            )
            if conversation
            else None
        )
        context["templates"] = (
            WhatsAppTemplate.objects.filter(
                is_active=True, company=conversation.company
            )
            .filter(Q(account__isnull=True) | Q(account=conversation.account))
            .filter(
                Q(content_type__isnull=True) | Q(content_type=conversation.content_type)
            )
            if conversation
            else []
        )
        context["send_flow_url"] = (
            reverse("whatsapp:whatsapp_send_flow_view", kwargs={"pk": conversation.pk})
            if conversation
            else None
        )
        context["flows"] = (
            WhatsAppFlow.objects.filter(
                is_active=True, account=conversation.account
            ).filter(
                Q(content_type__isnull=True) | Q(content_type=conversation.content_type)
            )
            if conversation and conversation.account
            else []
        )
        context["start_bot_rule_url"] = (
            reverse(
                "whatsapp:whatsapp_start_bot_rule_view", kwargs={"pk": conversation.pk}
            )
            if conversation
            else None
        )
        context["bot_rules"] = (
            WhatsAppBotRule.objects.filter(
                is_active=True, account=conversation.account, trigger_type="manual"
            ).filter(
                Q(content_type__isnull=True) | Q(content_type=conversation.content_type)
            )
            if conversation and conversation.account
            else []
        )
        return context


def _mark_group_starts(messages, previous_direction=None):
    """
    Flag each message with `group_start`: True when it is the first of a run of
    messages from the same side (customer or us), so only that bubble gets the
    WhatsApp-style tail. `previous_direction` is the direction of the message
    just before the first one given (None if there isn't one).
    """
    marked = []
    for message in messages:
        message.group_start = message.direction != previous_direction
        previous_direction = message.direction
        marked.append(message)
    return marked


@method_decorator(htmx_required, name="dispatch")
class WhatsAppMessageListView(LoginRequiredMixin, DetailView):
    """
    Renders the message list partial for a conversation (used for htmx polling
    refresh inside the conversation panel).
    """

    model = WhatsAppConversation
    template_name = "whatsapp_inbox/message_list_partial.html"
    context_object_name = "conversation"

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        related_object = self.object.related_to
        if related_object and not check_record_access(request.user, related_object):
            return render(request, "403.html", status=403)
        after = request.GET.get("after")
        if after is not None:
            # Catch-up request: just the bubbles newer than `after`.
            try:
                after_id = int(after)
            except ValueError:
                after_id = 0
            new_messages = (
                self.object.messages.filter(pk__gt=after_id)
                .select_related("template", "sent_by")
                .prefetch_related("attachments")
            )
            previous = (
                self.object.messages.filter(pk__lte=after_id).order_by("-pk").first()
            )
            return render(
                request,
                "whatsapp_inbox/message_items_partial.html",
                {
                    "messages": _mark_group_starts(
                        new_messages, previous.direction if previous else None
                    )
                },
            )
        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["messages"] = _mark_group_starts(
            self.object.messages.select_related("template", "sent_by").prefetch_related(
                "attachments"
            )
        )
        return context


@method_decorator(htmx_required, name="dispatch")
class WhatsAppMessageItemView(LoginRequiredMixin, View):
    """
    Renders a single message bubble. Used by the realtime socket handler to
    append a new message (or refresh a message's status ticks) without
    reloading the whole list.
    """

    def get(self, request, pk, message_pk):
        message = (
            WhatsAppMessage.objects.select_related(
                "conversation", "template", "sent_by"
            )
            .prefetch_related("attachments")
            .filter(pk=message_pk, conversation_id=pk)
            .first()
        )
        if not message:
            raise Http404(_("Message not found."))
        related_object = message.conversation.related_to
        if related_object and not check_record_access(request.user, related_object):
            return render(request, "403.html", status=403)
        previous = (
            WhatsAppMessage.objects.filter(conversation_id=pk, pk__lt=message.pk)
            .order_by("-pk")
            .first()
        )
        _mark_group_starts([message], previous.direction if previous else None)
        return render(request, "whatsapp_inbox/message_item.html", {"message": message})


@method_decorator(htmx_required, name="dispatch")
class WhatsAppSendMessageView(LoginRequiredMixin, FormView):
    """
    Handles sending an outbound WhatsApp message (with an optional attachment)
    from the conversation panel. Follows the same permission-checked FormView
    shape as HorillaNotesAttachmentCreateView.
    """

    form_class = WhatsAppSendMessageForm

    def dispatch(self, request, *args, **kwargs):
        self.conversation = WhatsAppConversation.objects.filter(
            pk=kwargs.get("pk")
        ).first()
        if not self.conversation or not self.conversation.account:
            raise Http404(_("Conversation not found."))

        related_object = self.conversation.related_to
        if related_object and not check_record_change_access(
            request.user, related_object
        ):
            messages.error(
                request, _("You don't have permission to message this record.")
            )
            return HttpResponse(status=403)
        return super().dispatch(request, *args, **kwargs)

    def form_invalid(self, form):
        messages.error(self.request, _("Please enter a message or attach a file."))
        return HttpResponse(status=400)

    def form_valid(self, form):
        conversation = self.conversation
        body = form.cleaned_data.get("body")
        attachment_file = form.cleaned_data.get("attachment")

        message = WhatsAppMessage.objects.create(
            conversation=conversation,
            direction=MESSAGE_DIRECTION_OUT,
            message_type="document" if attachment_file else "text",
            body=body,
            sent_by=self.request.user,
            company=conversation.company,
        )

        attachment = None
        if attachment_file:
            attachment = WhatsAppAttachment.objects.create(
                message=message,
                file=attachment_file,
                file_size=attachment_file.size,
                mime_type=attachment_file.content_type,
                company=conversation.company,
            )

        # Calling Meta's API can take seconds; do it off the request so the
        # bubble shows up at once and the tick updates when Meta answers.
        _enqueue_delivery(
            conversation.pk, message.pk, attachment.pk if attachment else None
        )

        return HttpResponse(status=204)


def _fill_placeholders(text, values):
    """Replace {{1}}, {{2}}... in text with the given 1-indexed values list."""
    for index, value in enumerate(values, start=1):
        text = text.replace("{{%d}}" % index, value or "")
    return text


class _TemplateParamMixin:
    """Shared card/body/header/button param field-name helpers for template send."""

    @staticmethod
    def _body_param_values(schema_body, data, prefix=""):
        return [
            data.get(f"{prefix}body_param_{i}", "")
            for i in range(1, schema_body["variables"] + 1)
        ]

    @staticmethod
    def _button_param_values(schema_buttons, data, prefix=""):
        return {
            button["index"]: data.get(f"{prefix}button_param_{button['index']}", "")
            for button in schema_buttons
            if button.get("url_has_variable")
        }


@method_decorator(htmx_required, name="dispatch")
class WhatsAppTemplateSendFormView(LoginRequiredMixin, _TemplateParamMixin, View):
    """
    Renders the parameter-collection form for a template (body variables,
    header media, dynamic button URLs, carousel cards) inside #modalBox.
    """

    def get(self, request, *args, **kwargs):
        conversation = WhatsAppConversation.objects.filter(pk=kwargs.get("pk")).first()
        if not conversation or not conversation.account:
            raise Http404(_("Conversation not found."))

        template = (
            WhatsAppTemplate.objects.filter(
                pk=request.GET.get("template_id"), company=conversation.company
            )
            .filter(Q(account__isnull=True) | Q(account=conversation.account))
            .first()
        )
        if not template:
            raise Http404(_("Template not found."))

        return render(
            request,
            "whatsapp_inbox/template_send_form.html",
            {
                "conversation": conversation,
                "template": template,
                "schema": template.get_send_schema(),
                "send_template_url": reverse(
                    "whatsapp:whatsapp_send_template_view",
                    kwargs={"pk": conversation.pk},
                ),
            },
        )


@method_decorator(htmx_required, name="dispatch")
class WhatsAppSendTemplateView(LoginRequiredMixin, _TemplateParamMixin, View):
    """
    Sends an approved WhatsApp template message from the conversation panel.
    Used to open (or re-open) the 24-hour messaging window with a contact.
    """

    def dispatch(self, request, *args, **kwargs):
        self.conversation = WhatsAppConversation.objects.filter(
            pk=kwargs.get("pk")
        ).first()
        if not self.conversation or not self.conversation.account:
            raise Http404(_("Conversation not found."))

        related_object = self.conversation.related_to
        if related_object and not check_record_change_access(
            request.user, related_object
        ):
            messages.error(
                request, _("You don't have permission to message this record.")
            )
            return HttpResponse(status=403)
        return super().dispatch(request, *args, **kwargs)

    def _build_components(self, template, schema, client):
        """
        Build the Meta Cloud API 'components' payload from submitted form
        data/files, uploading any header/carousel-card media first. Returns
        (components, preview_body, preview_media) where preview_media is the
        list of uploaded files to attach to the saved message for display.
        """
        data = self.request.POST
        files = self.request.FILES
        components = []
        preview_body = schema["body"]["text"]
        preview_media = []

        if schema["header"] and schema["header"]["variables"]:
            if schema["header"]["format"] == "TEXT":
                value = data.get("header_param_1", "")
                components.append(
                    {
                        "type": "header",
                        "parameters": [{"type": "text", "text": value}],
                    }
                )
            else:
                media_file = files.get("header_media")
                if not media_file:
                    raise ValueError(_("Please upload a header file."))
                media_id = client.upload_media(media_file)
                media_type = schema["header"]["format"].lower()
                components.append(
                    {
                        "type": "header",
                        "parameters": [
                            {"type": media_type, media_type: {"id": media_id}}
                        ],
                    }
                )
                preview_media.append((media_file, media_id))

        if schema["body"]["variables"]:
            values = self._body_param_values(schema["body"], data)
            components.append(
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": v} for v in values],
                }
            )
            preview_body = _fill_placeholders(preview_body, values)

        button_values = self._button_param_values(schema["buttons"], data)
        for index, value in button_values.items():
            components.append(
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": str(index),
                    "parameters": [{"type": "text", "text": value}],
                }
            )

        if schema["carousel"]:
            cards = []
            for card in schema["carousel"]["cards"]:
                prefix = f"card_{card['index']}_"
                card_components = []
                if card["header"] and card["header"]["variables"]:
                    media_file = files.get(f"{prefix}header_media")
                    if not media_file:
                        raise ValueError(
                            _("Please upload an image for card %(n)s.")
                            % {"n": card["index"] + 1}
                        )
                    media_id = client.upload_media(media_file)
                    media_type = card["header"]["format"].lower()
                    card_components.append(
                        {
                            "type": "header",
                            "parameters": [
                                {"type": media_type, media_type: {"id": media_id}}
                            ],
                        }
                    )
                    preview_media.append((media_file, media_id))
                if card["body"]["variables"]:
                    values = self._body_param_values(card["body"], data, prefix)
                    card_components.append(
                        {
                            "type": "body",
                            "parameters": [{"type": "text", "text": v} for v in values],
                        }
                    )
                card_button_values = self._button_param_values(
                    card["buttons"], data, prefix
                )
                for index, value in card_button_values.items():
                    card_components.append(
                        {
                            "type": "button",
                            "sub_type": "url",
                            "index": str(index),
                            "parameters": [{"type": "text", "text": value}],
                        }
                    )
                cards.append(
                    {"card_index": card["index"], "components": card_components}
                )
            components.append({"type": "carousel", "cards": cards})

        return components, preview_body, preview_media

    def post(self, request, *args, **kwargs):
        conversation = self.conversation
        template = (
            WhatsAppTemplate.objects.filter(
                pk=request.POST.get("template_id"), company=conversation.company
            )
            .filter(Q(account__isnull=True) | Q(account=conversation.account))
            .first()
        )
        if not template:
            messages.error(request, _("Please select a valid template."))
            return HttpResponse(status=400)

        client = WhatsAppCloudAPIClient(conversation.account)
        schema = template.get_send_schema()
        try:
            components, preview_body, preview_media = self._build_components(
                template, schema, client
            )
        except (ValueError, WhatsAppAPIError) as exc:
            return HttpResponse(
                f'<p class="text-xs text-red-600 p-2">{escape(str(exc))}</p>',
                status=400,
            )

        message = WhatsAppMessage.objects.create(
            conversation=conversation,
            direction=MESSAGE_DIRECTION_OUT,
            message_type="template",
            body=preview_body,
            template=template,
            sent_by=self.request.user,
            company=conversation.company,
        )
        for media_file, media_id in preview_media:
            media_file.seek(0)
            WhatsAppAttachment.objects.create(
                message=message,
                file=media_file,
                file_size=media_file.size,
                mime_type=media_file.content_type,
                media_id=media_id,
                company=conversation.company,
            )

        try:
            result = client.send_template(
                conversation.contact_number,
                template.name,
                template.language,
                components=components,
            )
            message.wa_message_id = result.get("messages", [{}])[0].get("id")
            message.status = MESSAGE_STATUS_SENT
            message.sent_at = timezone.now()
            message.save(update_fields=["wa_message_id", "status", "sent_at"])
        except WhatsAppAPIError as exc:
            message.status = MESSAGE_STATUS_FAILED
            message.status_message = str(exc)
            message.save(update_fields=["status", "status_message"])
            logger.error(
                "Failed to send WhatsApp template for conversation %s: %s",
                conversation.pk,
                exc,
            )
            messages.error(self.request, _("Failed to send template: %s") % exc)

        return HttpResponse(status=204)


@method_decorator(htmx_required, name="dispatch")
class WhatsAppSendFlowView(LoginRequiredMixin, View):
    """
    Sends a static WhatsApp Flow message (no dynamic/data-exchange screens)
    from the conversation panel.
    """

    def dispatch(self, request, *args, **kwargs):
        self.conversation = WhatsAppConversation.objects.filter(
            pk=kwargs.get("pk")
        ).first()
        if not self.conversation or not self.conversation.account:
            raise Http404(_("Conversation not found."))

        related_object = self.conversation.related_to
        if related_object and not check_record_change_access(
            request.user, related_object
        ):
            messages.error(
                request, _("You don't have permission to message this record.")
            )
            return HttpResponse(status=403)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        conversation = self.conversation
        flow = (
            WhatsAppFlow.objects.filter(
                pk=request.POST.get("flow_id"),
                account=conversation.account,
                is_active=True,
            )
            .filter(
                Q(content_type__isnull=True) | Q(content_type=conversation.content_type)
            )
            .first()
        )
        if not flow:
            messages.error(request, _("Please select a valid flow."))
            return HttpResponse(status=400)

        message = WhatsAppMessage.objects.create(
            conversation=conversation,
            direction=MESSAGE_DIRECTION_OUT,
            message_type="interactive",
            body=_("Flow sent: %(title)s") % {"title": flow.title},
            sent_by=self.request.user,
            company=conversation.company,
        )

        client = WhatsAppCloudAPIClient(conversation.account)
        flow_token = f"conv-{conversation.pk}-{uuid.uuid4().hex}"
        try:
            result = client.send_flow(
                conversation.contact_number,
                flow.flow_id,
                flow.cta_text,
                flow_token,
            )
            message.wa_message_id = result.get("messages", [{}])[0].get("id")
            message.status = MESSAGE_STATUS_SENT
            message.sent_at = timezone.now()
            message.additional_info = {
                "flow_token": flow_token,
                "flow_title": flow.title,
                "flow_cta": flow.cta_text,
                "flow_id": flow.flow_id,
            }
            message.save(
                update_fields=["wa_message_id", "status", "sent_at", "additional_info"]
            )
        except WhatsAppAPIError as exc:
            message.status = MESSAGE_STATUS_FAILED
            message.status_message = str(exc)
            message.save(update_fields=["status", "status_message"])
            logger.error(
                "Failed to send WhatsApp flow for conversation %s: %s",
                conversation.pk,
                exc,
            )
            messages.error(self.request, _("Failed to send flow: %s") % exc)

        return HttpResponse(status=204)


@method_decorator(htmx_required, name="dispatch")
class WhatsAppSendBotRuleView(LoginRequiredMixin, View):
    """Manually starts a manual-trigger Bot Rule flow for a conversation."""

    def dispatch(self, request, *args, **kwargs):
        self.conversation = WhatsAppConversation.objects.filter(
            pk=kwargs.get("pk")
        ).first()
        if not self.conversation or not self.conversation.account:
            raise Http404(_("Conversation not found."))

        related_object = self.conversation.related_to
        if related_object and not check_record_change_access(
            request.user, related_object
        ):
            messages.error(
                request, _("You don't have permission to message this record.")
            )
            return HttpResponse(status=403)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        from ..engine.base import FlowEngine

        conversation = self.conversation
        rule = (
            WhatsAppBotRule.objects.filter(
                pk=request.POST.get("bot_rule_id"),
                account=conversation.account,
                is_active=True,
                trigger_type="manual",
            )
            .filter(
                Q(content_type__isnull=True) | Q(content_type=conversation.content_type)
            )
            .first()
        )
        if not rule:
            messages.error(request, _("Please select a valid bot rule."))
            return HttpResponse(status=400)

        FlowEngine.start(rule, conversation)

        return HttpResponse(status=204)


class WhatsAppConversationTakeOverView(LoginRequiredMixin, View):
    """Disable the bot for a conversation so a human agent can take over."""

    def post(self, request, *args, **kwargs):
        conversation = WhatsAppConversation.objects.filter(pk=kwargs.get("pk")).first()
        if not conversation:
            raise Http404(_("Conversation not found."))

        related_object = conversation.related_to
        if related_object and not check_record_change_access(
            request.user, related_object
        ):
            return JsonResponse({"success": False}, status=403)

        conversation.is_bot_active = False
        conversation.assigned_to = request.user
        conversation.save(update_fields=["is_bot_active", "assigned_to"])
        return JsonResponse({"success": True})
