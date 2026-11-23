"""Core cadence views (list/form/actions)."""

# Standard library imports
from functools import cached_property
from urllib.parse import urlencode

# Third-party imports (Django)
from django.contrib import messages
from django.utils.safestring import mark_safe

from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla.contrib.utils.middlewares import get_active_company
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View

# First party imports (Horilla)
from horilla.web import ScriptResponse

# Local imports
from ..filters import CadenceFilter
from ..forms import CadenceForm
from ..models import Cadence, CadenceCondition


@method_decorator(
    permission_required_or_denied(["cadences.view_cadence"]),
    name="dispatch",
)
class CadenceView(LoginRequiredMixin, HorillaView):
    """Settings page for cadence."""

    template_name = "settings/settings_list_shell.html"
    view_id = "cadence-view"
    nav_url = reverse_lazy("cadences:cadence_nav_view")
    list_url = reverse_lazy("cadences:cadence_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["cadences.view_cadence"]), name="dispatch"
)
class CadenceNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar for cadence."""

    nav_title = _("Cadences")
    nav_description = _("Automate sequences of follow-ups for your records.")
    search_url = reverse_lazy("cadences:cadence_list_view")
    main_url = reverse_lazy("cadences:cadence_view")
    filterset_class = CadenceFilter
    nav_width = False
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False

    @cached_property
    def new_button(self):
        """Add new cadence button, shown if user has add permission."""
        if self.request.user.has_perm("cadences.add_cadence"):
            return {
                "url": reverse_lazy("cadences:cadence_create_view"),
                "attrs": {"id": "cadence-create"},
                "title": _("New"),
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["cadences.view_cadence"]), name="dispatch"
)
class CadenceListView(LoginRequiredMixin, HorillaListView):
    """List view for cadence."""

    model = Cadence
    view_id = "cadence-list"
    search_url = reverse_lazy("cadences:cadence_list_view")
    main_url = reverse_lazy("cadences:cadence_view")
    filterset_class = CadenceFilter
    save_to_list_option = False
    list_column_visibility = False
    bulk_select_option = False
    enable_sorting = False
    header_attrs = [
        {"description": {"style": "width: 300px;"}},
    ]

    columns = [
        "name",
        "module",
        "description",
        ("is_active", "is_active_col"),
    ]

    @cached_property
    def col_attrs(self):
        """Return column attributes for cadence list view."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {
            "hx-get": f"{{get_detail_url}}?{query_string}",
            "hx-target": "#mainContent",
            "hx-swap": "outerHTML",
            "hx-push-url": "true",
            "hx-select": "#mainContent",
            "permission": "cadences.view_cadence",
            "own_permission": "cadences.view_own_cadence",
            "owner_field": "owner",
        }
        return [{"name": {**attrs}}]

    actions = [
        {
            "action": _("Edit"),
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "reviews.change_reviewprocess",
            "attrs": """
                        hx-get="{get_edit_url}"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        },
        {
            "action": _("Delete"),
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "reviews.delete_reviewprocess",
            "attrs": """
                        hx-get="{get_delete_url}"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        },
    ]

    def no_record_add_button(self):
        """Show add button when no records exist, if user has permission."""
        if self.request.user.has_perm("cadences.add_cadence"):
            return {
                "url": f"{reverse_lazy('cadences:cadence_create_view')}?new=true",
                "attrs": 'id="review-process-create"',
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["cadences.add_cadence"]), name="dispatch"
)
class CadenceFormView(LoginRequiredMixin, HorillaSingleFormView):
    """Create/update view for cadence."""

    model = Cadence
    form_class = CadenceForm
    modal_height = False
    full_width_fields = ["name", "module", "description"]

    content_type_field = "module"
    condition_hx_include = "#id_module"
    condition_order_by = ["order"]

    condition_fields = ["field", "operator", "value", "logical_operator"]
    condition_model = CadenceCondition
    condition_related_name = "conditions"
    condition_field_title = mark_safe(
        f'{_("Conditions")} <span class="text-red-500">*</span>'
    )

    def get_initial(self):
        """Active company (hidden); preserve module from GET on HTMX reloads."""
        initial = super().get_initial()
        company = get_active_company()
        initial["company"] = company
        if self.request.method == "GET" and self.request.GET.get("module"):
            initial["module"] = self.request.GET.get("module")
        return initial

    @cached_property
    def form_url(self):
        """Get URL for form view."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("cadences:cadence_update_view", kwargs={"pk": pk})
        return reverse_lazy("cadences:cadence_create_view")


@method_decorator(htmx_required, name="dispatch")
class CadenceToggleView(LoginRequiredMixin, View):
    """Toggle active status for cadence via HTMX."""

    def post(self, request, *args, **kwargs):
        """Toggle the is_active status of a cadence and return an HTMX response to reload the list view."""
        try:
            cadence = Cadence.objects.get(pk=kwargs["pk"])
            user = request.user
            if user.has_perm("cadences.change_cadence"):
                cadence.is_active = not cadence.is_active
                status = "activated" if cadence.is_active else "deactivated"
                messages.success(request, f"{cadence.name} {status} successfully")
                cadence.save()
                return ScriptResponse(reload=True)
            return None
        except Exception as exc:
            messages.error(request, exc)
            return ScriptResponse(reload=True)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["cadences.delete_cadence"]), name="dispatch"
)
class CadenceDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """Delete view for cadence."""

    model = Cadence

    def get_post_delete_response(self):
        return ScriptResponse(reload=True)
