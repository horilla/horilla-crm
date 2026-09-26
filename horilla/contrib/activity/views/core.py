"""
Views for the Activity module in the Horilla platform.
"""

# Standard library imports
from urllib.parse import urlencode

# Third-party imports (Django)
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin

from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.mixins import RecentlyViewedMixin
from horilla.contrib.generics.views import (
    HorillaDetailSectionView,
    HorillaDetailTabView,
    HorillaDetailView,
    HorillaHistorySectionView,
    HorillaKanbanView,
    HorillaNavView,
    HorillaNotesAttachementSectionView,
    HorillaSingleDeleteView,
    HorillaTabView,
    HorillaView,
)
from horilla.contrib.generics.views.details import (
    check_record_access,
    check_record_change_access,
)
from horilla.shortcuts import render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.functional import cached_property  # type: ignore
from horilla.utils.translation import gettext_lazy as _

# First-party imports (Horilla)
from horilla.views.generic import DetailView, View
from horilla.web import HttpResponse, RefreshResponse, ScriptResponse

from ..filters import ActivityFilter
from ..methods import get_related_record_context
from ..models import Activity
from .list_view import AllActivityListView

# One source of truth — mark each field with where it should appear
ACTIVITY_TYPE_SPECIFIC_FIELDS = {
    "meeting": [
        ("title", "both"),
        ("start_datetime", "both"),
        ("end_datetime", "both"),
        ("is_all_day", "tab"),
        ("is_online", "tab"),
        ("location", "tab"),
        ("meeting_host", "tab"),
        ("participants", "tab"),
        ("meeting_provider", "tab"),
        ("meeting_url", "tab"),
        ("reminder", "tab"),
        ("external_participants", "tab"),
    ],
    "event": [
        ("title", "both"),
        ("start_datetime", "both"),
        ("end_datetime", "both"),
        ("location", "tab"),
        ("is_all_day", "tab"),
        ("participants", "tab"),
    ],
    "task": [
        ("owner", "both"),
        ("task_priority", "both"),
        ("due_datetime", "both"),
        ("assigned_to", "tab"),
    ],
    "log_call": [
        ("call_duration_display", "both"),
        ("call_duration_seconds", "both"),
        ("call_type", "tab"),
        ("call_purpose", "tab"),
        ("notes", "tab"),
    ],
}

COMMON_FIELDS = [
    "subject",
    "activity_type",
    "status",
    "description",
    "related_object",
]


def get_fields_for(activity_type, view="both"):
    """
    view="summary" → only fields marked "summary" or "both"
    view="tab"     → only fields marked "tab" or "both"
    """
    fields = ACTIVITY_TYPE_SPECIFIC_FIELDS.get(activity_type, [])
    return [field for field, scope in fields if scope in (view, "both")]


def get_activity_detail_view_fields(activity_type):
    """
    Return the activity detail view fields
    """
    return [
        "subject",
        "activity_type",
        "status",
        "assigned_to",
        *get_fields_for(activity_type, view="summary"),  # only "summary" + "both"
    ]


def get_activity_detail_tab_fields(activity_type):
    """
    Return the activity detail tab fields
    """
    return [
        "activity_type",
        "subject",
        "status",
        "description",
        "assigned_to",
        *get_fields_for(activity_type, view="tab"),  # "tab" + "both"
    ]


