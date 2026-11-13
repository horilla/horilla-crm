"""
History views for the approvals app.
"""

# Standard library imports
from functools import cached_property
from urllib.parse import urlencode

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin, login_redirect
from horilla.contrib.activity.models import Activity
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaTabView,
)
from horilla.db.models import Case, CharField, Q, Value, When
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse_lazy
from horilla.utils import timezone
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView, View
from horilla.web import HttpResponse, ScriptResponse

# Local imports
from ..filters import ApprovalInstanceFilter
from ..models import ApprovalDecision, ApprovalInstance
from ..utils import (
    get_cycle_started_at,
    get_first_user_step,
    get_rejected_policy,
    safe_content_object,
    user_matches_approver_step,
)
from ..views.jobs_detail import ApprovalJobReviewView


@method_decorator(htmx_required, name="dispatch")
class ApprovalHistoryNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar for approval history."""

    nav_title = _("Approval History")
    search_url = reverse_lazy("approvals:approval_history_list_view")
    filterset_class = ApprovalInstanceFilter
    main_url = reverse_lazy("approvals:approval_job_view")
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False


@method_decorator(htmx_required, name="dispatch")
class ApprovalHistoryListView(LoginRequiredMixin, HorillaListView):
    """History list of approval instances."""

    model = ApprovalInstance
    filterset_class = ApprovalInstanceFilter
    owner_filtration = False
    view_id = "approval-history-list"
    search_url = reverse_lazy("approvals:approval_history_list_view")
    main_url = reverse_lazy("approvals:approval_job_view")
    save_to_list_option = False
    list_column_visibility = False
    bulk_select_option = True
    bulk_update_option = False
    enable_sorting = False
    columns = ["rule", "content_object", "status", "requested_by", "updated_at"]
    actions = [
        {
            "action": _("Delete"),
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "approvals.delete_approvalinstance",
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

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .select_related("rule", "content_type", "current_step")
            .exclude(status="pending")
        )
        user = self.request.user
        if user.is_superuser:
            return qs
        role_q = Q()
        role = getattr(user, "role", None)
        if role and getattr(role, "role_name", None):
            role_q = Q(
                current_step__approver_type="role",
                current_step__role_identifier=role.role_name,
            )
        return qs.filter(
            Q(requested_by=user)
            | Q(current_step__approver_user=user)
            | role_q
            | Q(decisions__decided_by=user)
        ).distinct()

    @cached_property
    def col_attrs(self):
        """Clickable rule column (same HTMX pattern as notes / attachments)."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        hx_get = "{get_history_url}"
        if query_string:
            hx_get = f"{{get_history_url}}?{query_string}"
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


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        "approvals.delete_approvalinstance",
        modal=True,
    ),
    name="dispatch",
)
class ApprovalHistoryDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """Delete an approval history instance."""

    model = ApprovalInstance

    def get_post_delete_response(self):
        return ScriptResponse(reload=True)


