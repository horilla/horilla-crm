"""Forms for the approvals app."""

# Standard library imports
import json

# Third-party imports (Django)
from django import forms
from django.forms import inlineformset_factory

# First party imports (Horilla)
from horilla.contrib.core.models import Role
from horilla.contrib.generics.forms import HorillaModelForm
from horilla.contrib.utils.middlewares import get_current_request

# First party imports (Horilla)
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import ApprovalProcessRule, ApprovalRule, ApprovalStep


def record_modification_dict_from_post(data):
    """
    Build record_modification payload from compose POST.

    Per-stage configuration only when multiple approvers, Everyone, and Sequential.
    Otherwise a single waiting/rejected block applies (stage 1 / all parallel paths).
    """
    try:
        total_steps = int(data.get("steps-TOTAL_FORMS", "0"))
    except ValueError:
        total_steps = 0
    has_multiple = total_steps > 1
    who_overall = data.get("who_overall_method", "anyone")
    who_order = data.get("who_approval_order", "sequential")
    if not has_multiple:
        who_overall = "anyone"
        who_order = "sequential"
    stage_wise = (
        has_multiple and who_overall == "everyone" and who_order == "sequential"
    )

    def _clean_vals(qs):
        return [x for x in qs if x]

    if stage_wise:
        by_stage = {}
        for i in range(1, total_steps + 1):
            sk = f"stage_{i}"
            by_stage[sk] = {
                "waiting": {
                    "scope": data.get(f"record_waiting_scope_{sk}", "no_fields"),
                    "fields": _clean_vals(data.getlist(f"record_waiting_fields_{sk}")),
                },
                "rejected": {
                    "scope": data.get(f"record_rejected_scope_{sk}", "all_fields"),
                    "fields": _clean_vals(data.getlist(f"record_rejected_fields_{sk}")),
                },
            }
        return {"by_stage": by_stage}

    return {
        "waiting_scope": data.get("record_waiting_scope", "no_fields"),
        "waiting_fields": _clean_vals(data.getlist("record_waiting_fields")),
        "rejected_scope": data.get("record_rejected_scope", "all_fields"),
        "rejected_fields": _clean_vals(data.getlist("record_rejected_fields")),
    }