@method_decorator(htmx_required, name="dispatch")
class HorillaActivitySectionView(DetailView):
    """
    Generic Activity Tab View
    """

    template_name = "activity_tab.html"
    context_object_name = "obj"

    def dispatch(self, request, *args, **kwargs):
        """Dispatch the request; verify record access then handle errors with HX-Refresh."""
        try:
            self.object = self.get_object()
        except Exception as e:
            messages.error(self.request, e)
            return RefreshResponse(self.request)
        if not check_record_access(request.user, self.object):
            return render(request, "403.html", status=403)
        return super().dispatch(request, *args, **kwargs)

    def add_task_button(self):
        """Return button configuration for creating a new task."""
        return {
            "url": f"""{reverse_lazy("activity:task_create_form")}""",
            "attrs": 'id="task-create"',
        }

    def add_meetings_button(self):
        """Return button configuration for creating a new meeting."""
        return {
            "url": f"""{reverse_lazy("activity:meeting_create_form")}""",
            "attrs": 'id="meeting-create"',
        }

    def add_call_button(self):
        """Return button configuration for creating a new call log."""
        return {
            "url": f"""{reverse_lazy("activity:call_create_form")}""",
            "attrs": 'id="call-create"',
        }

    def add_email_button(self):
        """Return button configuration for sending an email."""
        return {
            "url": f"""{reverse_lazy("mail:send_mail_view")}""",
            "attrs": 'id="email-create"',
            "title": _("Send Email"),
        }

    def add_event_button(self):
        """Return button configuration for creating a new event."""
        return {
            "url": f"""{reverse_lazy("activity:event_create_form")}""",
            "attrs": 'id="event-create"',
        }

    def get_context_data(self, **kwargs):
        """Add activity tab context: object_id, content_type, and action buttons."""
        context = super().get_context_data(**kwargs)
        pk = self.kwargs.get("pk")
        context["object_id"] = pk
        context["model_name"] = self.model._meta.model_name
        context["app_label"] = self.model._meta.app_label
        content_type = HorillaContentType.objects.get_for_model(self.model)
        context["content_type_id"] = content_type.id
        context["add_task_button"] = self.add_task_button() or {}
        context["add_meetings_button"] = self.add_meetings_button() or {}
        context["add_call_button"] = self.add_call_button() or {}
        context["add_email_button"] = self.add_email_button() or {}
        context["add_event_button"] = self.add_event_button() or {}
        user = self.request.user

        can_view_record = check_record_access(user, self.object)
        can_change_record = check_record_change_access(user, self.object)

        can_send_mail = can_change_record
        context["can_send_mail"] = can_send_mail

        can_view_mail = can_view_record
        context["can_view_mail"] = can_view_mail

        # Add buttons are shown when the user can change the parent record
        context["can_add_as_owner"] = can_change_record
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["activity.view_activity", "activity.view_own_activity"]
    ),
    name="dispatch",
)
class AllActivityTabbedView(LoginRequiredMixin, HorillaTabView):
    """
    Tabbed list view that separates activities by type.
    Each tab shows its own HorillaListView with type-specific columns.
    """

    template_name = "activity_type_tab_view.html"
    view_id = "activity-type-tabs"

    tabs = [
        {
            "id": "tasks",
            "title": _("Tasks"),
            "url": reverse_lazy("activity:global_task_list"),
        },
        {
            "id": "meetings",
            "title": _("Meetings"),
            "url": reverse_lazy("activity:global_meeting_list"),
        },
        {
            "id": "calls",
            "title": _("Calls"),
            "url": reverse_lazy("activity:global_call_list"),
        },
        {
            "id": "events",
            "title": _("Events"),
            "url": reverse_lazy("activity:global_event_list"),
        },
    ]


