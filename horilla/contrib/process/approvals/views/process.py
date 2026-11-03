"""
Process views for the approvals app.
"""

# Standard library imports
from functools import cached_property

from django.contrib import messages

# Third-party imports (Django)
from django.db import IntegrityError

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.forms import condition_fields as condition_fields_module
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla.contrib.utils.middlewares import _thread_local
from horilla.db.models import Max
from horilla.shortcuts import get_object_or_404
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import ScriptResponse

# Local imports
from ..filters import ApprovalRuleFilter
from ..forms import (
    ApprovalProcessRuleComposeForm,
    ApprovalProcessRuleForm,
    ApprovalRuleForm,
    ApprovalStepComposeFormSet,
)
from ..models import ApprovalCondition, ApprovalProcessRule, ApprovalRule, ApprovalStep


@method_decorator(
    permission_required_or_denied(
        ["approvals.view_approvalrule"], wrapper_id="approval-process-view"
    ),
    name="dispatch",
)
class ApprovalProcessView(LoginRequiredMixin, HorillaView):
    """Settings wrapper view for approval process module."""

    template_name = "settings/settings_list_shell.html"
    view_id = "approval-process-view"
    nav_url = reverse_lazy("approvals:approval_process_navbar_view")
    list_url = reverse_lazy("approvals:approval_process_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["approvals.view_approvalrule"]),
    name="dispatch",
)
class ApprovalProcessNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar for Approval Process list."""

    nav_title = _("Approval Processes")
    nav_description = _("Set up approval rules and routing for your records.")
    search_url = reverse_lazy("approvals:approval_process_list_view")
    main_url = reverse_lazy("approvals:approval_process_view")
    model_name = "ApprovalRule"
    model_app_label = "approvals"
    nav_width = False
    all_view_types = False
    filter_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False

    @cached_property
    def new_button(self):
        """Return the new-button config if the user has permission to create an approval process."""
        if self.request.user.has_perm("approvals.add_approvalrule"):
            return {
                "url": f"{reverse_lazy('approvals:approval_process_create_view')}?new=true",
                "attrs": 'id="approval-process-create"',
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["approvals.view_approvalrule"]),
    name="dispatch",
)
class ApprovalProcessListView(LoginRequiredMixin, HorillaListView):
    """Approval process list with detail/edit/delete actions."""

    model = ApprovalRule
    view_id = "approval-process-list"
    search_url = reverse_lazy("approvals:approval_process_list_view")
    main_url = reverse_lazy("approvals:approval_process_view")
    filterset_class = ApprovalRuleFilter
    save_to_list_option = False
    bulk_select_option = False
    list_column_visibility = False
    columns = [
        "name",
        "model",
        (_("Execute on"), "get_execute_display"),
        ("is_active", "is_active_col"),
    ]
    actions = [
        {
            "action": _("Edit"),
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "approvals.change_approvalrule",
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
        """Return column attributes for approval process list view."""
        attrs = {}
        if self.request.user.has_perm("approvals.view_approvalrule"):
            attrs = {
                "hx-get": "{get_detail_url}",
                "hx-target": "#approval-process-view",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "hx-select": "#approval-process-view",
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
                "url": f"{reverse_lazy('approvals:approval_process_create_view')}?new=true",
                "attrs": 'id="approval-process-create"',
            }
        return None


@method_decorator(htmx_required, name="dispatch")
class ApprovalProcessCreateUpdateView(LoginRequiredMixin, HorillaSingleFormView):
    """Create/update approval process only (module, name, triggers). Criteria are edited per rule on detail."""

    model = ApprovalRule
    form_class = ApprovalRuleForm
    full_width_fields = ["description"]
    modal_height = False
    save_and_new = False

    @cached_property
    def form_url(self):
        """Return the create or update URL for the approval process form."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "approvals:approval_process_update_view",
                kwargs={"pk": pk},
            )
        return reverse_lazy("approvals:approval_process_create_view")


