"""
Forms for the duplicates app
"""

# Standard library imports
import logging

# Third-party imports (Django)
from django import forms

# First party imports (Horilla)
from horilla.apps import apps
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.forms import HorillaModelForm
from horilla.contrib.generics.forms.form_class_mixin import WIDGET_INPUT_CSS_CLASS
from horilla.db import models
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import (
    DuplicateRule,
    DuplicateRuleCondition,
    MatchingRule,
    MatchingRuleCriteria,
)

logger = logging.getLogger(__name__)


class MatchingRuleForm(HorillaModelForm):
    """
    Form for MatchingRule with condition fields for criteria (like Salesforce)
    """

    htmx_field_filter = {
        "only_text_fields": True,
        "exclude_choice_fields": True,
    }

    field_order = [
        "name",
        "content_type",
        "description",
    ]

    class Meta:
        """Meta options for MatchingRuleForm."""

        model = MatchingRule
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        self.row_id = kwargs.pop("row_id", "0")
        kwargs["condition_model"] = MatchingRuleCriteria
        self.instance_obj = kwargs.get("instance")
        super().__init__(*args, **kwargs)

        model_name = getattr(self, "model_name", None)
        if (
            not hasattr(self, "condition_field_choices")
            or not self.condition_field_choices
        ):
            self.condition_field_choices = {}

        self.condition_field_choices["field_name"] = self._get_model_field_choices(
            model_name
        )
        self.condition_field_choices["match_blank_fields"] = [
            ("False", "Blank fields do not match"),
            ("True", "Blank fields match"),
        ]
        if "field_name" in self.fields and hasattr(
            self.fields["field_name"], "choices"
        ):
            self.fields["field_name"].choices = self.condition_field_choices[
                "field_name"
            ]
        if "match_blank_fields" in self.fields and hasattr(
            self.fields["match_blank_fields"], "choices"
        ):
            self.fields["match_blank_fields"].choices = self.condition_field_choices[
                "match_blank_fields"
            ]

    def _get_model_field_choices(self, model_name):
        """Get CharField field choices for the selected model"""
        field_choices = [("", "---------")]

        if not model_name:
            return field_choices

        try:
            model_class = self._find_model_class(model_name)
            if model_class:
                field_choices.extend(self._extract_field_choices(model_class))
        except Exception as e:
            logger.error("Error fetching model fields for %s: %s", model_name, str(e))

        return field_choices

    def _find_model_class(self, model_name):
        """Find model class by name across all apps."""
        for app_config in apps.get_app_configs():
            try:
                return apps.get_model(app_config.label, model_name.lower())
            except (LookupError, ValueError):
                continue
        return None

    def _extract_field_choices(self, model_class):
        """Extract field choices from model class."""
        excluded_fields = [
            "id",
            "pk",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "company",
            "additional_info",
        ]
        field_choices = []

        for field in model_class._meta.get_fields():
            if not hasattr(field, "name") or field.name in excluded_fields:
                continue
            if not isinstance(
                field, (models.CharField, models.TextField, models.EmailField)
            ):
                continue
            if hasattr(field, "choices") and field.choices:
                continue

            verbose_name = (
                getattr(field, "verbose_name", None)
                or field.name.replace("_", " ").title()
            )
            field_choices.append((field.name, str(verbose_name)))

        return field_choices

    def clean(self):
        """
        Require at least one valid matching criterion row.

        This prevents creating/updating a matching rule when all criteria are empty.
        """
        cleaned_data = super().clean()

        row_ids = set()
        condition_fields = ["field_name", "matching_method", "match_blank_fields"]

        for key in self.data:
            for field_name in condition_fields:
                prefix = f"{field_name}_"
                if key.startswith(prefix) and key != field_name:
                    row_id = key.replace(prefix, "")
                    if row_id.isdigit() or row_id == "0":
                        row_ids.add(row_id)

        has_valid_criteria = False
        invalid_rows = []
        seen_field_names = set()
        duplicate_field_names = set()

        for row_id in row_ids:
            field_name_value = (self.data.get(f"field_name_{row_id}") or "").strip()
            matching_method_value = (
                self.data.get(f"matching_method_{row_id}") or ""
            ).strip()
            match_blank_value = (
                self.data.get(f"match_blank_fields_{row_id}") or ""
            ).strip()

            # Treat rows with any non-empty data as submitted rows.
            row_has_data = bool(
                field_name_value or matching_method_value or match_blank_value
            )

            if not row_has_data:
                continue

            if not field_name_value:
                invalid_rows.append(row_id)
                continue

            if field_name_value in seen_field_names:
                duplicate_field_names.add(field_name_value)
            else:
                seen_field_names.add(field_name_value)

            has_valid_criteria = True

        if duplicate_field_names:
            self.add_error(
                None,
                _(
                    "Each matching criterion must use a different field. "
                    "The following field(s) appear more than once: %(fields)s"
                )
                % {"fields": ", ".join(sorted(duplicate_field_names))},
            )

        if invalid_rows:
            self.add_error(
                None,
                _("Matching Criteria row has missing required field: Field."),
            )

        if not has_valid_criteria:
            self.add_error(
                None,
                _("At least one matching criterion is required."),
            )

        return cleaned_data


