"""
Global (standalone) per-type list views — shown in the tabbed activity page.
"""

from django.contrib.auth.mixins import LoginRequiredMixin

from horilla.contrib.generics.views import HorillaListView
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _

from .mixins import GlobalTypeListMixin


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["activity.view_activity", "activity.view_own_activity"]
    ),
    name="dispatch",
)
class GlobalTaskListView(GlobalTypeListMixin, LoginRequiredMixin, HorillaListView):
    """Global Task list — all tasks across all related objects."""

    _activity_type = "task"
    view_id = "global-task-list"

    columns = [
        "subject",
        "due_datetime",
        "task_priority",
        ("related_object", "related_object_col"),
        ("status", "status_col"),
    ]

    def get_search_url(self):
        """Return the search URL for the global task list."""
        return reverse_lazy("activity:global_task_list")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["activity.view_activity", "activity.view_own_activity"]
    ),
    name="dispatch",
)
class GlobalMeetingListView(GlobalTypeListMixin, LoginRequiredMixin, HorillaListView):
    """Global Meeting list — all meetings across all related objects."""

    _activity_type = "meeting"
    view_id = "global-meeting-list"

    columns = [
        "subject",
        ("start_datetime", "get_start_date"),
        ("end_datetime", "get_end_date"),
        ("meeting_url", "meeting_link_col"),
        ("related_object", "related_object_col"),
        ("status", "status_col"),
    ]

    def get_search_url(self):
        """Return the search URL for the global meeting list."""
        return reverse_lazy("activity:global_meeting_list")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["activity.view_activity", "activity.view_own_activity"]
    ),
    name="dispatch",
)
class GlobalCallListView(GlobalTypeListMixin, LoginRequiredMixin, HorillaListView):
    """Global Call list — all calls across all related objects."""

    _activity_type = "log_call"
    view_id = "global-call-list"

    columns = [
        "subject",
        "call_purpose",
        "call_type",
        "call_duration_display",
        ("related_object", "related_object_col"),
        ("status", "status_col"),
    ]

    def get_search_url(self):
        """Return the search URL for the global call list."""
        return reverse_lazy("activity:global_call_list")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["activity.view_activity", "activity.view_own_activity"]
    ),
    name="dispatch",
)
class GlobalEventListView(GlobalTypeListMixin, LoginRequiredMixin, HorillaListView):
    """Global Event list — all events across all related objects."""

    _activity_type = "event"
    view_id = "global-event-list"

    columns = [
        "subject",
        ("start_datetime", "get_start_date"),
        ("end_datetime", "get_end_date"),
        "location",
        ("related_object", "related_object_col"),
        ("status", "status_col"),
    ]

    def get_search_url(self):
        """Return the search URL for the global event list."""
        return reverse_lazy("activity:global_event_list")
