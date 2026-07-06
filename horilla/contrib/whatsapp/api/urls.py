"""
URL patterns for whatsapp API, consistent with core
"""

# Third-party imports (Django)
from rest_framework.routers import DefaultRouter

# First party imports (Horilla)
from horilla.urls import include, path

# Local imports
from .views import (
    WhatsAppAccountViewSet,
    WhatsAppAttachmentViewSet,
    WhatsAppConversationViewSet,
    WhatsAppFlowViewSet,
    WhatsAppMessageViewSet,
    WhatsAppTemplateViewSet,
)
from .webhook_views import WhatsAppWebhookView

router = DefaultRouter()
router.register(r"whatsapp-accounts", WhatsAppAccountViewSet)
router.register(r"whatsapp-templates", WhatsAppTemplateViewSet)
router.register(r"whatsapp-flows", WhatsAppFlowViewSet)
router.register(r"whatsapp-conversations", WhatsAppConversationViewSet)
router.register(r"whatsapp-messages", WhatsAppMessageViewSet)
router.register(r"whatsapp-attachments", WhatsAppAttachmentViewSet)

urlpatterns = [
    path("webhook/", WhatsAppWebhookView.as_view(), name="whatsapp_webhook"),
    path("", include(router.urls)),
]
