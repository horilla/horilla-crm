"""
Per-type tab list views for activities tied to a parent object
(Task, Meeting, Call, Email, Event).
"""

# Standard library imports
from urllib.parse import urlencode

from horilla.auth.mixins import LoginRequiredMixin, login_redirect
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.history import is_record_locked
from horilla.contrib.generics.views import HorillaListView
from horilla.contrib.generics.views.details import (
    check_record_access,
    check_record_change_access,
    check_record_delete_access,
)
from horilla.contrib.mail.models import HorillaMail
from horilla.shortcuts import render

# First-party imports (Horilla)
from horilla.urls import reverse_lazy
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.functional import cached_property  # type: ignore

# Local imports (Horilla)
from ...models import Activity
from .mixins import (
    ActivityTabListMixin,
    add_source_column_if_needed,
    guard_foreign_rows,
    scope_to_parent_history,
)

_EDIT_ACTION = {
    "action": "Edit",
    "src": "assets/icons/edit.svg",
    "img_class": "w-4 h-4",
    "permission": "activity.change_activity",
    "own_permission": "activity.change_own_activity",
    "owner_field": ["owner", "assigned_to"],
    "attrs": """
                hx-get="{get_edit_url}?new=true"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal()"
                """,
}

_DELETE_ACTION = {
    "action": "Delete",
    "src": "assets/icons/a4.svg",
    "img_class": "w-4 h-4",
    "permission": "activity.delete_activity",
    "attrs": """
                hx-post="{get_delete_url}"
                hx-target="#deleteModeBox"
                hx-swap="innerHTML"
                hx-trigger="click"
                hx-vals='{{"check_dependencies": "true"}}'
                onclick="openDeleteModeModal()"
            """,
}

_TAB_ACTIONS = [_EDIT_ACTION, _DELETE_ACTION]
_CALL_TAB_ACTIONS = [_EDIT_ACTION, _DELETE_ACTION]


@method_decorator(htmx_required, name="dispatch")
class TaskListView(ActivityTabListMixin, LoginRequiredMixin, HorillaListView):
    """Task List view."""

    model = Activity
    bulk_select_option = False
    paginate_by = 5
    table_auto = True
    list_column_visibility = False
    _col_attrs_first_field = "title"
    actions = _TAB_ACTIONS
    no_record_fit_height = False

    columns = [
        "title",
        "due_datetime",
        "task_priority",
        ("status", "status_col"),
    ]
    # Activity is shared across Task/Meeting/Call/Event tabs; keep the other
    # types' exclusive fields out of this tab's "Available Fields" picker.
    exclude_columns = [
        "start_datetime",
        "end_datetime",
        "location",
        "is_online",
        "meeting_provider",
        "meeting_url",
        "is_all_day",
        "meeting_host",
        "mail_template",
        "google_event_id",
        "call_duration_display",
        "call_duration_seconds",
        "call_type",
        "call_purpose",
        "recipient_email",
        "external_participants",
    ]

    def get_search_url(self):
        """Return the search URL for the task list scoped to this object."""
        return reverse_lazy(
            "activity:task_list", kwargs={"object_id": self.kwargs["object_id"]}
        )

    @property
    def search_url(self):
        """Return the search URL property."""
        return self.get_search_url()

    def get_queryset(self):
        status_view_map = {
            "pending": "ActivityTaskListPending",
            "completed": "ActivityTaskListCompleted",
        }
        queryset = super().get_queryset()
        object_id = self.kwargs.get("object_id")
        view_type = self.request.GET.get("view_type", "pending")
        content_type_id = self.request.GET.get("content_type_id")

        if object_id and content_type_id:
            try:
                HorillaContentType.objects.get(id=content_type_id)
                queryset = scope_to_parent_history(self, queryset).filter(
                    activity_type="task"
                )
            except HorillaContentType.DoesNotExist:
                queryset = queryset.none()
        else:
            queryset = queryset.none()

        if view_type == "completed":
            queryset = queryset.filter(status="completed")
            self.view_id = status_view_map["completed"]
        elif view_type == "pending":
            queryset = queryset.exclude(status="completed")
            self.view_id = status_view_map["pending"]

        return add_source_column_if_needed(self, queryset)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object_id"] = self.kwargs.get("object_id")
        context["view_type"] = self.request.GET.get("view_type", "pending")
        return context


