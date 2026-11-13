"""
Jobs list views for the approvals app.
"""

# Standard library imports
from functools import cached_property
from urllib.parse import urlencode

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin

# First party imports (Horilla)
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaTabView,
    HorillaView,
)
from horilla.urls import reverse_lazy
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.translation import gettext_lazy as _

# Local imports
from ..filters import ApprovalInstanceFilter
from ..models import ApprovalInstance
from ..utils import is_user_pending_approver


class ApprovalJobView(LoginRequiredMixin, HorillaView):
    """Main page for logged-in user's approval jobs."""

    template_name = "approval_job_view.html"
    nav_url = reverse_lazy("approvals:approval_job_navbar_view")
    list_url = reverse_lazy("approvals:approval_jobs_tab_view")


@method_decorator(htmx_required, name="dispatch")
class ApprovalJobNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar for approval jobs."""

    nav_title = _("My Approval Jobs")
    search_url = reverse_lazy("approvals:approval_job_list_view")
    filterset_class = ApprovalInstanceFilter
    main_url = reverse_lazy("approvals:approval_job_view")
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False


@method_decorator(htmx_required, name="dispatch")
class ApprovalJobsTabView(LoginRequiredMixin, HorillaTabView):
    """Top tabs for approval jobs and approval history."""

    view_id = "approval-jobs-tab-view"

    def setup(self, request, *args, **kwargs):
        """Configure approval jobs and history tabs."""
        super().setup(request, *args, **kwargs)
        self.tabs = [
            {
                "title": _("Approval Jobs"),
                "url": reverse_lazy("approvals:approval_job_list_view"),
                "target": "tab-approval-jobs-content",
                "id": "approval-jobs",
            },
            {
                "title": _("Approval History"),
                "url": reverse_lazy("approvals:approval_history_list_view"),
                "target": "tab-approval-history-content",
                "id": "approval-history",
            },
        ]


@method_decorator(htmx_required, name="dispatch")
class ApprovalJobListView(LoginRequiredMixin, HorillaListView):
    """List of pending approval jobs for current user."""

    model = ApprovalInstance
    filterset_class = ApprovalInstanceFilter
    owner_filtration = False
    view_id = "approval-job-list"
    search_url = reverse_lazy("approvals:approval_job_list_view")
    main_url = reverse_lazy("approvals:approval_job_view")
    save_to_list_option = False
    list_column_visibility = False
    bulk_select_option = False
    enable_sorting = False
    columns = ["rule", "content_object", "status", "created_at"]

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .filter(status="pending", is_active=True)
            .select_related("rule", "current_step", "content_type")
            .prefetch_related("decisions")
        )
        allowed_ids = [
            instance.id
            for instance in qs
            if is_user_pending_approver(instance, self.request.user)
        ]
        return qs.filter(id__in=allowed_ids)

    @cached_property
    def col_attrs(self):
        """Clickable rule column (same HTMX pattern as notes / attachments)."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        hx_get = "{get_review_url}"
        if query_string:
            hx_get = f"{{get_review_url}}?{query_string}"
        attrs = {
            "hx-get": hx_get,
            "hx-target": "#mainContent",
            "hx-select": "#mainContent",
            "hx-swap": "outerHTML",
            "hx-push-url": "true",
        }
        return [
            {
                "rule": {
                    "style": "cursor:pointer",
                    "class": "hover:text-primary-600",
                    **attrs,
                }
            }
        ]

    actions = [
        {
            "action": _("Respond"),
            "src": "assets/icons/respond.svg",
            "img_class": "w-4 h-4",
            "attrs": """
                        hx-get="{get_respond_modal_url}"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        }
    ]
