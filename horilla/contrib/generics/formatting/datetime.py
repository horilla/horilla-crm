"""
Gregorian date/time formatting used across Horilla template tags and views.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils.dateparse import parse_date as django_parse_date
from django.utils.dateparse import parse_datetime as django_parse_datetime

from horilla.utils import timezone


class DateTimeFormatter:
    """
    Format and parse date/datetime/time with user/company preferences.

    Extension apps may subclass via ``DateTimeFormatterExtension`` and override
    ``format_*`` / ``parse_*`` / ``period_bounds`` (e.g. Jalali).
    """

    def format(self, value, user=None, company=None, convert_timezone=True):
        """
        Format a date, datetime, or time value using user's format, else company's.

        Returns formatted string, ``""`` for ``None``, or ``None`` if value is not
        a date/datetime/time.
        """
        if value is None:
            return ""
        if isinstance(value, datetime):
            value = self._apply_timezone(
                value, user=user, company=company, convert_timezone=convert_timezone
            )
            fmt = self._resolve_datetime_format(user=user, company=company)
            return self.format_datetime(value, fmt, user=user)
        if isinstance(value, date):
            fmt = self._resolve_date_format(user=user, company=company)
            return self.format_date(value, fmt, user=user)
        if isinstance(value, time):
            fmt = self._resolve_time_format(user=user, company=company)
            return self.format_time(value, fmt, user=user)
        return None

    def format_datetime(self, value, fmt, *, user=None):
        """Format a datetime with ``strftime`` (Gregorian)."""
        try:
            return value.strftime(fmt)
        except Exception:
            return value.strftime("%Y-%m-%d %H:%M:%S")

    def format_date(self, value, fmt, *, user=None):
        """Format a date with ``strftime`` (Gregorian)."""
        try:
            return value.strftime(fmt)
        except Exception:
            return value.strftime("%Y-%m-%d")

    def format_time(self, value, fmt, *, user=None):
        """Format a time with ``strftime``."""
        try:
            return value.strftime(fmt)
        except Exception:
            return value.strftime("%I:%M:%S %p")

    def parse_date(self, value, *, user=None):
        """Parse a date string into a Gregorian ``date`` (or ``None``)."""
        if not value:
            return None
        return django_parse_date(str(value).strip())

    def period_bounds(self, period, day, *, user=None):
        """
        Return the inclusive ``(start, end)`` dates of the ``"week"`` or
        ``"month"`` that contains ``day``, or ``(None, None)`` for another
        ``period``.

        Gregorian, with weeks starting on Monday. Calendar extensions (e.g.
        Jalali) override this, so "This Week" and "This Month" follow the
        calendar the user reads dates in.
        """
        if period == "week":
            start = day - timedelta(days=day.weekday())
            return start, start + timedelta(days=6)
        if period == "month":
            start = day.replace(day=1)
            next_month = (start + timedelta(days=31)).replace(day=1)
            return start, next_month - timedelta(days=1)
        return None, None

    def parse_datetime(self, value, *, user=None):
        """Parse a datetime string into a Gregorian ``datetime`` (or ``None``)."""
        if not value:
            return None
        raw = str(value).strip()
        parsed = django_parse_datetime(raw)
        if parsed is not None:
            return parsed
        try:
            return datetime.strptime(raw, "%Y-%m-%dT%H:%M")
        except ValueError:
            return None

    def _apply_timezone(self, value, *, user=None, company=None, convert_timezone=True):
        if convert_timezone:
            tz_str = (user and getattr(user, "time_zone", None)) or (
                company and getattr(company, "time_zone", None)
            )
            if tz_str:
                try:
                    user_tz = ZoneInfo(tz_str)
                    if timezone.is_naive(value):
                        value = timezone.make_aware(
                            value, timezone.get_default_timezone()
                        )
                    value = value.astimezone(user_tz)
                    return value
                except Exception:
                    pass
            # No usable user/company timezone: fall back to the server's
            # local timezone rather than silently returning raw UTC, which
            # would otherwise be formatted and displayed as if it were
            # already in local time.
            if timezone.is_aware(value):
                value = timezone.localtime(value)
        elif timezone.is_aware(value):
            value = timezone.localtime(value)
        return value

    def _resolve_datetime_format(self, *, user=None, company=None) -> str:
        if user and getattr(user, "date_time_format", None):
            return user.date_time_format
        if company and getattr(company, "date_time_format", None):
            return company.date_time_format
        return "%Y-%m-%d %H:%M:%S"

    def _resolve_date_format(self, *, user=None, company=None) -> str:
        if user and getattr(user, "date_format", None):
            return user.date_format
        if company and getattr(company, "date_format", None):
            return company.date_format
        return "%Y-%m-%d"

    def _resolve_time_format(self, *, user=None, company=None) -> str:
        if user and getattr(user, "time_format", None):
            return user.time_format
        if company and getattr(company, "time_format", None):
            return company.time_format
        return "%I:%M:%S %p"
