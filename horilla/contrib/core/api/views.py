"""
API views for core models

This module includes enhanced API views with search, filtering, bulk update, and bulk delete capabilities.
"""

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema

# Third-party imports (Django)
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from horilla.api.docs import BULK_DELETE_DOCS, BULK_UPDATE_DOCS, SEARCH_FILTER_DOCS
from horilla.api.mixins import BulkOperationsMixin, SearchFilterMixin
from horilla.api.permissions import (
    HorillaModelPermissions,
    IsCompanyMember,
    IsOwnerOrAdmin,
)

# First party imports (Horilla)
from horilla.auth.models import User

# Local imports
from ..models import (
    BusinessHour,
    Company,
    CustomerRole,
    Department,
    Holiday,
    HorillaAttachment,
    ImportHistory,
    PartnerRole,
    Role,
    TeamRole,
)
from .serializers import (
    BusinessHourSerializer,
    CompanySerializer,
    CustomerRoleSerializer,
    DepartmentSerializer,
    HolidaySerializer,
    HorillaAttachmentSerializer,
    HorillaUserSerializer,
    ImportHistorySerializer,
    PartnerRoleSerializer,
    RoleSerializer,
    TeamRoleSerializer,
)

# Define common Swagger parameters for search and filtering
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


class CompanyViewSet(SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet):
    """ViewSet for Company model"""

    queryset = Company.objects.all()
    serializer_class = CompanySerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsOwnerOrAdmin,
        HorillaModelPermissions,
    ]
    scope_list_to_view_permission = True
    search_fields = ["name", "description", "email", "phone", "website", "address"]
    filterset_fields = ["name", "is_active", "created_by", "created_at"]

    @swagger_auto_schema(
        manual_parameters=[search_param], operation_description=SEARCH_FILTER_DOCS
    )
    def list(self, request, *args, **kwargs):
        """List companies with search and filter capabilities"""
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        request_body=bulk_update_body, operation_description=BULK_UPDATE_DOCS
    )
    @action(detail=False, methods=["post"])
    def bulk_update(self, request):
        """Update multiple companies in a single request"""
        return super().bulk_update(request)

    @swagger_auto_schema(
        request_body=bulk_delete_body, operation_description=BULK_DELETE_DOCS
    )
    @action(detail=False, methods=["post"])
    def bulk_delete(self, request):
        """Delete multiple companies in a single request"""
        return super().bulk_delete(request)


class DepartmentViewSet(SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet):
    """ViewSet for Department model"""

    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsCompanyMember,
        HorillaModelPermissions,
    ]
    scope_list_to_view_permission = True
    search_fields = ["name", "description"]
    filterset_fields = ["name", "company", "is_active"]


class RoleViewSet(SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet):
    """ViewSet for Role model"""

    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsCompanyMember,
        HorillaModelPermissions,
    ]
    scope_list_to_view_permission = True
    search_fields = ["name", "description"]
    filterset_fields = ["name", "company", "is_active"]


class HorillaUserViewSet(SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet):
    """ViewSet for User model"""

    queryset = User.objects.all()
    serializer_class = HorillaUserSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsCompanyMember,
        IsOwnerOrAdmin,
        HorillaModelPermissions,
    ]
    scope_list_to_view_permission = True
    search_fields = ["username", "email", "first_name", "last_name"]
    filterset_fields = ["is_active", "company", "department", "role"]

    def get_queryset(self):
        """Limit users to the requester's active company; only superusers see all."""
        queryset = super().get_queryset()
        user = self.request.user
        if user.is_superuser:
            return queryset
        company = getattr(self.request, "active_company", None) or getattr(
            user, "company", None
        )
        if company is None:
            return queryset.none()
        return queryset.filter(company=company)

    @action(detail=False, methods=["get"])
    def me(self, request):
        """Get current user information"""
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)


class BusinessHourViewSet(
    SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet
):
    """ViewSet for BusinessHour model"""

    queryset = BusinessHour.objects.all()
    serializer_class = BusinessHourSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsCompanyMember,
        HorillaModelPermissions,
    ]
    scope_list_to_view_permission = True
    search_fields = ["name", "description"]
    filterset_fields = ["name", "company", "is_active"]


class TeamRoleViewSet(SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet):
    """ViewSet for TeamRole model"""

    queryset = TeamRole.objects.all()
    serializer_class = TeamRoleSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsCompanyMember,
        HorillaModelPermissions,
    ]
    scope_list_to_view_permission = True
    search_fields = ["name", "description"]
    filterset_fields = ["name", "company", "is_active"]


class CustomerRoleViewSet(
    SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet
):
    """ViewSet for CustomerRole model"""

    queryset = CustomerRole.objects.all()
    serializer_class = CustomerRoleSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsCompanyMember,
        HorillaModelPermissions,
    ]
    scope_list_to_view_permission = True
    search_fields = ["name", "description"]
    filterset_fields = ["name", "company", "is_active"]


class PartnerRoleViewSet(SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet):
    """ViewSet for PartnerRole model"""

    queryset = PartnerRole.objects.all()
    serializer_class = PartnerRoleSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsCompanyMember,
        HorillaModelPermissions,
    ]
    scope_list_to_view_permission = True
    search_fields = ["name", "description"]
    filterset_fields = ["name", "company", "is_active"]


class ImportHistoryViewSet(
    SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet
):
    """ViewSet for ImportHistory model"""

    queryset = ImportHistory.objects.all()
    serializer_class = ImportHistorySerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsOwnerOrAdmin,
        HorillaModelPermissions,
    ]
    scope_list_to_view_permission = True
    search_fields = ["file_name", "model_name"]
    filterset_fields = ["model_name", "status", "created_by"]


class HorillaAttachmentViewSet(
    SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet
):
    """ViewSet for HorillaAttachment model"""

    queryset = HorillaAttachment.objects.all()
    serializer_class = HorillaAttachmentSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsOwnerOrAdmin,
        HorillaModelPermissions,
    ]
    scope_list_to_view_permission = True
    search_fields = ["name", "file_name"]
    filterset_fields = ["content_type", "object_id", "created_by"]


class HolidayViewSet(SearchFilterMixin, BulkOperationsMixin, viewsets.ModelViewSet):
    """ViewSet for Holiday model"""

    queryset = Holiday.objects.all()
    serializer_class = HolidaySerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsCompanyMember,
        HorillaModelPermissions,
    ]
    scope_list_to_view_permission = True
    search_fields = ["name", "description"]
    filterset_fields = ["name", "date", "company", "is_active"]
