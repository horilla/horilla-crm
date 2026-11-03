"""
HTMX fragment views for approval process rule compose dynamic area.
"""

# Standard library imports
import json

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.auth.models import User
from horilla.contrib.core.models import Role
from horilla.contrib.generics.forms import condition_fields as condition_fields_module
from horilla.contrib.mail.models import HorillaMailTemplate
from horilla.contrib.notifications.models import NotificationTemplate
from horilla.shortcuts import render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.views.generic import View

# Local imports
from ..models import ApprovalCondition, ApprovalProcessRule, ApprovalRule


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["approvals.change_approvalrule"]),
    name="dispatch",
)
class ApprovalProcessRuleActionFormView(LoginRequiredMixin, View):
    """HTMX fragment: render one action config form block."""

    @staticmethod
    def _resolve_model_by_name(model_name):
        if not model_name:
            return None
        for app_config in apps.get_app_configs():
            try:
                return apps.get_model(
                    app_label=app_config.label, model_name=model_name.lower()
                )
            except Exception:
                continue
        return None

    def get(self, request):
        """Render the action config fragment for one approval or rejection action type."""
        side = request.GET.get("side", "approval")
        action = request.GET.get("action", "")
        process_pk = request.GET.get("process_pk")
        model_name_query = request.GET.get("model_name")
        if side not in ("approval", "rejection"):
            side = "approval"
        if action not in ("update_field", "assign_task", "mail", "notification"):
            action = ""
        model_name = ""
        field_meta = []
        email_to_choices = [("self", "Self (User who triggered)")]
        notification_to_choices = [("self", "Self (User who triggered)")]
        mail_templates = HorillaMailTemplate.objects.all()
        notification_templates = NotificationTemplate.objects.all()
        try:
            company = getattr(request.user, "company", None)
            if company is not None:
                mail_templates = mail_templates.filter(
                    company=company
                ) | mail_templates.filter(company__isnull=True)
                notification_templates = notification_templates.filter(
                    company=company
                ) | notification_templates.filter(company__isnull=True)
        except Exception:
            pass
        active_company = getattr(request, "active_company", None)
        users = User.objects.filter(is_active=True)
        if active_company is not None:
            users = users.filter(company=active_company)
        if process_pk:
            process = (
                ApprovalRule.objects.filter(pk=process_pk)
                .select_related("model")
                .first()
            )
            if process and process.model_id:
                mail_templates = mail_templates.filter(
                    content_type__isnull=True
                ) | mail_templates.filter(content_type=process.model_id)
                notification_templates = notification_templates.filter(
                    content_type__isnull=True
                ) | notification_templates.filter(content_type=process.model_id)
            else:
                mail_templates = mail_templates.filter(content_type__isnull=True)
                notification_templates = notification_templates.filter(
                    content_type__isnull=True
                )
            model_cls = None
            if process and process.model_id:
                try:
                    model_cls = process.model.model_class()
                except Exception:
                    model_cls = None
                if model_cls is None:
                    try:
                        model_cls = apps.get_model(
                            process.model.app_label, process.model.model
                        )
                    except Exception:
                        model_cls = None
                model_name = process.model.model
                if model_cls:
                    for f in model_cls._meta.get_fields():
                        if not getattr(f, "concrete", False) or getattr(
                            f, "many_to_many", False
                        ):
                            continue
                        if not getattr(f, "editable", True):
                            continue
                        if getattr(f, "is_relation", False) and not getattr(
                            f, "many_to_one", False
                        ):
                            continue
                        if f.name == "id":
                            continue
                        dtype = "text"
                        itype = f.get_internal_type()
                        if getattr(f, "choices", None):
                            dtype = "choice"
                        elif itype in ("BooleanField",):
                            dtype = "boolean"
                        elif itype in ("DateField",):
                            dtype = "date"
                        elif itype in ("DateTimeField",):
                            dtype = "datetime-local"
                        elif itype in (
                            "IntegerField",
                            "BigIntegerField",
                            "PositiveIntegerField",
                            "SmallIntegerField",
                        ):
                            dtype = "number"
                        choices = []
                        for c in getattr(f, "choices", None) or []:
                            try:
                                choices.append({"value": str(c[0]), "label": str(c[1])})
                            except Exception:
                                continue
                        field_meta.append(
                            {
                                "name": f.name,
                                "label": str(
                                    getattr(f, "verbose_name", None)
                                    or f.name.replace("_", " ").title()
                                ),
                                "type": dtype,
                                "choices": choices,
                            }
                        )
                    for f in model_cls._meta.get_fields():
                        if not hasattr(f, "name"):
                            continue
                        try:
                            if f.get_internal_type() == "EmailField":
                                label = str(
                                    getattr(f, "verbose_name", None)
                                    or f.name.replace("_", " ").title()
                                )
                                email_to_choices.append(
                                    (
                                        f"instance.{f.name}",
                                        label,
                                    )
                                )
                                notification_to_choices.append(
                                    (
                                        f"instance.{f.name}",
                                        label,
                                    )
                                )
                        except Exception:
                            pass
                        if (
                            getattr(f, "many_to_one", False)
                            and getattr(f, "related_model", None) == User
                        ):
                            fk_label = str(
                                getattr(f, "verbose_name", None)
                                or f.name.replace("_", " ").title()
                            )
                            # Email action: resolve to address via instance.<fk>.email only.
                            email_to_choices.append(
                                (
                                    f"instance.{f.name}.email",
                                    f"{fk_label} Email",
                                )
                            )
                            # In-app notification: one row per user FK (no duplicate Email row).
                            notification_to_choices.append(
                                (
                                    f"instance.{f.name}",
                                    fk_label,
                                )
                            )
        else:
            mail_templates = mail_templates.filter(content_type__isnull=True)
            notification_templates = notification_templates.filter(
                content_type__isnull=True
            )
        if not field_meta:
            # Fallback: resolve by model_name (same strategy used by condition_fields)
            model_name = model_name or model_name_query or ""
            model_cls = self._resolve_model_by_name(model_name)
            if model_cls:
                for f in condition_fields_module.get_condition_model_fields(model_cls):
                    dtype = "text"
                    if getattr(f, "choices", None):
                        dtype = "choice"
                    elif f.get_internal_type() in ("BooleanField",):
                        dtype = "boolean"
                    choices = [
                        {"value": str(c[0]), "label": str(c[1])}
                        for c in (getattr(f, "choices", None) or [])
                    ]
                    field_meta.append(
                        {
                            "name": f.name,
                            "label": str(
                                getattr(f, "verbose_name", None)
                                or f.name.replace("_", " ").title()
                            ),
                            "type": dtype,
                            "choices": choices,
                        }
                    )
        if not field_meta and model_name:
            # Last fallback: at least show selectable fields from condition helper.
            class _Dummy:
                condition_model = ApprovalCondition
                condition_fields = ["field"]

            base_choices = condition_fields_module.get_model_field_choices(
                _Dummy(), model_name
            )
            for key, label in base_choices:
                if not key:
                    continue
                field_meta.append(
                    {"name": key, "label": str(label), "type": "text", "choices": []}
                )
        return render(
            request,
            "action_config_popup.html",
            {
                "side": side,
                "action": action,
                "model_name": model_name,
                "field_meta_json": field_meta,
                "mail_templates": mail_templates.distinct(),
                "notification_templates": notification_templates.distinct(),
                "users": users,
                "email_to_choices": email_to_choices,
                "notification_to_choices": notification_to_choices,
            },
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["approvals.change_approvalrule"]),
    name="dispatch",
)
class ApprovalProcessRuleComposeDynamicView(LoginRequiredMixin, View):
    """HTMX fragment for who-approves and record-modification dynamic area."""

    @staticmethod
    def _normalize_record_modification(value):
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("{") and raw.endswith("}"):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    return {}
        return {}

    def _record_field_choices(self, process_pk):
        process = (
            ApprovalRule.objects.filter(pk=process_pk).select_related("model").first()
        )
        if not (process and process.model_id):
            return []
        try:
            model_cls = process.model.model_class()
        except Exception:
            model_cls = None
        if model_cls is None:
            try:
                model_cls = apps.get_model(process.model.app_label, process.model.model)
            except Exception:
                model_cls = None
        if model_cls is None:
            return []
        fields = []
        for f in model_cls._meta.get_fields():
            if not getattr(f, "concrete", False):
                continue
            if getattr(f, "many_to_many", False) or getattr(f, "one_to_many", False):
                continue
            if getattr(f, "auto_created", False) or getattr(f, "primary_key", False):
                continue
            if hasattr(f, "editable") and not f.editable:
                continue
            fields.append(
                {
                    "name": f.name,
                    "label": str(
                        getattr(f, "verbose_name", None)
                        or f.name.replace("_", " ").title()
                    ),
                }
            )
        return fields

    def _parse_rows(self, request):
        rows = []
        try:
            total = int(request.POST.get("steps-TOTAL_FORMS", "0"))
        except Exception:
            total = 0
        for i in range(total):
            rows.append(
                {
                    "order": request.POST.get(f"steps-{i}-order", str(i + 1)),
                    "approver_type": request.POST.get(
                        f"steps-{i}-approver_type", "user"
                    )
                    or "user",
                    "approver_user": request.POST.get(f"steps-{i}-approver_user", ""),
                    "role_identifier": request.POST.get(
                        f"steps-{i}-role_identifier", ""
                    ),
                }
            )
        if not rows:
            rows = [
                {
                    "order": "1",
                    "approver_type": "user",
                    "approver_user": "",
                    "role_identifier": "",
                }
            ]
        return rows

    def post(self, request, process_pk):
        """Handle add/remove row actions and re-render the compose dynamic fragment."""
        action = request.POST.get("action", "refresh")
        rows = self._parse_rows(request)
        if action == "add":
            rows.append(
                {
                    "order": str(len(rows) + 1),
                    "approver_type": "user",
                    "approver_user": "",
                    "role_identifier": "",
                }
            )
        elif action == "remove":
            try:
                remove_idx = int(request.POST.get("row_idx", "-1"))
            except Exception:
                remove_idx = -1
            if 0 <= remove_idx < len(rows) and len(rows) > 1:
                rows.pop(remove_idx)

        for idx, row in enumerate(rows, start=1):
            row["order"] = str(idx)

        who_overall_method = request.POST.get("who_overall_method", "anyone")
        who_approval_order = request.POST.get("who_approval_order", "sequential")
        notify_approver_email = request.POST.get("notify_approver_email") in (
            "on",
            "true",
            "1",
        )
        notify_approver_notification = request.POST.get(
            "notify_approver_notification"
        ) in (
            "on",
            "true",
            "1",
        )
        has_multiple = len(rows) > 1
        if not has_multiple:
            who_overall_method = "anyone"
            who_approval_order = "sequential"

        stage_wise = (
            has_multiple
            and who_overall_method == "everyone"
            and who_approval_order == "sequential"
        )
        stage_count = len(rows) if stage_wise else 1
        stage_values = [f"stage_{i}" for i in range(1, stage_count + 1)]

        context = {
            "rows": rows,
            "who_overall_method": who_overall_method,
            "who_approval_order": who_approval_order,
            "has_multiple_approvers": has_multiple,
            "notify_approver_email": notify_approver_email,
            "notify_approver_notification": notify_approver_notification,
            "stage_wise": stage_wise,
            "stage_count": stage_count,
            "stage_values": stage_values,
            "user_select2_url": reverse_lazy(
                "generics:model_select2",
                kwargs={
                    "app_label": User._meta.app_label,
                    "model_name": User._meta.model_name,
                },
            ),
            "roles": Role.objects.all().order_by("role_name"),
            "record_field_choices": self._record_field_choices(process_pk),
            "process_pk": process_pk,
            "dynamic_url": reverse_lazy(
                "approvals:approval_process_rule_compose_dynamic_view",
                kwargs={"process_pk": process_pk},
            ),
        }
        if stage_wise:
            waiting_stage_rows = []
            rejected_stage_rows = []
            for i, sv in enumerate(stage_values, start=1):
                waiting_stage_rows.append(
                    {
                        "stage_key": sv,
                        "stage_num": i,
                        "scope": request.POST.get(
                            f"record_waiting_scope_{sv}", "no_fields"
                        ),
                        "fields": set(
                            request.POST.getlist(f"record_waiting_fields_{sv}")
                        ),
                    }
                )
                rejected_stage_rows.append(
                    {
                        "stage_key": sv,
                        "stage_num": i,
                        "scope": request.POST.get(
                            f"record_rejected_scope_{sv}", "all_fields"
                        ),
                        "fields": set(
                            request.POST.getlist(f"record_rejected_fields_{sv}")
                        ),
                    }
                )
            context["waiting_stage_rows"] = waiting_stage_rows
            context["rejected_stage_rows"] = rejected_stage_rows
        else:
            context["waiting_scope"] = request.POST.get(
                "record_waiting_scope", "no_fields"
            )
            context["rejected_scope"] = request.POST.get(
                "record_rejected_scope", "all_fields"
            )
            context["waiting_fields"] = set(
                request.POST.getlist("record_waiting_fields")
            )
            context["rejected_fields"] = set(
                request.POST.getlist("record_rejected_fields")
            )
        return render(
            request,
            "approval_process_rule_compose_dynamic_fragment.html",
            context,
        )

    def get(self, request, process_pk):
        """Render the initial compose dynamic fragment with one default step row."""
        rows = [
            {
                "order": "1",
                "approver_type": "user",
                "approver_user": "",
                "role_identifier": "",
            }
        ]
        who_overall_method = "anyone"
        who_approval_order = "sequential"
        notify_approver_email = False
        notify_approver_notification = False
        waiting_scope = "no_fields"
        rejected_scope = "all_fields"
        waiting_fields = set()
        rejected_fields = set()
        waiting_stage_rows = []
        rejected_stage_rows = []
        rm = {}

        rule_pk = request.GET.get("rule_pk")
        if rule_pk:
            rule = (
                ApprovalProcessRule.objects.filter(
                    pk=rule_pk, approval_process_id=process_pk
                )
                .prefetch_related("steps")
                .first()
            )
            if rule:
                step_rows = list(rule.steps.order_by("order", "id"))
                if step_rows:
                    rows = [
                        {
                            "order": str(step.order),
                            "approver_type": step.approver_type or "user",
                            "approver_user": str(step.approver_user_id or ""),
                            "role_identifier": step.role_identifier or "",
                        }
                        for step in step_rows
                    ]
                who_cfg = (rule.rule_config or {}).get("who_should_approve", {}) or {}
                who_overall_method = who_cfg.get("overall_method", "anyone")
                who_approval_order = who_cfg.get("approval_order", "sequential")
                notify_cfg = (rule.rule_config or {}).get("notify_approver", {}) or {}
                notify_approver_email = bool(notify_cfg.get("email"))
                notify_approver_notification = bool(notify_cfg.get("notification"))
                rm = self._normalize_record_modification(
                    (rule.rule_config or {}).get("record_modification", {})
                )

        has_multiple = len(rows) > 1
        if not has_multiple:
            who_overall_method = "anyone"
            who_approval_order = "sequential"
        stage_wise = (
            has_multiple
            and who_overall_method == "everyone"
            and who_approval_order == "sequential"
        )
        stage_count = len(rows) if stage_wise else 1
        stage_values = [f"stage_{i}" for i in range(1, stage_count + 1)]

        if stage_wise:
            by_stage = rm.get("by_stage", {}) if isinstance(rm, dict) else {}
            for i, sv in enumerate(stage_values, start=1):
                stage_cfg = by_stage.get(sv, {}) if isinstance(by_stage, dict) else {}
                w_cfg = (
                    stage_cfg.get("waiting", {}) if isinstance(stage_cfg, dict) else {}
                )
                r_cfg = (
                    stage_cfg.get("rejected", {}) if isinstance(stage_cfg, dict) else {}
                )
                waiting_stage_rows.append(
                    {
                        "stage_key": sv,
                        "stage_num": i,
                        "scope": w_cfg.get("scope", "no_fields"),
                        "fields": set(w_cfg.get("fields", []) or []),
                    }
                )
                rejected_stage_rows.append(
                    {
                        "stage_key": sv,
                        "stage_num": i,
                        "scope": r_cfg.get("scope", "all_fields"),
                        "fields": set(r_cfg.get("fields", []) or []),
                    }
                )
        else:
            waiting_scope = (
                rm.get("waiting_scope", "no_fields")
                if isinstance(rm, dict)
                else "no_fields"
            )
            rejected_scope = (
                rm.get("rejected_scope", "all_fields")
                if isinstance(rm, dict)
                else "all_fields"
            )
            waiting_fields = (
                set(rm.get("waiting_fields", []) or [])
                if isinstance(rm, dict)
                else set()
            )
            rejected_fields = (
                set(rm.get("rejected_fields", []) or [])
                if isinstance(rm, dict)
                else set()
            )

        context = {
            "rows": rows,
            "who_overall_method": who_overall_method,
            "who_approval_order": who_approval_order,
            "has_multiple_approvers": has_multiple,
            "notify_approver_email": notify_approver_email,
            "notify_approver_notification": notify_approver_notification,
            "stage_wise": stage_wise,
            "stage_count": stage_count,
            "stage_values": stage_values,
            "waiting_scope": waiting_scope,
            "rejected_scope": rejected_scope,
            "waiting_fields": waiting_fields,
            "rejected_fields": rejected_fields,
            "waiting_stage_rows": waiting_stage_rows,
            "rejected_stage_rows": rejected_stage_rows,
            "user_select2_url": reverse_lazy(
                "generics:model_select2",
                kwargs={
                    "app_label": User._meta.app_label,
                    "model_name": User._meta.model_name,
                },
            ),
            "roles": Role.objects.all().order_by("role_name"),
            "record_field_choices": self._record_field_choices(process_pk),
            "process_pk": process_pk,
            "dynamic_url": reverse_lazy(
                "approvals:approval_process_rule_compose_dynamic_view",
                kwargs={"process_pk": process_pk},
            ),
        }
        return render(
            request,
            "approval_process_rule_compose_dynamic_fragment.html",
            context,
        )
