"""
Booking list views — per-page booking list, My Bookings, status update, and detail modal.
"""

# Standard library imports
import logging
from functools import cached_property

from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaModalDetailView,
    HorillaNavView,
    HorillaView,
)
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View

# First party imports (Horilla)
from horilla.web import ScriptResponse

# Local imports
from ..filters import BookingFilter
from ..models import Booking, BookingPage

logger = logging.getLogger(__name__)


class BookingPageDetailView(LoginRequiredMixin, View):
    """Shell: renders nav + list into #settings-content (no full page reload)."""

    def get(self, request, pk):
        """Render the booking detail shell with nav and list fragment URLs."""
        page = get_object_or_404(BookingPage, pk=pk)
        nav_url = str(reverse_lazy("booking:booking_list_nav", kwargs={"pk": pk}))
        list_url = str(reverse_lazy("booking:booking_list", kwargs={"pk": pk}))
        return render(
            request,
            "settings/booking_detail.html",
            {"page": page, "nav_url": nav_url, "list_url": list_url},
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("booking.view_booking"), name="dispatch")
class BookingListNavView(LoginRequiredMixin, HorillaNavView):
    """Navbar for the per-BookingPage booking list."""

    model_name = "booking"
    model_app_label = "booking"
    nav_width = False
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False
    navbar_indication = True

    @property
    def navbar_indication_attrs(self):
        """Return HTMX attrs for the back-to-settings breadcrumb indicator."""
        return {
            "hx-get": str(reverse_lazy("booking:booking_settings")),
            "hx-target": "#settings-content",
            "hx-swap": "innerHTML",
            "hx-select": "#booking-settings-view",
            "hx-select-oob": "#settings-sidebar",
            "hx-push-url": "true",
        }

    @property
    def _nav_title(self):
        """Return the booking page title as the nav header."""
        page = get_object_or_404(BookingPage, pk=self.kwargs["pk"])
        return page.title

    @property
    def search_url(self):
        """Return the search/filter URL for the booking list."""
        return reverse_lazy("booking:booking_list", kwargs={"pk": self.kwargs["pk"]})

    @property
    def main_url(self):
        """Return the main URL for the booking page detail view."""
        return reverse_lazy(
            "booking:booking_page_detail", kwargs={"pk": self.kwargs["pk"]}
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("booking.view_booking"), name="dispatch")
class BookingListView(LoginRequiredMixin, HorillaListView):
    """List bookings made against a specific BookingPage."""

    model = Booking
    view_id = "booking-list"
    filterset_class = BookingFilter
    save_to_list_option = False
    bulk_select_option = False
    store_ordered_ids = True
    exclude_columns_from_sorting = ["meeting_link_col"]

    columns = [
        "booker_name",
        "booker_email",
        "start_datetime",
        "status",
        ("meeting_url", "meeting_link_col"),
    ]

    @cached_property
    def col_attrs(self):
        """Make booker_name clickable to open the detail modal."""
        query_string = self.request.session.get(self.ordered_ids_key, [])
        attrs = {}
        if self.request.user.has_perm("booking.view_booking"):
            attrs = {
                "hx-get": f"{{get_detail_url}}?instance_ids={query_string}",
                "hx-target": "#detailModalBox",
                "hx-swap": "innerHTML",
                "hx-push-url": "false",
                "hx-on:click": "openDetailModal();",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }
        return [{"booker_name": {**attrs}}]

    actions = [
        {
            "action": _("Change Status"),
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "booking.change_booking",
            "attrs": """
                hx-get="{get_status_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal()"
            """,
        },
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(booking_page_id=self.kwargs["pk"]).select_related(
            "booking_page"
        )

    @property
    def search_url(self):
        """Return the search URL scoped to this booking page's listing."""
        return reverse_lazy("booking:booking_list", kwargs={"pk": self.kwargs["pk"]})

    @property
    def main_url(self):
        """Return the main URL for this booking page's detail view."""
        return reverse_lazy(
            "booking:booking_page_detail", kwargs={"pk": self.kwargs["pk"]}
        )


def _own_bookings_q(user):
    """Bookings the user hosts/participates in, or whose meeting activity is theirs."""
    from horilla.db.models import Q

    return (
        Q(booking_page__host=user)
        | Q(booking_page__participants=user)
        | Q(activity__owner=user)
        | Q(activity__assigned_to=user)
        | Q(activity__participants=user)
    )


class MyBookingsView(LoginRequiredMixin, HorillaView):
    """Shell page for My Bookings under My Jobs."""

    nav_url = reverse_lazy("booking:my_bookings_nav")
    list_url = reverse_lazy("booking:my_bookings_list")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required(["booking.view_booking", "booking.view_own_booking"]),
    name="dispatch",
)
class MyBookingsNavView(LoginRequiredMixin, HorillaNavView):
    """Navbar partial for My Bookings."""

    _nav_title = _("My Bookings")
    search_url = reverse_lazy("booking:my_bookings_list")
    filterset_class = BookingFilter
    main_url = reverse_lazy("booking:my_bookings")
    model_name = "booking"
    model_app_label = "booking"
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    search_push_url = False


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required(["booking.view_booking", "booking.view_own_booking"]),
    name="dispatch",
)
class MyBookingsListView(LoginRequiredMixin, HorillaListView):
    """HTMX list partial — bookings the user hosts, participates in, or owns via the meeting."""

    model = Booking
    view_id = "my-bookings-list"
    filterset_class = BookingFilter
    save_to_list_option = False
    bulk_select_option = False
    list_column_visibility = False
    store_ordered_ids = True
    search_url = reverse_lazy("booking:my_bookings_list")
    main_url = reverse_lazy("booking:my_bookings")
    exclude_columns_from_sorting = ["meeting_link_col"]
    # Rows are already scoped to host/participant in get_queryset; Booking has
    # no OWNER_FIELDS, so the generic view_own filter would hide every row.
    owner_filtration = False

    columns = [
        "booking_page",
        "booker_name",
        "booker_email",
        "start_datetime",
        "status",
        ("meeting_url", "meeting_link_col"),
    ]

    @cached_property
    def col_attrs(self):
        """Make booker_name clickable to open the detail modal."""
        query_string = self.request.session.get(self.ordered_ids_key, [])
        attrs = {}
        user = self.request.user
        if user.has_perm("booking.view_booking") or user.has_perm(
            "booking.view_own_booking"
        ):
            attrs = {
                "hx-get": f"{{get_detail_url}}?instance_ids={query_string}",
                "hx-target": "#detailModalBox",
                "hx-swap": "innerHTML",
                "hx-push-url": "false",
                "hx-on:click": "openDetailModal();",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }
        return [{"booker_name": {**attrs}}]

    actions = [
        {
            "action": _("Change Status"),
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "booking.change_booking",
            "attrs": """
                hx-get="{get_status_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal()"
            """,
        },
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        return (
            qs.filter(_own_bookings_q(self.request.user))
            .distinct()
            .select_related("booking_page")
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("booking.change_booking"), name="dispatch")
class BookingStatusUpdateView(LoginRequiredMixin, View):
    """GET — show status change form. POST — update status."""

    template_name = "settings/booking_status_form.html"

    def get(self, request, pk):
        """Render the status-change form for the given Booking."""
        booking = get_object_or_404(Booking, pk=pk)
        return render(request, self.template_name, {"booking": booking})

    def post(self, request, pk):
        """Update the booking status and send a notification email if needed."""
        from ..tasks import send_status_change_email

        booking = get_object_or_404(Booking, pk=pk)
        new_status = request.POST.get("status")
        valid = [s for s, _ in booking._meta.get_field("status").choices]
        if new_status in valid:
            old_status = booking.status
            booking.status = new_status
            booking.save(update_fields=["status"])
            if old_status != new_status and new_status in ("confirmed", "cancelled"):
                import threading

                threading.Thread(
                    target=send_status_change_email,
                    args=(booking, new_status),
                    daemon=True,
                ).start()
        return ScriptResponse(close=True, reload=True)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required(["booking.view_booking", "booking.view_own_booking"]),
    name="dispatch",
)
class BookingDetailModalView(LoginRequiredMixin, HorillaModalDetailView):
    """Modal detail view for a single Booking."""

    model = Booking
    title = _("Booking Detail")

    def get_queryset(self):
        """Users with only view_own_booking see just their own bookings."""
        qs = super().get_queryset()
        user = self.request.user
        if not user.has_perm("booking.view_booking"):
            qs = qs.filter(_own_bookings_q(user)).distinct()
        return qs

    header = {
        "title": "booker_name",
        "subtitle": "booker_email",
        "avatar": "",
    }
    body = [
        "booking_page",
        "start_datetime",
        "end_datetime",
        "status",
        (_("Meeting URL"), "meeting_link_col"),
        "booker_timezone",
        "cancellation_reason",
    ]
    actions = [
        {
            "action": _("Change Status"),
            "src": "assets/icons/change.svg",
            "img_class": "w-3 h-3 filter brightness-0 invert",
            "permission": "booking.change_booking",
            "attrs": """
                class="justify-center px-4 py-2 bg-primary-600 text-white rounded-md text-xs flex items-center gap-2 hover:bg-primary-800 transition duration-300 cursor-pointer"
                hx-get="{get_status_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal()"
            """,
        },
    ]