@method_decorator(
    permission_required_or_denied(
        ["activity.view_activity", "activity.view_own_activity"]
    ),
    name="dispatch",
)
class ActivityView(LoginRequiredMixin, HorillaView):
    """
    Render the activity page.
    """

    nav_url = reverse_lazy("activity:activity_nav_view")
    list_url = reverse_lazy("activity:activity_tabbed_view")
    kanban_url = reverse_lazy("activity:activity_kanban_tabbed_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required(["activity.view_activity", "activity.view_own_activity"]),
    name="dispatch",
)
class ActivityNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navigation view for managing activity.
    """

    search_url = reverse_lazy("activity:activity_list_view")
    main_url = reverse_lazy("activity:activity_view")
    filterset_class = ActivityFilter
    kanban_url = reverse_lazy("activity:activity_kanban_tabbed_view")
    model_name = "Activity"
    model_app_label = "activity"
    enable_actions = True
    exclude_kanban_fields = "call_type,reminder,activity_type,meeting_host"

    @cached_property
    def new_button(self):
        """
        URL for creating a new Activity..
        """
        if self.request.user.has_perm(
            "activity.add_activity"
        ) or self.request.user.has_perm("activity.add_own_activity"):
            return {
                "url": f"""{reverse_lazy("activity:activity_create_form")}?new=true""",
            }
        return None


@method_decorator(
    permission_required_or_denied(
        ["activity.view_activity", "activity.view_own_activity"]
    ),
    name="dispatch",
)
class AcivityKanbanView(LoginRequiredMixin, HorillaKanbanView):
    """
    Activity Kanban view (all types — kept for backward compatibility).
    """

    model = Activity
    view_id = "activity-kanban"
    filterset_class = ActivityFilter
    search_url = reverse_lazy("activity:activity_list_view")
    main_url = reverse_lazy("activity:activity_view")
    group_by_field = "status"

    @cached_property
    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        if self.request.user.has_perm(
            "activity.add_activity"
        ) or self.request.user.has_perm("activity.add_own_activity"):
            return {
                "url": f"""{reverse_lazy("activity:activity_create_form")}?new=true""",
            }
        return None

    actions = AllActivityListView.actions

    columns = [
        "subject",
        "activity_type",
        "related_object",
    ]

    @cached_property
    def kanban_attrs(self):
        """
        Defines column attributes for rendering clickable Activity entries
        that load detailed views dynamically using HTMX.
        """

        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {
            "hx-get": f"{{get_detail_url}}?{query_string}",
            "hx-target": "#mainContent",
            "hx-swap": "outerHTML",
            "hx-push-url": "true",
            "hx-select": "#mainContent",
            "permission": "activity.change_activity",
            "own_permission": "activity.change_own_activity",
            "owner_field": ["owner"],
        }
        return attrs

    def update_kanban_item(self, request):
        """
        After drag-drop, save the status change then reload the active tab's
        kanban via reloadButton. We cannot re-render inline because the registry
        maps Activity → this view (all types), but the tabs each show only one type.
        """
        from horilla.apps import apps as horilla_apps
        from horilla.db.models import ForeignKey

        item_id = request.POST.get("item_id")
        new_column = request.POST.get("new_column")
        app_label = request.POST.get("app_label", "activity")
        model_name = request.POST.get("model_name", "activity")

        try:
            model = horilla_apps.get_model(
                app_label=app_label.split(".")[-1], model_name=model_name
            )
            item = model.all_objects.get(pk=item_id)

            if not self.can_user_modify_item(item):
                messages.error(
                    request, _("You do not have permission to modify this item.")
                )
                return ScriptResponse(reload=True)

            group_by = self.get_group_by_field()
            field = model._meta.get_field(group_by)

            if hasattr(field, "choices") and field.choices:
                valid_choices = dict(field.choices)
                reverse_choices = {v: k for k, v in valid_choices.items()}
                if new_column in reverse_choices:
                    setattr(item, group_by, reverse_choices[new_column])
                elif new_column in valid_choices:
                    setattr(item, group_by, new_column)
            elif isinstance(field, ForeignKey):
                if new_column.lower() == "none":
                    setattr(item, group_by, None)
                else:
                    related_obj = field.related_model.objects.filter(
                        pk=new_column
                    ).first()
                    if related_obj:
                        setattr(item, group_by, related_obj)

            item.save(update_fields=[group_by])

        except Exception as e:
            messages.error(request, str(e))

        return ScriptResponse(reload=True)


_KANBAN_TYPE_COLUMNS = {
    "task": [
        "subject",
        "related_object",
        "task_priority",
        "due_datetime",
        "assigned_to",
    ],
    "meeting": [
        "subject",
        "related_object",
        ("start_datetime", "get_start_date"),
        ("end_datetime", "get_end_date"),
        "get_meeting_url_display",
    ],
    "log_call": [
        "subject",
        "related_object",
        "call_purpose",
        "call_type",
        "call_duration_display",
    ],
    "event": [
        "subject",
        "related_object",
        ("start_datetime", "get_start_date"),
        ("end_datetime", "get_end_date"),
        "location",
    ],
}


def _make_type_kanban_view(activity_type, view_id):
    """Factory that creates a per-type kanban view class at import time."""

    @method_decorator(htmx_required, name="dispatch")
    @method_decorator(
        permission_required_or_denied(
            ["activity.view_activity", "activity.view_own_activity"]
        ),
        name="dispatch",
    )
    class _TypeKanbanView(LoginRequiredMixin, HorillaKanbanView):
        model = None  # Set after class creation to avoid __init_subclass__ registry collision
        filterset_class = ActivityFilter
        group_by_field = "status"
        height_kanban = "h-[calc(100vh_-_280px)]"
        list_column_visibility = False
        exclude_kanban_fields = "call_type,reminder,activity_type,meeting_host"
        actions = AllActivityListView.actions
        columns = _KANBAN_TYPE_COLUMNS[activity_type]

        @cached_property
        def kanban_attrs(self):
            """Return HTMX attrs for kanban card click navigation with section param."""
            query_params = {}
            if "section" in self.request.GET:
                query_params["section"] = self.request.GET.get("section")
            query_string = urlencode(query_params)
            return {
                "hx-get": f"{{get_detail_url}}?{query_string}",
                "hx-target": "#mainContent",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "hx-select": "#mainContent",
                "permission": "activity.change_activity",
                "own_permission": "activity.change_own_activity",
                "owner_field": ["owner"],
            }

        def get_queryset(self):
            """Filter the queryset to only this kanban view's activity type."""
            return super().get_queryset().filter(activity_type=activity_type)

        @property
        def search_url(self):
            """Return the URL used for search/filter requests."""
            return reverse_lazy("activity:activity_tabbed_view")

        @property
        def main_url(self):
            """Return the main activity list URL."""
            return reverse_lazy("activity:activity_view")

    _TypeKanbanView.__name__ = view_id
    _TypeKanbanView.__qualname__ = view_id
    _TypeKanbanView.view_id = view_id
    _TypeKanbanView.model = (
        Activity  # Assign after class creation — skips __init_subclass__ registry
    )
    return _TypeKanbanView


