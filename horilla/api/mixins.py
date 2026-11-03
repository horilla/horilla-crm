"""
API mixins for implementing advanced features like search, filtering, bulk update, and bulk delete
"""

# Standard library imports
from functools import reduce
from operator import or_

# Third-party imports (other)
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

# First party imports (Horilla)
from horilla.contrib.generics.views.helpers.queryset_utils import (
    get_granted_access_filter,
)
from horilla.db import transaction
from horilla.db.models import Q


def scope_queryset_to_permission(queryset, user, action: str):
    """
    Narrow ``queryset`` to the rows ``user`` is allowed to act on for
    ``action`` ("view", "change" or "delete"), mirroring the object-level
    rule in horilla.contrib.generics.views.details._check_record_permission:
    the global ``{action}_{model}`` permission grants every row, the
    ``{action}_own_{model}`` permission grants only rows the user owns (via
    OWNER_FIELDS) or has been explicitly granted access to.

    Returns ``queryset.none()`` if the user has neither permission, so
    callers never fall back to an unrestricted queryset.
    """
    if user.is_superuser:
        return queryset

    model = queryset.model
    app_label = model._meta.app_label
    model_name = model._meta.model_name

    has_global = user.has_perm(f"{app_label}.{action}_{model_name}")
    has_own = user.has_perm(f"{app_label}.{action}_own_{model_name}")

    if has_global:
        return queryset
    if not has_own:
        return queryset.none()

    owner_fields = getattr(model, "OWNER_FIELDS", None)
    ownership_query = None
    if owner_fields:
        ownership_query = reduce(
            or_, (Q(**{field: user}) for field in owner_fields), Q()
        )

    granted_query = get_granted_access_filter(model, user, action)
    if granted_query is not None:
        ownership_query = (
            granted_query
            if ownership_query is None
            else ownership_query | granted_query
        )

    if ownership_query is None:
        return queryset.none()
    return queryset.filter(ownership_query)


class CompanyScopedSerializerMixin:
    """
    Serializer mixin for HorillaCoreModel subclasses that ignores any
    client-supplied ``company`` value and derives it server-side from the
    request instead, matching the classic (non-DRF) create-form flow in
    horilla.contrib.generics.views.single_form.HorillaFormView.form_valid,
    which always assigns request.active_company (falling back to
    request.user.company) regardless of what the form posted.

    Without this, `company` is a plain writable FK on HorillaCoreModel and
    a ModelSerializer using `fields = "__all__"` lets any authenticated
    creator target an arbitrary company id, bypassing tenant isolation.
    """

    def validate(self, attrs):
        """Force ``company`` to the request's active company, ignoring any submitted value."""
        attrs = super().validate(attrs)
        request = self.context.get("request")
        if request is not None and hasattr(request, "user"):
            active_company = getattr(request, "active_company", None) or getattr(
                request.user, "company", None
            )
            if active_company is not None:
                attrs["company"] = active_company
            else:
                attrs.pop("company", None)
        return attrs