class DuplicateRuleForm(HorillaModelForm):
    """
    Form for DuplicateRule with optional conditions
    """

    SEPARATE_MESSAGE_FIELDS = (
        "alert_message_on_create",
        "alert_message_on_edit",
    )

    use_separate_alert_messages = forms.BooleanField(
        required=False,
        label=_("Customize Message Per Action"),
        help_text=_(
            "Show distinct alert message for create and edit instead of one shared message"
        ),
        widget=forms.CheckboxInput(
            attrs={
                "hx-on:change": (
                    "['alert_message_on_create','alert_message_on_edit'].forEach("
                    "n=>{var c=document.getElementById(n+'_container');"
                    "if(c){c.style.display=this.checked?'':'none';}});"
                    "var m=document.getElementById('alert_message_container');"
                    "if(m){m.style.display=this.checked?'none':'';}"
                )
            }
        ),
    )
    use_separate_alert_messages.is_custom_field = True
    alert_message_on_create = forms.CharField(
        required=False,
        label=_("Alert Message (Create)"),
        widget=forms.Textarea(
            attrs={"rows": 4, "placeholder": _("Enter Alert Message (Create) Here...")}
        ),
    )
    alert_message_on_create.is_custom_field = True
    alert_message_on_edit = forms.CharField(
        required=False,
        label=_("Alert Message (Edit)"),
        widget=forms.Textarea(
            attrs={"rows": 4, "placeholder": _("Enter Alert Message (Edit) Here...")}
        ),
    )
    alert_message_on_edit.is_custom_field = True

    field_order = [
        "name",
        "content_type",
        "description",
        "matching_rule",
        "action_on_create",
        "action_on_edit",
        "alert_title",
        "use_separate_alert_messages",
        "alert_message",
        "alert_message_on_create",
        "alert_message_on_edit",
        "show_duplicate_records",
        "is_active",
    ]

    class Meta:
        """Meta options for DuplicateRuleForm."""

        model = DuplicateRule
        fields = "__all__"
        keep_on_form = ["is_active"]

    def __init__(self, *args, **kwargs):
        self.row_id = kwargs.pop("row_id", "0")
        kwargs["condition_model"] = DuplicateRuleCondition
        self.instance_obj = kwargs.get("instance")
        super().__init__(*args, **kwargs)

        toggle_fields = ("use_separate_alert_messages",) + self.SEPARATE_MESSAGE_FIELDS
        for field_name in toggle_fields:
            self.fields[field_name].widget.attrs.setdefault(
                "class",
                (
                    "sr-only peer"
                    if field_name == "use_separate_alert_messages"
                    else WIDGET_INPUT_CSS_CLASS
                ),
            )

        info = (self.instance_obj.additional_info if self.instance_obj else None) or {}
        use_separate = bool(info.get("use_separate_alert_messages"))
        if self.is_bound:
            use_separate = bool(self.data.get("use_separate_alert_messages"))
        else:
            self.fields["use_separate_alert_messages"].initial = use_separate
            self.fields["alert_message_on_create"].initial = info.get(
                "alert_message_on_create", ""
            )
            self.fields["alert_message_on_edit"].initial = info.get(
                "alert_message_on_edit", ""
            )

        if use_separate:
            if "alert_message" in self.fields:
                self.fields["alert_message"].required = False
                self.fields["alert_message"].widget.attrs[
                    "container_style"
                ] = "display:none"
        else:
            for field_name in self.SEPARATE_MESSAGE_FIELDS:
                self.fields[field_name].widget.attrs["container_style"] = "display:none"

        # Limit content_type choices to models registered for duplicates feature
        if "content_type" in self.fields:
            from .methods import limit_content_types

            field = self.fields["content_type"]
            if hasattr(field, "queryset"):
                # Apply the limit_choices_to filter from the model
                field.queryset = field.queryset.filter(limit_content_types())

            self.fields["content_type"].widget.attrs.update(
                {
                    "class": "js-example-basic-single headselect",
                    "hx-get": reverse_lazy("duplicates:matching_rule_choices_view"),
                    "hx-target": "#id_matching_rule",
                    "hx-swap": "outerHTML",
                    "hx-include": "[name='content_type']",
                    "hx-trigger": "change",
                }
            )

        if "matching_rule" in self.fields:
            # Determine the content_type to filter by
            content_type = None
            if self.data and "content_type" in self.data:
                # Use content_type from form data (user's selection)
                try:
                    content_type_id = self.data.get("content_type")
                    if content_type_id:
                        content_type = HorillaContentType.objects.get(
                            pk=content_type_id
                        )
                except (HorillaContentType.DoesNotExist, ValueError):
                    pass
            elif self.instance_obj and self.instance_obj.content_type:
                # Use content_type from instance (for initial load)
                content_type = self.instance_obj.content_type

            if content_type:
                # Filter matching rules by content_type
                self.fields["matching_rule"].queryset = MatchingRule.objects.filter(
                    content_type=content_type
                )

                # If instance has a matching_rule that doesn't match the new content_type, clear it
                if self.instance_obj and self.instance_obj.matching_rule:
                    if self.instance_obj.matching_rule.content_type != content_type:
                        # Clear the initial value if it doesn't match
                        if "matching_rule" in self.initial:
                            self.initial["matching_rule"] = None
                        # Also clear from instance if we're editing
                        if (
                            hasattr(self, "instance")
                            and self.instance
                            and self.instance.pk
                        ):
                            # Don't modify the instance directly, just clear the form field
                            pass

    def clean(self):
        """Validate that matching rule applies to the same content type as duplicate rule"""
        cleaned_data = super().clean()
        content_type = cleaned_data.get("content_type")
        matching_rule = cleaned_data.get("matching_rule")

        # Also check instance's matching_rule if form data doesn't have one
        # This handles the case where content_type changed but matching_rule wasn't updated in POST
        if (
            not matching_rule
            and self.instance
            and self.instance.pk
            and self.instance.matching_rule
        ):
            # If instance has a matching_rule but form data doesn't, check if it matches new content_type
            if (
                content_type
                and self.instance.matching_rule.content_type != content_type
            ):
                # Instance's matching_rule doesn't match new content_type, so clear it
                cleaned_data["matching_rule"] = None
                if content_type:
                    self.add_error(
                        "matching_rule",
                        _(
                            "Matching rule must apply to the same content type as duplicate rule. Please select a matching rule for the selected module."
                        ),
                    )

        if content_type and matching_rule:
            # Check if matching rule's content type matches duplicate rule's content type
            if matching_rule.content_type != content_type:
                # Clear the matching_rule if it doesn't match and show error
                cleaned_data["matching_rule"] = None
                self.add_error(
                    "matching_rule",
                    _(
                        "Matching rule must apply to the same content type as duplicate rule. Please select a matching rule for the selected module."
                    ),
                )

        return cleaned_data

    def save(self, commit=True):
        """Persist the per-context alert messages into additional_info."""
        instance = super().save(commit=False)

        use_separate = bool(self.cleaned_data.get("use_separate_alert_messages"))
        if use_separate and not instance.alert_message:
            # The shared field is hidden/optional while separate messages are
            # enabled; keep the previous or model-default value instead of
            # persisting an empty string.
            instance.alert_message = (
                self.instance_obj.alert_message
                if self.instance_obj and self.instance_obj.alert_message
                else DuplicateRule._meta.get_field("alert_message").get_default()
            )

        info = dict(instance.additional_info or {})
        if use_separate:
            info["use_separate_alert_messages"] = True
            info["alert_message_on_create"] = self.cleaned_data.get(
                "alert_message_on_create", ""
            ).strip()
            info["alert_message_on_edit"] = self.cleaned_data.get(
                "alert_message_on_edit", ""
            ).strip()
        else:
            info.pop("use_separate_alert_messages", None)
            info.pop("alert_message_on_create", None)
            info.pop("alert_message_on_edit", None)
        instance.additional_info = info

        if commit:
            instance.save()
        return instance