GlobalTaskKanbanView = _make_type_kanban_view("task", "GlobalTaskKanbanView")
GlobalMeetingKanbanView = _make_type_kanban_view("meeting", "GlobalMeetingKanbanView")
GlobalCallKanbanView = _make_type_kanban_view("log_call", "GlobalCallKanbanView")
GlobalEventKanbanView = _make_type_kanban_view("event", "GlobalEventKanbanView")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["activity.view_activity", "activity.view_own_activity"]
    ),
    name="dispatch",
)
class AllActivityKanbanTabbedView(LoginRequiredMixin, HorillaTabView):
    """
    Tabbed kanban view — one kanban per activity type, wrapped in the white card shell.
    """

    template_name = "activity_type_tab_view.html"
    view_id = "activity-kanban-type-tabs"

    tabs = [
        {
            "id": "kanban-tasks",
            "title": _("Tasks"),
            "url": reverse_lazy("activity:global_task_kanban"),
        },
        {
            "id": "kanban-meetings",
            "title": _("Meetings"),
            "url": reverse_lazy("activity:global_meeting_kanban"),
        },
        {
            "id": "kanban-calls",
            "title": _("Calls"),
            "url": reverse_lazy("activity:global_call_kanban"),
        },
        {
            "id": "kanban-events",
            "title": _("Events"),
            "url": reverse_lazy("activity:global_event_kanban"),
        },
    ]


@method_decorator(
    permission_required_or_denied(
        ["activity.view_activity", "activity.view_own_activity"]
    ),
    name="dispatch",
)
class ActivityDetailView(RecentlyViewedMixin, LoginRequiredMixin, HorillaDetailView):
    """
    Detail view for Activity
    """

    model = Activity
    pipeline_field = "status"
    tab_url = reverse_lazy("activity:activity_detail_view_tabs")

    breadcrumbs = [
        (_("Schedule"), "activity:activity_view"),
        (_("Activities"), "activity:activity_view"),
    ]

    excluded_fields = [
        "id",
        "created_at",
        "updated_at",
        "additional_info",
        "history",
        "is_active",
    ]

    actions = AllActivityListView.actions

    @classmethod
    def get_available_fields_for_selector(cls, request, model):
        """
        Method to get the available fields
        """
        pk = request.GET.get("pk")
        if not pk:
            return None
        try:
            activity = model.objects.get(pk=pk)
        except model.DoesNotExist:
            return None

        activity_type = activity.activity_type
        default_header = get_activity_detail_view_fields(activity_type)
        default_details = get_activity_detail_tab_fields(activity_type)

        type_specific = [
            field if isinstance(field, str) else field[0]
            for field in ACTIVITY_TYPE_SPECIFIC_FIELDS.get(activity_type, [])
        ]

        allowed_fields = set(COMMON_FIELDS + type_specific)
        return default_header, default_details, allowed_fields

    def get_body(self):
        """Arrange detail fields based on the activity type."""
        self.body = get_activity_detail_view_fields(self.get_object().activity_type)
        return super().get_body()