class SearchFilterMixin:
    """
    Mixin to add search and filtering capabilities to ViewSets
    """

    search_fields = []  # Fields to search in, should be overridden in the ViewSet
    filterset_fields = []  # Fields to filter by, should be overridden in the ViewSet

    # Actions that return a list of objects (rather than a single object
    # reached via get_object()) and must therefore be scoped, at queryset
    # level, to rows the user has view/view_own permission on. Opt-in via
    # this attribute (or the `list_actions` attribute for extra actions
    # beyond "list") rather than on-by-default, since not every ViewSet
    # using this mixin is protected by HorillaModelPermissions' view/view_own
    # codenames -- e.g. ViewSets with a bespoke ownership model (a plain
    # `user` field checked by their own permission class) must scope their
    # own queryset instead and should leave this False.
    scope_list_to_view_permission = False

    def get_queryset(self):
        """
        Override get_queryset to add search and filtering capabilities,
        and, when opted in via scope_list_to_view_permission, to scope
        list-type actions down to rows the requesting user actually has
        view (or view_own) permission on. Detail actions (retrieve/update/
        destroy) are left to check_object_permissions, which applies the
        same OWNER_FIELDS rule per object.
        """
        queryset = super().get_queryset()

        action = getattr(self, "action", None)
        request = getattr(self, "request", None)
        if (
            self.scope_list_to_view_permission
            and request is not None
            and action in getattr(self, "list_actions", ("list",))
        ):
            queryset = scope_queryset_to_permission(queryset, request.user, "view")

        # Apply search if search parameter is provided
        search_term = self.request.query_params.get("search", None)
        if search_term and self.search_fields:
            q_objects = Q()
            for field in self.search_fields:
                q_objects |= Q(**{f"{field}__icontains": search_term})
            queryset = queryset.filter(q_objects)

        # Apply filtering for each filter parameter
        for param, value in self.request.query_params.items():
            if param in self.filterset_fields and value:
                queryset = queryset.filter(**{param: value})

        return queryset