@method_decorator(htmx_required, name="dispatch")
class ApprovalProcessRuleCriteriaView(LoginRequiredMixin, HorillaSingleFormView):
    """Modal: edit when-this-rule-applies criteria for one process rule."""

    permission_required = ["approvals.change_approvalrule"]
    model = ApprovalProcessRule
    form_class = ApprovalProcessRuleForm
    fields = ["order"]
    hidden_fields = ["order"]
    full_width_fields = []
    modal_height = False
    save_and_new = False
    form_title = _("Rule Criteria")
    view_id = "approval-process-rule-criteria-form"

    condition_fields = ["field", "operator", "value", "logical_operator"]
    condition_model = ApprovalCondition
    condition_related_name = "conditions"
    condition_order_by = ["order", "created_at"]
    content_type_field = None
    condition_field_title = _("When should this rule apply?")

    def get_model_name_from_content_type(self, request=None):
        obj = getattr(self, "object", None)
        if obj is None and self.kwargs.get("pk"):
            obj = (
                ApprovalProcessRule.objects.filter(pk=self.kwargs["pk"])
                .select_related("approval_process__model")
                .first()
            )
        if obj and getattr(obj, "approval_process_id", None):
            ct = obj.approval_process.model
            if ct and hasattr(ct, "model"):
                return ct.model
        return None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        model_name = self.get_model_name_from_content_type(self.request)
        if model_name:
            kwargs.setdefault("initial", {})
            kwargs["initial"]["model_name"] = model_name
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.object:
            context["form_title"] = _("Rule %(order)s — Criteria") % {
                "order": self.object.order,
            }
        return context

    @cached_property
    def form_url(self):
        """Return the URL for editing this process rule's criteria."""
        return reverse_lazy(
            "approvals:approval_process_rule_criteria_view",
            kwargs={"pk": self.kwargs["pk"]},
        )


