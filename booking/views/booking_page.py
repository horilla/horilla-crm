"""
Booking page settings views — CRUD, availability, embed/share, and toggle partials.
"""

# Standard library imports
import logging
from functools import cached_property

# Third-party imports (Django)
from django.contrib import messages

from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
)
from horilla.contrib.mail.models import HorillaMailConfiguration
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse_lazy
from horilla.utils.choices import DAY_LABELS, WEEK_ORDER
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View

# First party imports (Horilla)
from horilla.web import HttpResponseRedirect

# Local imports
from ..filters import BookingPageFilter
from ..forms import BookingPageForm
from ..models import BookingPage
from ..utils import _get_day_hours

_get_schedule_hours = _get_day_hours

logger = logging.getLogger(__name__)

# ─── Settings ────────────────────────────────────────────────────────────────


class GoToWorkingHoursView(LoginRequiredMixin, View):
    """
    Sets the Working Hours tab as active for the company tab view, then
    redirects to Company Information so the tab opens directly.
    """

    def get(self, request, *args, **kwargs):
        """Activate the Working Hours tab and redirect to Company Information."""
        from horilla.contrib.core.models import ActiveTab

        tab_path = "/company-tab-view/"
        tab_target = "tab-business-hour-view-content"
        company = getattr(request, "active_company", None) or getattr(
            request.user, "company", None
        )

        ActiveTab.objects.filter(created_by=request.user, path=tab_path).delete()
        ActiveTab.objects.create(
            created_by=request.user,
            path=tab_path,
            tab_target=tab_target,
            company=company,
        )
        return HttpResponseRedirect("/company-information/")