class BulkOperationsMixin:
    """
    Mixin to add bulk update and bulk delete capabilities to ViewSets
    with support for filtering operations
    """

    def _sanitize_bulk_update_data(self, raw_data):
        """
        Reduce ``raw_data`` to the fields the ViewSet's serializer actually
        allows a client to write, running it through the same
        read_only_fields/write_only/validate() pipeline that a normal
        PATCH goes through.

        bulk_update operates on a queryset with .update(**data) instead of
        per-instance serializer.save(), so without this step it would
        completely bypass every serializer-level protection -- read_only
        fields (e.g. HorillaUserSerializer.is_superuser/is_staff),
        write_only secrets, and CompanyScopedSerializerMixin's forcing of
        `company` from the request. Returns (validated_data, error_response);
        error_response is None on success.
        """
        serializer = self.get_serializer(data=raw_data, partial=True)
        if not serializer.is_valid():
            return None, Response(
                {
                    "error": "Invalid 'data' for bulk update",
                    "details": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        validated = dict(serializer.validated_data)
        model = self.get_queryset().model
        # Only plain columns/FKs can be set via queryset.update(); M2M
        # fields (e.g. User.user_permissions/groups, Report.shared_with)
        # raise FieldError there and always required per-instance .set()
        # instead, so drop them rather than let bulk_update crash -- this
        # doesn't newly expose anything, since M2M bulk assignment via
        # .update() was never possible.
        concrete_field_names = {
            f.name for f in model._meta.get_fields() if not f.many_to_many
        }
        validated = {k: v for k, v in validated.items() if k in concrete_field_names}
        # write_only fields (e.g. password, mail credentials/tokens) still
        # appear in validated_data -- write_only only hides them from
        # output. A serializer's create()/update() override normally does
        # extra work for these (e.g. HorillaUserSerializer hashes password
        # via set_password()); queryset.update() would instead write the
        # raw value straight into the column, so drop any field the
        # serializer declared write_only rather than silently corrupt it.
        write_only_fields = {
            name
            for name, field in serializer.fields.items()
            if getattr(field, "write_only", False)
        }
        validated = {k: v for k, v in validated.items() if k not in write_only_fields}
        return validated, None

    def _apply_filters_to_queryset(self, queryset, filters):
        """
        Apply filters to queryset based on provided filter criteria

        Filter format:
        {
            "field1": "value1",
            "field2__contains": "value2",
            "field3__in": [1, 2, 3],
            ...
        }
        """
        if not filters:
            return queryset

        try:
            return queryset.filter(**filters)
        except Exception:
            # Log the error or handle invalid filter fields
            return queryset

    @action(detail=False, methods=["post"])
    def bulk_update(self, request):
        """
        Update multiple instances in a single request with optional filtering

        Expected request format:
        {
            "ids": [1, 2, 3, ...],  # Optional if filters are provided
            "filters": {            # Optional if ids are provided
                "field1": "value1",
                "field2__contains": "value2",
                ...
            },
            "data": {
                "field1": "value1",
                "field2": "value2",
                ...
            }
        }
        """
        ids = request.data.get("ids", [])
        filters = request.data.get("filters", {})
        update_data = request.data.get("data", {})

        if not update_data:
            return Response(
                {"error": "'data' is required for bulk update"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not ids and not filters:
            return Response(
                {"error": "Either 'ids' or 'filters' must be provided for bulk update"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Run the requested changes through the ViewSet's serializer so
        # read_only_fields, write_only secrets, and mixins like
        # CompanyScopedSerializerMixin are enforced exactly as they would be
        # for a single PATCH -- queryset.update() has no other opportunity
        # to apply that field-level policy.
        update_data, error_response = self._sanitize_bulk_update_data(update_data)
        if error_response is not None:
            return error_response
        if not update_data:
            return Response(
                {"error": "No writable fields were provided for bulk update"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Start with the base queryset, narrowed to rows the user actually
        # has change (or change_own) permission on -- bulk operations must
        # not be able to touch more than get_object()/check_object_permissions
        # would allow one at a time.
        queryset = scope_queryset_to_permission(
            self.get_queryset(), request.user, "change"
        )

        # Apply ID filtering if provided
        if ids:
            queryset = queryset.filter(id__in=ids)

        # Apply additional filters if provided
        if filters:
            queryset = self._apply_filters_to_queryset(queryset, filters)

        # Check if any records match the criteria
        record_count = queryset.count()
        if record_count == 0:
            return Response(
                {"error": "No records match the provided criteria"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Save per instance rather than queryset.update() so model-level
        # clean()/save() sanitization (e.g. HTML stripping on rich-text
        # fields) runs exactly as it does for a single PATCH.
        with transaction.atomic():
            updated_count = 0
            for instance in queryset:
                for field_name, value in update_data.items():
                    setattr(instance, field_name, value)
                instance.save(update_fields=list(update_data))
                updated_count += 1

        return Response(
            {
                "message": f"Successfully updated {updated_count} records",
                "updated_count": updated_count,
            }
        )

    @action(detail=False, methods=["post"])
    def bulk_delete(self, request):
        """
        Delete multiple instances in a single request with optional filtering

        Expected request format:
        {
            "ids": [1, 2, 3, ...],  # Optional if filters are provided
            "filters": {            # Optional if ids are provided
                "field1": "value1",
                "field2__contains": "value2",
                ...
            }
        }

        Or for simple ID-based deletion:
        [1, 2, 3, ...]
        """
        # Handle direct array format for backward compatibility
        if isinstance(request.data, list):
            ids = request.data
            filters = {}
        else:
            ids = request.data.get("ids", [])
            filters = request.data.get("filters", {})

        if not ids and not filters:
            return Response(
                {"error": "Either 'ids' or 'filters' must be provided for bulk delete"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Start with the base queryset, narrowed to rows the user actually
        # has delete (or delete_own) permission on -- bulk operations must
        # not be able to touch more than get_object()/check_object_permissions
        # would allow one at a time.
        queryset = scope_queryset_to_permission(
            self.get_queryset(), request.user, "delete"
        )

        # Apply ID filtering if provided
        if ids:
            queryset = queryset.filter(id__in=ids)

        # Apply additional filters if provided
        if filters:
            queryset = self._apply_filters_to_queryset(queryset, filters)

        # Check if any records match the criteria
        record_count = queryset.count()
        if record_count == 0:
            return Response(
                {"error": "No records match the provided criteria"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Perform bulk delete within a transaction
        with transaction.atomic():
            deleted_count, _ = queryset.delete()

        return Response(
            {
                "message": f"Successfully deleted {deleted_count} records",
                "deleted_count": deleted_count,
            }
        )