class ApprovalHistoryDetailView(LoginRequiredMixin, TemplateView):
    """Read-only detail with decision timeline."""

    template_name = "approval_history_detail.html"

    def get(self, request, *args, **kwargs):
        """Redirect to the jobs view if the approval is still pending."""
        base_url = reverse_lazy("approvals:approval_job_view")
        is_htmx = request.headers.get("HX-Request") == "true"
        obj = ApprovalInstance.objects.filter(pk=self.kwargs["pk"]).first()

        if obj is None:
            messages.warning(
                request,
                str(_("This approval no longer exists.")),
            )
            if is_htmx:
                resp = HttpResponse()
                resp["HX-Redirect"] = f"{base_url}?section=my_jobs"
                return resp
            return HttpResponse(
                f'<html><body><script>window.location.replace("{base_url}?section=my_jobs");</script></body></html>'
            )

        # Direct (non-HTMX) page loads can't render the fragment properly.
        if not is_htmx:
            query = request.GET.copy()
            query.setdefault("section", "my_jobs")
            return render(
                request,
                "approval_detail_page.html",
                {"query_string": query.urlencode()},
            )

        if obj.status == "pending":
            section = request.GET.get("section", "my_jobs")
            resp = HttpResponse()
            resp["HX-Redirect"] = f"{base_url}?section={section}"
            return resp
        if safe_content_object(obj) is None and obj.content_type:
            obj.delete()
            messages.error(
                request,
                str(
                    _(
                        "Module not found: the linked record no longer exists. The approval entry has been removed."
                    )
                ),
            )
            resp = HttpResponse()
            resp["HX-Redirect"] = f"{base_url}?section=my_jobs"
            return resp
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Build context with approval instance details and step history."""
        context = super().get_context_data(**kwargs)
        obj = get_object_or_404(
            ApprovalInstance.objects.select_related(
                "rule", "content_type", "requested_by"
            ),
            pk=self.kwargs["pk"],
        )
        user = self.request.user
        if not user.is_superuser:
            allowed = (
                obj.requested_by_id == user.id
                or ApprovalDecision.objects.filter(
                    instance=obj, decided_by=user
                ).exists()
                or (
                    obj.current_step_id
                    and user_matches_approver_step(user, obj.current_step, instance=obj)
                )
            )
            if not allowed:
                return render(self.request, "403.html")
        record = safe_content_object(obj)
        can_edit_record = bool(
            record
            and (
                user.is_superuser
                or (obj.requested_by_id and obj.requested_by_id == user.id)
            )
            and obj.status in ("approved", "rejected")
        )
        field_permissions = {}
        body = ApprovalJobReviewView._detail_tab_body(record)
        if can_edit_record:
            if obj.status == "approved":
                for _, field_name in body:
                    field_permissions[field_name] = "readwrite"
            else:
                rejected_policy = get_rejected_policy(obj)
                rejected_scope = rejected_policy.get("scope", "all_fields")
                rejected_fields = set(rejected_policy.get("fields", []) or [])
                for _, field_name in body:
                    if rejected_scope == "all_fields":
                        field_permissions[field_name] = "readwrite"
                    elif (
                        rejected_scope == "specific_fields"
                        and field_name in rejected_fields
                    ):
                        field_permissions[field_name] = "readwrite"
                    else:
                        field_permissions[field_name] = "readonly"
        else:
            for _, field_name in body:
                field_permissions[field_name] = "readonly"

        related_tasks = ApprovalJobReviewView._related_tasks(obj)

        context["instance"] = obj
        context["record"] = record
        context["obj"] = record
        context["body"] = body
        context["field_permissions"] = field_permissions
        context["app_label"] = record._meta.app_label if record else ""
        context["model_name"] = record._meta.model_name if record else ""
        context["edit_field"] = True
        context["non_editable_fields"] = []
        context["can_update"] = can_edit_record
        context["pipeline_field"] = None
        context["can_resubmit"] = bool(
            obj.status == "rejected"
            and record
            and (
                user.is_superuser
                or (obj.requested_by_id and obj.requested_by_id == user.id)
            )
        )
        context["tab_url"] = reverse_lazy(
            "approvals:approval_history_detail_tab_view",
            kwargs={"pk": obj.pk},
        )
        context["related_tasks"] = related_tasks
        context["task_status_choices"] = list(Activity.STATUS_CHOICES)
        context["decisions"] = obj.decisions.select_related(
            "step", "decided_by"
        ).order_by("-decided_at", "-id")
        return context


@method_decorator(htmx_required, name="dispatch")
class ApprovalHistoryResubmitView(LoginRequiredMixin, View):
    """Resubmit a rejected approval  after optional edits."""

    @staticmethod
    def _reload_response(pk):
        """Reload the history detail tab in place, showing any queued messages."""
        url = reverse_lazy("approvals:approval_history_detail_view", kwargs={"pk": pk})
        return ScriptResponse(
            msgs=True,
            extra=(
                f"htmx.ajax('GET', '{url}?section=my_jobs',"
                "{target:'#mainContent',swap:'outerHTML',select:'#mainContent'});"
            ),
        )

    def post(self, request, pk):
        """Resubmit a rejected approval instance, resetting it to pending."""
        instance = get_object_or_404(
            ApprovalInstance.objects.select_related("current_step", "rule"),
            pk=pk,
            status="rejected",
        )
        if not (
            request.user.is_superuser
            or (
                instance.requested_by_id and instance.requested_by_id == request.user.id
            )
        ):
            messages.error(
                request, _("Only the original requester can resubmit this record.")
            )
            return self._reload_response(pk)

        process_rule = (
            getattr(instance.current_step, "approval_process_rule", None)
            if instance.current_step_id
            else None
        )
        if process_rule is None:
            decision = (
                ApprovalDecision.objects.filter(instance=instance)
                .select_related("step__approval_process_rule")
                .order_by("-decided_at", "-id")
                .first()
            )
            process_rule = (
                getattr(decision.step, "approval_process_rule", None)
                if decision
                else None
            )
        if process_rule is None:
            # Fallback: use first rule in the process that has approver steps.
            process_rule = (
                instance.rule.process_rules.prefetch_related("steps")
                .order_by("order", "id")
                .first()
            )

        first_step = get_first_user_step(process_rule) if process_rule else None
        if not first_step and process_rule:
            first_step = process_rule.steps.all().order_by("order", "id").first()
        if not first_step:
            messages.error(request, _("No approver step configured."))
            return self._reload_response(pk)

        # Start a fresh run for this same instance while retaining prior timeline.
        # Current run logic uses this timestamp boundary.
        info = dict(getattr(instance, "additional_info", None) or {})
        info["approval_cycle_started_at"] = timezone.now().isoformat()
        instance.additional_info = info
        instance.status = "pending"
        instance.current_step = first_step
        instance.updated_by = request.user
        instance.save(
            update_fields=[
                "status",
                "current_step",
                "additional_info",
                "updated_by",
                "updated_at",
            ]
        )
        messages.success(request, _("Record resubmitted for approval."))
        return HttpResponse(
            f"<script>window.location.href='{reverse_lazy('approvals:approval_job_view')}?section=my_jobs';</script>"
        )


@method_decorator(htmx_required, name="dispatch")
class ApprovalHistoryTaskStatusUpdateView(LoginRequiredMixin, View):
    """Update task status from approval history task tab."""

    @staticmethod
    def _reload_response(pk):
        """Reload the history detail tab in place, showing any queued messages."""
        url = reverse_lazy("approvals:approval_history_detail_view", kwargs={"pk": pk})
        return ScriptResponse(
            msgs=True,
            extra=(
                f"htmx.ajax('GET', '{url}?section=my_jobs',"
                "{target:'#mainContent',swap:'outerHTML',select:'#mainContent'});"
            ),
        )

    def post(self, request, pk):
        """Toggle the task status for an activity linked to a completed approval instance."""
        instance = get_object_or_404(
            ApprovalInstance.objects.select_related("requested_by", "content_type"),
            pk=pk,
        )
        if not (
            request.user.is_superuser
            or (
                instance.requested_by_id and instance.requested_by_id == request.user.id
            )
        ):
            messages.error(
                request, _("Only the original requester can update this task.")
            )
            return self._reload_response(pk)

        task_id = (request.POST.get("task_id") or "").strip()
        new_status = (request.POST.get("status") or "").strip()
        valid_statuses = {choice[0] for choice in Activity.STATUS_CHOICES}
        if not task_id or new_status not in valid_statuses:
            messages.error(request, _("Invalid task status."))
            return self._reload_response(pk)

        try:
            related_object_id = int(instance.object_id)
        except Exception:
            messages.error(request, _("Invalid related record."))
            return self._reload_response(pk)

        task = get_object_or_404(
            Activity.objects.filter(
                pk=task_id,
                content_type=instance.content_type,
                object_id=related_object_id,
                activity_type="task",
            )
        )
        task.status = new_status
        task.updated_by = request.user
        task.save(update_fields=["status", "updated_by", "updated_at"])
        messages.success(request, _("Task status updated successfully."))
        return self._reload_response(pk)


@method_decorator(htmx_required, name="dispatch")
class ApprovalHistoryDetailTabView(HorillaTabView):
    """Tab container view for the approval history detail page."""

    view_id = "approval-history-detail-tab-view"

    def dispatch(self, request, *args, **kwargs):
        """Ensure the user is authenticated before rendering tabs."""
        if not request.user.is_authenticated:
            return login_redirect(request)
        return TemplateView.dispatch(self, request, *args, **kwargs)

    def setup(self, request, *args, **kwargs):
        """Configure approval history detail tabs."""
        super().setup(request, *args, **kwargs)
        self.tabs = [
            {
                "title": _("Details"),
                "url": reverse_lazy(
                    "approvals:approval_history_detail_details_tab_view"
                ),
                "target": "tab-history-details-content",
                "id": "history-details",
            },
            {
                "title": _("Decision Timeline"),
                "url": reverse_lazy(
                    "approvals:approval_history_detail_timeline_tab_view"
                ),
                "target": "tab-history-timeline-content",
                "id": "history-timeline",
            },
            {
                "title": _("Tasks"),
                "url": reverse_lazy("approvals:approval_history_detail_tasks_tab_view"),
                "target": "tab-history-tasks-content",
                "id": "history-tasks",
            },
        ]


class ApprovalHistoryDetailDetailsTabView(LoginRequiredMixin, TemplateView):
    """Renders the Details tab for a completed approval history entry."""

    template_name = "approval_tabs/history_details_tab.html"

    def get_context_data(self, **kwargs):
        """Build context with the approval record and edit permissions."""
        context = super().get_context_data(**kwargs)
        pk = self.request.GET.get("pk")
        obj = get_object_or_404(ApprovalInstance, pk=pk)
        record = safe_content_object(obj)
        user = self.request.user
        can_edit_record = bool(
            record
            and (
                user.is_superuser
                or (obj.requested_by_id and obj.requested_by_id == user.id)
            )
            and obj.status in ("approved", "rejected")
        )
        body = ApprovalJobReviewView._detail_tab_body(record)
        field_permissions = {}
        if can_edit_record and obj.status == "approved":
            for _, field_name in body:
                field_permissions[field_name] = "readwrite"
        elif can_edit_record and obj.status == "rejected":
            rejected_policy = get_rejected_policy(obj)
            rejected_scope = rejected_policy.get("scope", "no_fields")
            rejected_fields = set(rejected_policy.get("fields", []) or [])
            for _, field_name in body:
                if rejected_scope == "all_fields":
                    field_permissions[field_name] = "readwrite"
                elif (
                    rejected_scope == "specific_fields"
                    and field_name in rejected_fields
                ):
                    field_permissions[field_name] = "readwrite"
                else:
                    field_permissions[field_name] = "readonly"
        else:
            for _, field_name in body:
                field_permissions[field_name] = "readonly"
        context.update(
            {
                "instance": obj,
                "obj": record,
                "body": body,
                "field_permissions": field_permissions,
                "app_label": record._meta.app_label if record else "",
                "model_name": record._meta.model_name if record else "",
                "edit_field": True,
                "non_editable_fields": [],
                "can_update": can_edit_record,
                "pipeline_field": None,
            }
        )
        return context


@method_decorator(htmx_required, name="dispatch")
class ApprovalHistoryDetailTimelineTabView(LoginRequiredMixin, HorillaListView):
    """Renders the Decision Timeline tab for a completed approval history entry."""

    model = ApprovalDecision
    view_id = "approval-history-timeline-list"
    search_url = reverse_lazy("approvals:approval_history_detail_timeline_tab_view")
    main_url = reverse_lazy("approvals:approval_history_detail_timeline_tab_view")
    owner_filtration = False
    save_to_list_option = False
    list_column_visibility = False
    bulk_select_option = False
    bulk_export_option = False
    bulk_update_option = False
    bulk_delete_enabled = False
    filterset_class = None
    enable_sorting = False
    columns = [
        "step",
        (_("Cycle"), "cycle_label"),
        "get_decision_display",
        "decided_by",
        "comment",
        "decided_at",
    ]

    def get_queryset(self):
        pk = self.request.GET.get("pk")
        obj = get_object_or_404(ApprovalInstance, pk=pk)
        user = self.request.user
        if not user.is_superuser:
            allowed = (
                obj.requested_by_id == user.id
                or ApprovalDecision.objects.filter(
                    instance=obj, decided_by=user
                ).exists()
                or (
                    obj.current_step_id
                    and user_matches_approver_step(user, obj.current_step, instance=obj)
                )
            )
            if not allowed:
                return ApprovalDecision.objects.none()
        qs = (
            super()
            .get_queryset()
            .filter(instance=obj)
            .select_related("step", "decided_by")
        )
        cycle_started_at = get_cycle_started_at(obj)
        if cycle_started_at:
            qs = qs.annotate(
                cycle_label=Case(
                    When(
                        decided_at__gte=cycle_started_at,
                        then=Value(str(_("Current (After Resubmit)"))),
                    ),
                    default=Value(str(_("Previous"))),
                    output_field=CharField(),
                )
            )
        else:
            qs = qs.annotate(
                cycle_label=Value(str(_("Current")), output_field=CharField())
            )
        return qs.order_by("-decided_at", "-id")


@method_decorator(htmx_required, name="dispatch")
class ApprovalHistoryDetailTasksTabView(LoginRequiredMixin, HorillaListView):
    """Renders the Tasks tab for a completed approval history entry."""

    model = Activity
    owner_filtration = False
    save_to_list_option = False
    list_column_visibility = False
    bulk_select_option = False
    bulk_export_option = False
    bulk_update_option = False
    bulk_delete_enabled = False
    filterset_class = None
    enable_sorting = False
    search_url = reverse_lazy("approvals:approval_history_detail_tasks_tab_view")
    main_url = reverse_lazy("approvals:approval_history_detail_tasks_tab_view")
    view_id = "approval-history-tasks-list"
    columns = [
        "subject",
        ("status", "get_status_update_html"),
        "get_task_priority_display",
        "due_datetime",
    ]
    col_attrs = [
        {
            "subject": {
                "hx-get": "{get_detail_url}?section=schedule",
                "hx-target": "#mainContent",
                "hx-select": "#mainContent",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }
        }
    ]

    def get_queryset(self):
        if not hasattr(self, "_tasks_cache"):
            pk = self.request.GET.get("pk")
            obj = get_object_or_404(ApprovalInstance, pk=pk)
            status_update_url = reverse_lazy(
                "approvals:approval_history_task_status_update_view",
                kwargs={"pk": obj.pk},
            )
            tasks = list(ApprovalJobReviewView._related_tasks(obj))
            for task in tasks:
                task._status_update_url = status_update_url

            class _ListQuerysetProxy(list):
                """Thin list proxy that satisfies HorillaListView's queryset API."""

                def count(self):
                    return len(self)

                def values_list(self, *fields, flat=False):
                    """Return a flat list or list of tuples from the proxy list."""
                    if flat and len(fields) == 1:
                        return [getattr(obj, fields[0]) for obj in self]
                    return [tuple(getattr(obj, f) for f in fields) for obj in self]

            self._tasks_cache = _ListQuerysetProxy(tasks)
        return self._tasks_cache
