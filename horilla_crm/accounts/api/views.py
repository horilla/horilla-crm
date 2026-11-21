"""
API views for horilla_crm.accounts models

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
from horilla_crm.accounts.api.docs import (
    ACCOUNT_CHILD_ACCOUNTS_DOCS,
    ACCOUNT_CREATE_DOCS,
    ACCOUNT_DETAIL_DOCS,
    ACCOUNT_LIST_DOCS,
    ACCOUNT_PARTNER_ACCOUNTS_DOCS,
    PARTNER_RELATIONSHIP_BY_ACCOUNT_DOCS,
    PARTNER_RELATIONSHIP_BY_PARTNER_DOCS,
    PARTNER_RELATIONSHIP_CREATE_DOCS,
    PARTNER_RELATIONSHIP_DETAIL_DOCS,
    PARTNER_RELATIONSHIP_LIST_DOCS,
)
from horilla_crm.accounts.api.serializers import (
    AccountSerializer,
    PartnerAccountRelationshipSerializer,
)
from horilla_crm.accounts.models import Account, PartnerAccountRelationship

# Define common Swagger parameters and bodies consistent with core
search_param = openapi.Parameter(
    "search",
    openapi.IN_QUERY,
    description="Search term for full-text search across relevant fields",
    type=openapi.TYPE_STRING,
)

filter_param = openapi.Parameter(
    "filter",
    openapi.IN_QUERY,
    description="Filter parameters in format field=value",
    type=openapi.TYPE_STRING,
)

bulk_update_body = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "ids": openapi.Schema(
            type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_INTEGER)
        ),
        "filters": openapi.Schema(type=openapi.TYPE_OBJECT, additional_properties=True),
        "data": openapi.Schema(type=openapi.TYPE_OBJECT, additional_properties=True),
    },
    required=["data"],
)

bulk_delete_body = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "ids": openapi.Schema(
            type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_INTEGER)
        ),
        "filters": openapi.Schema(type=openapi.TYPE_OBJECT, additional_properties=True),
    },
)


class AccountViewSet(SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet):
    """ViewSet for Account model"""

    queryset = Account.objects.all()
    serializer_class = AccountSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsCompanyMember,
        HorillaModelPermissions,
    ]
    # Scope list-type actions to view/view_own permission (see
    # SearchFilterMixin.get_queryset); partner_accounts also returns a bare
    # list of Accounts, so it needs the same scoping as list.
    scope_list_to_view_permission = True
    list_actions = ("list", "partner_accounts")

    # Search across common account fields
    search_fields = [
        "name",
        "account_number",
        "website",
        "contact_number",
        "billing_city",
        "billing_state",
        "shipping_city",
        "shipping_state",
        "description",
    ]

    # Filtering on key fields and common core fields
    filterset_fields = [
        "account_owner",
        "account_type",
        "account_source",
        "industry",
        "ownership",
        "is_partner",
        "rating",
        "number_of_employees",
        "parent_account",
        "is_active",
        "created_by",
        "company",
    ]

    @swagger_auto_schema(
        manual_parameters=[search_param],
        operation_description=ACCOUNT_LIST_DOCS,
    )
    def list(self, request, *args, **kwargs):
        """List accounts with search and filter capabilities"""
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=ACCOUNT_DETAIL_DOCS)
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a specific account"""
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=ACCOUNT_CREATE_DOCS)
    def create(self, request, *args, **kwargs):
        """Create a new account"""
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(
        request_body=bulk_update_body, operation_description=BULK_UPDATE_DOCS
    )
    @action(detail=False, methods=["post"])
    def bulk_update(self, request):
        """Update multiple accounts in a single request"""
        return super().bulk_update(request)

    @swagger_auto_schema(
        request_body=bulk_delete_body, operation_description=BULK_DELETE_DOCS
    )
    @action(detail=False, methods=["post"])
    def bulk_delete(self, request):
        """Delete multiple accounts in a single request"""
        return super().bulk_delete(request)

    @swagger_auto_schema(operation_description=ACCOUNT_PARTNER_ACCOUNTS_DOCS)
    @action(detail=False, methods=["get"])
    def partner_accounts(self, request):
        """Get accounts that are marked as partners"""
        queryset = self.filter_queryset(self.get_queryset().filter(is_partner=True))
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(operation_description=ACCOUNT_CHILD_ACCOUNTS_DOCS)
    @action(detail=True, methods=["get"])
    def child_accounts(self, request, pk=None):
        """Get child accounts for a specific account"""
        account = self.get_object()
        # get_object() only checks access to the parent; without this,
        # any child account the parent links to is returned regardless of
        # whether the caller individually holds view/view_own on it.
        queryset = scope_queryset_to_permission(
            account.child_accounts.all(), request.user, "view"
        )
        queryset = self.filter_queryset(queryset)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class PartnerAccountRelationshipViewSet(
    SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet
):
    """ViewSet for PartnerAccountRelationship model"""

    queryset = PartnerAccountRelationship.objects.all()
    serializer_class = PartnerAccountRelationshipSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsCompanyMember,
        HorillaModelPermissions,
    ]

    # by_account/by_partner return bare collections via get_queryset(), so
    # gate them like "list" and scope rows to view/view_own permission.
    scope_list_to_view_permission = True
    list_actions = ("list", "by_account", "by_partner")

    search_fields = [
        "account__name",
        "partner__name",
        "role__name",
    ]

    filterset_fields = [
        "account",
        "partner",
        "role",
        "is_active",
        "created_by",
        "company",
    ]

    @swagger_auto_schema(
        manual_parameters=[search_param],
        operation_description=PARTNER_RELATIONSHIP_LIST_DOCS,
    )
    def list(self, request, *args, **kwargs):
        """List partner account relationships with search and filter capabilities"""
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=PARTNER_RELATIONSHIP_DETAIL_DOCS)
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a specific partner account relationship"""
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(operation_description=PARTNER_RELATIONSHIP_CREATE_DOCS)
    def create(self, request, *args, **kwargs):
        """Create a new partner account relationship"""
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(
        request_body=bulk_update_body, operation_description=BULK_UPDATE_DOCS
    )
    @action(detail=False, methods=["post"])
    def bulk_update(self, request):
        """Update multiple partner account relationships in a single request"""
        return super().bulk_update(request)

    @swagger_auto_schema(
        request_body=bulk_delete_body, operation_description=BULK_DELETE_DOCS
    )
    @action(detail=False, methods=["post"])
    def bulk_delete(self, request):
        """Delete multiple partner account relationships in a single request"""
        return super().bulk_delete(request)

    @swagger_auto_schema(operation_description=PARTNER_RELATIONSHIP_BY_ACCOUNT_DOCS)
    @action(detail=False, methods=["get"])
    def by_account(self, request):
        """Get partner relationships filtered by account ID"""
        account_id = request.query_params.get("account_id")
        if not account_id:
            return Response(
                {"error": "account_id parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        queryset = self.filter_queryset(
            self.get_queryset().filter(account_id=account_id)
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(operation_description=PARTNER_RELATIONSHIP_BY_PARTNER_DOCS)
    @action(detail=False, methods=["get"])
    def by_partner(self, request):
        """Get partner relationships filtered by partner ID"""
        partner_id = request.query_params.get("partner_id")
        if not partner_id:
            return Response(
                {"error": "partner_id parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        queryset = self.filter_queryset(
            self.get_queryset().filter(partner_id=partner_id)
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
