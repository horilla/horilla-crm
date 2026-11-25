"""
This view handles the methods for user sepcific holidays view
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
from horilla.db.models import Q
from horilla.urls import reverse_lazy
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.decorators.wrapper import permission_required_or_denied
from horilla.utils.translation import gettext_lazy as _

# Local imports
from ..filters import HolidayFilter
from ..models import Holiday


@method_decorator(
    permission_required_or_denied(
        ["core.view_holiday", "core.view_own_holiday"],
        wrapper_id="user-holiday-view",
    ),
    name="dispatch",
)
class UserHolidayView(LoginRequiredMixin, HorillaView):
    """
    Templateviews for user sepcific holiday page
    """

    template_name = "settings/my_settings_list_shell.html"
    view_id = "user-holiday-view"
    nav_url = reverse_lazy("core:user_holiday_nav")
    list_url = reverse_lazy("core:user_holiday_list")


@method_decorator(htmx_required, name="dispatch")
class UserHolidayNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar fro user sepcific holidays
    """

    nav_title = _("My Holidays")
    nav_description = _("View the holidays that apply to you.")
    search_url = reverse_lazy("core:user_holiday_list")
    main_url = reverse_lazy("core:user_holiday_view")
    filterset_class = HolidayFilter
    one_view_only = True
    all_view_types = False
    filter_option = False
    reload_option = False
    model_name = "Holiday"
    model_app_label = "core"
    nav_width = False


@method_decorator(htmx_required, name="dispatch")
class UserHolidayListView(LoginRequiredMixin, HorillaListView):
    """
    List view of user sepcific holidays
    """

    model = Holiday
    view_id = "user_holiday_list"
    filterset_class = HolidayFilter
    search_url = reverse_lazy("core:user_holiday_list")
    main_url = reverse_lazy("core:user_holiday_view")
    table_width = False
    bulk_select_option = False
    store_ordered_ids = True

    columns = [
        "name",
        "start_date",
        "end_date",
        "is_recurring",
        (_("Holiday Type"), "holiday_type"),
    ]

    def get_queryset(self):
        user = self.request.user
        app_label = self.model._meta.app_label
        model_name = self.model._meta.model_name

        if user.has_perm(f"{app_label}.view_{model_name}") or user.has_perm(
            f"{app_label}.view_own_{model_name}"
        ):
            queryset = self.model.objects.filter(
                Q(all_users=True) | Q(specific_users=user)
            ).distinct()
        else:
            queryset = self.model.objects.none()

        if self.store_ordered_ids:
            self.request.session[f"ordered_ids_{self.model.__name__.lower()}"] = list(
                queryset.values_list("pk", flat=True)
            )

        return queryset

    @cached_property
    def col_attrs(self):
        """
        Get the column attributes for the list view.
        """
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = self.request.session.get(self.ordered_ids_key, [])
        htmx_attrs = {
            "hx-get": f"{{get_user_detail_url}}?instance_ids={query_string}",
            "hx-target": "#detailModalBox",
            "hx-swap": "innerHTML",
            "hx-push-url": "false",
            "hx-on:click": "openDetailModal();",
        }
        return [
            {
                "name": {
                    "style": "cursor:pointer",
                    "class": "hover:text-primary-600",
                    **htmx_attrs,
                }
            }
        ]


@method_decorator(htmx_required, name="dispatch")
class UserHolidayDetailView(LoginRequiredMixin, HorillaModalDetailView):
    """
    detail view of page
    """

    model = Holiday
    title = _("Details")
    header = {
        "title": "name",
        "subtitle": "",
        "avatar": "get_avatar",
    }

    body = [
        "start_date",
        "end_date",
        ("specific_users", "specific_users_enable"),
        ("is_recurring", "get_recurrence_description"),
    ]
