"""
Views and utilities for managing groups and permissions in Horilla.
"""

# Standard library imports
from functools import cached_property
from urllib.parse import urlencode

# Third-party imports (Django)
from django.contrib import messages
from django.contrib.auth.models import Permission
from django.core.paginator import Paginator

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.auth.models import User
from horilla.contrib.generics.views import HorillaListView, HorillaTabView
from horilla.shortcuts import get_object_or_404, redirect, render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.html import escapejs
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView, View
from horilla.web import HttpResponse, JsonResponse, ScriptResponse

from ...models import FieldPermission, HorillaContentType, Role

# Local imports
from .permission_utils import PermissionUtils


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "auth.view_permission",
            "auth.view_group",
            "auth.change_permission",
            "auth.change_group",
        ]
    ),
    name="dispatch",
)
class ModelFieldsModalView(LoginRequiredMixin, TemplateView):
    """
    View to display model fields in a modal for field-level permissions
    Supports both role-based and user-based contexts
    """

    template_name = "permissions/field_permissions_modal.html"

    def get_extra_permission_fields(self, model, existing_permissions):
        """
        Extra entries for the field list that aren't model columns, as dicts
        with ``name``, ``verbose_name``, ``field_type``, ``current_permission``
        and ``is_mandatory``. ``existing_permissions`` maps field name to the
        saved permission. Extensions override this.
        """
        return []

    def get(self, request, app_label, model_name, *args, **kwargs):
        """Load field permissions modal for role or user context; support bulk selected users."""
        role_id = kwargs.get("role_id")
        user_id = kwargs.get("user_id")
        context_type = request.GET.get("context", "role")

        selected_user_ids = None
        selected_users_count = 0
        if context_type == "bulk":
            user_ids_str = request.GET.get("selected_user_ids", "")
            if user_ids_str:
                try:
                    selected_user_ids = [
                        int(uid.strip())
                        for uid in user_ids_str.split(",")
                        if uid.strip()
                    ]
                    selected_users_count = len(selected_user_ids)
                except (ValueError, AttributeError):
                    selected_user_ids = None

        role = None
        user = None

        if role_id:
            try:
                role = get_object_or_404(Role, id=role_id)
            except Exception:
                messages.error(request, _("Role does not exist"))
                return ScriptResponse(reload=True)

        if user_id:
            try:
                user = get_object_or_404(User, id=user_id)
            except Exception:
                messages.error(request, _("User does not exist"))
                return ScriptResponse(reload=True)

        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:
            messages.error(request, _("Model not found"))
            return HttpResponse("")

        if not model._meta.managed:
            messages.info(
                request, _("Field-level permissions are not available for this model.")
            )
            return ScriptResponse(close=True, reload=True, msgs=True)

        content_type = HorillaContentType.objects.get_for_model(model)

        existing_permissions = {}
        role_inherited_permissions = {}

        if role:
            field_perms = FieldPermission.objects.filter(
                role=role, content_type=content_type
            )
            for perm in field_perms:
                existing_permissions[perm.field_name] = perm.permission_type

        elif user:
            user_field_perms = FieldPermission.objects.filter(
                user=user, content_type=content_type
            )
            for perm in user_field_perms:
                existing_permissions[perm.field_name] = perm.permission_type

            if hasattr(user, "role") and user.role:
                role_field_perms = FieldPermission.objects.filter(
                    role=user.role, content_type=content_type
                )
                for perm in role_field_perms:
                    role_inherited_permissions[perm.field_name] = perm.permission_type
                    if perm.field_name not in existing_permissions:
                        existing_permissions[perm.field_name] = perm.permission_type

        excluded_fields = getattr(model, "field_permissions_exclude", None)
        if not isinstance(excluded_fields, (list, tuple, set)):
            excluded_fields = set()
        else:
            excluded_fields = set(excluded_fields)

        globally_excluded_fields = {"id", "pk"}
        excluded_fields.update(globally_excluded_fields)

        model_defaults = getattr(model, "default_field_permissions", {})

        fields = []

        for field in model._meta.get_fields():
            if field.many_to_many or field.one_to_many or field.one_to_one:
                continue

            field_name = field.name

            if field_name in excluded_fields:
                continue

            verbose_name = (
                getattr(field, "verbose_name", None)
                or field_name.replace("_", " ").title()
            )

            if field_name in existing_permissions:
                current_permission = existing_permissions[field_name]
            elif field_name in model_defaults:
                current_permission = model_defaults[field_name]
            else:
                current_permission = "readwrite"

            # Check if field is mandatory (required)
            is_mandatory = False
            try:
                # Field is mandatory if it doesn't allow null and doesn't allow blank
                is_mandatory = not field.null and not field.blank
            except AttributeError:
                # Some field types might not have null/blank attributes
                pass

            # current_permission = existing_permissions.get(field_name, "readwrite")

            fields.append(
                {
                    "name": field_name,
                    "verbose_name": verbose_name,
                    "field_type": field.__class__.__name__,
                    "current_permission": current_permission,
                    "is_mandatory": is_mandatory,
                }
            )

        fields.extend(self.get_extra_permission_fields(model, existing_permissions))

        context = {
            "role": role,
            "user": user,
            "model": model,
            "model_name": model_name,
            "app_label": app_label,
            "verbose_name": model._meta.verbose_name,
            "fields": fields,
            "context_type": context_type,
            "role_id": role_id,
            "user_id": user_id,
            "is_bulk": context_type == "bulk",
            "no_users_selected": context_type == "bulk" and selected_users_count == 0,
            "selected_user_ids": (
                ",".join(map(str, selected_user_ids)) if selected_user_ids else ""
            ),
            "selected_users_count": selected_users_count,
        }

        return render(request, self.template_name, context)


