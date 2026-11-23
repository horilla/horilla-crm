"""Shared helpers and constants for the calendar views."""

# Standard library imports
import datetime
import re

# Third-party imports (Django)
from django.db.models.functions import Coalesce
from django.utils.dateparse import parse_datetime
from django.utils.encoding import force_str

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.activity.methods import get_related_record_urls
from horilla.contrib.activity.models import Activity
from horilla.contrib.core.utils import get_allowed_user_ids
from horilla.contrib.generics.templatetags.horilla_tags._shared import (
    format_datetime_value,
)
from horilla.contrib.generics.views.details import check_record_change_access
from horilla.contrib.generics.views.helpers.queryset_utils import (
    apply_conditions,
    get_granted_access_filter,
    get_queryset_for_module,
)
from horilla.contrib.utils.middlewares import get_active_company
from horilla.db.models import Q
from horilla.utils import timezone
from horilla.utils.translation import gettext as _

# Local imports
from ..models import UserCalendarPreference

# Default sidebar/checkbox colors per calendar type (keep in sync with calendar UI).
DEFAULT_CALENDAR_TYPE_COLORS = {
    "task": "#3B82F6",
    "event": "#10B981",
    "meeting": "#F50CCE",
    "unavailability": "#F5E614",
}


# Default "Color by: Status" colors; user overrides are UserCalendarPreference rows.
DEFAULT_STATUS_COLORS = {
    "status_completed": "#10B981",
    "status_pending": "#F97316",
}


TEXT_COLOR_PREFIX = "text_"


DEFAULT_TEXT_COLOR = "#FFFFFF"


HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _related_record_urls(activities, user):
    """
    Map each related record's ``(content_type_id, object_id)`` to its detail
    URL if the user may open it, else "". The records are checked together, so
    a month of activities on hundreds of records costs a few queries per
    related model rather than a few per record.
    """
    records = {}
    for activity in activities:
        key = (activity.content_type_id, activity.object_id)
        if all(key) and key not in records and activity.related_object:
            records[key] = activity.related_object
    return get_related_record_urls(records, user)


def _choice_labels(model, field_name):
    """
    Return ``{value: label}`` for a choices field, as get_<field>_display()
    renders them. That method rebuilds and hashes the lazy labels on every
    call, which adds up over a month of events.
    """
    return {
        value: force_str(label, strings_only=True)
        for value, label in model._meta.get_field(field_name).flatchoices
    }


def _pk_url(url_method):
    """
    Return ``activity -> str(url_method(activity))`` for an Activity URL method
    that depends only on the pk, such as get_detail_url().

    Reversing a URL per event is a large share of a busy month's response, so
    reverse once for a placeholder pk and put each event's pk in its place.
    Falls back to calling the method if the placeholder isn't in the URL
    exactly once.
    """
    placeholder = "2147483647"
    url = str(url_method(Activity(pk=int(placeholder))))
    if url.count(placeholder) != 1:
        return lambda activity: str(url_method(activity))
    prefix, suffix = url.split(placeholder)
    return lambda activity: f"{prefix}{activity.pk}{suffix}"


def _team_scope_available(user):
    """
    Return True if the calendar's Team view would show ``user`` more than
    their own activities.

    Follows the All Activities list (``HorillaListView.get_queryset``):
    ``activity.view_activity`` covers every activity in the company, while
    ``activity.view_own_activity`` covers those owned by or assigned to the
    user or anyone in a subordinate role, so it only adds something for a
    user with subordinates (or a granted-access filter on Activity).
    """
    if user.has_perm("activity.view_activity"):
        return True
    if not user.has_perm("activity.view_own_activity"):
        return False
    return (
        len(get_allowed_user_ids(user)) > 1
        or get_granted_access_filter(Activity, user, "view") is not None
    )


def _team_members(request):
    """
    Return the users the Team view can be narrowed to, for the members filter.

    Everyone in the active company with ``activity.view_activity``, otherwise
    the user and the users in subordinate roles (``activity.view_own_activity``).
    Nobody when the Team view is not available to the user.
    """
    user = request.user
    if not _team_scope_available(user):
        return User.objects.none()
    if user.has_perm("activity.view_activity"):
        company = get_active_company(request)
        members = User.objects.filter(company=company)
    else:
        members = User.objects.filter(pk__in=get_allowed_user_ids(user))
    return (
        members.filter(is_active=True)
        .select_related("role")
        .order_by("first_name", "last_name", "pk")
    )


