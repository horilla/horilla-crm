"""
AllActivityListView and ActivityStatusUpdateView.
"""

from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin

from horilla.contrib.generics.views import HorillaListView
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.functional import cached_property  # type: ignore
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import HttpResponse, ScriptResponse

from ...filters import ActivityFilter
from ...models import Activity


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["activity.view_activity", "activity.view_own_activity"]
    ),
    name="dispatch",
)
class AllActivityListView(LoginRequiredMixin, HorillaListView):
    """Activity List view."""

    model = Activity
    view_id = "activity-list"
    filterset_class = ActivityFilter
    search_url = reverse_lazy("activity:activity_list_view")
    main_url = reverse_lazy("activity:activity_view")
    bulk_update_fields = ["status"]
    header_attrs = [
        {"subject": {"style": "width: 300px;"}},
    ]

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

    @cached_property
    def col_attrs(self):
        """Return col_attrs with HTMX attrs for navigating to the activity detail."""
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
            "owner_field": "owner",
        }
        return [{"subject": {**attrs}}]

    columns = [
        "subject",
        "activity_type",
        ("related_object", "related_object_col"),
        ("status", "status_col"),
    ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "activity.change_activity",
            "own_permission": "activity.change_own_activity",
            "owner_field": ["owner", "assigned_to"],
            "attrs": """
                        hx-get="{get_activity_edit_url}?new=true"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        },
        {
            "action": _("Duplicate"),
            "src": "assets/icons/duplicate.svg",
            "img_class": "w-4 h-4",
            "permission": "activity.add_activity",
            "attrs": """
                            hx-get="{get_activity_edit_url}?duplicate=true"
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            onclick="openModal()"
                            """,
        },
        {
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
        },
    ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["activity.change_activity", "activity.change_own_activity"]
    ),
    name="dispatch",
)
class ActivityStatusUpdateView(LoginRequiredMixin, View):
    """
    Inline status update view for activities.
    Handles HTMX POST requests from the status select dropdown in the list view.
    """

    def post(self, request, *args, **kwargs):
        """Update the activity status inline and return an appropriate response."""
        status = request.POST.get("status")
        valid_statuses = [choice[0] for choice in Activity.STATUS_CHOICES]
        if status not in valid_statuses:
            messages.error(request, _("Invalid status."))
            return HttpResponse(status=400)

        try:
            activity = Activity.objects.get(pk=kwargs["pk"])
        except Activity.DoesNotExist:
            messages.error(request, _("Activity not found."))
            return HttpResponse(status=404)

        activity.status = status
        activity.save(update_fields=["status"])
        messages.success(request, _("Status Updated."))

        tab_map = {
            "task": "tab-tasks",
            "meeting": "tab-meetings",
            "log_call": "tab-calls",
            "event": "tab-events",
        }
        sub_tab = "completed" if status == "completed" else "pending"
        tab_id = tab_map.get(activity.activity_type, "")
        if tab_id:
            return HttpResponse(
                f"<script>"
                f"localStorage.setItem('horilla_active_activity_tab','{tab_id}');"
                f"localStorage.setItem('horilla_active_activity_subtab','{sub_tab}');"
                f"$('#reloadButton').click();"
                f"</script>"
            )
        return ScriptResponse(reload=True)
