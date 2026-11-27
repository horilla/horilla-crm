"""
``_inherit_formatter`` for Jalali date/time display and parse.

Does not change stored values (database remains Gregorian).
"""

from horilla.contrib.generics.formatting import DateTimeFormatter
from horilla.extension.formatting import DateTimeFormatterExtension
from horilla_jalali.calendar import (
    format_gregorian_as_jalali,
    parse_jalali_date,
    parse_jalali_datetime,
    shamsi_period_bounds,
    uses_jalali_calendar,
)


def _request_user():
    """The signed-in user of the current request, or ``None``."""
    from horilla.contrib.utils.middlewares import get_current_request

    user = getattr(get_current_request(), "user", None)
    return user if getattr(user, "is_authenticated", False) else None


class JalaliDateTimeFormatterExtension(DateTimeFormatterExtension):
    """Override DateTimeFormatter format/parse when Shamsi calendar is active."""

    _inherit_formatter = (
        "horilla.contrib.generics.formatting.datetime.DateTimeFormatter"
    )

    def format_date(self, value, fmt, *, user=None):
        """Format a date as Jalali when the Shamsi calendar is active."""
        if not uses_jalali_calendar(user=user):
            return DateTimeFormatter.format_date(self, value, fmt, user=user)
        try:
            return format_gregorian_as_jalali(value, fmt)
        except Exception:
            return DateTimeFormatter.format_date(self, value, fmt, user=user)

    def format_datetime(self, value, fmt, *, user=None):
        """Format a datetime as Jalali when the Shamsi calendar is active."""
        if not uses_jalali_calendar(user=user):
            return DateTimeFormatter.format_datetime(self, value, fmt, user=user)
        try:
            return format_gregorian_as_jalali(value, fmt)
        except Exception:
            return DateTimeFormatter.format_datetime(self, value, fmt, user=user)

    def parse_date(self, value, *, user=None):
        """Parse a Jalali date string when the Shamsi calendar is active."""
        if uses_jalali_calendar(user=user):
            parsed = parse_jalali_date(value)
            if parsed is not None:
                return parsed
        return DateTimeFormatter.parse_date(self, value, user=user)

    def period_bounds(self, period, day, *, user=None):
        """
        The Shamsi week (Saturday to Friday) or month when the Shamsi calendar
        is active, so "This Week" and "This Month" match the dates shown.

        Callers without a user (the dashboard's date filter) get the request's
        user, so a Persian user who chose the Gregorian calendar keeps it.
        """
        if user is None:
            user = _request_user()
        if uses_jalali_calendar(user=user):
            bounds = shamsi_period_bounds(period, day)
            if bounds is not None:
                return bounds
        return DateTimeFormatter.period_bounds(self, period, day, user=user)

    def parse_datetime(self, value, *, user=None):
        """Parse a Jalali datetime string when the Shamsi calendar is active."""
        if uses_jalali_calendar(user=user):
            parsed = parse_jalali_datetime(value)
            if parsed is not None:
                return parsed
        return DateTimeFormatter.parse_datetime(self, value, user=user)