def _requested_member_ids(request):
    """
    Return the member ids the Team view is narrowed to, or None for everyone.

    Only ids from ``_team_members`` count, so the parameter can never reach
    beyond what the filter offers.
    """
    requested = {
        int(value) for value in request.GET.getlist("members[]") if str(value).isdigit()
    }
    if not requested:
        return None
    allowed = set(
        _team_members(request).filter(pk__in=requested).values_list("pk", flat=True)
    )
    return allowed or None


def _calendar_activities(user, activity_types, team=False, member_ids=None):
    """
    Return the activities of ``activity_types`` to show on ``user``'s calendar.

    Without ``team`` ("Mine"), these are the activities the user is assigned
    to, takes part in, owns or hosts. ``team`` adds the activities the user
    may see in the All Activities list: every one with
    ``activity.view_activity``, otherwise those whose ``OWNER_FIELDS`` hold
    the user or a subordinate (``activity.view_own_activity``). Without
    either permission ``team`` adds nothing, so the request parameter can
    never widen what a user sees.

    ``member_ids`` narrows the Team view to the activities owned by or
    assigned to those users; it has no effect on Mine.
    """
    queryset = Activity.objects.filter(activity_type__in=activity_types)
    visible = (
        Q(assigned_to=user)
        | Q(participants=user)
        | Q(owner=user)
        | Q(meeting_host=user)
    )
    if team and user.has_perm("activity.view_activity"):
        activities = queryset
    else:
        if team and user.has_perm("activity.view_own_activity"):
            allowed_user_ids = list(get_allowed_user_ids(user))
            for field_name in Activity.OWNER_FIELDS:
                visible |= Q(**{f"{field_name}__in": allowed_user_ids})
            granted_query = get_granted_access_filter(Activity, user, "view")
            if granted_query is not None:
                visible |= granted_query
        activities = queryset.filter(visible)
    if team and member_ids:
        by_member = Q()
        for field_name in Activity.OWNER_FIELDS:
            by_member |= Q(**{f"{field_name}__in": member_ids})
        activities = activities.filter(by_member)
    return activities


def _requested_range(request):
    """
    Return the ``(start, end)`` window FullCalendar asks events for, or None.

    FullCalendar sends its visible range as ISO 8601 ``start``/``end`` and
    draws only what overlaps it. It gives an event without a usable end a
    default length and snaps all-day events to whole days, so the window is
    widened by a day on each side to never drop an event it would draw.
    A missing or malformed bound means no window, as before the calendar
    sent one.
    """
    try:
        start = parse_datetime(request.GET.get("start", ""))
        end = parse_datetime(request.GET.get("end", ""))
        if start is None or end is None:
            return None
        if timezone.is_naive(start):
            start = timezone.make_aware(start)
        if timezone.is_naive(end):
            end = timezone.make_aware(end)
        if start >= end:
            return None
        margin = datetime.timedelta(days=1)
        # Converted to UTC as the database stores them; a bound too close to
        # the datetime limits overflows here instead of in the query.
        return (
            (start - margin).astimezone(datetime.timezone.utc),
            (end + margin).astimezone(datetime.timezone.utc),
        )
    except (ValueError, OverflowError):
        return None


def _whole_day_span(start, end):
    """
    Return (first_day, last_day) when start..end covers whole days, else None.

    That is a start at 00:00 and an end at 23:59 (or exactly 00:00 of a later
    day, which is the same moment as the end of the day before).
    """
    if not start or not end:
        return None
    first = timezone.localtime(start)
    last = timezone.localtime(end)
    if (first.hour, first.minute) != (0, 0):
        return None
    if (last.hour, last.minute) == (23, 59):
        last_day = last.date()
    elif (last.hour, last.minute) == (0, 0) and last.date() > first.date():
        last_day = last.date() - datetime.timedelta(days=1)
    else:
        return None
    if last_day < first.date():
        return None
    return first.date(), last_day


