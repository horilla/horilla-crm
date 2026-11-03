"""
Forms for the workflow app
"""

# Third-party imports (Django)
from django import forms

from horilla.contrib.generics.forms import HorillaModelForm
from horilla.contrib.mail.models import HorillaMailConfiguration

# First party imports (Horilla)
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .action_types import (
    get_action_channel,
    get_channel_template_kind,
    is_builtin_action_type,
)
from .models import WorkflowAction, WorkflowRule, WorkflowTimeTriggerAction


class WorkflowRuleForm(HorillaModelForm):
    """Create/edit workflow rule (module, name, triggers)."""

    field_order = [
        "name",
        "model",
        "description",
        "trigger_on_create",
        "trigger_on_edit",
        "is_active",
    ]

    class Meta:
        """Meta options for WorkflowRuleForm"""

        model = WorkflowRule
        fields = "__all__"
        keep_on_form = ("is_active",)


_INPUT_CLASS = (
    "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 "
    "rounded-md focus-visible:outline-0 placeholder:text-dark-100 text-sm "
    "[transition:.3s] focus:border-primary-600"
)
_SELECT_CLASS = (
    "js-example-basic-single headselect text-color-600 p-2 placeholder:text-xs "
    "pr-[40px] w-full border border-dark-50 rounded-md focus-visible:outline-0 "
    "placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600"
)


_ACTION_CONFIG_FIELD_NAMES = [
    "update_field",
    "update_value",
    "task_title",
    "task_due_basis",
    "task_due_in_days",
    "task_status",
    "task_priority",
    "task_description",
    "email_template_id",
    "email_to",
    "email_also_send_to",
    "notification_template_id",
    "notification_to",
    "notification_also_notify_to",
    "notification_custom_message",
    "channel_template_id",
    "channel_to",
    "channel_also_send_to",
]


def action_config_initials(action_type, config, default_due_basis):
    """
    The hidden compose fields of an action form for a saved ``action_config``.

    ``default_due_basis`` is the task due basis shown when none is saved.
    A delivery channel action's ``{template_id, to, also_send_to}`` fill the
    ``channel_*`` fields.
    """
    cfg = config or {}
    if action_type == "update_field":
        return {
            "update_field": cfg.get("field", ""),
            "update_value": cfg.get("value", ""),
        }
    if action_type == "assign_task":
        return {
            "task_title": cfg.get("title", ""),
            "task_due_basis": cfg.get("due_basis", default_due_basis),
            "task_due_in_days": cfg.get("due_in_days", "1"),
            "task_status": cfg.get("status", "not_started"),
            "task_priority": cfg.get("priority", "low"),
            "task_description": cfg.get("description", ""),
        }
    if action_type == "email":
        return {
            "email_template_id": cfg.get("template_id", ""),
            "email_to": cfg.get("to", ""),
            "email_also_send_to": cfg.get("also_send_to", ""),
        }
    if action_type == "notification":
        return {
            "notification_template_id": cfg.get("template_id", ""),
            "notification_to": cfg.get("to", ""),
            "notification_also_notify_to": cfg.get("also_notify_to", ""),
            "notification_custom_message": cfg.get("custom_message", ""),
        }
    if action_type:
        return {
            "channel_template_id": cfg.get("template_id", ""),
            "channel_to": cfg.get("to", ""),
            "channel_also_send_to": cfg.get("also_send_to", ""),
        }
    return {}


