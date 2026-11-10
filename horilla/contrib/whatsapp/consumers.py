"""
WebSocket consumer that tells an open WhatsApp conversation panel to refresh
its message list when a message in that conversation is created or updated.
"""

# Standard library imports
import json

# Third-party imports (Django)
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer


def conversation_group_name(conversation_id):
    """Channel group name for a conversation."""
    return f"whatsapp_conversation_{conversation_id}"


class WhatsAppConversationConsumer(AsyncWebsocketConsumer):
    """Pushes a 'refresh' event to users viewing a conversation."""

    async def connect(self):
        user = self.scope["user"]
        if user.is_anonymous:
            await self.close()
            return

        conversation_id = self.scope["url_route"]["kwargs"]["pk"]
        if not await self._can_access(user, conversation_id):
            await self.close()
            return

        self.group_name = conversation_group_name(conversation_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def conversation_refresh(self, event):
        """Forward the refresh signal to the browser."""
        await self.send(text_data=json.dumps({"message_id": event.get("message_id")}))

    @database_sync_to_async
    def _can_access(self, user, conversation_id):
        from horilla.contrib.generics.views.details import check_record_access

        from .models import WhatsAppConversation

        conversation = WhatsAppConversation.objects.filter(pk=conversation_id).first()
        if not conversation:
            return False
        related = conversation.related_to
        return not related or check_record_access(user, related)