def _multi_day_span(start, end):
    """
    Return (first_day, last_day) when start..end crosses midnight, else None.

    An end of exactly 00:00 belongs to the day before. Like Google Calendar,
    such a block is drawn in the all-day row instead of being cut into one
    time-grid slice per day.
    """
    if not start or not end:
        return None
    first = timezone.localtime(start)
    last = timezone.localtime(end)
    last_day = last.date()
    if (last.hour, last.minute) == (0, 0):
        last_day -= datetime.timedelta(days=1)
    if last_day <= first.date():
        return None
    return first.date(), last_day


def _all_day_fields(request, first_day, last_day):
    """FullCalendar start/end (end exclusive) and the popup texts for whole days."""
    return {
        "start": first_day.isoformat(),
        "end": (last_day + datetime.timedelta(days=1)).isoformat(),
        "start_display": (
            f"{format_datetime_value(first_day, user=request.user)} ({_('All Day')})"
        ),
        "end_display": format_datetime_value(last_day, user=request.user),
    }


def _activity_events(request, activities, team, custom_calendar=None):
    """
    Turn an Activity queryset into FullCalendar event dicts.

    The queryset is narrowed to FullCalendar's visible window. With
    ``custom_calendar`` the events take its color and are keyed to it
    (``calendarType`` ``custom_<pk>``) so the sidebar's checkbox and color
    pickers drive them; ``activityType`` still holds the real type.
    """
    date_range = _requested_range(request)
    if date_range:
        range_start, range_end = date_range
        # Same start/end fallbacks as the event payload below.
        activities = activities.alias(
            calendar_start=Coalesce("start_datetime", "due_datetime", "created_at"),
            calendar_end=Coalesce("end_datetime", "due_datetime", "created_at"),
        ).filter(
            Q(calendar_start__gte=range_start) | Q(calendar_end__gte=range_start),
            calendar_start__lt=range_end,
        )
    if team:
        # check_record_change_access() reads each owner.
        activities = activities.select_related("owner")
    activities = activities.prefetch_related("assigned_to", "related_object")
    activities = list(activities.distinct())
    can_delete = team and request.user.has_perm("activity.delete_activity")

    related_urls = _related_record_urls(activities, request.user)
    activity_type_labels = _choice_labels(Activity, "activity_type")
    status_labels = _choice_labels(Activity, "status")
    edit_url = _pk_url(Activity.get_activity_edit_url)
    delete_url = _pk_url(Activity.get_delete_url)
    detail_url = _pk_url(Activity.get_detail_url)

    events = []
    for activity in activities:
        start_dt = activity.get_start_date()
        end_dt = activity.get_end_date()
        start_display = (
            format_datetime_value(start_dt, user=request.user)
            if not isinstance(start_dt, str)
            else start_dt
        )
        end_display = (
            format_datetime_value(end_dt, user=request.user)
            if not isinstance(end_dt, str) and end_dt
            else None
        )
        due_date_display = None
        if activity.activity_type == "task" and activity.due_datetime:
            due_date_display = format_datetime_value(
                activity.due_datetime, user=request.user
            )
        # get_start_date()/get_end_date() return a translated
        # "All Day Event" label (not a datetime) for all-day
        # events/meetings, so the actual ISO timestamps for
        # FullCalendar must come from the raw datetime fields.
        start_raw = (
            activity.start_datetime or activity.due_datetime or activity.created_at
        )
        end_raw = activity.end_datetime or activity.due_datetime or activity.created_at
        all_day_fields = None
        if activity.activity_type in ["event", "meeting"] and activity.is_all_day:
            # An all-day activity spans whole days: show the dates, not the
            # "All Day Event" label with an empty end.
            all_day_fields = _all_day_fields(
                request,
                timezone.localtime(start_raw).date(),
                timezone.localtime(end_raw or start_raw).date(),
            )
            start_display = all_day_fields["start_display"]
            end_display = all_day_fields["end_display"]
        type_label = activity_type_labels.get(
            activity.activity_type, activity.activity_type
        )
        event = {
            # The type after the name tells apart e.g. a task and an event
            # that share a name.
            "title": f"{activity.title or activity.subject} - {type_label}",
            "start": start_raw.isoformat(),
            "end": end_raw.isoformat() if end_raw else None,
            "calendarType": activity.activity_type,
            "activityType": activity.activity_type,
            "activity_type_display": type_label,
            "description": activity.description or "",
            "subject": activity.subject or "",
            "assignedTo": [
                {
                    "id": user.id,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.email,
                }
                for user in activity.assigned_to.all()
            ],
            "status": activity.status,
            "status_display": status_labels.get(activity.status, activity.status),
            "start_display": start_display,
            "end_display": end_display,
            "due_date_display": due_date_display,
            "id": activity.id,
            "activityId": activity.id,
            "url": (edit_url(activity) if activity.activity_type != "email" else None),
            "deleteUrl": (
                delete_url(activity) if activity.activity_type != "email" else None
            ),
            "detailUrl": (
                detail_url(activity) if activity.activity_type != "email" else None
            ),
            "relatedUrl": related_urls.get(
                (activity.content_type_id, activity.object_id), ""
            ),
            "dueDate": (
                activity.due_datetime.isoformat()
                if activity.activity_type == "task" and activity.due_datetime
                else None
            ),
            "textColor": "#FFFFFF",
        }
        if all_day_fields:
            event["allDay"] = True
            event["start"] = all_day_fields["start"]
            event["end"] = all_day_fields["end"]
        elif activity.start_datetime and activity.end_datetime:
            # Whole days (00:00 to 23:59 / next 00:00) or a span across
            # midnight: shown in the all-day row, like Google Calendar. The
            # popup keeps the exact start and end times unless it is whole days.
            whole_days = _whole_day_span(activity.start_datetime, activity.end_datetime)
            if whole_days:
                event["allDay"] = True
                event.update(_all_day_fields(request, *whole_days))
            else:
                multi_day = _multi_day_span(
                    activity.start_datetime, activity.end_datetime
                )
                if multi_day:
                    event["allDay"] = True
                    event["start"] = multi_day[0].isoformat()
                    event["end"] = (
                        multi_day[1] + datetime.timedelta(days=1)
                    ).isoformat()
        if custom_calendar:
            calendar_type = f"custom_{custom_calendar.pk}"
            event["calendarType"] = calendar_type
            # Unique per calendar: one activity can also be on a standard type
            # or on another custom calendar.
            event["id"] = f"{calendar_type}_{activity.id}"
            event["backgroundColor"] = custom_calendar.color
            event["borderColor"] = custom_calendar.color
        if team:
            # The Team view also lists other people's
            # activities, so the popup offers only what the
            # user may do on each one, like the All Activities
            # list's row actions: Edit and Mark as Complete
            # need change access to the record, Delete needs
            # activity.delete_activity (as ActivityDeleteView).
            event["canChange"] = check_record_change_access(request.user, activity)
            event["canDelete"] = can_delete
        events.append(event)
    return events