@method_decorator(
    permission_required_or_denied(
        [
            "auth.view_permission",
            "auth.view_group",
            "auth.change_permission",
            "auth.change_group",
        ]
    ),
    name="dispatch",
)
class RolePermissionView(LoginRequiredMixin, TemplateView):
    """
    View to display role and permission management interface
    """

    template_name = "permissions/group_perm_view.html"


@method_decorator(
    permission_required_or_denied(
        [
            "auth.view_permission",
            "auth.view_group",
            "auth.change_permission",
            "auth.change_group",
        ]
    ),
    name="dispatch",
)
class RolePermissionTabView(LoginRequiredMixin, HorillaTabView):
    """
    Tab view for permission
    """

    view_id = "group-permission-view"
    background_class = "bg-primary-100 rounded-md"

    @cached_property
    def tabs(self):
        """Define tabs for groups and permissions."""
        if self.request.user.has_perm("core.view_company"):
            return [
                {
                    "title": _("Roles"),
                    "url": reverse_lazy("core:role_tab"),
                    "target": "group-view-content",
                    "id": "group-detail-view",
                },
                {
                    "title": _("Permissions"),
                    "url": reverse_lazy("core:permission_tab"),
                    "target": "permission-view-content",
                    "id": "permission-detail-view",
                },
                {
                    "title": _("Super Users"),
                    "url": reverse_lazy("core:super_user_tab"),
                    "target": "super-user-view-content",
                    "id": "super-user-detail-view",
                },
            ]
        return []


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "auth.view_permission",
            "auth.view_group",
            "auth.change_permission",
            "auth.change_group",
        ]
    ),
    name="dispatch",
)
class GroupTab(LoginRequiredMixin, TemplateView):
    """
    Tab view for groups
    """

    template_name = "permissions/group.html"

    def get_context_data(self, **kwargs):
        """Add roles and all_models (permission data) to context."""
        context = super().get_context_data(**kwargs)
        context["roles"] = Role.objects.all().order_by("role_name")
        context["all_models"] = PermissionUtils.get_all_models_data()
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "auth.view_permission",
            "auth.view_group",
            "auth.change_permission",
            "auth.change_group",
        ]
    ),
    name="dispatch",
)
class RolePermissionsView(LoginRequiredMixin, TemplateView):
    """
    View to display and manage permissions for a specific role
    """

    template_name = "permissions/group_role_detail.html"

    def get(self, request, *args, **kwargs):
        """Validate role_id and return reload script on error; otherwise delegate to parent."""
        role_id = kwargs.get("role_id")
        try:
            _role = get_object_or_404(Role, id=role_id)
        except Exception:
            messages.error(request, _("Role does not exist"))
            return HttpResponse(
                "<div id=\"followup-contents\"><script>$('#reloadButton').click();</script></div>"
            )

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Add role and all_models (permission data for role) to context."""
        context = super().get_context_data(**kwargs)
        role_id = self.kwargs.get("role_id")

        role = get_object_or_404(Role, id=role_id)

        context["role"] = role
        context["role_id"] = role_id
        context["all_models"] = PermissionUtils.get_all_models_data(role=role)
        context["master_select_all_checked"] = PermissionUtils.all_models_selected(
            context["all_models"]
        )

        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "auth.view_permission",
            "auth.view_group",
            "auth.change_permission",
            "auth.change_group",
        ]
    ),
    name="dispatch",
)
class RoleMembersView(LoginRequiredMixin, TemplateView):
    """View to display members of a specific role"""

    template_name = "permissions/role_members.html"

    def get(self, request, *args, **kwargs):
        """Validate role_id and return reload script on error; otherwise delegate to parent."""
        role_id = kwargs.get("role_id")
        try:
            _role = get_object_or_404(Role, id=role_id)
        except Exception:
            messages.error(request, _("Role does not exist"))
            return ScriptResponse(reload=True)

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Add role, members list view context, and column/action config to context."""
        context = super().get_context_data(**kwargs)
        role_id = self.kwargs.get("role_id")
        role = get_object_or_404(Role, id=role_id)

        columns = [
            ("Employee", "get_avatar_with_name"),
            ("Email", "email"),
        ]

        confirm_msg = escapejs(
            _("Are you sure you want to delete the user from this role?")
        )
        actions = [
            {
                "action": "Delete",
                "src": "assets/icons/a4.svg",
                "img_class": "w-4 h-4",
                "attrs": f"""
                    hx-post="{{get_delete_user_from_role}}"
                    hx-target="#deleteModeBox"
                    hx-swap="innerHTML"
                    hx-trigger="confirmed"
                    hx-on:click="hxConfirm(this,'{confirm_msg}')"
                    hx-on::after-request="$('#reloadMessagesButton').click();"
                """,
            }
        ]

        list_view = HorillaListView(
            model=User,
            view_id=f"role-members-{role_id}",
            search_url=reverse_lazy(
                "core:role_members_view", kwargs={"role_id": role_id}
            ),
            main_url=reverse_lazy(
                "core:role_members_view", kwargs={"role_id": role_id}
            ),
            columns=columns,
            table_width=False,
            table_height_as_class="h-[calc(100vh-460px)]",
            bulk_select_option=False,
            bulk_export_option=False,
            bulk_update_option=False,
            bulk_delete_enabled=False,
            list_column_visibility=False,
            enable_sorting=True,
            save_to_list_option=False,
            actions=actions,
        )

        list_view.request = self.request
        list_view.kwargs = self.kwargs
        list_view.get_queryset = lambda: User.objects.filter(role=role).select_related(
            "role"
        )
        list_view.object_list = list_view.get_queryset()

        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        list_view.col_attrs = [
            {
                "get_avatar_with_name": {
                    "hx-get": f"{{get_detail_view_url}}?{query_string}",
                    "hx-target": "#permission-view",
                    "hx-swap": "innerHTML",
                    "hx-push-url": "true",
                    "hx-select": "#users-view",
                    "permission": f"{User._meta.app_label}.view_{User._meta.model_name}",
                }
            }
        ]

        context.update(list_view.get_context_data())
        context["role"] = role
        context["model_verbose_name"] = f"{role.role_name} Role Members"
        context["no_record_msg"] = _(
            f'No members found in the "{role.role_name}" role.'
        )
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "auth.view_permission",
            "auth.view_group",
            "auth.change_permission",
            "auth.change_group",
        ]
    ),
    name="dispatch",
)
class PermissionTab(LoginRequiredMixin, TemplateView):
    """
    Template view for permission tab
    """

    template_name = "permissions/permission.html"

    def get_context_data(self, **kwargs):
        """Add paginated non-superuser users for current company to context."""
        context = super().get_context_data(**kwargs)
        company = (
            getattr(self.request, "active_company", None) or self.request.user.company
        )
        users = User.objects.filter(is_superuser=False, company=company)
        paginator = Paginator(users, 10)
        page_number = self.request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)
        context["users"] = page_obj
        context["page_obj"] = page_obj
        return context