class BookingSettingsView(LoginRequiredMixin, View):
    """Settings page for Booking Pages — renders nav + list directly, no tabs."""

    def get(self, request, *args, **kwargs):
        """Render the booking settings page with nav and list URLs."""
        from horilla.contrib.core.models.business_hours import BusinessHour

        active_company = getattr(request, "active_company", None)
        has_business_hour = (
            BusinessHour.objects.filter(company=active_company).exists()
            if active_company
            else BusinessHour.objects.exists()
        )
        return render(
            request,
            "settings/booking_pages.html",
            {
                "nav_url": str(reverse_lazy("booking:booking_page_nav")),
                "list_url": str(reverse_lazy("booking:booking_page_list")),
                "has_business_hour": has_business_hour,
            },
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("booking.view_bookingpage"), name="dispatch")
class BookingPageNavView(LoginRequiredMixin, HorillaNavView):
    """Horilla navbar for the Booking Pages settings view."""

    nav_description = _("Create booking pages so others can schedule time with you.")
    search_url = reverse_lazy("booking:booking_page_list")
    main_url = reverse_lazy("booking:booking_settings")
    filterset_class = BookingPageFilter
    model_name = "bookingpage"
    model_app_label = "booking"
    nav_width = False
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False

    @cached_property
    def new_button(self):
        """New button for lead"""
        if self.request.user.has_perm("booking.add_bookingpage"):
            return {
                "url": str(reverse_lazy("booking:booking_page_create")),
                "attrs": {"id": "booking-page-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("booking.view_bookingpage"), name="dispatch")
class BookingPageListView(LoginRequiredMixin, HorillaListView):
    """List view for BookingPage records in settings."""

    model = BookingPage
    view_id = "booking-page-list"
    filterset_class = BookingPageFilter
    search_url = reverse_lazy("booking:booking_page_list")
    main_url = reverse_lazy("booking:booking_settings")
    save_to_list_option = False
    bulk_select_option = False
    max_visible_actions = 5
    list_column_visibility = False

    @cached_property
    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        if self.request.user.has_perm("booking.add_bookingpage"):
            return {
                "url": str(reverse_lazy("booking:booking_page_create")),
                "attrs": 'id="booking-page-create"',
            }
        return None

    columns = [
        "title",
        "host",
        "duration",
        "is_online",
        "meeting_provider",
        "is_active",
    ]

    @cached_property
    def col_attrs(self):
        """Return column attribute overrides that make the title open the detail panel."""
        return [
            {
                "title": {
                    "hx-get": "{get_detail_url}",
                    "hx-target": "#settings-content",
                    "hx-swap": "innerHTML",
                    "permission": "booking.view_booking",
                }
            }
        ]

    actions = [
        {
            "action": _("Edit"),
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "booking.change_bookingpage",
            "attrs": """
                hx-get="{get_edit_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal()"
            """,
        },
        {
            "action": _("Availability"),
            "src": "assets/icons/booking-calendar.svg",
            "img_class": "w-4 h-4",
            "permission": "booking.change_bookingpage",
            "attrs": """
                hx-get="{get_availability_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal()"
            """,
        },
        {
            "action": _("Embed"),
            "src": "assets/icons/booking-share.svg",
            "img_class": "w-4 h-4",
            "permission": "booking.view_bookingpage",
            "attrs": """
                hx-get="{get_embed_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal()"
            """,
        },
        {
            "action": _("Delete"),
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "booking.delete_bookingpage",
            "attrs": """
                hx-post="{get_delete_url}"
                hx-target="#deleteModeBox"
                hx-swap="innerHTML"
                hx-trigger="click"
                onclick="openDeleteModeModal()"
            """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("booking.add_bookingpage"), name="dispatch")
class BookingPageCreateView(LoginRequiredMixin, HorillaSingleFormView):
    """Create a new BookingPage."""

    model = BookingPage
    form_class = BookingPageForm
    modal_height_class = "h-[600px]"
    full_width_fields = ["description"]

    @property
    def form_url(self):
        """Return the POST URL for the create form."""
        if self.object:
            return reverse_lazy(
                "booking:booking_page_edit", kwargs={"pk": self.object.pk}
            )
        return reverse_lazy("booking:booking_page_create")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if "initial" not in kwargs:
            kwargs["initial"] = {}
        kwargs["initial"]["host"] = self.request.user.pk
        return kwargs

    def form_valid(self, form):
        """Save the booking page, warning if no outgoing mail server is configured."""
        response = super().form_valid(form)
        if not HorillaMailConfiguration.objects.filter(
            mail_channel="outgoing"
        ).exists():
            messages.warning(
                self.request,
                _(
                    "No outgoing mail configuration is set up. Booking "
                    "confirmation, reminder, and cancellation emails will not "
                    "be delivered until a mail server is configured."
                ),
            )
        return response


@method_decorator(htmx_required, name="dispatch")
class BookingToggleLocationView(LoginRequiredMixin, View):
    """Return the location and meeting provider partials based on the is_online state."""

    def post(self, request, *args, **kwargs):
        """Swap the location field and meeting provider field depending on is_online."""
        is_online = request.POST.get("is_online") == "on"
        location_value = request.POST.get("location", "")
        meeting_provider_value = request.POST.get("meeting_provider", "")

        provider_choices = BookingPageForm._meeting_provider_choices(request.user)
        valid_values = {value for value, _label in provider_choices}
        return render(
            request,
            "partials/location_field.html",
            {
                "show_location": not is_online,
                "location_value": location_value,
                "show_meeting_provider": is_online,
                "meeting_provider_value": (
                    meeting_provider_value
                    if meeting_provider_value in valid_values
                    else ""
                ),
                "meeting_provider_choices": [
                    choice for choice in provider_choices if choice[0]
                ],
            },
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("booking.delete_bookingpage"), name="dispatch")
class BookingPageDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """Delete a BookingPage."""

    model = BookingPage
    success_url = reverse_lazy("booking:booking_page_list")


@method_decorator(htmx_required, name="dispatch")
class BookingToggleRescheduleCutoffView(LoginRequiredMixin, View):
    """Return reschedule_cutoff_days field based on allow_reschedule state."""

    def post(self, request, *args, **kwargs):
        """Re-render the reschedule cutoff field partial based on toggle state."""
        allow = request.POST.get("allow_reschedule") == "on"
        value = request.POST.get("reschedule_cutoff_days", "1")
        return render(
            request,
            "partials/reschedule_cutoff_field.html",
            {"show_field": allow, "field_value": value},
        )


@method_decorator(htmx_required, name="dispatch")
class BookingToggleCancelCutoffView(LoginRequiredMixin, View):
    """Return cancel_cutoff_days field based on allow_cancel state."""

    def post(self, request, *args, **kwargs):
        """Re-render the cancel cutoff field partial based on toggle state."""
        allow = request.POST.get("allow_cancel") == "on"
        value = request.POST.get("cancel_cutoff_days", "1")
        return render(
            request,
            "partials/cancel_cutoff_field.html",
            {"show_field": allow, "field_value": value},
        )


# ─── Availability ────────────────────────────────────────────────────────────


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("booking.change_bookingpage"), name="dispatch")
class BookingAvailabilityView(LoginRequiredMixin, View):
    """
    Modal panel showing:
    - The BusinessHour schedule linked to this page
    - The ShiftHour schedule (if set — overrides BH for slot times)
    - The host's UserUnavailability blocks from the calendar app
    Hosts can add / delete unavailability blocks directly from here.
    """

    template_name = "settings/booking_availability.html"

    def get(self, request, pk):
        """Render the availability modal for the given BookingPage."""
        from horilla.contrib.calendar.models import UserAvailability

        page = get_object_or_404(BookingPage, pk=pk)
        bh = page.business_hour
        sh = page.shift_hour
        schedule = sh or bh

        day_rows = []
        if schedule:
            for code in WEEK_ORDER:
                start, end = _get_schedule_hours(schedule, code)
                day_rows.append(
                    {
                        "label": str(DAY_LABELS[code]),
                        "start": start,
                        "end": end,
                        "open": start is not None,
                    }
                )

        all_users = [page.host_id] + list(
            page.participants.values_list("id", flat=True)
        )
        unavailabilities = (
            UserAvailability.objects.filter(user__in=all_users)
            .select_related("user")
            .order_by("from_datetime")
        )

        return render(
            request,
            self.template_name,
            {
                "page": page,
                "business_hour": bh,
                "shift_hour": sh,
                "day_rows": day_rows,
                "unavailabilities": unavailabilities,
            },
        )


# ─── Embed / Share ────────────────────────────────────────────────────────────


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("booking.view_bookingpage"), name="dispatch")
class BookingEmbedView(LoginRequiredMixin, View):
    """Show embed code and public URL for a BookingPage."""

    template_name = "settings/booking_embed.html"

    def get(self, request, pk):
        """Render the embed/share modal for the given BookingPage."""
        page = get_object_or_404(BookingPage, pk=pk)
        public_url = page.get_public_url(request)
        return render(
            request, self.template_name, {"page": page, "public_url": public_url}
        )
