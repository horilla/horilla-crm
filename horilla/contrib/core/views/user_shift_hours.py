"""
Views for the shift hours assigned to the logged-in user (My Settings).
"""

# Standard library imports
from functools import cached_property

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaModalDetailView,
    HorillaNavView,
    HorillaView,
)
from horilla.urls import reverse_lazy
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.translation import gettext_lazy as _

# Local imports
from ..filters import ShiftHourFilter
from ..models import ShiftHour


class UserShiftHourView(LoginRequiredMixin, HorillaView):
    """
    Template view for the user specific shift hour page.
    """

    template_name = "settings/my_settings_list_shell.html"
    view_id = "user-shift-hour-view"
    nav_url = reverse_lazy("core:user_shift_hour_nav")
    list_url = reverse_lazy("core:user_shift_hour_list")


@method_decorator(htmx_required, name="dispatch")
class UserShiftHourNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar for the user specific shift hours.
    """

    nav_title = _("My Shift Hours")
    nav_description = _("View the shift hours assigned to you.")
    search_url = reverse_lazy("core:user_shift_hour_list")
    main_url = reverse_lazy("core:user_shift_hour_view")
    filterset_class = ShiftHourFilter
    one_view_only = True
    all_view_types = False
    filter_option = False
    reload_option = False
    model_name = "ShiftHour"
    model_app_label = "core"
    nav_width = False


@method_decorator(htmx_required, name="dispatch")
class UserShiftHourListView(LoginRequiredMixin, HorillaListView):
    """
    List view of the shift hours assigned to the logged-in user.
    """

    model = ShiftHour
    view_id = "user-shift-hour-list"
    filterset_class = ShiftHourFilter
    search_url = reverse_lazy("core:user_shift_hour_list")
    main_url = reverse_lazy("core:user_shift_hour_view")
    table_width = False
    bulk_select_option = False
    store_ordered_ids = True
    list_column_visibility = False
    # The queryset is already limited to the user's own shifts, so skip the
    # permission-based record filter (regular users lack core.view_shifthour).
    owner_filtration = False
    header_attrs = [
        {"get_timing_type_display": {"style": "width: 240px;"}},
        {"get_formatted_week_days": {"style": "width: 320px;"}},
    ]

    columns = [
        "name",
        "get_timing_type_display",
        ("week_days", "get_formatted_week_days"),
        "time_zone",
    ]

    def get_queryset(self):
        queryset = super().get_queryset().filter(assigned_users=self.request.user)
        queryset = queryset.distinct()

        if self.store_ordered_ids:
            self.request.session[self.ordered_ids_key] = list(
                queryset.values_list("pk", flat=True)
            )

        return queryset

    @cached_property
    def col_attrs(self):
        """
        Open the read-only detail modal when the shift name is clicked.
        """
        query_string = self.request.session.get(self.ordered_ids_key, [])
        return [
            {
                "name": {
                    "hx-get": f"{{get_user_detail_url}}?instance_ids={query_string}",
                    "hx-target": "#detailModalBox",
                    "hx-swap": "innerHTML",
                    "hx-push-url": "false",
                    "hx-on:click": "openDetailModal();",
                    "style": "cursor:pointer",
                    "class": "hover:text-primary-600",
                }
            }
        ]


@method_decorator(htmx_required, name="dispatch")
class UserShiftHourDetailView(LoginRequiredMixin, HorillaModalDetailView):
    """
    Read-only detail of a shift hour assigned to the logged-in user.
    """

    model = ShiftHour
    title = _("Shift hour details")
    header = {
        "title": "name",
        "subtitle": "time_zone",
        "avatar": "get_avatar",
    }

    body = [
        "get_timing_type_display",
        ("break1_mode", "get_break1_detail"),
        ("break2_mode", "get_break2_detail"),
        ("week_days", "get_formatted_week_days_detail"),
    ]

    def get_queryset(self):
        """Only the shifts assigned to the logged-in user can be opened."""
        return super().get_queryset().filter(assigned_users=self.request.user)