def events_for_custom_calendar(request, cc, team=False, member_ids=None):
    """
    Return the FullCalendar events of a CustomCalendar: the chosen activity
    types of the records of its module that match its conditions.

    The records are limited the way the module's own list is (permissions and
    the calendar's conditions) and the activities by the same visibility as the
    standard calendars, so a custom calendar never shows more than they would.
    """
    model = cc.module.model_class()
    activity_types = cc.get_activity_types_list()
    if not model or not activity_types:
        return []

    records = get_queryset_for_module(request.user, model)
    records = apply_conditions(records, cc.conditions.all().order_by("sequence"))

    activities = _calendar_activities(
        request.user, activity_types, team=team, member_ids=member_ids
    ).filter(content_type=cc.module, object_id__in=records.values("pk"))
    return _activity_events(request, activities, team, custom_calendar=cc)


def _save_unchecked_calendar_types(user, company, checked_types):
    """
    Give each standard calendar type not in ``checked_types`` an unselected
    preference row if it has none. The sidebar shows a type without a row as
    checked, so otherwise unchecking it doesn't stick. Callers unselect the
    user's existing rows first.
    """
    saved_types = set(
        UserCalendarPreference.objects.filter(user=user, company=company).values_list(
            "calendar_type", flat=True
        )
    )
    for calendar_type, color in DEFAULT_CALENDAR_TYPE_COLORS.items():
        if calendar_type in checked_types or calendar_type in saved_types:
            continue
        # Not create(): a quick double click can post the same change twice.
        UserCalendarPreference.objects.get_or_create(
            user=user,
            calendar_type=calendar_type,
            company=company,
            defaults={"color": color, "is_selected": False},
        )
