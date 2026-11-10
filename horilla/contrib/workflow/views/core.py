"""
Views for the workflow app
"""

# Standard library imports
import json
import logging
from functools import cached_property

# Third-party imports (Django)
from django.contrib import messages
from django.utils.safestring import mark_safe

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin, login_redirect
from horilla.auth.models import User
from horilla.contrib.generics.views import HorillaListView, HorillaNavView, HorillaView
from horilla.contrib.mail.models import HorillaMailTemplate
from horilla.contrib.notifications.models import NotificationTemplate
from horilla.urls import reverse, reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import DetailView
from horilla.web import HttpNotFound, RefreshResponse

from ..filters import ScheduledWorkflowExecutionFilter, WorkflowRuleFilter

# Local imports
from ..models import ScheduledWorkflowExecution, WorkflowRule

logger = logging.getLogger(__name__)


@method_decorator(
    permission_required_or_denied(
        "workflow.view_workflowrule", wrapper_id="workflow-rule-view"
    ),
    name="dispatch",
)
class WorkflowRuleView(LoginRequiredMixin, HorillaView):
    """
    WorkflowRuleView is a view for displaying the details of a single WorkflowRule, including its conditions and actions.
    """

    template_name = "settings/settings_list_shell.html"
    view_id = "workflow-rule-view"
    nav_url = reverse_lazy("workflow:workflow_rule_nav_view")
    list_url = reverse_lazy("workflow:workflow_rule_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["workflow.view_workflowrule"]),
    name="dispatch",
)
class WorkflowRuleNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar for the WorkflowRuleView, displaying a list of all WorkflowRules.
    """

    nav_title = _("Workflow Rules")
    nav_description = _("Automate actions when records meet the conditions you set.")
    search_url = reverse_lazy("workflow:workflow_rule_list_view")
    main_url = reverse_lazy("workflow:workflow_rule_view")
    model_name = "WorkflowRule"
    model_app_label = "workflow"
    nav_width = False
    all_view_types = False
    filter_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False

    @cached_property
    def new_button(self):
        """Return the configuration for the "New Workflow Rule" button, which is shown on the navbar. Only users with the appropriate permission will see this button."""
        if self.request.user.has_perm("workflow.add_workflowrule"):
            return {
                "url": f"{reverse_lazy('workflow:workflow_rule_create_view')}?new=true",
                "attrs": 'id="workflow-rule-create"',
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["workflow.view_workflowrule"]),
    name="dispatch",
)
class WorkflowRuleListView(LoginRequiredMixin, HorillaListView):
    """WorkflowRuleListView is a view for displaying a list of WorkflowRules, with options to view, edit, or delete each rule."""

    model = WorkflowRule
    view_id = "workflow-rule-list"
    search_url = reverse_lazy("workflow:workflow_rule_list_view")
    main_url = reverse_lazy("workflow:workflow_rule_view")
    filterset_class = WorkflowRuleFilter
    save_to_list_option = False
    bulk_select_option = False
    list_column_visibility = False
    columns = [
        "name",
        "model",
        "description",
        (_("Execute on"), "get_execute_display"),
        ("is_active", "is_active_col"),
    ]
    actions = [
        {
            "action": _("Edit"),
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "workflow.change_workflowrule",
            "attrs": """
                        hx-get="{get_edit_url}?new=true"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                     """,
        },
        {
            "action": _("Delete"),
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "approvals.delete_approvalrule",
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

    @cached_property
    def col_attrs(self):
        """Return column attributes for workflow rule list view."""
        attrs = {}
        if self.request.user.has_perm("workflow.view_workflowrule"):
            attrs = {
                "hx-get": "{get_detail_url}",
                "hx-target": "#workflow-rule-view",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "hx-select": "#workflow-rule-view",
            }
        return [
            {
                "name": {
                    "style": "cursor:pointer",
                    "class": "hover:text-primary-600",
                    **attrs,
                }
            }
        ]

    def no_record_add_button(self):
        """Return the add-button config shown on the empty-state screen."""
        if self.request.user.has_perm("approvals.add_approvalrule"):
            return {
                "url": f"{reverse_lazy('workflow:workflow_rule_create_view')}?new=true",
                "attrs": 'id="approval-process-create"',
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("workflow.view_workflowrule"),
    name="dispatch",
)
class WorkflowRuleDetailNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar for the WorkflowRule detail view, showing the rule name and a back button."""

    search_url = reverse_lazy("workflow:workflow_rule_list_view")
    main_url = reverse_lazy("workflow:workflow_rule_view")
    filterset_class = WorkflowRuleFilter
    one_view_only = True
    all_view_types = False
    filter_option = False
    model_name = "WorkflowRule"
    model_app_label = "Workflow"
    nav_width = False
    url_name = "workflow_rule_list_view"
    search_option = False
    border_enabled = False
    navbar_indication = True
    reload_option = False
    navbar_indication_attrs = {
        "hx-get": reverse_lazy("workflow:workflow_rule_view"),
        "hx-target": "#workflow-rule-view",
        "hx-swap": "outerHTML",
        "hx-push-url": "true",
        "hx-select": "#workflow-rule-view",
    }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj_id = self.request.GET.get("obj")
        if obj_id:
            obj_id_clean = str(obj_id).split("?")[0].strip()
            try:
                obj_id_int = int(obj_id_clean)
                obj = WorkflowRule.objects.filter(pk=obj_id_int).first()
                if obj:
                    self.nav_title = obj.name
                    context["nav_title"] = self.nav_title
            except ValueError:
                pass
        return context

    @cached_property
    def second_button(self):
        """Secondary: edit the workflow rule itself (opens modal, pencil icon)."""
        if not self.request.user.has_perm("workflow.change_workflowrule"):
            return None
        obj = self.request.GET.get("obj")
        if not obj:
            return None
        try:
            obj_id = int(str(obj).split("?")[0].strip())
        except (TypeError, ValueError):
            return None
        return {
            "url": f"{reverse('workflow:workflow_rule_update_view', kwargs={'pk': obj_id})}?new=true&obj={obj_id}",
            "title": mark_safe(
                '<img src="/static/assets/icons/edit.svg" alt="Edit" width="15">'
            ),
            "class": "border rounded-md p-3 border-dark-50",
            "attrs": {"id": "workflow-rule-edit"},
        }


