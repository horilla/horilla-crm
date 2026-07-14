"""
Sends outbound WhatsApp messages on behalf of Bot Rule nodes, recording each
one as a WhatsAppMessage - mirrors WhatsAppBotEngine._reply/_send in bot.py.
"""

# Standard library imports
import logging
import uuid

# Third-party imports (Django)
from django.utils import timezone

# Local imports
from ..services import WhatsAppAPIError, WhatsAppCloudAPIClient

logger = logging.getLogger(__name__)


def send_text(session, body):
    """Send a plain text message and record it as an outbound WhatsAppMessage."""
    return _send_and_record(
        session,
        body=body,
        message_type="text",
        send=lambda client: (
            client.send_text(session.conversation.contact_number, body)
        ),
    )


def send_buttons(session, body, options):
    """Send a reply-buttons interactive message. `options` = [{"id","label"}, ...]."""
    buttons = [{"id": opt["id"], "title": opt["label"]} for opt in options]
    return _send_and_record(
        session,
        body=body,
        message_type="interactive",
        send=lambda client: (
            client.send_interactive_buttons(
                session.conversation.contact_number, body, buttons
            )
        ),
    )


def send_list(session, body, options, button_text="Choose an option"):
    """Send a list interactive message. `options` = [{"id","label","description"}, ...]."""
    rows = [
        {
            "id": opt["id"],
            "title": opt["label"],
            "description": opt.get("description", ""),
        }
        for opt in options
    ]
    sections = [{"title": "", "rows": rows}]
    return _send_and_record(
        session,
        body=body,
        message_type="interactive",
        send=lambda client: (
            client.send_interactive_list(
                session.conversation.contact_number, body, button_text, sections
            )
        ),
    )


def send_template(session, template):
    """Send an approved WhatsAppTemplate to this session's contact."""
    return _send_and_record(
        session,
        body=template.sample_body,
        message_type="template",
        send=lambda client: client.send_template(
            session.conversation.contact_number, template.name, template.language
        ),
        template=template,
    )


def send_meta_flow(session, meta_flow):
    """
    Send a static, published Meta WhatsApp Flow (a WhatsAppFlow reference) and
    tag the outbound WhatsAppMessage with a flow_token, so the eventual
    nfm_reply webhook event can be correlated back to this session.
    """
    flow_token = f"session-{session.pk}-{uuid.uuid4().hex}"
    message = _send_and_record(
        session,
        body=f"Flow sent: {meta_flow.title}",
        message_type="interactive",
        send=lambda client: client.send_flow(
            session.conversation.contact_number,
            meta_flow.flow_id,
            meta_flow.cta_text,
            flow_token,
        ),
    )
    message.additional_info = {
        "flow_token": flow_token,
        "flow_title": meta_flow.title,
        "flow_cta": meta_flow.cta_text,
        "flow_id": meta_flow.flow_id,
    }
    message.save(update_fields=["additional_info"])
    return message


def _send_and_record(session, body, message_type, send, template=None):
    """Send via `send(client)`, recording the attempt as a WhatsAppMessage."""
    from ..models import MESSAGE_DIRECTION_OUT, MESSAGE_STATUS_SENT, WhatsAppMessage

    conversation = session.conversation
    client = WhatsAppCloudAPIClient(conversation.account)
    message = WhatsAppMessage.objects.create(
        conversation=conversation,
        direction=MESSAGE_DIRECTION_OUT,
        message_type=message_type,
        body=body,
        sent_by_bot=True,
        company=conversation.company,
        template=template,
    )
    try:
        result = send(client)
        message.wa_message_id = result.get("messages", [{}])[0].get("id")
        message.status = MESSAGE_STATUS_SENT
        message.sent_at = timezone.now()
        message.save(update_fields=["wa_message_id", "status", "sent_at"])
    except WhatsAppAPIError as exc:
        message.status = "failed"
        message.status_message = str(exc)
        message.save(update_fields=["status", "status_message"])
        logger.error(
            "Failed to send bot flow message for session %s: %s", session.pk, exc
        )
    return message
