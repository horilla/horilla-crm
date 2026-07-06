"""
Serializers for whatsapp models, consistent with core conventions
"""

# Third-party imports (Django)
from rest_framework import serializers

# Local imports
from ..models import (
    WhatsAppAccount,
    WhatsAppAttachment,
    WhatsAppConversation,
    WhatsAppFlow,
    WhatsAppMessage,
    WhatsAppTemplate,
)


class WhatsAppAccountSerializer(serializers.ModelSerializer):
    """Serializer for WhatsAppAccount model. Access tokens are write-only."""

    access_token = serializers.CharField(write_only=True, required=True)
    webhook_verify_token = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )

    class Meta:
        """Meta class for WhatsAppAccountSerializer"""

        model = WhatsAppAccount
        fields = "__all__"

    def validate(self, attrs):
        """Ensure only one primary WhatsApp account exists per company."""
        is_primary = attrs.get(
            "is_primary", getattr(self.instance, "is_primary", False)
        )
        company = attrs.get("company", getattr(self.instance, "company", None))
        if is_primary:
            qs = WhatsAppAccount.objects.exclude(
                pk=getattr(self.instance, "pk", None)
            ).filter(is_primary=True, company=company)
            if qs.exists():
                raise serializers.ValidationError(
                    {"is_primary": "Another primary WhatsApp account already exists."}
                )
        return attrs


class WhatsAppTemplateSerializer(serializers.ModelSerializer):
    """Serializer for WhatsAppTemplate model"""

    class Meta:
        """Meta class for WhatsAppTemplateSerializer"""

        model = WhatsAppTemplate
        fields = "__all__"


class WhatsAppFlowSerializer(serializers.ModelSerializer):
    """Serializer for WhatsAppFlow model"""

    class Meta:
        """Meta class for WhatsAppFlowSerializer"""

        model = WhatsAppFlow
        fields = "__all__"


class WhatsAppConversationSerializer(serializers.ModelSerializer):
    """Serializer for WhatsAppConversation model"""

    class Meta:
        """Meta class for WhatsAppConversationSerializer"""

        model = WhatsAppConversation
        fields = "__all__"


class WhatsAppMessageSerializer(serializers.ModelSerializer):
    """
    Serializer for WhatsAppMessage model.

    Read-mostly: creation goes through WhatsAppSendMessageView so that the
    Cloud API side-effect (actually pushing the message to WhatsApp) stays
    centralized in one place.
    """

    class Meta:
        """Meta class for WhatsAppMessageSerializer"""

        model = WhatsAppMessage
        fields = "__all__"
        read_only_fields = [
            "wa_message_id",
            "status",
            "status_message",
            "sent_at",
            "delivered_at",
            "read_at",
        ]


class WhatsAppAttachmentSerializer(serializers.ModelSerializer):
    """Serializer for WhatsAppAttachment model"""

    class Meta:
        """Meta class for WhatsAppAttachmentSerializer"""

        model = WhatsAppAttachment
        fields = "__all__"