class ActionConfigMixin:
    """Shared hidden fields, init seeding, clean, and save logic for action_config."""

    def _inject_action_config_fields(self):
        """Add hidden action-config fields to self.fields at init time."""
        for name in _ACTION_CONFIG_FIELD_NAMES:
            self.fields[name] = forms.CharField(
                required=False, widget=forms.HiddenInput()
            )

    def _seed_action_config_initials(self):
        """Populate hidden-field initials from the saved action_config on the instance."""
        if not (self.instance and self.instance.pk):
            return
        initials = action_config_initials(
            self.instance.action_type, self.instance.action_config, ""
        )
        for name, value in initials.items():
            self.fields[name].initial = value

    def _build_action_config(self, cleaned_data):
        """Return the action_config dict built from cleaned hidden fields."""
        action_type = cleaned_data.get("action_type")
        if action_type == "update_field":
            return {
                "field": cleaned_data.get("update_field", ""),
                "value": cleaned_data.get("update_value", ""),
            }
        if action_type == "assign_task":
            return {
                "title": cleaned_data.get("task_title", ""),
                "due_basis": cleaned_data.get(
                    "task_due_basis", "record_submission_date"
                ),
                "due_in_days": cleaned_data.get("task_due_in_days", "1"),
                "status": cleaned_data.get("task_status", "not_started"),
                "priority": cleaned_data.get("task_priority", "low"),
                "description": cleaned_data.get("task_description", ""),
            }
        if action_type == "email":
            return {
                "template_id": cleaned_data.get("email_template_id", ""),
                "to": cleaned_data.get("email_to", ""),
                "also_send_to": cleaned_data.get("email_also_send_to", ""),
            }
        if action_type == "notification":
            return {
                "template_id": cleaned_data.get("notification_template_id", ""),
                "to": cleaned_data.get("notification_to", ""),
                "also_notify_to": cleaned_data.get("notification_also_notify_to", ""),
                "custom_message": cleaned_data.get("notification_custom_message", ""),
            }
        if get_action_channel(action_type) is not None:
            return {
                "template_id": cleaned_data.get("channel_template_id", ""),
                "to": cleaned_data.get("channel_to", ""),
                "also_send_to": cleaned_data.get("channel_also_send_to", ""),
            }
        return {}

    def _clean_action_type(self, cleaned_data):
        """
        ``action_type`` is a built-in or a delivery channel registered and
        available to the action's company; a channel needs its template.
        """
        action_type = cleaned_data.get("action_type")
        if not action_type or is_builtin_action_type(action_type):
            return
        channel = get_action_channel(action_type)
        company = getattr(self.instance, "company", None) or getattr(
            cleaned_data.get("rule"), "company", None
        )
        if channel is None or not channel.is_available(company):
            # action_type and the compose fields are hidden inputs: the
            # templates show non-field errors.
            self.add_error(
                None,
                _("%(action_type)s is not an available action.")
                % {"action_type": action_type},
            )
            return
        if get_channel_template_kind(channel) and not cleaned_data.get(
            "channel_template_id"
        ):
            self.add_error(None, _("Select a template."))

    def clean(self):
        """Build action_config from hidden fields and attach it to cleaned_data."""
        cleaned_data = super().clean()
        self._clean_action_type(cleaned_data)
        cleaned_data["action_config"] = self._build_action_config(cleaned_data)
        if (
            cleaned_data.get("action_type") == "email"
            and not HorillaMailConfiguration.objects.filter(
                mail_channel="outgoing"
            ).exists()
        ):
            self.add_error(
                "email_template_id",
                _(
                    "No outgoing mail configuration is set up. "
                    "Please configure a mail server before adding an email action."
                ),
            )
        return cleaned_data

    def save(self, commit=True):
        """Persist the model with action_config from cleaned_data."""
        instance = super().save(commit=False)
        instance.action_config = self.cleaned_data.get("action_config", {})
        if commit:
            instance.save()
        return instance


class WorkflowActionForm(ActionConfigMixin, forms.ModelForm):
    """Form to create/edit a WorkflowAction; action_config is built from hidden fields."""

    class Meta:
        """Meta options for WorkflowActionForm"""

        model = WorkflowAction
        fields = ["rule", "action_type", "order"]
        widgets = {
            "rule": forms.HiddenInput(),
            "order": forms.HiddenInput(),
            "action_type": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._inject_action_config_fields()
        self._seed_action_config_initials()


class WorkflowTimeTriggerActionForm(ActionConfigMixin, forms.ModelForm):
    """Form for creating/editing a WorkflowTimeTriggerAction.

    The timing row (delay_value / delay_unit / delay_direction / trigger_date_field)
    is rendered as four inline fields. Action-specific config is collected via the
    same hidden-field pattern as WorkflowActionForm and assembled in clean().
    """

    class Meta:
        """Meta options for WorkflowTimeTriggerActionForm"""

        model = WorkflowTimeTriggerAction
        fields = [
            "rule",
            "delay_value",
            "delay_unit",
            "delay_direction",
            "trigger_date_field",
            "action_type",
            "order",
        ]
        widgets = {
            "rule": forms.HiddenInput(),
            "order": forms.HiddenInput(),
            "action_type": forms.HiddenInput(),
            "delay_value": forms.NumberInput(
                attrs={
                    "class": _INPUT_CLASS,
                    "id": "tt-delay-value",
                    "min": "1",
                }
            ),
            "delay_unit": forms.Select(
                attrs={
                    "class": (
                        "js-example-basic-single headselect text-color-600 px-2 py-1 "
                        "border border-dark-50 rounded-md focus-visible:outline-0 "
                        "text-xs [transition:.3s] focus:border-primary-600"
                    ),
                    "id": "tt-delay-unit",
                    "style": "width: auto;",
                }
            ),
            "delay_direction": forms.Select(
                attrs={
                    "class": (
                        "js-example-basic-single headselect text-color-600 px-2 py-1 "
                        "border border-dark-50 rounded-md focus-visible:outline-0 "
                        "text-xs [transition:.3s] focus:border-primary-600"
                    ),
                    "id": "tt-delay-direction",
                    "style": "width: auto;",
                }
            ),
            "trigger_date_field": forms.Select(
                attrs={
                    "class": "w-full text-sm border border-dark-50 rounded-md p-2 focus-visible:outline-0 focus:border-primary-600 text-color-600",
                    "id": "tt-trigger-date-field",
                }
            ),
        }

    def __init__(self, *args, date_field_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._inject_action_config_fields()
        choices = [("rule_trigger_date", _("Rule Trigger Date"))]
        if date_field_choices:
            choices += date_field_choices
        self.fields["trigger_date_field"].widget.choices = choices
        self._seed_action_config_initials()
