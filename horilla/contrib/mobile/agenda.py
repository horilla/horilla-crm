"""
Agenda: the signed-in user's tasks, meetings and events day by day, with a
week strip, the user's unavailability, and adding a meeting, an event or a
task on the picked day.

"Mine" shows the user's own activities, as on My work. "Team", for users
with a team, adds what the desktop calendar's Team view adds (the All
Activities list rule), optionally narrowed to some members; the choice is
kept in the session. With the calendar app installed, the types shown follow
the desktop calendar's type filter (``UserCalendarPreference``), and the
filter saved here is that one.
"""

# Standard library imports
import json
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode

# Third-party imports (Django)
from django.utils import formats
from django.utils.dates import WEEKDAYS

# First party imports (Horilla)
from horilla.apps import apps
from horilla.auth.models import User
from horilla.contrib.activity.models import Activity
from horilla.contrib.core.utils import get_allowed_user_ids
from horilla.contrib.generics.views.helpers.queryset_utils import (
    get_granted_access_filter,
)
from horilla.contrib.utils.middlewares import get_active_company
from horilla.db.models import Q
from horilla.urls import NoReverseMatch, reverse
from horilla.utils.translation import gettext_lazy as _
from horilla.utils.translation import pgettext_lazy
from horilla.views.generic import TemplateView

# Local imports
from .access import can_add_activity, can_edit_activity, scope_queryset
from .activities import get_type_colors
from .dates import day_number, day_start, long_date, parse_day, user_now
from .navigation import agenda_url
from .today import TODAY_TYPES, ActivityRows, is_all_day, my_activities, with_when
from .utils import user_display_name
from .views import MobilePageMixin

CALENDAR_APP = "horilla.contrib.calendar"
WEEK_LENGTH = 7
# Activity types the Agenda lists, in the order of a day's dots and its
# filter; "unavailability" is the user's blocked time from the calendar app.
AGENDA_TYPES = ("meeting", "event", "task")
FILTER_TYPES = (*AGENDA_TYPES, "unavailability")
FILTER_LABELS = {
    "meeting": _("Meetings"),
    "event": _("Events"),
    "task": _("Tasks"),
    # Its own context: the shared catalog's reads as "no access".
    "unavailability": pgettext_lazy("mobile agenda filter", "Unavailability"),
}
UNAVAILABILITY_COLOR = "#94A3B8"

# Mine or Team, and the members Team is narrowed to, kept between visits.
SCOPE_SESSION_KEY = "mobile_agenda_scope"
MEMBERS_SESSION_KEY = "mobile_agenda_members"

# What "Add" offers, with an icon and a hint.
ADD_CHOICES = (
    (
        "meeting",
        _("New meeting"),
        "fa-solid fa-user-group",
        _("With colleagues or guests, in person or online"),
    ),
    ("event", _("New event"), "fa-regular fa-calendar", _("A date to keep in mind")),
    (
        "task",
        _("New task"),
        "fa-solid fa-list-check",
        _("Something to do next, with a due date"),
    ),
)


@dataclass
class UnavailableRow:
    """A stretch of the user's own unavailability on the day."""

    when: str
    reason: str


def calendar_installed():
    """True when the desktop calendar app is installed."""
    return apps.is_installed(CALENDAR_APP)


def shown_types(user):
    """
    Types the user's calendar filter shows: all of them, except those with
    an unselected preference row (the desktop calendar's rule).
    """
    if not calendar_installed():
        return set(AGENDA_TYPES)
    preference = apps.get_model("calendar", "UserCalendarPreference")
    unchecked = set(
        preference.objects.filter(user=user, is_selected=False).values_list(
            "calendar_type", flat=True
        )
    )
    return {
        calendar_type
        for calendar_type in FILTER_TYPES
        if calendar_type not in unchecked
    }