@method_decorator(htmx_required, name="dispatch")
class MeetingListView(ActivityTabListMixin, HorillaListView):
    """Meeting list view."""

    model = Activity
    paginate_by = 10
    bulk_select_option = False
    table_auto = True
    list_column_visibility = False
    _col_attrs_first_field = "title"
    actions = _TAB_ACTIONS
    no_record_fit_height = False

    columns = [
        "title",
        ("start_datetime", "get_start_date"),
        ("end_datetime", "get_end_date"),
        ("meeting_url", "meeting_link_col"),
        ("status", "status_col"),
    ]
    # Activity is shared across Task/Meeting/Call/Event tabs; keep the other
    # types' exclusive fields out of this tab's "Available Fields" picker.
    exclude_columns = [
        "task_priority",
        "due_datetime",
        "call_duration_display",
        "call_duration_seconds",
        "call_type",
        "call_purpose",
        "recipient_email",
        "external_participants",
    ]

    def get_search_url(self):
        """Return the search URL for the meeting list scoped to this object."""
        return reverse_lazy(
            "activity:meeting_list", kwargs={"object_id": self.kwargs["object_id"]}
        )

    @property
    def search_url(self):
        """Return the search URL property."""
        return self.get_search_url()

    def get_queryset(self):
        status_view_map = {
            "pending": "ActivityMeetingListPending",
            "completed": "ActivityMeetingListCompleted",
        }
        queryset = super().get_queryset()
        object_id = self.kwargs.get("object_id")
        view_type = self.request.GET.get("view_type", "pending")
        content_type_id = self.request.GET.get("content_type_id")

        if object_id and content_type_id:
            try:
                HorillaContentType.objects.get(id=content_type_id)
                queryset = scope_to_parent_history(self, queryset).filter(
                    activity_type="meeting"
                )
            except HorillaContentType.DoesNotExist:
                queryset = queryset.none()
        else:
            queryset = queryset.none()

        if view_type == "completed":
            queryset = queryset.filter(status="completed")
            self.view_id = status_view_map["completed"]
        elif view_type == "pending":
            queryset = queryset.exclude(status="completed")
            self.view_id = status_view_map["pending"]

        return add_source_column_if_needed(self, queryset)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object_id"] = self.kwargs.get("object_id")
        context["view_type"] = self.request.GET.get("view_type", "pending")
        return context


@method_decorator(htmx_required, name="dispatch")
class CallListView(ActivityTabListMixin, HorillaListView):
    """List view for call activities."""

    model = Activity
    paginate_by = 10
    bulk_select_option = False
    table_auto = True
    list_column_visibility = False
    _col_attrs_first_field = "call_purpose"
    actions = _CALL_TAB_ACTIONS
    no_record_fit_height = False

    columns = [
        "call_purpose",
        "call_type",
        "call_duration_display",
        ("status", "status_col"),
    ]
    # Activity is shared across Task/Meeting/Call/Event tabs; keep the other
    # types' exclusive fields out of this tab's "Available Fields" picker.
    exclude_columns = [
        "task_priority",
        "due_datetime",
        "start_datetime",
        "end_datetime",
        "location",
        "is_online",
        "meeting_provider",
        "meeting_url",
        "is_all_day",
        "meeting_host",
        "mail_template",
        "google_event_id",
    ]

    def get_search_url(self):
        """Return the search URL for the call list scoped to this object."""
        return reverse_lazy(
            "activity:call_list", kwargs={"object_id": self.kwargs["object_id"]}
        )

    @property
    def search_url(self):
        """Return the search URL property."""
        return self.get_search_url()

    def get_queryset(self):
        status_view_map = {
            "pending": "ActivityCallListPending",
            "completed": "ActivityCallListCompleted",
        }
        queryset = super().get_queryset()
        object_id = self.kwargs.get("object_id")
        view_type = self.request.GET.get("view_type", "pending")
        content_type_id = self.request.GET.get("content_type_id")

        if object_id and content_type_id:
            try:
                HorillaContentType.objects.get(id=content_type_id)
                queryset = (
                    scope_to_parent_history(self, queryset)
                    .filter(activity_type="log_call")
                    .exclude(call_purpose="telephony")
                )
            except HorillaContentType.DoesNotExist:
                queryset = queryset.none()
        else:
            queryset = queryset.none()

        if view_type == "completed":
            queryset = queryset.filter(status="completed")
            self.view_id = status_view_map["completed"]
        elif view_type == "pending":
            queryset = queryset.exclude(status="completed")
            self.view_id = status_view_map["pending"]

        return add_source_column_if_needed(self, queryset)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object_id"] = self.kwargs.get("object_id")
        context["view_type"] = self.request.GET.get("view_type", "pending")
        return context


