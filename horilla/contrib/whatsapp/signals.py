"""
Signals for the whatsapp app
"""

# Note: last_message_at is kept in sync directly in WhatsAppMessage.save()
# (see models.py) rather than via a post_save signal, since it needs to run
# synchronously before the sender continues.

# Third-party imports (Django)
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from horilla.contrib.automations.signals import is_running_migrations
from horilla.contrib.core.models import HorillaContentType

# First party imports (Horilla)
from horilla.db.models.signals import pre_delete
from horilla.registry.feature import FEATURE_REGISTRY


@receiver(pre_delete)
def delete_whatsapp_conversations_for_related_record(sender, instance, **kwargs):
    """
    Cascade-delete WhatsApp conversations (and, via real FK CASCADE, their
    messages/bot sessions) linked to any deleted CRM record through the
    conversation's generic relation (content_type/object_id), for every
    model registered as a valid WhatsApp link target - since
    GenericForeignKey has no on_delete of its own and would otherwise leave
    the conversation orphaned.
    """
    if is_running_migrations():
        return

    allowed_models = FEATURE_REGISTRY.get("whatsapp_template_models", [])
    if sender not in allowed_models:
        return

    from .models import WhatsAppConversation

    content_type = HorillaContentType.objects.get_for_model(sender)
    WhatsAppConversation.objects.filter(
        content_type=content_type, object_id=instance.pk
    ).delete()


def _push_message_event(conversation_id, message_id):
    """Tell anyone viewing the conversation that a message was added/changed."""
    if is_running_migrations() or not conversation_id:
        return

    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    from .consumers import conversation_group_name

    layer = get_channel_layer()
    if layer is None:
        return
    group = conversation_group_name(conversation_id)

    def _send():
        try:
            async_to_sync(layer.group_send)(
                group, {"type": "conversation.refresh", "message_id": message_id}
            )
        except Exception:  # pylint: disable=broad-except
            # Never let a realtime hiccup (e.g. Redis down) break saving.
            pass

    transaction.on_commit(_send)


@receiver(post_save, sender="whatsapp.WhatsAppMessage")
def notify_message_saved(sender, instance, **kwargs):
    """New/inbound messages and status ticks."""
    _push_message_event(instance.conversation_id, instance.pk)


@receiver(post_save, sender="whatsapp.WhatsAppAttachment")
def notify_attachment_saved(sender, instance, **kwargs):
    """Attachments are saved after their message, so push again to show them."""
    message = instance.message
    _push_message_event(message.conversation_id, message.pk)