def selected_custom_calendars(user):
    """
    The user's selected custom calendars, as the desktop filter names them.
    The phone doesn't show them, but saving the filter keeps them selected.
    """
    if not calendar_installed():
        return []
    custom = apps.get_model("calendar", "CustomCalendar")
    return [
        f"custom_{pk}"
        for pk in custom.objects.filter(user=user, is_selected=True).values_list(
            "pk", flat=True
        )
    ]


def team_available(user):
    """
    True when the Team view would show ``user`` more than their own
    activities: the desktop calendar's rule, after the All Activities list.
    ``view_activity`` covers the company; ``view_own_activity`` adds
    something only with subordinates (or a granted-access filter).
    """
    if user.has_perm("activity.view_activity"):
        return True
    if not user.has_perm("activity.view_own_activity"):
        return False
    return (
        len(get_allowed_user_ids(user)) > 1
        or get_granted_access_filter(Activity, user, "view") is not None
    )


def team_members(request):
    """
    The users the Team view can be narrowed to, as the desktop offers them:
    the active company's users with ``view_activity``, else the user and the
    users in subordinate roles. Nobody without a team.
    """
    user = request.user
    if not team_available(user):
        return User.objects.none()
    if user.has_perm("activity.view_activity"):
        company = get_active_company(request)
        members = User.objects.filter(company=company)
    else:
        members = User.objects.filter(pk__in=get_allowed_user_ids(user))
    return members.filter(is_active=True).order_by("first_name", "last_name", "pk")


def agenda_scope(request):
    """
    ``(team, member_ids)`` the Agenda shows. ``?scope=mine|team`` and
    ``?members_set=1&members=...`` change the choice, which the session keeps;
    Team only for users with a team, and only members it offers.
    """
    session = request.session
    scope = request.GET.get("scope")
    if scope in ("mine", "team"):
        session[SCOPE_SESSION_KEY] = scope
    if request.GET.get("members_set"):
        session[MEMBERS_SESSION_KEY] = [
            int(value) for value in request.GET.getlist("members") if value.isdigit()
        ]
    team = session.get(SCOPE_SESSION_KEY) == "team" and team_available(request.user)
    member_ids = None
    if team and session.get(MEMBERS_SESSION_KEY):
        allowed = team_members(request).filter(pk__in=session[MEMBERS_SESSION_KEY])
        member_ids = set(allowed.values_list("pk", flat=True)) or None
    return team, member_ids


def agenda_activities(user, team=False, member_ids=None):
    """
    The activities the Agenda may list, with ``_when``. Mine: the user's own.
    Team: those too, and the ones the All Activities list shows the user
    (``scope_queryset``); ``member_ids`` narrows Team to the activities those
    users own, are assigned to, take part in or host.
    """
    if not team:
        return my_activities(user)
    base = Activity.objects.filter(activity_type__in=TODAY_TYPES)
    visible = base.filter(
        Q(pk__in=my_activities(user).values("pk"))
        | Q(pk__in=scope_queryset(user, base).values("pk"))
    )
    if member_ids:
        by_member = Q()
        for field_name in Activity.OWNER_FIELDS:
            by_member |= Q(**{f"{field_name}__in": member_ids})
        visible = visible.filter(pk__in=base.filter(by_member).values("pk"))
    return with_when(visible)


def week_start(day):
    """First day of ``day``'s week in the active language (Saturday in Persian)."""
    first = formats.get_format("FIRST_DAY_OF_WEEK")  # 0 is Sunday
    python_first = (first - 1) % 7  # Python's weekday(): 0 is Monday
    return day - timedelta(days=(day.weekday() - python_first) % 7)


def activities_between(user, start, end, types, team=False, member_ids=None):
    """
    The activities of ``types`` on [start, end) (see ``agenda_activities``),
    cancelled ones aside: tasks by due date, meetings and events by the time
    they span.
    """
    spans = Q(
        activity_type__in=("meeting", "event"),
        start_datetime__lt=end,
    ) & (
        Q(end_datetime__gte=start)
        | Q(end_datetime__isnull=True, start_datetime__gte=start)
    )
    due = Q(activity_type="task", due_datetime__gte=start, due_datetime__lt=end)
    return (
        agenda_activities(user, team, member_ids)
        .filter(activity_type__in=types)
        .exclude(status="cancelled")
        .filter(spans | due)
        .select_related("owner")
    )