@method_decorator(
    permission_required_or_denied(
        [
            "auth.view_permission",
            "auth.view_group",
            "auth.change_permission",
            "auth.change_group",
        ]
    ),
    name="dispatch",
)
class UpdateRolePermissionsView(LoginRequiredMixin, View):
    """
    Toggle permission for a role and its members when checkbox is clicked.
    """

    def post(self, request, role_id):
        """Toggle permission for a specific role."""
        role = get_object_or_404(Role, id=role_id)
        perm_id = request.POST.get("permission_id")
        checked = request.POST.get("checked") == "true"

        try:
            permission = Permission.objects.get(id=perm_id)
        except Permission.DoesNotExist:
            return JsonResponse({"success": False, "message": "Permission not found"})

        members = User.objects.filter(role=role)
        if checked:
            role.permissions.add(permission)
            for member in members:
                member.user_permissions.add(permission)
            messages.success(request, _("Permission added successfully."))
        else:
            role.permissions.remove(permission)
            for member in members:
                member.user_permissions.remove(permission)
            messages.success(request, _("Permission removed successfully."))

        return ScriptResponse(msgs=True)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "auth.view_permission",
            "auth.view_group",
            "auth.change_permission",
            "auth.change_group",
        ]
    ),
    name="dispatch",
)
class AssignUsersView(LoginRequiredMixin, View):
    """
    Optimized view to handle assigning permissions to users.
    """

    template_name = "permissions/assign_perm_form.html"

    def get(self, request, *args, **kwargs):
        """Render the assign permissions form."""
        context = {
            "all_models": PermissionUtils.get_all_models_data(
                user=None,
            )
        }
        if request.headers.get("HX-Request"):
            return render(request, self.template_name, context)
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        """Handle assigning permissions to selected users."""
        user_ids = request.POST.getlist("users")
        permission_ids = request.POST.getlist("permissions")

        if not user_ids or not permission_ids:
            errors = {}
            if not user_ids:
                errors["users"] = [_("Please select at least one user.")]
            if not permission_ids:
                errors["permissions"] = [_("Please select at least one permission.")]
            context = {
                "all_models": PermissionUtils.get_all_models_data(),
                "form": {"errors": errors},
            }
            return render(request, self.template_name, context)

        users = User.objects.filter(id__in=user_ids, is_superuser=False)
        permissions = Permission.objects.filter(id__in=permission_ids)

        try:
            for user in users:
                user.user_permissions.add(*permissions)

            messages.success(
                request,
                _(
                    "Successfully assigned {permissions_count} permission(s) to {users_count} user(s)."
                ).format(
                    permissions_count=permissions.count(),
                    users_count=users.count(),
                ),
            )

            if request.headers.get("HX-Request"):
                return HttpResponse(
                    "<script>closeContentModal(); location.reload();</script>"
                )
            return redirect("core:permission_tab")

        except Exception as e:
            messages.error(
                request, _("Error assigning permissions: {error}").format(error=str(e))
            )
            return self.get(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "auth.view_permission",
            "auth.view_group",
            "auth.change_permission",
            "auth.change_group",
        ]
    ),
    name="dispatch",
)
class UpdateRoleModelPermissionsView(LoginRequiredMixin, View):
    """
    Toggle all permissions for a specific model for a role when select all checkbox is clicked.
    """

    def post(self, request, role_id):
        """Toggle all permissions for a specific model for a role."""
        try:
            role = get_object_or_404(Role, id=role_id)
        except Exception:
            messages.error(self.request, _("Role Does not Exist"))
            return ScriptResponse(reload=True)

        model_name = request.POST.get("model_name")
        app_label = request.POST.get("app_label")
        checked = request.POST.get("checked") == "true"

        if not model_name or not app_label:
            return JsonResponse(
                {"success": False, "message": "Model information not provided"}
            )

        try:
            permissions = PermissionUtils.get_model_permissions(app_label, model_name)
            if not permissions:
                return JsonResponse(
                    {"success": False, "message": "No permissions found for this model"}
                )

            permission_objects = Permission.objects.filter(
                id__in=[p["id"] for p in permissions]
            )
            members = User.objects.filter(role=role)

            if checked:
                role.permissions.add(*permission_objects)
                for member in members:
                    member.user_permissions.add(*permission_objects)
                messages.success(request, f"All permissions added for {model_name}.")
            else:
                role.permissions.remove(*permission_objects)
                for member in members:
                    member.user_permissions.remove(*permission_objects)
                messages.success(request, f"All permissions removed for {model_name}.")

            return ScriptResponse(msgs=True)

        except Exception as e:
            return JsonResponse(
                {"success": False, "message": f"Error updating permissions: {str(e)}"}
            )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "auth.view_permission",
            "auth.view_group",
            "auth.change_permission",
            "auth.change_group",
        ]
    ),
    name="dispatch",
)
class UpdateRoleAllPermissionsView(LoginRequiredMixin, View):
    """
    Toggle ALL permissions for a role when master select all checkbox is clicked.
    """

    def post(self, request, role_id):
        """Toggle ALL permissions for a role."""
        try:
            role = get_object_or_404(Role, id=role_id)
        except Exception:
            messages.error(self.request, _("Role Does not Exist"))
            return ScriptResponse(reload=True)
        checked = request.POST.get("checked") == "true"

        try:
            all_permissions = PermissionUtils.get_all_permission_ids()

            if not all_permissions:
                return JsonResponse(
                    {"success": False, "message": "No permissions found"}
                )

            members = User.objects.filter(role=role)
            if checked:
                PermissionUtils.grant_permissions_to_role(role, all_permissions)
                PermissionUtils.grant_permissions_to_users(
                    members.values_list("id", flat=True), all_permissions
                )
                messages.success(
                    request, f"All permissions granted to {role.role_name} role."
                )
            else:
                PermissionUtils.revoke_permissions_from_users(
                    members.values_list("id", flat=True), all_permissions
                )
                PermissionUtils.revoke_permissions_from_role(role, all_permissions)
                messages.success(
                    request, f"All permissions revoked from {role.role_name} role."
                )

            return ScriptResponse(msgs=True)

        except Exception as e:
            return JsonResponse(
                {"success": False, "message": f"Error updating permissions: {str(e)}"}
            )
