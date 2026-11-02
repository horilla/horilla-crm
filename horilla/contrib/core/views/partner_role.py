"""
This view handles the methods for team role view
"""

# Standard library imports
from functools import cached_property

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.web import HxTriggerResponse, ScriptResponse

# Local imports
from ..filters import PartnerRoleFilter
from ..models import PartnerRole


@method_decorator(
    permission_required_or_denied(
        "core.view_partnerrole", wrapper_id="partner-role-view"
    ),
    name="dispatch",
)
class PartnerRoleView(LoginRequiredMixin, HorillaView):
    """
    Template view for partner role page
    """

    template_name = "settings/settings_list_shell.html"
    view_id = "partner-role-view"
    nav_url = reverse_lazy("core:partner_role_nav_view")
    list_url = reverse_lazy("core:partner_role_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("core.view_partnerrole"), name="dispatch")
class PartnerRoleNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar fro partner role
    """

    nav_description = _("Define roles for the partner contacts you work with.")
    search_url = reverse_lazy("core:partner_role_list_view")
    main_url = reverse_lazy("core:partner_role_view")
    filterset_class = PartnerRoleFilter
    one_view_only = True
    all_view_types = False
    filter_option = False
    reload_option = False
    model_name = "PartnerRole"
    model_app_label = "core"
    nav_width = False
    url_name = "partner_role_list_view"
    border_enabled = False

    @cached_property
    def new_button(self):
        """
        Returns the new button configuration if the user has permission to add a partner role.
        """
        if self.request.user.has_perm("core.add_partnerrole"):
            return {
                "url": f"""{reverse_lazy("core:partner_role_create_form")}?new=true""",
                "attrs": {"id": "partner-role-create"},
            }
        return None

    @cached_property
    def actions(self):
        """
        Returns the list of actions available in the navbar.
        """
        if self.request.user.has_perm("core.view_partnerrole"):
            return [
                {
                    "action": _("Add Column to List"),
                    "attrs": f"""
                            hx-get="{reverse_lazy("generics:column_selector")}?app_label={self.model_app_label}&model_name={self.model_name}&url_name={self.url_name}"
                            onclick="openModal()"
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            """,
                }
            ]
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.view_partnerrole"), name="dispatch"
)
class PartnerRoleListView(LoginRequiredMixin, HorillaListView):
    """
    List view of partner role
    """

    model = PartnerRole
    view_id = "partner_role_list"
    filterset_class = PartnerRoleFilter
    search_url = reverse_lazy("core:partner_role_list_view")
    main_url = reverse_lazy("core:partner_role_view")
    bulk_select_option = False
    save_to_list_option = False

    @cached_property
    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        if self.request.user.has_perm("core.add_partnerrole"):
            return {
                "url": f"""{reverse_lazy("core:partner_role_create_form")}?new=true""",
                "attrs": 'id="partner-role-create"',
            }
        return None

    columns = ["partner_role_name", "description"]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "core.change_partnerrole",
            "attrs": """
                hx-get="{get_edit_url}?new=true"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal()"
                """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "core.delete_partnerrole",
            "attrs": """
                hx-post="{get_delete_url}"
                hx-target="#deleteModeBox"
                hx-swap="innerHTML"
                hx-trigger="click"
                hx-vals='{{"check_dependencies": "true"}}'
                onclick="openDeleteModeModal()"
            """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.add_partnerrole"), name="dispatch"
)
class PartnerRoleFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    create and update from view for partner role
    """

    model = PartnerRole
    fields = ["partner_role_name", "description"]
    full_width_fields = ["partner_role_name", "description"]
    modal_height = False

    @cached_property
    def form_url(self):
        """
        Returns the URL for the form, either for creating or updating a partner role.
        """

        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("core:partner_role_update_form", kwargs={"pk": pk})
        return reverse_lazy("core:partner_role_create_form")

    def get(self, request, *args, **kwargs):
        pk = kwargs.get("pk")
        if pk:
            try:
                self.model.objects.get(pk=pk)
            except self.model.DoesNotExist:
                messages.error(request, _("The requested data does not exist."))
                return ScriptResponse(reload=True)

        return super().get(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.delete_partnerrole", modal=True),
    name="dispatch",
)
class PartnerRoleDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete view for partner role
    """

    model = PartnerRole

    def get_post_delete_response(self):
        return HxTriggerResponse()