@method_decorator(htmx_required, name="dispatch")
class EmailListView(HorillaListView):
    """List view for email activities."""

    model = HorillaMail
    bulk_select_option = False
    paginate_by = 10
    table_auto = True
    list_column_visibility = False
    no_record_fit_height = False
    # HorillaMail has no OWNER_FIELDS, so the base owner_filtration would return
    # queryset.none() for view_own users. Ownership is handled manually below.
    owner_filtration = False

    columns = [
        ("subject", "render_subject"),
        "to",
        "sent_at",
        "get_mail_status_display",
    ]

    def get_search_url(self):
        """Return the search URL for the email list scoped to this object."""
        return reverse_lazy(
            "activity:email_list", kwargs={"object_id": self.kwargs["object_id"]}
        )

    @property
    def search_url(self):
        """Return the search URL property."""
        return self.get_search_url()

    @property
    def main_session_id(self):
        """
        Swap target for column-sort clicks — this list renders inside a detail-view
        tab, not the top-level page, so sort must target its own root (view_id)
        rather than the page-wide "#mainSession", which doesn't exist in its response.
        """
        return self.view_id

    @property
    def main_url(self):
        """
        URL the sort-click reloads, carrying the params get_queryset() needs.

        The sort click only appends the top-level page's own query string, not
        this fragment's — so content_type_id and view_type (required to scope
        the queryset to this object/tab) must be baked into the URL itself or
        the resulting request queryset.none()s.
        """
        base_url = str(self.get_search_url())
        content_type_id = self.request.GET.get("content_type_id")
        view_type = self.request.GET.get("view_type")
        params = {}
        if content_type_id:
            params["content_type_id"] = content_type_id
        if view_type:
            params["view_type"] = view_type
        if not params:
            return base_url
        return f"{base_url}?{urlencode(params)}"

    action_col = {
        "draft": [
            {
                "action": "Send Email",
                "src": "assets/icons/email_black.svg",
                "img_class": "w-4 h-4",
                "attrs": """
                            hx-get="{get_edit_url}"
                            hx-target="#horillaModalBox"
                            hx-swap="innerHTML"
                            onclick="openhorillaModal()"
                            """,
            },
            {
                "action": "Delete",
                "src": "assets/icons/a4.svg",
                "img_class": "w-4 h-4",
                "attrs": """
                        hx-post="{get_delete_url}?view=draft"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        hx-trigger="click"
                        hx-vals='{{"check_dependencies": "false"}}'
                        onclick="openModal()"
                    """,
            },
        ],
        "scheduled": [
            {
                "action": "Cancel",
                "src": "assets/icons/cancel.svg",
                "img_class": "w-4 h-4",
                "attrs": """
                        hx-get="{get_edit_url}?cancel=true"
                        hx-target="#horillaModalBox"
                        hx-swap="innerHTML"
                        hx-trigger="click"
                        onclick="openhorillaModal()"
                    """,
            },
            {
                "action": "Snooze",
                "src": "assets/icons/clock.svg",
                "img_class": "w-4 h-4",
                "attrs": """
                        hx-get="{get_reschedule_url}"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        hx-trigger="click"
                        onclick="openModal()"
                    """,
            },
            {
                "action": "Delete",
                "src": "assets/icons/a4.svg",
                "img_class": "w-4 h-4",
                "attrs": """
                        hx-post="{get_delete_url}?view=scheduled"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        hx-trigger="click"
                        hx-vals='{{"check_dependencies": "false"}}'
                        onclick="openModal()"
                    """,
            },
        ],
        "sent": [
            {
                "action": "View Email",
                "src": "assets/icons/eye1.svg",
                "img_class": "w-4 h-4",
                "attrs": """
                            hx-get="{get_view_url}"
                            hx-target="#contentModalBox"
                            hx-swap="innerHTML"
                            onclick="openContentModal()"
                            """,
            },
            {
                "action": "Delete",
                "src": "assets/icons/a4.svg",
                "img_class": "w-4 h-4",
                "attrs": """
                hx-post="{get_delete_url}?view=sent"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                hx-trigger="click"
                hx-vals='{{"check_dependencies": "false"}}'
                onclick="openModal()"
            """,
            },
        ],
    }

    # Delivered / bounced / opened / failed share the same actions as "sent"
    action_col["delivered"] = action_col["sent"]
    action_col["bounced"] = action_col["sent"]
    action_col["opened"] = action_col["sent"]
    action_col["failed"] = action_col["sent"]

    def dispatch(self, request, *args, **kwargs):
        """Require mail permission or access to the parent record before listing emails."""
        user = request.user
        if not user.is_authenticated:
            return login_redirect(request)
        mail_perms = [
            "mail.view_horillamail",
            "mail.view_own_horillamail",
            "mail.add_horillamail",
            "mail.add_own_horillamail",
        ]
        if any(user.has_perm(p) for p in mail_perms):
            return super().dispatch(request, *args, **kwargs)
        # Allow access if user can access the parent record
        object_id = kwargs.get("object_id")
        content_type_id = request.GET.get("content_type_id")
        if object_id and content_type_id:
            try:
                ct = HorillaContentType.objects.get(id=content_type_id)
                from horilla.apps import apps as horilla_apps

                model_class = horilla_apps.get_model(ct.app_label, ct.model)
                obj = model_class.objects.get(pk=object_id)
                if check_record_access(user, obj):
                    return super().dispatch(request, *args, **kwargs)
            except Exception:
                pass
        return render(request, "403.html", status=403)

    def _get_parent_object(self):
        """Resolve the parent object from URL kwargs + query params."""
        object_id = self.kwargs.get("object_id")
        content_type_id = self.request.GET.get("content_type_id")
        if not object_id or not content_type_id:
            return None
        try:
            ct = HorillaContentType.objects.get(id=content_type_id)
            model_class = ct.model_class()
            return model_class.objects.get(pk=object_id)
        except Exception:
            return None

    @cached_property
    def actions(self):
        """Return actions for the current email view_type, filtered by parent record permissions."""
        view_type = self.request.GET.get("view_type")
        base_actions = list(self.action_col.get(view_type) or [])

        parent_obj = self._get_parent_object()
        if not parent_obj:
            return base_actions

        user = self.request.user
        app = parent_obj._meta.app_label
        model = parent_obj._meta.model_name
        locked = is_record_locked(parent_obj)
        has_global_change = not locked and (
            user.is_superuser or user.has_perm(f"{app}.change_{model}")
        )
        has_global_delete = not locked and (
            user.is_superuser or user.has_perm(f"{app}.delete_{model}")
        )
        can_change = has_global_change or check_record_change_access(user, parent_obj)
        can_delete = has_global_delete or check_record_delete_access(user, parent_obj)

        _CHANGE_KEYWORDS = {"send", "cancel", "snooze", "edit", "change"}
        _DELETE_KEYWORDS = {"delete", "remove"}

        filtered = []
        for action in base_actions:
            label = str(action.get("action", "")).lower()
            if any(k in label for k in _DELETE_KEYWORDS):
                if can_delete or locked:
                    filtered.append(guard_foreign_rows(action, parent_obj))
            elif any(k in label for k in _CHANGE_KEYWORDS):
                if can_change or locked:
                    filtered.append(guard_foreign_rows(action, parent_obj))
            else:
                filtered.append(action)
        return filtered

    def get_queryset(self):
        status_view_map = {
            "sent": "activity-email-list-sent",
            "draft": "activity-email-list-draft",
            "scheduled": "activity-email-list-scheduled",
        }
        sent_statuses = ["sent", "delivered", "bounced", "opened", "failed"]

        queryset = super().get_queryset()
        object_id = self.kwargs.get("object_id")
        view_type = self.request.GET.get("view_type", "sent")
        content_type_id = self.request.GET.get("content_type_id")

        if object_id and content_type_id:
            try:
                HorillaContentType.objects.get(id=content_type_id)
                queryset = scope_to_parent_history(self, queryset)
            except HorillaContentType.DoesNotExist:
                queryset = queryset.none()
        else:
            queryset = queryset.none()

        if view_type in status_view_map:
            if view_type == "sent":
                queryset = queryset.filter(mail_status__in=sent_statuses)
            else:
                queryset = queryset.filter(mail_status=view_type)
            self.view_id = status_view_map[view_type]

        user = self.request.user
        if not user.has_perm("mail.view_horillamail") and not user.has_perm(
            "mail.add_horillamail"
        ):
            queryset = queryset.filter(created_by=user)

        return add_source_column_if_needed(self, queryset)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object_id"] = self.kwargs.get("object_id")
        context["view_type"] = self.request.GET.get("view_type", "sent")
        return context


