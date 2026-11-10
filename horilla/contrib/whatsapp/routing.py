"""
WebSocket URL routing for the whatsapp app.
"""

# First party imports (Horilla)
from horilla.urls import re_path

# Local imports
from . import consumers

websocket_urlpatterns = [
    re_path(
        r"ws/whatsapp/conversation/(?P<pk>\d+)/$",
        consumers.WhatsAppConversationConsumer.as_asgi(),
    ),
]
