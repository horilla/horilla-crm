"""
API views for horilla_crm.leads models

This module mirrors core API patterns including search, filtering,
bulk update, bulk delete, permissions, and documentation.
"""

# Third-party imports (other)
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

# First party imports (Horilla)
from horilla.api.docs import BULK_DELETE_DOCS, BULK_UPDATE_DOCS
from horilla.api.mixins import (
    BulkOperationsMixin,
    SearchFilterMixin,
    scope_queryset_to_permission,
)
from horilla.api.permissions import HorillaModelPermissions, IsCompanyMember

# Local imports
from horilla_crm.leads.api.docs import (
    LEAD_BY_OWNER_DOCS,
    LEAD_BY_SOURCE_DOCS,
    LEAD_BY_STATUS_DOCS,
    LEAD_CONVERT_DOCS,
    LEAD_CREATE_DOCS,
    LEAD_DETAIL_DOCS,
    LEAD_HIGH_SCORE_DOCS,
    LEAD_LIST_DOCS,
    LEAD_STATUS_CREATE_DOCS,
    LEAD_STATUS_DETAIL_DOCS,
    LEAD_STATUS_FINAL_STAGES_DOCS,
    LEAD_STATUS_LIST_DOCS,
    LEAD_STATUS_REORDER_DOCS,
)
from horilla_crm.leads.api.serializers import LeadSerializer, LeadStatusSerializer
from horilla_crm.leads.models import Lead, LeadStatus

# Define common Swagger parameters and bodies consistent with core
search_param = openapi.Parameter(
    "search",
    openapi.IN_QUERY,
    description="Search term for full-text search across relevant fields",
    type=openapi.TYPE_STRING,
)

# Define common Swagger request bodies for bulk operations
bulk_update_body = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "ids": openapi.Schema(
            type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_INTEGER)
        ),
        "data": openapi.Schema(type=openapi.TYPE_OBJECT, additional_properties=True),
    },
    required=["ids", "data"],
)

bulk_delete_body = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "ids": openapi.Schema(
            type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_INTEGER)
        )
    },
    required=["ids"],
)


