"""
API views for whatsapp models

Follows core architecture: ModelViewSets with SearchFilterMixin and BulkOperationsMixin,
permissions, and swagger documentation.
"""

# Third-party imports (Django)
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status, viewsets
from rest_framework.response import Response

# First party imports (Horilla)
from horilla.api.mixins import BulkOperationsMixin, SearchFilterMixin
from horilla.api.permissions import IsCompanyMember, IsOwnerOrAdmin

from ..models import (
    WhatsAppAccount,
    WhatsAppAttachment,
    WhatsAppConversation,
    WhatsAppFlow,
    WhatsAppMessage,
    WhatsAppTemplate,
)

# Local imports
from .docs import (
    WHATSAPP_BULK_DELETE_DOCS,
    WHATSAPP_BULK_UPDATE_DOCS,
    WHATSAPP_SEARCH_FILTER_DOCS,
)
from .serializers import (
    WhatsAppAccountSerializer,
    WhatsAppAttachmentSerializer,
    WhatsAppConversationSerializer,
    WhatsAppFlowSerializer,
    WhatsAppMessageSerializer,
    WhatsAppTemplateSerializer,
)

# Common search parameter
search_param = openapi.Parameter(
    "search",
    openapi.IN_QUERY,
    description="Search term for full-text search across relevant fields",
    type=openapi.TYPE_STRING,
)


class WhatsAppAccountViewSet(
    SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet
):
    """ViewSet for WhatsAppAccount model"""

    queryset = WhatsAppAccount.objects.all().select_related("company", "created_by")
    serializer_class = WhatsAppAccountSerializer
    permission_classes = [permissions.IsAuthenticated, IsCompanyMember, IsOwnerOrAdmin]
    search_fields = ["display_name", "display_phone_number", "business_account_id"]
    filterset_fields = ["is_primary", "bot_enabled", "company", "is_active"]

    @swagger_auto_schema(
        manual_parameters=[search_param],
        operation_description=WHATSAPP_SEARCH_FILTER_DOCS,
    )
    def list(self, request, *args, **kwargs):
        """List WhatsApp accounts with search and filter support."""
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=WHATSAPP_BULK_UPDATE_DOCS)
    def bulk_update(self, request, *args, **kwargs):
        """Update multiple WhatsApp accounts."""
        return super().bulk_update(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=WHATSAPP_BULK_DELETE_DOCS)
    def bulk_delete(self, request, *args, **kwargs):
        """Delete multiple WhatsApp accounts."""
        return super().bulk_delete(request, *args, **kwargs)


class WhatsAppTemplateViewSet(
    SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet
):
    """ViewSet for WhatsAppTemplate model"""

    queryset = WhatsAppTemplate.objects.all().select_related(
        "content_type", "company", "created_by"
    )
    serializer_class = WhatsAppTemplateSerializer
    permission_classes = [permissions.IsAuthenticated, IsCompanyMember]
    search_fields = ["title", "name"]
    filterset_fields = ["language", "category", "content_type", "company"]

    @swagger_auto_schema(
        manual_parameters=[search_param],
        operation_description=WHATSAPP_SEARCH_FILTER_DOCS,
    )
    def list(self, request, *args, **kwargs):
        """List WhatsApp templates with search and filter support."""
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=WHATSAPP_BULK_UPDATE_DOCS)
    def bulk_update(self, request, *args, **kwargs):
        """Update multiple WhatsApp templates."""
        return super().bulk_update(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=WHATSAPP_BULK_DELETE_DOCS)
    def bulk_delete(self, request, *args, **kwargs):
        """Delete multiple WhatsApp templates."""
        return super().bulk_delete(request, *args, **kwargs)


class WhatsAppFlowViewSet(
    SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet
):
    """ViewSet for WhatsAppFlow model"""

    queryset = WhatsAppFlow.objects.all().select_related(
        "account", "company", "created_by"
    )
    serializer_class = WhatsAppFlowSerializer
    permission_classes = [permissions.IsAuthenticated, IsCompanyMember]
    search_fields = ["title", "flow_id", "flow_name"]
    filterset_fields = ["account", "is_active", "company"]

    @swagger_auto_schema(
        manual_parameters=[search_param],
        operation_description=WHATSAPP_SEARCH_FILTER_DOCS,
    )
    def list(self, request, *args, **kwargs):
        """List WhatsApp flows with search and filter support."""
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=WHATSAPP_BULK_UPDATE_DOCS)
    def bulk_update(self, request, *args, **kwargs):
        """Update multiple WhatsApp flows."""
        return super().bulk_update(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=WHATSAPP_BULK_DELETE_DOCS)
    def bulk_delete(self, request, *args, **kwargs):
        """Delete multiple WhatsApp flows."""
        return super().bulk_delete(request, *args, **kwargs)


