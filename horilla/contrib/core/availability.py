"""
Who is unavailable at a given time?

Users mark themselves unavailable in the calendar app (``UserAvailability``).
This module lets the rest of the CRM (lead assignment, cadences, workflows,
approvals, reviews) ask about it without importing the optional calendar app.
When the calendar app is not installed nobody is ever unavailable.

A period counts for a time window ``[start, end]`` when it overlaps it:
``from_datetime <= end and to_datetime >= start``. Both ends are inclusive,
like ``UserAvailability.is_currently_unavailable``. ``end=None`` makes the
window the single moment ``start``. Everything is compared as aware datetimes;
only the date shown to a person needs the viewer's time zone.
"""

# Third-party imports (Django)
from django.utils.formats import date_format

# First party imports (Horilla)
from horilla.apps import apps
from horilla.utils import timezone

CALENDAR_APP = "horilla.contrib.calendar"


def calendar_installed():
    """True when the calendar app, which stores the unavailability, is installed."""
    return apps.is_installed(CALENDAR_APP)


def _overlapping(start, end=None):
    """
    Return the unavailability periods that overlap ``[start, end]``, or None
    when the calendar app is not installed.

    ``all_objects`` is used on purpose: the default manager narrows rows to the
    company of the current request, and someone's leave applies whichever
    company is being looked at.
    """
    if not calendar_installed():
        return None
    availability = apps.get_model("calendar", "UserAvailability")
    return availability.all_objects.filter(
        from_datetime__lte=start if end is None else end,
        to_datetime__gte=start,
    )


def unavailable_user_ids(start, end=None, users=None):
    """
    Return the ids of the users who are unavailable at some point of
    ``[start, end]``.

    ``users`` (ids, or a queryset of users) narrows the search to those people.
    One query.
    """
    periods = _overlapping(start, end)
    if periods is None:
        return set()
    if users is not None:
        if hasattr(users, "values_list"):
            users = users.values_list("pk", flat=True)
        periods = periods.filter(user_id__in=users)
    return set(periods.values_list("user_id", flat=True))


def exclude_unavailable(users_qs, start, end=None):
    """
    Return ``users_qs`` without the users who are unavailable at some point of
    ``[start, end]``.

    A ``pk__in`` subquery is used rather than excluding across the reverse
    relation, which does not combine several conditions on one row.
    """
    periods = _overlapping(start, end)
    if periods is None:
        return users_qs
    return users_qs.exclude(pk__in=periods.values("user_id"))


def unavailable_until(user_ids, at):
    """
    Return ``{user_id: datetime}``: when each of ``user_ids`` who is unavailable
    at ``at`` is back.

    Periods that overlap or follow each other without a gap are chained, so a
    leave entered as "Mon-Tue" and "Wed-Fri" reports the end of Friday. People
    who are available at ``at`` are left out.
    """
    user_ids = list(user_ids)
    result = {}
    if not user_ids or not calendar_installed():
        return result
    availability = apps.get_model("calendar", "UserAvailability")
    # Periods that end before ``at`` cannot take part in a chain that covers it.
    rows = (
        availability.all_objects.filter(user_id__in=user_ids, to_datetime__gte=at)
        .order_by("user_id", "from_datetime")
        .values_list("user_id", "from_datetime", "to_datetime")
    )
    by_user = {}
    for user_id, from_datetime, to_datetime in rows:
        by_user.setdefault(user_id, []).append((from_datetime, to_datetime))
    for user_id, periods in by_user.items():
        back = None
        for from_datetime, to_datetime in periods:
            if back is None:
                # The chain has to start by covering ``at`` itself.
                if from_datetime <= at <= to_datetime:
                    back = to_datetime
            elif from_datetime <= back:
                back = max(back, to_datetime)
        if back is not None:
            result[user_id] = back
    return result


def format_when(moment):
    """
    ``moment`` as "25 Nov 2026, 5:00 PM" in the viewer's time zone (the active
    one), for tooltips that say when someone is back.
    """
    return date_format(timezone.localtime(moment), "j M Y, g:i A")