@method_decorator(
    permission_required_or_denied("workflow.view_workflowrule"),
    name="dispatch",
)
class WorkflowRuleDetailView(DetailView):
    """Detail view for a WorkflowRule, showing its conditions and actions."""

    template_name = "workflow_rule_detail_view.html"
    model = WorkflowRule
    context_object_name = "workflow_rule"

    @staticmethod
    def _normalize_rule_config(config):
        """Normalize stringified JSON fragments for display templates."""
        if not isinstance(config, dict):
            return config
        normalized = dict(config)
        for key in "record_modification":
            value = normalized.get(key)
            if isinstance(value, dict):
                continue
            if isinstance(value, str):
                value = value.strip()
                while (
                    isinstance(value, str)
                    and value.startswith("{")
                    and value.endswith("}")
                ):
                    try:
                        parsed = json.loads(value)
                        if isinstance(parsed, dict):
                            normalized[key] = parsed
                            break
                        if isinstance(parsed, str):
                            value = parsed.strip()
                            continue
                        break
                    except Exception:
                        break
        return normalized

    @staticmethod
    def _resolve_field_verbose_name(field_name, model_cls):
        """Return the verbose name for a model field."""
        if not model_cls or not field_name:
            return field_name
        from horilla.contrib.generics.forms.condition_fields import (
            get_condition_field_label,
        )

        try:
            field = model_cls._meta.get_field(field_name)
            return str(
                getattr(field, "verbose_name", None)
                or field_name.replace("_", " ").title()
            )
        except Exception:
            # A field contributed by another app (e.g. a custom field) has no
            # model field; its owner supplies the label.
            return get_condition_field_label(field_name) or field_name

    def get_queryset(self):
        """Return workflow rules with prefetched conditions and actions."""
        return WorkflowRule.objects.select_related("model").prefetch_related(
            "conditions",
            "actions",
        )

    def get_context_data(self, **kwargs):
        """Build context with enriched conditions and actions for the rule."""
        from horilla.contrib.generics.methods import get_condition_value_display

        context = super().get_context_data(**kwargs)
        workflow = self.object
        context["current_obj"] = workflow
        context["nav_url"] = reverse_lazy("workflow:workflow_rule_detail_navbar")

        model_cls = None
        try:
            model_cls = workflow.model.model_class()
        except Exception:
            pass
        if model_cls is None:
            try:
                model_cls = apps.get_model(
                    workflow.model.app_label, workflow.model.model
                )
            except Exception:
                pass

        enriched_conditions = []
        for condition in workflow.conditions.order_by("order"):
            condition.value_display = get_condition_value_display(
                model_cls, condition.field, condition.value
            )
            condition.field_verbose_name = self._resolve_field_verbose_name(
                condition.field, model_cls
            )
            enriched_conditions.append(condition)

        context["enriched_conditions"] = enriched_conditions
        context["actions"] = self._enrich_actions(workflow.actions.order_by("order"))
        context["time_trigger_actions"] = list(
            workflow.time_trigger_actions.order_by("order")
        )
        return context

    @staticmethod
    def _enrich_actions(actions_qs):
        """Resolve PKs in action_config to human-readable display values."""
        actions = list(actions_qs)

        # Collect all PKs that need resolution
        mail_tpl_ids, notif_tpl_ids, user_ids = set(), set(), set()
        for action in actions:
            cfg = action.action_config or {}
            if action.action_type == "email":
                if cfg.get("template_id"):
                    try:
                        mail_tpl_ids.add(int(cfg["template_id"]))
                    except (ValueError, TypeError):
                        pass
                for uid in str(cfg.get("also_send_to", "")).split(","):
                    uid = uid.strip()
                    if uid.isdigit():
                        user_ids.add(int(uid))
            elif action.action_type == "notification":
                if cfg.get("template_id"):
                    try:
                        notif_tpl_ids.add(int(cfg["template_id"]))
                    except (ValueError, TypeError):
                        pass
                for uid in str(cfg.get("also_notify_to", "")).split(","):
                    uid = uid.strip()
                    if uid.isdigit():
                        user_ids.add(int(uid))

        # Bulk-fetch lookup dicts
        mail_tpls = {
            t.pk: t.title
            for t in HorillaMailTemplate.all_objects.filter(pk__in=mail_tpl_ids)
        }
        notif_tpls = {
            t.pk: t.title
            for t in NotificationTemplate.all_objects.filter(pk__in=notif_tpl_ids)
        }
        users = {
            u.pk: (u.get_full_name() or u.username)
            for u in User.objects.filter(pk__in=user_ids)
        }

        def _resolve_users(ids_str):
            if not ids_str:
                return ""
            parts = []
            for uid in str(ids_str).split(","):
                uid = uid.strip()
                if uid.isdigit():
                    parts.append(users.get(int(uid), uid))
                elif uid:
                    parts.append(uid)
            return ", ".join(parts)

        # Attach display_config to each action
        for action in actions:
            cfg = action.action_config or {}
            display = dict(cfg)
            if action.action_type == "email":
                tpl_pk = cfg.get("template_id", "")
                try:
                    display["template_id"] = mail_tpls.get(int(tpl_pk), tpl_pk)
                except (ValueError, TypeError):
                    display["template_id"] = tpl_pk
                display["also_send_to"] = _resolve_users(cfg.get("also_send_to", ""))
            elif action.action_type == "notification":
                tpl_pk = cfg.get("template_id", "")
                try:
                    display["template_id"] = notif_tpls.get(int(tpl_pk), tpl_pk)
                except (ValueError, TypeError):
                    display["template_id"] = tpl_pk
                display["also_notify_to"] = _resolve_users(
                    cfg.get("also_notify_to", "")
                )
            action.display_config = display

        return actions

    def dispatch(self, request, *args, **kwargs):
        """Authenticate and resolve the process object before dispatch."""
        if not request.user.is_authenticated:
            return login_redirect(request)
        try:
            self.object = self.get_object()
        except Exception as exc:
            if request.headers.get("HX-Request") == "true":
                messages.error(self.request, exc)
                return RefreshResponse(request)
            raise HttpNotFound(exc) from exc
        return super().dispatch(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("workflow.view_workflowrule", modal=True),
    name="dispatch",
)
class WorkflowTimeTriggerHistoryView(LoginRequiredMixin, HorillaListView):
    """List view showing all ScheduledWorkflowExecution history for a rule's time triggers."""

    model = ScheduledWorkflowExecution
    template_name = "workflow_tt_history_modal.html"
    view_id = "workflow-tt-history-list"
    filterset_class = ScheduledWorkflowExecutionFilter
    save_to_list_option = False
    bulk_select_option = False
    list_column_visibility = False
    table_width = False
    main_url = ""
    columns = [
        (_("Record"), "get_record_name"),
        "scheduled_at",
        "executed_at",
        "status",
        (_("Details"), "error_message"),
    ]

    @cached_property
    def search_url(self):
        """Return the search URL for this rule's time-trigger execution history."""
        return reverse(
            "workflow:workflow_time_trigger_history_view",
            kwargs={"rule_pk": self.kwargs["rule_pk"]},
        )

    def get_queryset(self):
        rule_pk = self.kwargs.get("rule_pk")
        return ScheduledWorkflowExecution.objects.filter(
            time_trigger__rule_id=rule_pk
        ).order_by("-scheduled_at")
