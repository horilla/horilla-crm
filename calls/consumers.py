"""WebSocket consumers for real-time incoming call and call status notifications."""

import json

from channels.generic.websocket import AsyncWebsocketConsumer


class IncomingCallConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time incoming call popups.

    Each authenticated user connects to the group "calls_{user_id}".
    When an inbound call arrives via webhook, the system pushes to the
    matched agent's group so a popup appears in their browser instantly.
    """

    async def connect(self):
        """On WebSocket connect, add to user-specific group for incoming call notifications."""
        user = self.scope["user"]
        if user.is_anonymous:
            await self.close()
            return
        self.group_name = f"calls_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        """On WebSocket disconnect, remove from group."""
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def incoming_call(self, event):
        """
        Called by group_send with type='incoming_call'.
        Forwards the payload to the connected browser.
        """
        await self.send(
            text_data=json.dumps(
                {
                    "type": "incoming_call",
                    "from_number": event["from_number"],
                    "to_number": event["to_number"],
                    "provider_name": event["provider_name"],
                    "call_log_id": event["call_log_id"],
                    "related_name": event.get("related_name"),
                }
            )
        )

    async def call_status(self, event):
        """
        Called by group_send with type='call_status'.
        Tells the calling modal that a call changed state so it can refresh itself.
        """
        await self.send(
            text_data=json.dumps(
                {
                    "type": "call_status",
                    "call_log_id": event["call_log_id"],
                    "status": event["status"],
                }
            )
        )
