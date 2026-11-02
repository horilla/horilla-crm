"""
This view handles the methods for team role view
"""

# Third-party imports (Django)
from django.contrib import messages

# First-party imports (Horilla)
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
from horilla.web import HxTriggerResponse, ScriptResponse

# Local imports
from ..filters import CustomerRoleFilter
from ..models import CustomerRole


@method_decorator(
    permission_required_or_denied(
        "core.view_customerrole", wrapper_id="customer-role-view"
    ),
    name="dispatch",
)
class CustomerRoleView(LoginRequiredMixin, HorillaView):
    """
    Template view for customer role page
    """

    template_name = "settings/settings_list_shell.html"
    view_id = "customer-role-view"
    nav_url = reverse_lazy("core:customer_role_nav_view")
    list_url = reverse_lazy("core:customer_role_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("core.view_customerrole"), name="dispatch")
class CustomerRoleNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar fro customer role
    """

    nav_description = _("Define roles for the customer contacts you work with.")
    search_url = reverse_lazy("core:customer_role_list_view")
    main_url = reverse_lazy("core:customer_role_view")
    filterset_class = CustomerRoleFilter
    one_view_only = True
    all_view_types = False
    filter_option = False
    reload_option = False
    model_name = "CustomerRole"
    model_app_label = "core"
    nav_width = False
    url_name = "customer_role_list_view"
    border_enabled = False

    @cached_property
    def new_button(self):
        """
        Return configuration for the 'Create Customer Role' button
        if the user has add permission.
        """
        if self.request.user.has_perm("core.add_customerrole"):
            return {
                "url": f"""{reverse_lazy("core:customer_role_create_form")}?new=true""",
                "attrs": {"id": "customer-role-create"},
            }
        return None

    @cached_property
    def actions(self):
        """
        Return navbar actions available for the customer role list.
        """
        if self.request.user.has_perm("core.view_customerrole"):
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
    permission_required_or_denied("core.view_customerrole"), name="dispatch"
)
class CustomerRoleListView(LoginRequiredMixin, HorillaListView):
    """
    List view of customer role
    """

    model = CustomerRole
    view_id = "customer_role_list"
    filterset_class = CustomerRoleFilter
    search_url = reverse_lazy("core:customer_role_list_view")
    main_url = reverse_lazy("core:customer_role_view")
    bulk_select_option = False

    @cached_property
    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        if self.request.user.has_perm("core.add_customerrole"):
            return {
                "url": f"""{reverse_lazy("core:customer_role_create_form")}?new=true""",
                "attrs": 'id="customer-role-create"',
            }
        return None

    columns = ["customer_role_name", "description"]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "core.change_customerrole",
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
            "permission": "core.delete_customerrole",
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
    permission_required_or_denied("core.add_customerrole"), name="dispatch"
)
class CustomerRoleFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    create and update from view for customer role
    """

    model = CustomerRole
    fields = ["customer_role_name", "description"]
    full_width_fields = ["customer_role_name", "description"]
    modal_height = False
    save_and_new = False

    @cached_property
    def form_url(self):
        """
        Resolve form submission URL for create or update operation.
        """
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("core:customer_role_update_form", kwargs={"pk": pk})
        return reverse_lazy("core:customer_role_create_form")

    def post(self, request, *args, **kwargs):
        """Delegate to parent post for form submission."""
        return super().post(request, *args, **kwargs)

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
    permission_required_or_denied("core.delete_customerrole", modal=True),
    name="dispatch",
)
class CustomerRoleDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete view for customer role.
    """

    model = CustomerRole

    def get_post_delete_response(self):
        return HxTriggerResponse()