@method_decorator(htmx_required, name="dispatch")
class ApprovalProcessRuleComposeView(LoginRequiredMixin, HorillaSingleFormView):
    """Modal: add a process rule with criteria, approvers, and rule automation JSON in one form."""

    permission_required = ["approvals.change_approvalrule"]
    template_name = "approval_process_rule_compose.html"
    model = ApprovalProcessRule
    form_class = ApprovalProcessRuleComposeForm
    fields = [
        "order",
        "approval_actions",
        "approval_update_field",
        "approval_update_value",
        "approval_task_title",
        "approval_task_description",
        "approval_email_subject",
        "approval_email_body",
        "approval_notification_template_id",
        "approval_notification_to",
        "approval_notification_also_sent_to",
        "approval_notification_message",
        "rejection_actions",
        "rejection_update_field",
        "rejection_update_value",
        "rejection_task_title",
        "rejection_task_description",
        "rejection_email_subject",
        "rejection_email_body",
        "rejection_notification_template_id",
        "rejection_notification_to",
        "rejection_notification_also_sent_to",
        "rejection_notification_message",
        "record_modification",
    ]
    full_width_fields = [
        "order",
        "approval_task_description",
        "approval_email_body",
        "rejection_task_description",
        "rejection_email_body",
        "record_modification",
    ]
    modal_height = True
    save_and_new = False
    view_id = "approval-process-rule-compose-form"

    condition_fields = ["field", "operator", "value", "logical_operator"]
    condition_model = ApprovalCondition
    condition_related_name = "conditions"
    condition_order_by = ["order", "created_at"]
    content_type_field = None
    condition_field_title = _("When should this rule apply?")

    def get_model_name_from_content_type(self, request=None):
        pk = self.kwargs.get("process_pk")
        if pk:
            ar = ApprovalRule.objects.filter(pk=pk).select_related("model").first()
            if ar and ar.model_id and hasattr(ar.model, "model"):
                return ar.model.model
        return None

    def dispatch(self, request, *args, **kwargs):
        try:
            self.process = get_object_or_404(ApprovalRule, pk=self.kwargs["process_pk"])
        except Exception as e:
            messages.error(request, e)
            return ScriptResponse(
                reload=True,
                close=True,
            )
        return super().dispatch(request, *args, **kwargs)

    def get_record_field_choices(self):
        """Return editable model fields for record-modification specific-field picks."""
        pk = self.kwargs.get("process_pk")
        if not pk:
            return []
        ar = ApprovalRule.objects.filter(pk=pk).select_related("model").first()
        if not (ar and ar.model_id):
            return []
        try:
            model_cls = ar.model.model_class()
        except Exception:
            model_cls = None
        if model_cls is None:
            try:
                model_cls = apps.get_model(ar.model.app_label, ar.model.model)
            except Exception:
                model_cls = None
        if model_cls is None:
            return []
        fields = []
        seen = set()
        for f in model_cls._meta.get_fields():
            # keep normal editable DB-backed fields only
            if not getattr(f, "concrete", False):
                continue
            if getattr(f, "many_to_many", False) or getattr(f, "one_to_many", False):
                continue
            if getattr(f, "auto_created", False) or getattr(f, "primary_key", False):
                continue
            if hasattr(f, "editable") and not f.editable:
                continue
            seen.add(f.name)
            fields.append(
                {
                    "name": f.name,
                    "label": str(
                        getattr(f, "verbose_name", None)
                        or f.name.replace("_", " ").title()
                    ),
                }
            )
        # Fallback: include condition-field choices if model introspection yielded none/limited fields.
        try:

            class _Dummy:
                condition_model = ApprovalCondition
                condition_fields = ["field"]

            model_name = getattr(ar.model, "model", None)
            for key, label in condition_fields_module.get_model_field_choices(
                _Dummy(), model_name
            ):
                if not key or key in seen:
                    continue
                seen.add(key)
                fields.append({"name": key, "label": str(label)})
        except Exception:
            pass
        return fields

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        process = self.process
        kwargs.setdefault("initial", {})
        if not getattr(self, "object", None):
            max_o = process.process_rules.aggregate(m=Max("order"))["m"] or 0
            kwargs["initial"].setdefault("order", max_o + 1)
        model_name = self.get_model_name_from_content_type(self.request)
        if model_name:
            kwargs["initial"]["model_name"] = model_name
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        is_update = bool(
            getattr(self, "object", None) and getattr(self.object, "pk", None)
        )
        context["process_pk"] = self.kwargs.get("process_pk")
        context["compose_dynamic_url"] = reverse_lazy(
            "approvals:approval_process_rule_compose_dynamic_view",
            kwargs={"process_pk": self.kwargs["process_pk"]},
        )
        if is_update:
            context["compose_dynamic_url"] = (
                f"{context['compose_dynamic_url']}?rule_pk={self.object.pk}"
            )
        context["action_model_name"] = (
            self.get_model_name_from_content_type(self.request) or ""
        )
        context["form_title"] = (
            _("Update Process Rule") if is_update else _("Create Process Rule")
        )
        context["record_field_choices"] = self.get_record_field_choices()
        if self.request.method == "POST":
            context["who_should_approve"] = {
                "overall_method": self.request.POST.get("who_overall_method", "anyone"),
                "approval_order": self.request.POST.get(
                    "who_approval_order", "sequential"
                ),
                "notify_email": self.request.POST.get("notify_approver_email")
                in ("on", "true", "1"),
                "notify_notification": self.request.POST.get(
                    "notify_approver_notification"
                )
                in ("on", "true", "1"),
            }
        else:
            context["who_should_approve"] = {
                "overall_method": "anyone",
                "approval_order": "sequential",
                "notify_email": False,
                "notify_notification": False,
            }
        if "step_formset" in kwargs:
            context["step_formset"] = kwargs["step_formset"]
        elif hasattr(self, "step_formset"):
            context["step_formset"] = self.step_formset
        elif is_update:
            context["step_formset"] = ApprovalStepComposeFormSet(
                instance=self.object,
                prefix="steps",
            )
        else:
            process = self.process
            wr = ApprovalProcessRule(approval_process=process)
            max_o = process.process_rules.aggregate(m=Max("order"))["m"] or 0
            wr.order = max_o + 1
            context["step_formset"] = ApprovalStepComposeFormSet(
                instance=wr,
                prefix="steps",
            )
        return context

    def form_invalid(self, form):
        wr = getattr(self, "object", None)
        if not wr:
            wr = ApprovalProcessRule(
                approval_process=get_object_or_404(
                    ApprovalRule, pk=self.kwargs["process_pk"]
                )
            )
        self.step_formset = ApprovalStepComposeFormSet(
            self.request.POST,
            instance=wr,
            prefix="steps",
        )
        return self.render_to_response(
            self.get_context_data(form=form, step_formset=self.step_formset)
        )

    def form_valid(self, form):
        process = self.process
        was_update = bool(
            getattr(self, "object", None) and getattr(self.object, "pk", None)
        )
        self.object = form.save(commit=False)
        self.object.approval_process = process
        rule_config = form.cleaned_data.get("rule_config", {})
        rule_config["who_should_approve"] = {
            "overall_method": self.request.POST.get("who_overall_method", "anyone"),
            "approval_order": self.request.POST.get("who_approval_order", "sequential"),
        }
        rule_config["notify_approver"] = {
            "email": self.request.POST.get("notify_approver_email")
            in ("on", "true", "1"),
            "notification": self.request.POST.get("notify_approver_notification")
            in ("on", "true", "1"),
        }
        self.object.rule_config = rule_config
        if form.cleaned_data.get("order"):
            self.object.order = form.cleaned_data.get("order")
        elif not was_update:
            max_o = process.process_rules.aggregate(m=Max("order"))["m"] or 0
            self.object.order = max_o + 1
        if not was_update:
            self.object.created_by = self.request.user
        self.object.updated_by = self.request.user
        self.object.company = (
            getattr(self.object, "company", None)
            or form.cleaned_data.get("company")
            or (
                getattr(_thread_local, "request", None).active_company
                if hasattr(_thread_local, "request")
                else getattr(self.request.user, "company", None)
            )
        )
        try:
            self.object.save()
        except IntegrityError:
            form.add_error(
                "order",
                _("A rule with this order already exists for this process."),
            )
            self.step_formset = ApprovalStepComposeFormSet(
                self.request.POST,
                instance=ApprovalProcessRule(approval_process=process),
                prefix="steps",
            )
            return self.render_to_response(
                self.get_context_data(form=form, step_formset=self.step_formset)
            )

        form.save_m2m()
        self.save_conditions(form)

        self._save_steps_from_post()
        self.request.session["condition_row_count"] = 0
        self.request.session.modified = True
        if was_update:
            messages.success(self.request, _("Process rule updated successfully."))
        else:
            messages.success(self.request, _("Process rule created successfully."))
        return ScriptResponse(close=True, reload=True)

    def _save_steps_from_post(self):
        """Persist approver rows from POST payload to avoid formset index/swap issues."""
        ApprovalStep.objects.filter(approval_process_rule=self.object).delete()
        try:
            total = int(self.request.POST.get("steps-TOTAL_FORMS", "0"))
        except ValueError:
            total = 0
        for i in range(total):
            if self.request.POST.get(f"steps-{i}-DELETE") in ("on", "true", "1"):
                continue
            approver_type = (
                self.request.POST.get(f"steps-{i}-approver_type") or "user"
            ).strip()
            order_raw = (self.request.POST.get(f"steps-{i}-order") or "").strip()
            try:
                order_val = int(order_raw) if order_raw else i + 1
            except ValueError:
                order_val = i + 1
            approver_user_id = (
                self.request.POST.get(f"steps-{i}-approver_user") or ""
            ).strip()
            role_identifier = (
                self.request.POST.get(f"steps-{i}-role_identifier") or ""
            ).strip()
            if approver_type == "user" and not approver_user_id:
                continue
            if approver_type == "role" and not role_identifier:
                continue
            kwargs = {
                "approval_process_rule": self.object,
                "order": order_val,
                "approver_type": approver_type,
                "role_identifier": role_identifier,
                "company": getattr(self.object, "company", None),
                "created_by": self.request.user,
                "updated_by": self.request.user,
            }
            if approver_type == "user" and approver_user_id:
                # Support int PKs, UUID strings, etc. (do not use isdigit() only).
                kwargs["approver_user_id"] = approver_user_id
            ApprovalStep.objects.create(**kwargs)

    @cached_property
    def form_url(self):
        """Return the create or update URL for the compose process rule form."""
        if self.kwargs.get("pk"):
            return reverse_lazy(
                "approvals:approval_process_rule_update_view",
                kwargs={
                    "process_pk": self.kwargs["process_pk"],
                    "pk": self.kwargs["pk"],
                },
            )
        return reverse_lazy(
            "approvals:approval_process_rule_create_view",
            kwargs={"process_pk": self.kwargs["process_pk"]},
        )


