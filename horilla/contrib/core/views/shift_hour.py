"""
Shift hour views .
"""

# Standard library imports
import logging

# First-party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaModalDetailView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
)
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.functional import cached_property
from horilla.utils.translation import gettext_lazy as _
from horilla.web import HttpResponse, ScriptResponse

# Local imports
from ..forms import ShiftHourForm
from ..models import ShiftHour

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.view_businesshour"), name="dispatch"
)
class ShiftHourListView(LoginRequiredMixin, HorillaListView):
    """List shift hours for the active company."""

    model = ShiftHour
    view_id = "shift-hour-list-view"
    bulk_select_option = True
    search_url = reverse_lazy("core:shift_hour_list_view")
    store_ordered_ids = True
    list_column_visibility = False
    bulk_update_option = False
    header_attrs = [
        {"get_formatted_week_days": {"style": "width: 320px;"}},
    ]

    @cached_property
    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        if self.request.user.has_perm("core.add_businesshour"):
            return {
                "url": f"""{reverse_lazy("core:shift_hour_create_form")}?new=true""",
                "attrs": 'id="shift-hour-create"',
            }
        return None

    columns = [
        "name",
        "get_timing_type_display",
        ("week_days", "get_formatted_week_days"),
        "time_zone",
        ("assigned_users", "get_assigned_users_count_display"),
    ]

    @cached_property
    def col_attrs(self):
        """Add htmx attributes to the name column for opening the detail modal on click, passing the ordered ids for context."""
        query_string = self.request.session.get(self.ordered_ids_key, [])
        attrs = {
            "hx-get": f"{{get_detail_url}}?instance_ids={query_string}",
            "hx-target": "#detailModalBox",
            "hx-swap": "innerHTML",
            "hx-push-url": "false",
            "hx-on:click": "openDetailModal();",
            "style": "cursor:pointer",
            "class": "hover:text-primary-600",
        }
        return [{"name": {**attrs}}]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4 flex gap-4",
            "permission": "core.change_businesshour",
            "attrs": """
                hx-get="{get_edit_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal()"
            """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "core.delete_businesshour",
            "attrs": """
                    hx-post="{get_delete_url}"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    hx-trigger="click"
                    hx-vals='{{"check_dependencies": "false"}}'
                    onclick="openModal()"
                """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
class ShiftHourFormView(LoginRequiredMixin, HorillaSingleFormView):
    """Create or update a shift hour."""

    model = ShiftHour
    form_class = ShiftHourForm
    view_id = "shift-hour-form-view"
    full_width_fields = [
        "timing_type",
        "week_days",
        "break1_week_days",
        "break2_week_days",
        "assigned_users",
    ]
    hidden_fields = ["company"]
    return_response = ScriptResponse(
        close=True,
        extra="$('#reloadShiftHourButton').click();$('#detailViewReloadButton').click();",
    )

    def get_auto_permissions(self):
        """Use business hour permissions so the same admins manage shifts."""
        pk_key = self.get_pk_key()
        duplicate_mode = getattr(self, "duplicate_mode", False)
        is_edit_mode = bool(self.kwargs.get(pk_key)) and not duplicate_mode
        if is_edit_mode:
            return ["core.change_businesshour"]
        return ["core.add_businesshour"]

    @cached_property
    def form_url(self):
        """Form URL for shift hour create/update, using pk from kwargs or GET parameters."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("core:shift_hour_update_form", kwargs={"pk": pk})
        return reverse_lazy("core:shift_hour_create_form")

    def get_initial(self):
        """Get initial data for the form, supporting pre-fill from GET parameters when toggled."""
        initial = super().get_initial()
        toggle = self.request.GET.get("toggle_data")
        company = getattr(self.request, "active_company", None)
        initial["company"] = company
        if toggle == "true":
            initial["timing_type"] = self.request.GET.get("timing_type", "")
            initial["break1_mode"] = self.request.GET.get("break1_mode", "")
            initial["break2_mode"] = self.request.GET.get("break2_mode", "")
        elif hasattr(self, "object") and self.object:
            initial["timing_type"] = getattr(self.object, "timing_type", "") or ""
            initial["break1_mode"] = (
                getattr(self.object, "break1_mode", "none") or "none"
            )
            initial["break2_mode"] = (
                getattr(self.object, "break2_mode", "none") or "none"
            )
        else:
            initial["timing_type"] = ""
            initial["break1_mode"] = "none"
            initial["break2_mode"] = "none"
        initial.update(self.request.GET.dict())
        return initial


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.delete_businesshour", modal=True),
    name="dispatch",
)
class ShiftHourDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """Delete a shift hour."""

    model = ShiftHour

    def get_post_delete_response(self):
        return HttpResponse(
            "<script>$('#reloadShiftHourButton').click();closeDeleteModeModal();closeDetailModal();</script>"
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.view_businesshour"), name="dispatch"
)
class ShiftHourDetailView(LoginRequiredMixin, HorillaModalDetailView):
    """Modal detail for a shift hour."""

    model = ShiftHour
    title = _("Shift hour details")
    header = {
        "title": "name",
        "subtitle": "time_zone",
        "avatar": "get_avatar",
    }

    body = [
        "get_timing_type_display",
        ("assigned_users", "get_assigned_users_label"),
        ("break1_mode", "get_break1_detail"),
        ("break2_mode", "get_break2_detail"),
        ("week_days", "get_formatted_week_days_detail"),
    ]

    actions = [
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "svg-themed w-3 h-3",
            "permission": "core.delete_businesshour",
            "attrs": """
                    class="outline outline-1 outline-offset-[-1px] outline-primary-600 rounded-md hover:bg-primary-300 transition duration-300 text-primary-600 w-24 justify-center bg-[white] flex items-center gap-2 disabled:cursor-not-allowed cursor-pointer text-xs px-4 py-2"
                    hx-post="{get_delete_url}"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    hx-trigger="click"
                    hx-vals='{{"check_dependencies": "false"}}'
                    onclick="openModal()"
                """,
        },
        {
            "action": "Edit",
            "src": "assets/icons/edit_white.svg",
            "img_class": "w-3 h-3 flex gap-4 filter brightness-0 invert",
            "permission": "core.change_businesshour",
            "attrs": """
                class="w-24 justify-center px-4 py-2 bg-primary-600 text-white rounded-md text-xs flex items-center gap-2 hover:bg-primary-800 transition duration-300 disabled:cursor-not-allowed cursor-pointer"
                hx-get="{get_edit_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal();"
            """,
        },
    ]