class LeadViewSet(SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet):
    """ViewSet for Lead model"""

    queryset = Lead.objects.all()
    serializer_class = LeadSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsCompanyMember,
        HorillaModelPermissions,
    ]
    scope_list_to_view_permission = True
    # Every custom GET action below returns a bare collection via
    # get_queryset() (never get_object()), so each needs the same
    # view/view_own gating and OWNER_FIELDS-based queryset scoping as list.
    list_actions = ("list", "by_status", "by_owner", "by_source", "high_score")

    def get_serializer_class(self):
        """Return the serializer class for the view"""
        # Handle Swagger schema generation
        if getattr(self, "swagger_fake_view", False):
            return LeadSerializer
        return super().get_serializer_class()

    # Search across common lead fields
    search_fields = [
        "first_name",
        "last_name",
        "email",
        "title",
        "lead_company",
        "contact_number",
        "city",
        "state",
        "country",
        "requirements",
    ]

    # Filtering on key fields and common core fields
    filterset_fields = [
        "lead_owner",
        "lead_source",
        "lead_status",
        "industry",
        "no_of_employees",
        "annual_revenue",
        "city",
        "state",
        "country",
        "is_convert",
        "lead_score",
        "is_active",
        "created_by",
        "company",
    ]

    @swagger_auto_schema(
        manual_parameters=[search_param],
        operation_description=LEAD_LIST_DOCS,
    )
    def list(self, request, *args, **kwargs):
        """List leads with search and filter capabilities"""
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=LEAD_DETAIL_DOCS)
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a specific lead"""
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=LEAD_CREATE_DOCS)
    def create(self, request, *args, **kwargs):
        """Create a new lead"""
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(
        request_body=bulk_update_body, operation_description=BULK_UPDATE_DOCS
    )
    @action(detail=False, methods=["post"])
    def bulk_update(self, request):
        """Update multiple leads in a single request"""
        return super().bulk_update(request)

    @swagger_auto_schema(
        request_body=bulk_delete_body, operation_description=BULK_DELETE_DOCS
    )
    @action(detail=False, methods=["post"])
    def bulk_delete(self, request):
        """Delete multiple leads in a single request"""
        return super().bulk_delete(request)

    @swagger_auto_schema(operation_description=LEAD_BY_STATUS_DOCS)
    @action(detail=False, methods=["get"])
    def by_status(self, request):
        """Get leads filtered by lead status ID"""
        status_id = request.query_params.get("status_id")
        if not status_id:
            return Response(
                {"error": "status_id parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        queryset = self.filter_queryset(
            self.get_queryset().filter(lead_status_id=status_id)
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(operation_description=LEAD_BY_OWNER_DOCS)
    @action(detail=False, methods=["get"])
    def by_owner(self, request):
        """Get leads filtered by lead owner ID"""
        owner_id = request.query_params.get("owner_id")
        if not owner_id:
            return Response(
                {"error": "owner_id parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        queryset = self.filter_queryset(
            self.get_queryset().filter(lead_owner_id=owner_id)
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(operation_description=LEAD_BY_SOURCE_DOCS)
    @action(detail=False, methods=["get"])
    def by_source(self, request):
        """Get leads filtered by lead source"""
        source = request.query_params.get("source")
        if not source:
            return Response(
                {"error": "source parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        queryset = self.filter_queryset(self.get_queryset().filter(lead_source=source))
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(operation_description=LEAD_HIGH_SCORE_DOCS)
    @action(detail=False, methods=["get"])
    def high_score(self, request):
        """Get leads with high lead scores"""
        threshold = request.query_params.get("threshold", 70)
        try:
            threshold = int(threshold)
        except ValueError:
            return Response(
                {"error": "threshold must be a valid integer"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = self.filter_queryset(
            self.get_queryset().filter(lead_score__gte=threshold)
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(operation_description=LEAD_CONVERT_DOCS)
    @action(detail=True, methods=["post"])
    def convert(self, request, pk=None):
        """Convert a lead to account, contact, and opportunity"""
        lead = self.get_object()

        # This is a placeholder for lead conversion logic
        # The actual conversion logic would depend on the business requirements
        # and would typically involve creating Account, Contact, and Opportunity records

        if lead.is_convert:
            return Response(
                {"error": "Lead has already been converted"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Mark lead as converted
        lead.is_convert = True
        lead.save()

        return Response(
            {
                "message": "Lead conversion initiated successfully",
                "lead_id": lead.id,
                "converted": True,
            }
        )


class LeadStatusViewSet(SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet):
    """ViewSet for LeadStatus model"""

    queryset = LeadStatus.objects.all()
    serializer_class = LeadStatusSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsCompanyMember,
        HorillaModelPermissions,
    ]
    scope_list_to_view_permission = True
    # final_stages returns a bare collection via get_queryset(), so it is
    # gated and scoped like "list".
    list_actions = ("list", "final_stages")
    # reorder only mutates existing rows (it never creates one), so it must
    # be gated on change/change_own like bulk_update, not on add_leadstatus
    # via the generic "any POST needs add" fallback.
    change_actions = ("reorder",)

    search_fields = [
        "name",
    ]

    filterset_fields = [
        "name",
        "order",
        "is_final",
        "probability",
        "is_active",
        "created_by",
        "company",
    ]

    @swagger_auto_schema(
        manual_parameters=[search_param],
        operation_description=LEAD_STATUS_LIST_DOCS,
    )
    def list(self, request, *args, **kwargs):
        """List lead statuses with search and filter capabilities"""
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=LEAD_STATUS_DETAIL_DOCS)
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a specific lead status"""
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=LEAD_STATUS_CREATE_DOCS)
    def create(self, request, *args, **kwargs):
        """Create a new lead status"""
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(
        request_body=bulk_update_body, operation_description=BULK_UPDATE_DOCS
    )
    @action(detail=False, methods=["post"])
    def bulk_update(self, request):
        """Update multiple lead statuses in a single request"""
        return super().bulk_update(request)

    @swagger_auto_schema(
        request_body=bulk_delete_body, operation_description=BULK_DELETE_DOCS
    )
    @action(detail=False, methods=["post"])
    def bulk_delete(self, request):
        """Delete multiple lead statuses in a single request"""
        return super().bulk_delete(request)

    @swagger_auto_schema(operation_description=LEAD_STATUS_FINAL_STAGES_DOCS)
    @action(detail=False, methods=["get"])
    def final_stages(self, request):
        """Get lead statuses that are marked as final stages"""
        queryset = self.filter_queryset(self.get_queryset().filter(is_final=True))
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(operation_description=LEAD_STATUS_REORDER_DOCS)
    @action(detail=False, methods=["post"])
    def reorder(self, request):
        """Reorder lead statuses by updating their order values"""
        order_data = request.data.get("order_data", [])

        if not order_data:
            return Response(
                {"error": "order_data is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Scope to rows the caller actually has change/change_own access to,
        # the same way bulk_update does -- otherwise this raw .update() can
        # reorder any company's lead stages by id regardless of ownership,
        # since LeadStatus.objects is unfiltered here by default.
        queryset = scope_queryset_to_permission(
            self.get_queryset(), request.user, "change"
        )

        try:
            updated_count = 0
            for item in order_data:
                status_id = item.get("id")
                new_order = item.get("order")

                if status_id is None or new_order is None:
                    return Response(
                        {"error": "Each item must have 'id' and 'order' fields"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                updated_count += queryset.filter(id=status_id).update(order=new_order)

            return Response(
                {
                    "message": "Lead statuses reordered successfully",
                    "updated_count": updated_count,
                }
            )

        except Exception as e:
            return Response(
                {"error": f"Failed to reorder lead statuses: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
