"""
This view handles the methods for department view
"""

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
from horilla.utils.functional import cached_property
from horilla.utils.translation import gettext_lazy as _
from horilla.web import HxTriggerResponse

# Local imports
from ..filters import DepartmentFilter
from ..models import Department


@method_decorator(
    permission_required_or_denied("core.view_department", wrapper_id="department-view"),
    name="dispatch",
)
class DepartmentView(LoginRequiredMixin, HorillaView):
    """
    Templateviews for department page
    """

    template_name = "settings/settings_list_shell.html"
    view_id = "department-view"
    nav_url = reverse_lazy("core:department_nav_view")
    list_url = reverse_lazy("core:department_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("core.view_department"), name="dispatch")
class DepartmentNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar fro department
    """

    nav_description = _("Organize employees into departments across your company.")
    search_url = reverse_lazy("core:department_list_view")
    main_url = reverse_lazy("core:department_view")
    filterset_class = DepartmentFilter
    one_view_only = True
    all_view_types = False
    reload_option = False
    model_name = "Department"
    model_app_label = "core"
    nav_width = False
    url_name = "department_list_view"

    @cached_property
    def new_button(self):
        """
        Return the configuration for the 'Create Department' button
        if the user has add permission.
        """
        if self.request.user.has_perm("core.add_department"):
            return {
                "url": f"""{reverse_lazy("core:department_create_form")}?new=true""",
                "attrs": {"id": "department-create"},
            }
        return None

    @cached_property
    def actions(self):
        """
        Return navbar actions available for the department list.
        """
        if self.request.user.has_perm("core.view_department"):
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
    permission_required_or_denied("core.view_department"), name="dispatch"
)
class DepartmentListView(LoginRequiredMixin, HorillaListView):
    """
    List view of department
    """

    model = Department
    view_id = "department_list"
    filterset_class = DepartmentFilter
    search_url = reverse_lazy("core:department_list_view")
    main_url = reverse_lazy("core:department_view")
    # bulk_select_option = False
    bulk_update_option = False

    @cached_property
    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        if self.request.user.has_perm("core.add_department"):
            return {
                "url": f"""{reverse_lazy("core:department_create_form")}?new=true""",
                "attrs": 'id="department-create"',
            }
        return None

    columns = ["department_name", "description"]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "core.change_department",
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
            "permission": "core.delete_department",
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
@method_decorator(permission_required_or_denied("core.add_department"), name="dispatch")
class DepartmentFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    create and update from view for department
    """

    model = Department
    fields = ["department_name", "description"]
    full_width_fields = ["department_name", "description"]
    modal_height = False

    @cached_property
    def form_url(self):
        """
        Resolve the form submission URL for create or update operation.
        """
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("core:department_update_form", kwargs={"pk": pk})
        return reverse_lazy("core:department_create_form")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.delete_department", modal=True),
    name="dispatch",
)
class DepartmentDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete view for Department. Handles deletion and returns an HTMX
    response to reload the department list.
    """

    model = Department

    def get_post_delete_response(self):
        return HxTriggerResponse()
