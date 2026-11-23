"""
Views for managing superusers in the permissions module."""

# Standard library imports
from functools import cached_property
from urllib.parse import urlencode

# Third-party imports (Django)
from django.contrib import messages
from django.db import transaction

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.auth.models import User
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla.contrib.utils.middlewares import get_active_company
from horilla.shortcuts import get_object_or_404
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import HttpResponse, ScriptResponse

# Local imports
from ...forms import AddSuperUsersForm


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
class SuperUserView(LoginRequiredMixin, HorillaView):
    """
    Template view for customer role page
    """

    template_name = "permissions/super_user_view.html"
    nav_url = reverse_lazy("core:super_user_nav_bar")
    list_url = reverse_lazy("core:super_user_list")


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
class SuperUserNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar fro customer role
    """

    search_url = reverse_lazy("core:super_user_list")
    main_url = reverse_lazy("core:super_user_tab")
    one_view_only = True
    all_view_types = False
    filter_option = False
    reload_option = False
    nav_width = False
    search_option = False
    border_enabled = False

    @cached_property
    def new_button(self):
        """Button for adding super users"""
        return {
            "title": _("Add"),
            "url": reverse_lazy("core:add_super_users"),
            "target": "#modalBox",
            "onclick": "openModal()",
            "attrs": {"id": "add-super-users"},
        }


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
class SuperUserTab(LoginRequiredMixin, HorillaListView):
    """
    List view of the super user tab
    """

    model = User
    view_id = "super_user_list"
    list_column_visibility = False
    bulk_select_option = False
    table_width = False
    table_height_as_class = "h-[calc(100vh-350px)]"
    main_url = reverse_lazy("core:super_user_tab")

    @cached_property
    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        return {
            "title": _("Add Super Users"),
            "url": reverse_lazy("core:add_super_users"),
            "target": "#modalBox",
            "onclick": "openModal()",
            "attrs": 'id="add-super-users"',
        }

    columns = [(_("First Name"), "get_avatar_with_name"), "role"]

    action_method = "super_user_action_col"

    def get_queryset(self):
        queryset = super().get_queryset()
        company = get_active_company(self.request)
        queryset = queryset.filter(is_superuser=True, company=company)
        return queryset

    @cached_property
    def col_attrs(self):
        """
        Get the column attributes for the list view.
        """
        query_params = self.request.GET.dict()
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {
            "hx-get": f"{{get_detail_view_url}}?{query_string}",
            "hx-target": "#permission-view",
            "hx-swap": "innerHTML",
            "hx-push-url": "true",
            "hx-select": "#users-view",
            "permission": f"{User._meta.app_label}.view_{User._meta.model_name}",
        }
        return [
            {
                "get_avatar_with_name": {
                    **attrs,
                }
            }
        ]


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
class ToggleSuperuserView(LoginRequiredMixin, View):
    """
    Toggle superuser status for a user.
    """

    def post(self, request, *args, **kwargs):
        """Toggle superuser status for a user."""
        user_id = kwargs.get("pk")
        try:
            user = get_object_or_404(User, pk=user_id)
        except Exception:
            messages.error(self.request, _("User Does not Exist"))
            return ScriptResponse(reload=True)

        # Re-check on the server: the Remove button may be stale (e.g. another
        # tab already removed a superuser), so never rely on the rendered UI.
        with transaction.atomic():
            superusers = list(
                User.objects.select_for_update()
                .filter(is_superuser=True)
                .values_list("pk", flat=True)
            )
            if user.pk not in superusers:
                messages.warning(
                    request,
                    _("{name} is no longer a superuser.").format(
                        name=user.get_full_name()
                    ),
                )
            else:
                if len(superusers) <= 1:
                    messages.error(
                        request,
                        _(
                            "At least one superuser is required. "
                            "Cannot remove the last superuser."
                        ),
                    )
                else:
                    user.is_superuser = False
                    user.save(update_fields=["is_superuser"])
                    messages.success(
                        request,
                        f"Superuser status of {user.get_full_name()} removed successfully",
                    )

        return HttpResponse(
            "<script>htmx.trigger($('#super_user_list #reloadButton')[0],'click');</script>"
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
class AddSuperUsersView(LoginRequiredMixin, HorillaSingleFormView):
    """
    View to add multiple users as superusers using single form view
    """

    model = User
    form_class = AddSuperUsersForm
    form_title = _("Add Super Users")
    full_width_fields = ["users"]
    modal_height = False
    form_url = reverse_lazy("core:add_super_users")
    save_and_new = False
    view_id = "add-super-users"

    def get_form_kwargs(self):
        """Add request to form kwargs for company filtering"""
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        """Handle valid form submission to add users as superusers"""
        users = form.save(commit=True)
        messages.success(
            self.request,
            _("Successfully added {count} user(s) as superuser(s).").format(
                count=len(users)
            ),
        )
        return HttpResponse(
            "<script>htmx.trigger($('#super_user_list #reloadButton')[0],'click');closeModal();</script>"
        )