@method_decorator(
    permission_required_or_denied(
        ["activity.view_activity", "activity.view_own_activity"]
    ),
    name="dispatch",
)
class ActivityDetailTab(LoginRequiredMixin, HorillaDetailSectionView):
    """
    Activity Detail Tab View
    """

    model = Activity
    template_name = "activity_details_tab.html"

    def get_template_names(self):
        """Serve the plain details tab when refreshing its own content (e.g. Cancel on edit)."""
        if self.request.headers.get("HX-Target") == "details-tab-content":
            return ["details_tab.html"]
        return super().get_template_names()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj = self.get_object()
        self.include_fields = get_activity_detail_tab_fields(obj.activity_type)

        context["body"] = self.body or self.get_default_body()
        context["related_record"] = get_related_record_context(obj, self.request.user)
        return context


@method_decorator(
    permission_required_or_denied(
        ["activity.view_activity", "activity.view_own_activity"]
    ),
    name="dispatch",
)
class ActivityDetailViewTabView(LoginRequiredMixin, HorillaDetailTabView):
    """
    Activity Detail Tab View
    """

    def _prepare_detail_tabs(self):
        self.object_id = self.request.GET.get("object_id")
        self.model = Activity
        self.urls = {
            "details": "activity:activity_details_tab",
            "notes_attachments": "activity:activity_notes_attachments",
            "history": "activity:activity_history_tab_view",
        }
        super()._prepare_detail_tabs()


@method_decorator(
    permission_required_or_denied(
        ["activity.view_activity", "activity.view_own_activity"]
    ),
    name="dispatch",
)
class ActivitynNotesAndAttachments(
    LoginRequiredMixin, HorillaNotesAttachementSectionView
):
    """Notes and Attachments Tab View"""

    model = Activity


@method_decorator(
    permission_required_or_denied(
        ["activity.view_activity", "activity.view_own_activity"]
    ),
    name="dispatch",
)
class ActivityHistoryTabView(LoginRequiredMixin, HorillaHistorySectionView):
    """
    History Tab View
    """

    model = Activity


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("activity.delete_activity", modal=True),
    name="dispatch",
)
class ActivityDeleteView(HorillaSingleDeleteView):
    """
    Activity delete view
    """

    model = Activity

    def get_post_delete_response(self):
        activity_type = self.object.activity_type
        if "calendar" in self.request.META.get("HTTP_REFERER", ""):
            return ScriptResponse(extra="$('#reloadMainContent').click();", reload=True)

        TAB_MAP = {
            "task": "tab-tasks",
            "meeting": "tab-meetings",
            "log_call": "tab-calls",
            "event": "tab-events",
        }
        if activity_type in TAB_MAP:
            tab_id = TAB_MAP[activity_type]
            return HttpResponse(
                f"<script>"
                f"(function(){{"
                f"var $globalTab = $('#{tab_id}');"
                f"if ($globalTab.length) {{ htmx.trigger($globalTab[0],'click'); return; }}"
                f"localStorage.setItem('horilla_active_activity_tab','{tab_id}');"
                f"$('#reloadButton').click();"
                f"}})();"
                f"</script>"
            )

        return ScriptResponse(reload=True)


def _pills_field_context(email_list, field_type):
    """Shared render context for email_pills_field.html re-renders.

    Always includes Activity's own add/remove/suggestions URLs so a pill
    add/remove swap doesn't fall back to the Mail app's permission-gated
    endpoints on the next interaction (email_pills_field.html defaults to
    mail:* URLs when these are omitted).
    """
    from horilla.urls import reverse

    return {
        "email_list": email_list,
        "email_string": ", ".join(email_list),
        "field_type": field_type,
        "current_search": "",
        "add_email_url": reverse("activity:meeting_add_email"),
        "remove_email_url": reverse("activity:meeting_remove_email"),
        "email_suggestions_url": reverse("activity:meeting_email_suggestions"),
    }


