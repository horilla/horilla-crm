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
from ..filters import TeamRoleFilter
from ..models import TeamRole


@method_decorator(
    permission_required_or_denied("core.view_teamrole", wrapper_id="team-role-view"),
    name="dispatch",
)
class TeamRoleView(LoginRequiredMixin, HorillaView):
    """
    Template view for team role page
    """

    template_name = "settings/settings_list_shell.html"
    view_id = "team-role-view"
    nav_url = reverse_lazy("core:team_role_nav_view")
    list_url = reverse_lazy("core:team_role_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("core.view_teamrole"), name="dispatch")
class TeamRoleNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar fro team role
    """

    nav_description = _("Define roles for members collaborating on team-selling deals.")
    search_url = reverse_lazy("core:team_role_list_view")
    main_url = reverse_lazy("core:team_role_view")
    filterset_class = TeamRoleFilter
    one_view_only = True
    all_view_types = False
    filter_option = False
    reload_option = False
    model_name = "TeamRole"
    model_app_label = "core"
    nav_width = False
    url_name = "team_role_list_view"
    border_enabled = False

    @cached_property
    def new_button(self):
        """
        Get the configuration for the "New" button in the navbar.
        """
        if self.request.user.has_perm("core.add_teamrole"):
            return {
                "url": f"""{reverse_lazy("core:team_role_create_form")}?new=true""",
                "attrs": {"id": "team-role-create"},
            }
        return None

    @cached_property
    def actions(self):
        """
        Get the list of actions available in the navbar.
        """
        if self.request.user.has_perm("core.view_teamrole"):
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
@method_decorator(permission_required_or_denied("core.view_teamrole"), name="dispatch")
class TeamRoleListView(LoginRequiredMixin, HorillaListView):
    """
    List view of team role
    """

    model = TeamRole
    view_id = "team_role_list"
    filterset_class = TeamRoleFilter
    search_url = reverse_lazy("core:team_role_list_view")
    main_url = reverse_lazy("core:team_role_view")
    bulk_select_option = False

    @cached_property
    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        if self.request.user.has_perm("core.add_teamrole"):
            return {
                "url": f"""{reverse_lazy("core:team_role_create_form")}?new=true""",
                "attrs": 'id="team-role-create"',
            }
        return None

    columns = ["team_role_name", "description"]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "core.change_teamrole",
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
            "permission": "core.delete_teamrole",
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
@method_decorator(permission_required_or_denied("core.add_teamrole"), name="dispatch")
class TeamRoleFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    create and update from view for team role
    """

    model = TeamRole
    fields = ["team_role_name", "description"]
    full_width_fields = ["team_role_name", "description"]
    modal_height = False

    @cached_property
    def form_url(self):
        """
        Get the URL for form submission based on whether it's a create or update action.
        """
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("core:team_role_update_form", kwargs={"pk": pk})
        return reverse_lazy("core:team_role_create_form")

    def get(self, request, *args, **kwargs):
        """
        Handle GET requests to ensure the requested TeamRole exists for editing.
        """
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
    permission_required_or_denied("core.delete_teamrole", modal=True),
    name="dispatch",
)
class TeamRoleDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    View to delete a Team Role
    """

    model = TeamRole

    def get_post_delete_response(self):
        return HxTriggerResponse()