class ApprovalBaseForm(HorillaModelForm):
    """Base form for approvals: ensure all select widgets get select2 class."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.Select):
                existing = widget.attrs.get("class", "")
                classes = set(existing.split()) if existing else set()
                classes.update({"js-example-basic-single", "headselect"})
                widget.attrs["class"] = " ".join(sorted(classes))


class ApprovalRuleForm(ApprovalBaseForm):
    """Create/edit approval process only (module, name, triggers). Criteria are per process rule."""

    field_order = fields = [
        "name",
        "model",
        "trigger_on_create",
        "trigger_on_edit",
        "is_active",
        "description",
    ]

    class Meta:
        """Meta options for ApprovalRuleForm."""

        model = ApprovalRule
        fields = "__all__"
        keep_on_form = ["is_active"]

    def clean(self):
        cleaned_data = super().clean()
        is_active = cleaned_data.get("is_active")
        model = cleaned_data.get("model")
        if is_active and model:
            request = get_current_request()
            company = getattr(request, "active_company", None) if request else None
            qs = ApprovalRule.all_objects.filter(
                model=model,
                is_active=True,
                company=company,
            )
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                conflicting = qs.first()
                self.add_error(
                    None,
                    _(
                        "'%(name)s' is already the active approval process for this module. "
                        "Deactivate it before activating another."
                    )
                    % {"name": conflicting.name},
                )
        return cleaned_data


class ApprovalProcessRuleForm(ApprovalBaseForm):
    """Edit criteria for one process rule (conditions only; order is hidden)."""

    class Meta:
        """Meta options for ApprovalProcessRuleForm."""

        model = ApprovalProcessRule
        fields = ["order"]
        widgets = {
            "order": forms.HiddenInput(),
        }


class ApprovalProcessRuleComposeForm(ApprovalBaseForm):
    """Create a process rule with friendly fields (no raw JSON input)."""

    APPROVAL_ACTION_CHOICES = [
        ("", _("Select action")),
        ("update_field", _("Edit field")),
        ("assign_task", _("Assign task")),
        ("mail", _("Mail")),
        ("notification", _("Notification")),
    ]
    REJECTION_ACTION_CHOICES = [
        ("", _("Select action")),
        ("update_field", _("Edit field")),
        ("assign_task", _("Assign task")),
        ("mail", _("Mail")),
        ("notification", _("Notification")),
    ]
    approval_actions = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )
    rejection_actions = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )
    record_modification = forms.CharField(required=False, widget=forms.HiddenInput())
    process_admins = forms.CharField(required=False, widget=forms.HiddenInput())
    approval_update_field = forms.CharField(
        required=False,
        label=_("Approval: field to update"),
        widget=forms.HiddenInput(
            attrs={
                "class": "oh-input w-full",
                "placeholder": _("Ex: status"),
            }
        ),
    )
    approval_update_value = forms.CharField(
        required=False,
        label=_("Approval: updated value"),
        widget=forms.HiddenInput(
            attrs={
                "class": "oh-input w-full",
                "placeholder": _("Ex: Approved"),
            }
        ),
    )
    approval_task_title = forms.CharField(
        required=False,
        label=_("Approval: task title"),
        widget=forms.HiddenInput(
            attrs={
                "class": "oh-input w-full",
                "placeholder": _("Follow up with requester"),
            }
        ),
    )
    approval_task_description = forms.CharField(
        required=False,
        label=_("Approval: task description"),
        widget=forms.HiddenInput(
            attrs={
                "class": "oh-input w-full",
                "rows": 2,
            }
        ),
    )
    rejection_update_field = forms.CharField(
        required=False,
        label=_("Rejection: field to update"),
        widget=forms.HiddenInput(
            attrs={
                "class": "oh-input w-full",
                "placeholder": _("Ex: status"),
            }
        ),
    )
    rejection_update_value = forms.CharField(
        required=False,
        label=_("Rejection: updated value"),
        widget=forms.HiddenInput(
            attrs={
                "class": "oh-input w-full",
                "placeholder": _("Ex: Rejected"),
            }
        ),
    )
    rejection_task_title = forms.CharField(
        required=False,
        label=_("Rejection: task title"),
        widget=forms.HiddenInput(
            attrs={
                "class": "oh-input w-full",
                "placeholder": _("Resolve and Resubmit"),
            }
        ),
    )
    rejection_task_description = forms.CharField(
        required=False,
        label=_("Rejection: task description"),
        widget=forms.HiddenInput(
            attrs={
                "class": "oh-input w-full",
                "rows": 2,
            }
        ),
    )
    approval_task_payload = forms.CharField(required=False, widget=forms.HiddenInput())
    rejection_task_payload = forms.CharField(required=False, widget=forms.HiddenInput())
    approval_email_subject = forms.CharField(
        required=False,
        label=_("Approval: email subject"),
        widget=forms.HiddenInput(attrs={"class": "oh-input w-full"}),
    )
    approval_email_body = forms.CharField(
        required=False,
        label=_("Approval: email body"),
        widget=forms.HiddenInput(attrs={"class": "oh-input w-full", "rows": 3}),
    )
    rejection_email_subject = forms.CharField(
        required=False,
        label=_("Rejection: email subject"),
        widget=forms.HiddenInput(attrs={"class": "oh-input w-full"}),
    )
    rejection_email_body = forms.CharField(
        required=False,
        label=_("Rejection: email body"),
        widget=forms.HiddenInput(attrs={"class": "oh-input w-full", "rows": 3}),
    )
    approval_email_template_id = forms.CharField(
        required=False, widget=forms.HiddenInput()
    )
    approval_email_to = forms.CharField(required=False, widget=forms.HiddenInput())
    approval_email_also_sent_to = forms.CharField(
        required=False, widget=forms.HiddenInput()
    )
    rejection_email_template_id = forms.CharField(
        required=False, widget=forms.HiddenInput()
    )
    rejection_email_to = forms.CharField(required=False, widget=forms.HiddenInput())
    rejection_email_also_sent_to = forms.CharField(
        required=False, widget=forms.HiddenInput()
    )
    approval_notification_template_id = forms.CharField(
        required=False, widget=forms.HiddenInput()
    )
    approval_notification_to = forms.CharField(
        required=False, widget=forms.HiddenInput()
    )
    approval_notification_also_sent_to = forms.CharField(
        required=False, widget=forms.HiddenInput()
    )
    approval_notification_message = forms.CharField(
        required=False, widget=forms.HiddenInput()
    )
    rejection_notification_template_id = forms.CharField(
        required=False, widget=forms.HiddenInput()
    )
    rejection_notification_to = forms.CharField(
        required=False, widget=forms.HiddenInput()
    )
    rejection_notification_also_sent_to = forms.CharField(
        required=False, widget=forms.HiddenInput()
    )
    rejection_notification_message = forms.CharField(
        required=False, widget=forms.HiddenInput()
    )

    class Meta:
        """Meta options for ApprovalProcessRuleComposeForm."""

        model = ApprovalProcessRule
        fields = ["order"]
        widgets = {
            "order": forms.NumberInput(
                attrs={
                    "class": "oh-input w-full",
                    "min": 1,
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cfg = {}
        if self.instance and getattr(self.instance, "rule_config", None):
            cfg = self.instance.rule_config or {}
        for k in (
            "approval_actions",
            "rejection_actions",
            "record_modification",
            "process_admins",
        ):
            self.fields[k].initial = cfg.get(k, "")
        approval_cfg = cfg.get("approval_action_config", {}) or {}
        rejection_cfg = cfg.get("rejection_action_config", {}) or {}
        for k in (
            "approval_update_field",
            "approval_update_value",
            "approval_task_title",
            "approval_task_description",
            "approval_task_payload",
            "approval_email_subject",
            "approval_email_body",
            "approval_email_template_id",
            "approval_email_to",
            "approval_email_also_sent_to",
            "approval_notification_template_id",
            "approval_notification_to",
            "approval_notification_also_sent_to",
            "approval_notification_message",
        ):
            if k == "approval_task_payload":
                self.fields[k].initial = json.dumps(
                    approval_cfg.get("task_payload", {}) or {}
                )
            else:
                key = k.replace("approval_", "")
                self.fields[k].initial = approval_cfg.get(key, "")
        legacy_nu = (approval_cfg.get("notification_users") or "").strip()
        if legacy_nu and not (approval_cfg.get("notification_to") or "").strip():
            if not (approval_cfg.get("notification_also_sent_to") or "").strip():
                self.fields["approval_notification_also_sent_to"].initial = legacy_nu
        for k in (
            "rejection_update_field",
            "rejection_update_value",
            "rejection_task_title",
            "rejection_task_description",
            "rejection_task_payload",
            "rejection_email_subject",
            "rejection_email_body",
            "rejection_email_template_id",
            "rejection_email_to",
            "rejection_email_also_sent_to",
            "rejection_notification_template_id",
            "rejection_notification_to",
            "rejection_notification_also_sent_to",
            "rejection_notification_message",
        ):
            if k == "rejection_task_payload":
                self.fields[k].initial = json.dumps(
                    rejection_cfg.get("task_payload", {}) or {}
                )
            else:
                key = k.replace("rejection_", "")
                self.fields[k].initial = rejection_cfg.get(key, "")
        legacy_rnu = (rejection_cfg.get("notification_users") or "").strip()
        if legacy_rnu and not (rejection_cfg.get("notification_to") or "").strip():
            if not (rejection_cfg.get("notification_also_sent_to") or "").strip():
                self.fields["rejection_notification_also_sent_to"].initial = legacy_rnu

    def clean(self):
        cleaned_data = super().clean()
        approval_action = cleaned_data.get("approval_actions", "") or ""
        rejection_action = cleaned_data.get("rejection_actions", "") or ""
        try:
            approval_task_payload = json.loads(
                cleaned_data.get("approval_task_payload", "") or "{}"
            )
        except Exception:
            approval_task_payload = {}
        try:
            rejection_task_payload = json.loads(
                cleaned_data.get("rejection_task_payload", "") or "{}"
            )
        except Exception:
            rejection_task_payload = {}
        rm_dict = record_modification_dict_from_post(self.data)
        rm_json = json.dumps(rm_dict)
        cleaned_data["record_modification"] = rm_json
        cleaned_data["rule_config"] = {
            "approval_actions": approval_action,
            "rejection_actions": rejection_action,
            "record_modification": rm_json,
            "process_admins": cleaned_data.get("process_admins", "") or "",
            "approval_action_config": {
                "update_field": cleaned_data.get("approval_update_field", "") or "",
                "update_value": cleaned_data.get("approval_update_value", "") or "",
                "task_title": cleaned_data.get("approval_task_title", "") or "",
                "task_description": cleaned_data.get("approval_task_description", "")
                or "",
                "task_payload": approval_task_payload,
                "email_subject": cleaned_data.get("approval_email_subject", "") or "",
                "email_body": cleaned_data.get("approval_email_body", "") or "",
                "email_template_id": cleaned_data.get("approval_email_template_id", "")
                or "",
                "email_to": cleaned_data.get("approval_email_to", "") or "",
                "email_also_sent_to": cleaned_data.get(
                    "approval_email_also_sent_to", ""
                )
                or "",
                "notification_template_id": cleaned_data.get(
                    "approval_notification_template_id", ""
                )
                or "",
                "notification_to": cleaned_data.get("approval_notification_to", "")
                or "",
                "notification_also_sent_to": cleaned_data.get(
                    "approval_notification_also_sent_to", ""
                )
                or "",
                "notification_message": cleaned_data.get(
                    "approval_notification_message", ""
                )
                or "",
            },
            "rejection_action_config": {
                "update_field": cleaned_data.get("rejection_update_field", "") or "",
                "update_value": cleaned_data.get("rejection_update_value", "") or "",
                "task_title": cleaned_data.get("rejection_task_title", "") or "",
                "task_description": cleaned_data.get("rejection_task_description", "")
                or "",
                "task_payload": rejection_task_payload,
                "email_subject": cleaned_data.get("rejection_email_subject", "") or "",
                "email_body": cleaned_data.get("rejection_email_body", "") or "",
                "email_template_id": cleaned_data.get("rejection_email_template_id", "")
                or "",
                "email_to": cleaned_data.get("rejection_email_to", "") or "",
                "email_also_sent_to": cleaned_data.get(
                    "rejection_email_also_sent_to", ""
                )
                or "",
                "notification_template_id": cleaned_data.get(
                    "rejection_notification_template_id", ""
                )
                or "",
                "notification_to": cleaned_data.get("rejection_notification_to", "")
                or "",
                "notification_also_sent_to": cleaned_data.get(
                    "rejection_notification_also_sent_to", ""
                )
                or "",
                "notification_message": cleaned_data.get(
                    "rejection_notification_message", ""
                )
                or "",
            },
        }
        return cleaned_data


class ApprovalStepForm(ApprovalBaseForm):
    """Single approval step form."""

    class Meta:
        """Meta options for ApprovalStepForm."""

        model = ApprovalStep
        fields = ["order", "approver_type", "approver_user", "role_identifier"]
        widgets = {
            "order": forms.NumberInput(
                attrs={
                    "class": "oh-input w-full",
                    "min": 1,
                }
            ),
            "approver_type": forms.Select(
                attrs={
                    "class": "oh-select w-full",
                }
            ),
            "approver_user": forms.Select(
                attrs={
                    "class": "oh-select oh-select-2 w-full",
                }
            ),
            "role_identifier": forms.TextInput(
                attrs={
                    "class": "oh-input w-full",
                    "placeholder": _("Ex: manager"),
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Match requested UI wording/order.
        self.fields["approver_type"].choices = [
            ("user", _("User")),
            ("role", _("Role")),
            ("owner_manager", _("Record owner")),
        ]
        role_choices = [("", _("Select role"))]
        for role in Role.objects.all().order_by("role_name"):
            role_choices.append((role.role_name, role.role_name))
        current_val = self.initial.get("role_identifier") or (
            self.instance.role_identifier if self.instance and self.instance.pk else ""
        )
        if current_val and all(v != current_val for v, _ in role_choices):
            role_choices.append((current_val, current_val))
        self.fields["role_identifier"] = forms.ChoiceField(
            required=False,
            choices=role_choices,
            label=self.fields["role_identifier"].label,
            widget=forms.Select(
                attrs={
                    "class": "js-example-basic-single headselect text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                }
            ),
        )


ApprovalStepFormSet = inlineformset_factory(
    parent_model=ApprovalProcessRule,
    model=ApprovalStep,
    form=ApprovalStepForm,
    fields=["order", "approver_type", "approver_user", "role_identifier"],
    extra=1,
    can_delete=True,
)

ApprovalStepComposeFormSet = inlineformset_factory(
    parent_model=ApprovalProcessRule,
    model=ApprovalStep,
    form=ApprovalStepForm,
    fields=["order", "approver_type", "approver_user", "role_identifier"],
    extra=1,
    can_delete=True,
)
