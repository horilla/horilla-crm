"""
Filters for the whatsapp app
"""

# First party imports (Horilla)
from horilla.contrib.generics.filters import HorillaFilterSet

# Local imports
from .models import (
    WhatsAppAccount,
    WhatsAppBotRule,
    WhatsAppConversation,
    WhatsAppFlow,
    WhatsAppMessage,
    WhatsAppTemplate,
)


class WhatsAppAccountFilter(HorillaFilterSet):
    """Filter set for WhatsAppAccount model."""

    class Meta:
        """Meta class for WhatsAppAccountFilter."""

        model = WhatsAppAccount
        fields = "__all__"
        exclude = ["additional_info", "access_token", "webhook_verify_token"]
        search_fields = ["display_name", "display_phone_number"]


class WhatsAppTemplateFilter(HorillaFilterSet):
    """Filter set for WhatsAppTemplate model."""

    class Meta:
        """Meta class for WhatsAppTemplateFilter."""

        model = WhatsAppTemplate
        fields = "__all__"
        exclude = ["additional_info", "components"]
        search_fields = ["title", "name"]


class WhatsAppFlowFilter(HorillaFilterSet):
    """Filter set for WhatsAppFlow model."""

    class Meta:
        """Meta class for WhatsAppFlowFilter."""

        model = WhatsAppFlow
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = ["title", "flow_id", "flow_name"]


class WhatsAppConversationFilter(HorillaFilterSet):
    """Filter set for WhatsAppConversation model."""

    class Meta:
        """Meta class for WhatsAppConversationFilter."""

        model = WhatsAppConversation
        fields = "__all__"
        exclude = ["additional_info", "content_type", "object_id"]
        search_fields = ["contact_name", "contact_number"]


class WhatsAppMessageFilter(HorillaFilterSet):
    """Filter set for WhatsAppMessage model."""

    class Meta:
        """Meta class for WhatsAppMessageFilter."""

        model = WhatsAppMessage
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = ["body"]


class WhatsAppBotRuleFilter(HorillaFilterSet):
    """Filter set for WhatsAppBotRule model."""

    class Meta:
        """Meta class for WhatsAppBotRuleFilter."""

        model = WhatsAppBotRule
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = ["name", "trigger_keywords"]
