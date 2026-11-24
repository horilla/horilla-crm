"""Home dashboard components for the activity module."""

# Standard library imports
from datetime import timedelta

# First party imports (Horilla)
from django.utils.http import urlencode

from horilla.contrib.dashboard.utils import (
    DefaultDashboardGenerator,
    build_grouped_chart,
    filtered_list_url,
)
from horilla.contrib.utils.methods import get_section_info_for_model
from horilla.db.models import Count
from horilla.utils import timezone
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import Activity

# Activity type -> the tab that lists it on the Activities page.
TYPE_TABS = {
    "task": "tasks",
    "meeting": "meetings",
    "log_call": "calls",
    "event": "events",
}
OPEN_STATUSES = ["not_started", "scheduled", "in_progress", "waiting", "deferred"]


def _open_tasks(qs):
    return qs.filter(activity_type="task", status__in=OPEN_STATUSES)


def _upcoming_meetings(qs, days=None):
    """Meetings and events from the start of today, so today's already count."""
    today = timezone.localdate()
    qs = qs.filter(
        activity_type__in=["meeting", "event"],
        start_datetime__date__gte=today,
    ).exclude(status="cancelled")
    if days is not None:
        qs = qs.filter(start_datetime__date__lte=today + timedelta(days=days))
    return qs


def activity_kpi_cards(generator, model_info):
    """What needs doing: overdue tasks and upcoming meetings."""
    qs = generator.get_queryset(model_info["model"])
    now = timezone.now()
    open_tasks = _open_tasks(qs)
    return [
        {
            "title": _("Overdue Tasks"),
            "value": open_tasks.filter(due_datetime__lt=now).count(),
            "icon": "fa-triangle-exclamation",
            "color": "red",
            "url": filtered_list_url(
                model_info["model"],
                [
                    ("activity_type", "exact", "task"),
                    ("status", "exact", ",".join(OPEN_STATUSES)),
                    ("due_datetime", "lt", timezone.localdate().isoformat()),
                ],
                extra_params={"tab": "tasks"},
            ),
        },
        {
            "title": _("Meetings Today"),
            "value": _upcoming_meetings(qs, days=0)
            .filter(activity_type="meeting")
            .count(),
            "icon": "fa-calendar-days",
            "color": "teal",
            "url": filtered_list_url(
                model_info["model"],
                [
                    ("activity_type", "exact", "meeting"),
                    (
                        "start_datetime",
                        "between",
                        timezone.localdate().isoformat(),
                        timezone.localdate().isoformat(),
                    ),
                ],
                extra_params={"tab": "meetings"},
            ),
        },
    ]


def create_tasks_by_owner_chart(self, queryset, model_info):
    """Open tasks per person - shows who is overloaded."""
    rows = list(
        _open_tasks(queryset)
        .values("owner", "owner__first_name", "owner__last_name")
        .annotate(total=Count("id"))
        .order_by("-total")[:8]
    )
    if not rows:
        return None
    section = get_section_info_for_model(queryset.model)
    return {
        "title": _("Open Tasks by Owner"),
        "type": "bar",
        "data": {
            "labels": [
                f"{row['owner__first_name']} {row['owner__last_name']}".strip()
                or _("Unassigned")
                for row in rows
            ],
            "data": [row["total"] for row in rows],
            "urls": [
                f"{section['url']}?"
                + urlencode(
                    {
                        "section": section["section"],
                        "apply_filter": "true",
                        "field": "owner",
                        "operator": "exact",
                        "value": row["owner"] or "",
                        "tab": "tasks",
                    }
                )
                for row in rows
            ],
            "labelField": _("Owner"),
        },
    }


def create_task_priority_chart(self, queryset, model_info):
    """Open tasks split by priority."""
    return build_grouped_chart(
        _open_tasks(queryset).exclude(task_priority__isnull=True),
        "task_priority",
        _("Open Tasks by Priority"),
        "column",
        _("Priority"),
        extra_params=lambda value: {"tab": "tasks"},
    )


def upcoming_meetings_table_func(generator, model_info):
    """Today's meetings and events, earliest first."""
    today = timezone.localdate()
    return generator.build_table_context(
        model_info=model_info,
        title=_("Today's Meetings & Events"),
        description=_("Everything scheduled for today, earliest first"),
        filter_kwargs={
            "activity_type__in": ["meeting", "event"],
            "start_datetime__date": today,
        },
        no_found_img="assets/img/not-found-list.svg",
        no_record_msg=_("No meetings or events today."),
        view_id="activity_dashboard_meetings",
        order_by=["start_datetime"],
        table_fields=[
            {"name": "subject", "verbose_name": _("Subject")},
            {"name": "activity_type", "verbose_name": _("Type")},
            {"name": "start_datetime", "verbose_name": _("Starts At")},
            {"name": "owner", "verbose_name": _("Owner")},
        ],
    )


def open_tasks_table_func(generator, model_info):
    """Open tasks due within the next 7 days (or overdue), earliest first."""
    return generator.build_table_context(
        model_info=model_info,
        title=_("Tasks Due This Week"),
        description=_("Overdue tasks and tasks due in the next 7 days"),
        filter_kwargs={
            "activity_type": "task",
            "status__in": OPEN_STATUSES,
            "due_datetime__lte": timezone.now() + timedelta(days=7),
        },
        no_found_img="assets/img/not-found-list.svg",
        no_record_msg=_("No tasks due this week. You're all caught up!"),
        view_id="activity_dashboard_tasks",
        order_by=["due_datetime"],
        table_fields=[
            {"name": "subject", "verbose_name": _("Task")},
            {"name": "task_priority", "verbose_name": _("Priority")},
            {"name": "due_datetime", "verbose_name": _("Due")},
            {"name": "status", "verbose_name": _("Status")},
        ],
    )


DefaultDashboardGenerator.extra_models.append(
    {
        "model": Activity,
        "name": _("Activities"),
        "icon": "fa-calendar-check",
        "color": "blue",
        "kpi_func": activity_kpi_cards,
        "chart_func": [create_tasks_by_owner_chart, create_task_priority_chart],
        "chart_titles": [_("Open Tasks by Owner"), _("Open Tasks by Priority")],
        "chart_descriptions": [
            _("Who has the most open tasks"),
            _("Open tasks grouped by urgency"),
        ],
        "table_func": open_tasks_table_func,
        "order": 2,
    }
)

# Registered separately so its table sorts after the leads, campaigns and
# accounts cards on the home page (cards are ordered by their ``order``).
DefaultDashboardGenerator.extra_models.append(
    {
        "model": Activity,
        "name": _("Activities"),
        "icon": "fa-calendar-check",
        "color": "blue",
        "table_func": upcoming_meetings_table_func,
        "order": 6,
    }
)
