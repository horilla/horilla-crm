"""
Filters for the horilla_booking app.
"""

from horilla.contrib.generics.filters import HorillaFilterSet

from .models import Booking, BookingPage


class BookingPageFilter(HorillaFilterSet):
    """Filter for BookingPage list view."""

    class Meta:
        """Meta options for BookingPageFilter."""

        model = BookingPage
        fields = "__all__"
        exclude = ["additional_info", "questions"]
        search_fields = [
            "title",
            "host__username",
            "host__first_name",
            "host__last_name",
            "location",
        ]
        name_split_fields = ["host__first_name", "host__last_name"]


class BookingFilter(HorillaFilterSet):
    """Filter for Booking list view."""

    class Meta:
        """Meta options for BookingFilter."""

        model = Booking
        fields = "__all__"
        exclude = [
            "additional_info",
            "answers",
            "cancellation_token",
            "cancellation_reason",
        ]
        search_fields = ["booker_name", "booker_email", "booking_page__title"]