def days_of(activity, tzinfo):
    """The days ``activity`` falls on, in ``tzinfo``."""
    first = activity._when.astimezone(tzinfo).date()
    end = activity.end_datetime if activity.activity_type != "task" else None
    if end is None or end <= activity._when:
        return [first]
    local_end = end.astimezone(tzinfo)
    last = local_end.date()
    # Ending at midnight, it doesn't reach into that day.
    if local_end == day_start(last, tzinfo) and last > first:
        last -= timedelta(days=1)
    return [first + timedelta(days=n) for n in range((last - first).days + 1)]


def unavailability_between(user, start, end):
    """The user's own unavailability overlapping [start, end)."""
    if not calendar_installed():
        return []
    availability = apps.get_model("calendar", "UserAvailability")
    return list(
        availability.objects.filter(
            user=user, from_datetime__lt=end, to_datetime__gt=start
        ).order_by("from_datetime", "pk")
    )


def build_agenda(request, day):
    """
    Context of the Agenda on ``day``: its week, its activities and the
    filter, Mine or Team as the user chose (``agenda_scope``).
    """
    user = request.user
    team, member_ids = agenda_scope(request)
    now = user_now(user)
    tzinfo = now.tzinfo
    today = now.date()
    first = week_start(day)
    days = [first + timedelta(days=n) for n in range(WEEK_LENGTH)]
    week_from = day_start(first, tzinfo)
    week_to = week_from + timedelta(days=WEEK_LENGTH)
    types = shown_types(user)
    colors = get_type_colors(user)

    by_day = {each: [] for each in days}
    for activity in activities_between(
        user,
        week_from,
        week_to,
        [t for t in AGENDA_TYPES if t in types],
        team,
        member_ids,
    ).order_by("_when", "pk"):
        for each in days_of(activity, tzinfo):
            if each in by_day:
                by_day[each].append(activity)

    week = []
    for each in days:
        present = {activity.activity_type for activity in by_day[each]}
        week.append(
            {
                "date": each,
                "initial": str(WEEKDAYS[each.weekday()])[:1],
                "name": long_date(user, each),
                "number": day_number(user, each),
                "is_today": each == today,
                "is_selected": each == day,
                "url": agenda_url(each),
                "colors": [
                    colors.get(kind, "") for kind in AGENDA_TYPES if kind in present
                ],
            }
        )

    # The selected day: all-day and running-over items first, then by time.
    rows = AgendaRows(
        user, now, urlencode({"from": "agenda", "date": day.isoformat()}), team
    )
    starts = day_start(day, tzinfo)
    ends = starts + timedelta(days=1)
    all_day_items = []
    timed_items = []
    for activity in by_day[day]:
        if is_all_day(activity):
            all_day_items.append({"kind": "activity", "row": rows.row(activity)})
        elif activity.activity_type != "task" and activity._when < starts:
            end = activity.end_datetime
            when = (
                _("Until %(time)s") % {"time": rows.time_text(end)}
                if end and end < ends
                else _("All day")
            )
            all_day_items.append(
                {"kind": "activity", "row": rows.row(activity, when=str(when))}
            )
        else:
            when = rows.time_text(activity._when)
            end = activity.end_datetime if activity.activity_type != "task" else None
            if end and activity._when < end <= ends:
                when = f"{when} – {rows.time_text(end)}"
            timed_items.append(
                (
                    activity._when,
                    {"kind": "activity", "row": rows.row(activity, when=when)},
                )
            )
    if "unavailability" in types:
        for blocked in unavailability_between(user, starts, ends):
            item = {"kind": "unavailable", "row": None}
            if blocked.from_datetime <= starts and blocked.to_datetime >= ends:
                item["row"] = UnavailableRow(str(_("All day")), blocked.reason)
                all_day_items.append(item)
                continue
            begin = max(blocked.from_datetime, starts)
            finish = min(blocked.to_datetime, ends)
            item["row"] = UnavailableRow(
                f"{rows.time_text(begin)} – {rows.time_text(finish)}", blocked.reason
            )
            timed_items.append((begin, item))
    timed_items.sort(key=lambda pair: pair[0])

    filter_url = ""
    if calendar_installed():
        try:
            filter_url = reverse("calendar:save_calendar_preferences")
        except NoReverseMatch:
            filter_url = ""

    members = []
    if team:
        chosen = member_ids or set()
        members = [
            {
                "id": member.pk,
                "name": user_display_name(member),
                "selected": member.pk in chosen,
            }
            for member in team_members(request)
        ]
    day_url = agenda_url(day)

    return {
        "state": {"view": "agenda", "date": day.isoformat()},
        "team_available": team_available(user),
        "team": team,
        "mine_url": f"{day_url}&scope=mine",
        "team_url": f"{day_url}&scope=team",
        "members": members,
        "members_url": f"{day_url}&members_set=1",
        "day": day,
        "day_label": long_date(user, day),
        # The top bar already shows today's date.
        "day_title": str(_("Today")) if day == today else long_date(user, day),
        "is_today": day == today,
        "today_url": agenda_url(today),
        "week": week,
        "prev_url": agenda_url(day - timedelta(days=WEEK_LENGTH)),
        "next_url": agenda_url(day + timedelta(days=WEEK_LENGTH)),
        "all_day_items": all_day_items,
        "timed_items": [item for _when, item in timed_items],
        "can_add": can_add_activity(user),
        "add_choices": [
            {
                "label": label,
                "icon": icon,
                "hint": hint,
                "url": (
                    reverse("mobile:agenda_activity", args=[kind])
                    + f"?date={day.isoformat()}"
                ),
            }
            for kind, label, icon, hint in ADD_CHOICES
        ],
        "type_filter": (
            [
                {
                    "type": calendar_type,
                    "label": FILTER_LABELS[calendar_type],
                    "color": colors.get(calendar_type, UNAVAILABILITY_COLOR),
                    "selected": calendar_type in types,
                }
                for calendar_type in FILTER_TYPES
            ]
            if filter_url
            else []
        ),
        "filter_active": len(types) < len(FILTER_TYPES) or bool(member_ids),
        "filter_url": filter_url,
        "filter_keep": (
            json.dumps(selected_custom_calendars(user)) if filter_url else "[]"
        ),
    }


class AgendaRows(ActivityRows):
    """
    Agenda rows. On the Team view a row also says whose activity it is, and
    its done circle is read-only when the user may not change the activity.
    """

    def __init__(self, user, now, detail_query="", team=False):
        super().__init__(user, now, detail_query)
        self.team = team

    def row(self, activity, with_date=False, when=None):
        """Row for ``activity``, with its person on the Team view."""
        row = super().row(activity, with_date, when)
        if self.team:
            owner = activity.owner
            if owner is not None:
                row.person = (
                    str(_("You"))
                    if owner.pk == self.user.pk
                    else user_display_name(owner)
                )
            row.can_change = can_edit_activity(self.user, activity)
        return row


class MobileAgendaView(MobilePageMixin, TemplateView):
    """The Agenda page; ``?date=`` picks the day (today by default)."""

    template_name = "mobile/agenda.html"

    def get_template_names(self):
        """Only the day's content for an HTMX request (day or week change)."""
        if self.request.headers.get("HX-Request") == "true":
            return ["mobile/partials/agenda_content.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        """The picked day and its week."""
        context = super().get_context_data(**kwargs)
        request = self.request
        context.update(
            build_agenda(request, parse_day(request.user, request.GET.get("date")))
        )
        return context
