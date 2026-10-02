"""
Shamsi (Jalali) display for History tab timestamps and date diff values.

Registered with the generics ``history_datetime`` filter from
``registration.py``; the filter keeps its default format when the Shamsi
calendar is not active.
"""

# Standard library imports
from datetime import date, datetime

# Third-party imports
from dateutil import parser as dateutil_parser

# First party imports (Horilla)
from horilla.extension.formatting import get_datetime_formatter
from horilla_jalali.calendar import (
    format_gregorian_as_jalali,
    parse_localized_gregorian_display,
    uses_jalali_calendar,
)


def format_shamsi(value, *, user=None, company=None, convert_timezone=True):
    """Timezone-adjust then format with the Jalali calendar (24-hour, no seconds)."""
    formatter = get_datetime_formatter()
    if isinstance(value, datetime):
        if convert_timezone:
            value = formatter._apply_timezone(
                value, user=user, company=company, convert_timezone=True
            )
        fmt = formatter._resolve_datetime_format(user=user, company=company)
    elif isinstance(value, date):
        fmt = formatter._resolve_date_format(user=user, company=company)
    else:
        return None
    return format_gregorian_as_jalali(value, fmt)


def parse_history_datetime_string(value):
    """Parse a stored diff display string, including Django's Persian-localized
    Gregorian form (``19 اوت 2026، ساعت 8:27``). A value without a time parses
    as a ``date``."""
    if not isinstance(value, str) or value in ("", "--", "None", "none"):
        return None
    localized = parse_localized_gregorian_display(value)
    if localized is not None:
        return localized
    try:
        parsed = dateutil_parser.parse(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if ":" not in value:
        return parsed.date()
    return parsed


def format_history_datetime_as_jalali(value, *, user=None, company=None):
    """``history_datetime`` formatter: Shamsi when the Jalali calendar is active.

    Returns ``None`` (keep the default format) otherwise, or when ``value``
    is not a date/datetime or a string that parses as one.
    """
    if not uses_jalali_calendar(user=user):
        return None
    if isinstance(value, (date, datetime)):
        return format_shamsi(value, user=user, company=company)
    parsed = parse_history_datetime_string(value)
    if parsed is None:
        return None
    # auditlog writes DateTimeField diff values in settings.TIME_ZONE, not the
    # viewer's timezone, so shift them the same way as the entry timestamps.
    # Date-only values parse as dates and are never shifted.
    return format_shamsi(parsed, user=user, company=company)
