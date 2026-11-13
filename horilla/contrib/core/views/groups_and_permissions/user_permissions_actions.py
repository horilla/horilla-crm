"""
Views for managing user permissions in the permissions module.
"""

# Third-party imports (Django)
from django.contrib import messages
from django.contrib.auth.models import Permission

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.auth.models import User
from horilla.shortcuts import get_object_or_404
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import JsonResponse, ScriptResponse

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
class UpdateUserPermissionsView(LoginRequiredMixin, View):
    """
    Toggle permission for a specific user when checkbox is clicked.
    """

    def post(self, request, user_id):
        """Toggle permission for a specific user."""
        try:
            user = get_object_or_404(User, id=user_id)
        except Exception:
            messages.error(request, _("User does not exist"))
            return ScriptResponse(reload=True)

        perm_id = request.POST.get("permission_id")
        checked = request.POST.get("checked") == "true"

        try:
            permission = Permission.objects.get(id=perm_id)
        except Permission.DoesNotExist:
            return JsonResponse({"success": False, "message": "Permission not found"})

        if checked:
            user.user_permissions.add(permission)
            messages.success(
                request,
                f"Permission '{permission.name}' added to {user.get_full_name()}.",
            )
        else:
            user.user_permissions.remove(permission)
            messages.success(
                request,
                f"Permission '{permission.name}' removed from {user.get_full_name()}.",
            )

        return ScriptResponse(msgs=True)


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
class UpdateUserModelPermissionsView(LoginRequiredMixin, View):
    """
    Toggle all permissions for a specific model for a user when select all checkbox is clicked.
    """

    def post(self, request, user_id):
        """Toggle all permissions for a specific model for a user."""
        try:
            user = get_object_or_404(User, id=user_id)
        except Exception:
            messages.error(self.request, _("User Does not Exist"))
            return ScriptResponse(reload=True)

        model_name = request.POST.get("model_name")
        app_label = request.POST.get("app_label")
        checked = request.POST.get("checked") == "true"

        if not model_name or not app_label:
            return JsonResponse(
                {"success": False, "message": "Model information not provided"}
            )

        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:
            return JsonResponse({"success": False, "message": "Model not found"})

        model_verbose_name = model._meta.verbose_name

        try:
            permissions = PermissionUtils.get_model_permissions(app_label, model_name)
            if not permissions:
                return JsonResponse(
                    {"success": False, "message": "No permissions found for this model"}
                )

            permission_objects = Permission.objects.filter(
                id__in=[p["id"] for p in permissions]
            )

            if checked:
                user.user_permissions.add(*permission_objects)
                messages.success(
                    request,
                    _("All permissions added for {model} to user {username}.").format(
                        model=model_verbose_name, username=user.username
                    ),
                )
            else:
                user.user_permissions.remove(*permission_objects)
                messages.success(
                    request,
                    _(
                        "All permissions removed for {model} from user {username}."
                    ).format(model=model_verbose_name, username=user.username),
                )

            # Return success response
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
class UpdateUserAllPermissionsView(LoginRequiredMixin, View):
    """
    Toggle ALL permissions for a user when master select all checkbox is clicked.
    """

    def post(self, request, user_id):
        """Toggle ALL permissions for a user."""
        try:
            user = get_object_or_404(User, id=user_id)
        except Exception:
            messages.error(self.request, _("User Does not Exist"))
            return ScriptResponse(reload=True)

        checked = request.POST.get("checked") == "true"

        try:
            all_permissions = PermissionUtils.get_all_permission_ids()

            if not all_permissions:
                return JsonResponse(
                    {"success": False, "message": "No permissions found"}
                )

            if checked:
                user.user_permissions.add(*all_permissions)
                messages.success(
                    request, f"All permissions granted to user {user.username}."
                )
            else:
                user.user_permissions.remove(*all_permissions)
                messages.success(
                    request, f"All permissions revoked from user {user.username}."
                )

            # Return success response
            return ScriptResponse(msgs=True)

        except Exception as e:
            return JsonResponse(
                {"success": False, "message": f"Error updating permissions: {str(e)}"}
            )


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
class BulkUpdateUserModelPermissionsView(LoginRequiredMixin, View):
    """
    Toggle all permissions for a specific model for multiple users when select all checkbox is clicked.
    """

    def post(self, request):
        """Toggle all permissions for a specific model for multiple users."""
        user_ids = request.POST.getlist("users")
        model_name = request.POST.get("model_name")
        app_label = request.POST.get("app_label")
        checked = request.POST.get("checked") == "true"

        if not user_ids:
            return JsonResponse({"success": False, "message": "No users selected"})

        if not model_name or not app_label:
            return JsonResponse(
                {"success": False, "message": "Model information not provided"}
            )

        try:
            users = User.objects.filter(id__in=user_ids, is_superuser=False)
            if not users.exists():
                return JsonResponse(
                    {"success": False, "message": "No valid users found"}
                )

            permissions = PermissionUtils.get_model_permissions(app_label, model_name)
            if not permissions:
                return JsonResponse(
                    {"success": False, "message": "No permissions found for this model"}
                )

            permission_objects = Permission.objects.filter(
                id__in=[p["id"] for p in permissions]
            )

            for user in users:
                if checked:
                    user.user_permissions.add(*permission_objects)
                else:
                    user.user_permissions.remove(*permission_objects)

            if checked:
                messages.success(
                    request,
                    f"All {model_name} permissions added to {users.count()} user(s).",
                )
            else:
                messages.success(
                    request,
                    f"All {model_name} permissions removed from {users.count()} user(s).",
                )

            return ScriptResponse(msgs=True)

        except Exception as e:
            return JsonResponse(
                {"success": False, "message": f"Error updating permissions: {str(e)}"}
            )


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
class BulkUpdateUserAllPermissionsView(LoginRequiredMixin, View):
    """
    Toggle ALL permissions for multiple users when master select all checkbox is clicked.
    """

    def post(self, request):
        """Toggle ALL permissions for multiple users."""
        user_ids = request.POST.getlist("users")
        checked = request.POST.get("checked") == "true"

        if not user_ids:
            return JsonResponse({"success": False, "message": "No users selected"})

        try:
            users = User.objects.filter(id__in=user_ids, is_superuser=False)
            if not users.exists():
                return JsonResponse(
                    {"success": False, "message": "No valid users found"}
                )

            all_permissions = PermissionUtils.get_all_permission_ids()

            if not all_permissions:
                return JsonResponse(
                    {"success": False, "message": "No permissions found"}
                )

            for user in users:
                if checked:
                    user.user_permissions.add(*all_permissions)
                else:
                    user.user_permissions.remove(*all_permissions)

            if checked:
                messages.success(
                    request, _("All permissions granted to selected users.")
                )
            else:
                messages.success(
                    request, _("All permissions revoked from selected users.")
                )

            return ScriptResponse(msgs=True)

        except Exception as e:
            return JsonResponse(
                {"success": False, "message": f"Error updating permissions: {str(e)}"}
            )