class WhatsAppConversationViewSet(
    SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet
):
    """ViewSet for WhatsAppConversation model"""

    queryset = WhatsAppConversation.objects.all().select_related(
        "account", "content_type", "assigned_to", "company"
    )
    serializer_class = WhatsAppConversationSerializer
    permission_classes = [permissions.IsAuthenticated, IsCompanyMember]
    search_fields = ["contact_name", "contact_number"]
    filterset_fields = [
        "account",
        "status",
        "is_bot_active",
        "assigned_to",
        "content_type",
        "object_id",
        "company",
    ]

    @swagger_auto_schema(
        manual_parameters=[search_param],
        operation_description=WHATSAPP_SEARCH_FILTER_DOCS,
    )
    def list(self, request, *args, **kwargs):
        """List WhatsApp conversations with search and filter support."""
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=WHATSAPP_BULK_UPDATE_DOCS)
    def bulk_update(self, request, *args, **kwargs):
        """Update multiple WhatsApp conversations."""
        return super().bulk_update(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=WHATSAPP_BULK_DELETE_DOCS)
    def bulk_delete(self, request, *args, **kwargs):
        """Delete multiple WhatsApp conversations."""
        return super().bulk_delete(request, *args, **kwargs)


class WhatsAppMessageViewSet(
    SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet
):
    """
    ViewSet for WhatsAppMessage model.

    Read-mostly: sending a message must go through WhatsAppSendMessageView
    so the Cloud API call stays centralized. Direct creation via the API is
    blocked for v1.
    """

    queryset = WhatsAppMessage.objects.all().select_related(
        "conversation", "template", "sent_by", "company"
    )
    serializer_class = WhatsAppMessageSerializer
    permission_classes = [permissions.IsAuthenticated, IsCompanyMember]
    search_fields = ["body"]
    filterset_fields = [
        "conversation",
        "direction",
        "message_type",
        "status",
        "company",
    ]

    def create(self, request, *args, **kwargs):
        """Block direct message creation via the API; use the send-message flow instead."""
        return Response(
            {
                "detail": "Sending messages via the API is not supported. Use the WhatsApp inbox instead."
            },
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @swagger_auto_schema(
        manual_parameters=[search_param],
        operation_description=WHATSAPP_SEARCH_FILTER_DOCS,
    )
    def list(self, request, *args, **kwargs):
        """List WhatsApp messages with search and filter support."""
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=WHATSAPP_BULK_UPDATE_DOCS)
    def bulk_update(self, request, *args, **kwargs):
        """Update multiple WhatsApp messages."""
        return super().bulk_update(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=WHATSAPP_BULK_DELETE_DOCS)
    def bulk_delete(self, request, *args, **kwargs):
        """Delete multiple WhatsApp messages."""
        return super().bulk_delete(request, *args, **kwargs)


class WhatsAppAttachmentViewSet(
    SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet
):
    """ViewSet for WhatsAppAttachment model"""

    queryset = WhatsAppAttachment.objects.all().select_related(
        "message", "company", "created_by"
    )
    serializer_class = WhatsAppAttachmentSerializer
    permission_classes = [permissions.IsAuthenticated, IsCompanyMember]
    search_fields = ["mime_type"]
    filterset_fields = ["message", "company"]

    @swagger_auto_schema(
        manual_parameters=[search_param],
        operation_description=WHATSAPP_SEARCH_FILTER_DOCS,
    )
    def list(self, request, *args, **kwargs):
        """List WhatsApp attachments with search and filter support."""
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=WHATSAPP_BULK_UPDATE_DOCS)
    def bulk_update(self, request, *args, **kwargs):
        """Update multiple WhatsApp attachments."""
        return super().bulk_update(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=WHATSAPP_BULK_DELETE_DOCS)
    def bulk_delete(self, request, *args, **kwargs):
        """Delete multiple WhatsApp attachments."""
        return super().bulk_delete(request, *args, **kwargs)