@method_decorator(htmx_required, name="dispatch")
class ApprovalProcessToggleView(LoginRequiredMixin, View):
    """Toggle is_active status for an approval process via HTMX."""

    def post(self, request, *args, **kwargs):
        """Toggle is_active; when activating, deactivate any other active process for the same company+module."""
        try:
            rule = ApprovalRule.objects.get(pk=kwargs["pk"])
            if request.user.has_perm("approvals.change_approvalrule"):
                new_state = not rule.is_active
                deactivated_names = []
                if new_state:
                    siblings = ApprovalRule.all_objects.filter(
                        model=rule.model,
                        company=rule.company,
                        is_active=True,
                    ).exclude(pk=rule.pk)
                    deactivated_names = list(siblings.values_list("name", flat=True))
                    siblings.update(is_active=False)
                rule.is_active = new_state
                rule.save()
                status = _("activated") if new_state else _("deactivated")
                if deactivated_names:
                    messages.success(
                        request,
                        _(
                            "%(name)s %(status)s successfully. %(deactivated)s deactivated for this module."
                        )
                        % {
                            "name": rule.name,
                            "status": status,
                            "deactivated": ", ".join(deactivated_names),
                        },
                    )
                else:
                    messages.success(request, f"{rule.name} {status} successfully")
                rule.save()
            return ScriptResponse(reload=True)
        except Exception as exc:
            messages.error(request, exc)
            return ScriptResponse(reload=True)