@method_decorator(htmx_required, name="dispatch")
class MeetingAddEmailView(LoginRequiredMixin, View):
    """Add an email pill to the external participants field."""

    def post(self, request, *args, **kwargs):
        """Append an external participant email to the hidden comma list and re-render pills."""

        email = request.POST.get("email", "").strip()
        field_type = request.POST.get("field_type", "external_participants")
        current_list = request.POST.get(f"{field_type}_email_list", "")
        email_list = (
            [e.strip() for e in current_list.split(",") if e.strip()]
            if current_list
            else []
        )
        if email and email not in email_list:
            email_list.append(email)
        return render(
            request,
            "email_pills_field.html",
            _pills_field_context(email_list, field_type),
        )


@method_decorator(htmx_required, name="dispatch")
class MeetingRemoveEmailView(LoginRequiredMixin, View):
    """Remove an email pill from the external participants field."""

    def post(self, request, *args, **kwargs):
        """Remove one email from the external participants list and re-render pills."""

        email_to_remove = request.POST.get("email_to_remove", "").strip()
        field_type = request.POST.get("field_type", "external_participants")
        current_list = request.POST.get(f"{field_type}_email_list", "")
        email_list = (
            [e.strip() for e in current_list.split(",") if e.strip()]
            if current_list
            else []
        )
        if email_to_remove in email_list:
            email_list.remove(email_to_remove)
        return render(
            request,
            "email_pills_field.html",
            _pills_field_context(email_list, field_type),
        )


@method_decorator(htmx_required, name="dispatch")
class MeetingEmailSuggestionsView(LoginRequiredMixin, View):
    """Email autocomplete for the meeting/activity external participants field.

    Mirrors mail.EmailSuggestionView's suggestion logic, but only requires login
    (like MeetingAddEmailView/MeetingRemoveEmailView) instead of Mail-app
    permissions — a user creating a meeting has no inherent reason to hold
    mail.view_horillamail, and gating this widget on that caused it to render
    an inline 403 instead of the autocomplete list.
    """

    def get(self, request, *args, **kwargs):
        """Get email suggestions for the meeting/activity external participants field."""
        from horilla.apps import apps as horilla_apps

        field_type = request.GET.get("field", "external_participants")
        current_input = request.GET.get(f"{field_type}_email_input", "").strip()
        current_email_list = request.GET.get(f"{field_type}_email_list", "")

        existing_emails = [
            e.strip().lower() for e in current_email_list.split(",") if e.strip()
        ]

        all_emails = set()
        for model in horilla_apps.get_models():
            model_name = model._meta.model_name.lower()
            if model_name in (
                "session",
                "contenttype",
                "permission",
                "group",
                "logentry",
            ):
                continue
            for field in model._meta.get_fields():
                if (
                    "email" in field.name.lower()
                    or field.__class__.__name__ == "EmailField"
                ):
                    try:
                        values = model.objects.values_list(
                            field.name, flat=True
                        ).distinct()
                    except Exception:
                        continue
                    for value in values:
                        if value and "@" in str(value):
                            all_emails.add(str(value).strip().lower())

        valid_emails = sorted(
            e
            for e in all_emails
            if len(e) >= 5 and "@" in e and "." in e.split("@")[-1]
        )

        available_emails = [e for e in valid_emails if e not in existing_emails]

        if current_input:
            search_lower = current_input.lower()
            filtered = [e for e in available_emails if search_lower in e]
            exact = [e for e in filtered if e == search_lower]
            starts_with = [
                e for e in filtered if e.startswith(search_lower) and e not in exact
            ]
            contains = [e for e in filtered if e not in exact and e not in starts_with]
            filtered_emails = exact + starts_with + contains
        else:
            filtered_emails = available_emails[:10]

        filtered_emails = filtered_emails[:15]

        from horilla.urls import reverse

        return render(
            request,
            "email_suggestions.html",
            {
                "emails": filtered_emails,
                "field_type": field_type,
                "query": current_input,
                "add_email_url": reverse("activity:meeting_add_email"),
            },
        )
