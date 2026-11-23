"""
Shared helpers for horilla_tags (no template register).
Used by datetime_filters, field_filters, display_tags, etc.
"""

# First party imports (Horilla)
from horilla.contrib.utils.middlewares import _thread_local, get_active_company


def _get_request_user_company():
    """Get request, user, and company from thread-local. Used for format fallback."""
    request = getattr(_thread_local, "request", None)
    user = (
        request.user
        if request and hasattr(request, "user") and request.user.is_authenticated
        else None
    )
    company = None
    if request:
        company = get_active_company(request)
    if not company and user:
        company = getattr(user, "company", None)
    return request, user, company


def format_datetime_value(value, user=None, company=None, convert_timezone=True):
    """
    Format a date, datetime, or time value using user's format, else company's.

    Delegates to the composed ``DateTimeFormatter``.

    Returns formatted string, or None if value is not date/datetime/time.
    """
    # Lazy import: avoid cycles with extension bootstrap / generics imports.
    from horilla.extension.formatting import get_datetime_formatter

    return get_datetime_formatter().format(
        value,
        user=user,
        company=company,
        convert_timezone=convert_timezone,
    )


def display_fk(value):
    """Return the string representation of a related foreign-key value if available."""
    if hasattr(value, "__str__"):
        return str(value)
    return value