@method_decorator(htmx_required, name="dispatch")
class EventListView(ActivityTabListMixin, HorillaListView):
    """List view for event activities."""

    model = Activity
    bulk_select_option = False
    paginate_by = 10
    table_auto = True
    list_column_visibility = False
    _col_attrs_first_field = "title"
    actions = _TAB_ACTIONS
    no_record_fit_height = False

    columns = [
        "title",
        ("start_datetime", "get_start_date"),
        ("end_datetime", "get_end_date"),
        "location",
        ("status", "status_col"),
    ]
    # Activity is shared across Task/Meeting/Call/Event tabs; keep the other
    # types' exclusive fields out of this tab's "Available Fields" picker.
    exclude_columns = [
        "task_priority",
        "due_datetime",
        "call_duration_display",
        "call_duration_seconds",
        "call_type",
        "call_purpose",
        "recipient_email",
        "external_participants",
        "is_online",
        "meeting_provider",
        "meeting_url",
        "meeting_host",
        "mail_template",
        "google_event_id",
    ]

    def get_search_url(self):
        """Return the search URL for the event list scoped to this object."""
        return reverse_lazy(
            "activity:event_list", kwargs={"object_id": self.kwargs["object_id"]}
        )

    @property
    def search_url(self):
        """Return the search URL property."""
        return self.get_search_url()

    def get_queryset(self):
        status_view_map = {
            "pending": "ActivityEventListPending",
            "completed": "ActivityEventListCompleted",
        }
        queryset = super().get_queryset()
        object_id = self.kwargs.get("object_id")
        view_type = self.request.GET.get("view_type", "pending")
        content_type_id = self.request.GET.get("content_type_id")

        if object_id and content_type_id:
            try:
                HorillaContentType.objects.get(id=content_type_id)
                queryset = scope_to_parent_history(self, queryset).filter(
                    activity_type="event"
                )
            except HorillaContentType.DoesNotExist:
                queryset = queryset.none()
        else:
            queryset = queryset.none()

        if view_type == "completed":
            queryset = queryset.filter(status="completed")
            self.view_id = status_view_map["completed"]
        elif view_type == "pending":
            queryset = queryset.exclude(status="completed")
            self.view_id = status_view_map["pending"]

        return add_source_column_if_needed(self, queryset)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object_id"] = self.kwargs.get("object_id")
        context["view_type"] = self.request.GET.get("view_type", "pending")
        return context
