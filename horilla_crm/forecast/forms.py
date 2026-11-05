"""
Module containing forms for ForecastTarget and ForecastType management,
including dynamic condition handling and role-based logic.
"""

# Standard library imports
import logging
from decimal import Decimal, InvalidOperation

# Third-party imports (Django)
from django import forms

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.generics.forms import HorillaModelForm
from horilla.core.exceptions import ValidationError
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import ForecastCondition, ForecastTarget, ForecastType

logger = logging.getLogger(__name__)


class ForecastTargetForm(HorillaModelForm):
    """Form to create or update forecast targets with dynamic conditions."""

    field_order = [
        "role",
        "assigned_to",
        "period",
        "forcasts_type",
        "target_amount",
        "is_role_based",
        "is_period_same",
        "is_target_same",
        "is_forecast_type_same",
    ]

    is_role_based = forms.BooleanField(
        required=False,
        label=_("Role-Based Assignment"),
        help_text=_("Filter users by selected role"),
        widget=forms.CheckboxInput(
            attrs={
                "class": "sr-only peer",
                "hx-post": reverse_lazy("forecast:toggle_role_based"),
                "hx-target": "#condition-fields-container",
                "hx-swap": "innerHTML",
                "hx-include": '[name="role"],[name="is_role_based"],[name="is_period_same"],[name="is_target_same"],[name="is_forecast_type_same"],[name="period"],[name="target_amount"],[name="forcasts_type"]',
                "hx-trigger": "change",
            }
        ),
    )

    is_period_same = forms.BooleanField(
        required=False,
        label=_("Same Period for All"),
        help_text=_("Apply the same period for all users"),
        widget=forms.CheckboxInput(
            attrs={
                "class": "sr-only peer",
                "hx-post": reverse_lazy("forecast:toggle_condition_fields"),
                "hx-target": "#condition-fields-container",
                "hx-swap": "innerHTML",
                "hx-include": '[name="is_period_same"],[name="is_target_same"],[name="is_forecast_type_same"],[name="period"],[name="target_amount"],[name="forcasts_type"],[name="role"],[name="is_role_based"]',
                "hx-trigger": "change",
            }
        ),
    )

    is_target_same = forms.BooleanField(
        required=False,
        label=_("Same Target for All"),
        help_text=_("Apply the same target amount for all users"),
        widget=forms.CheckboxInput(
            attrs={
                "class": "sr-only peer",
                "hx-post": reverse_lazy("forecast:toggle_condition_fields"),
                "hx-target": "#condition-fields-container",
                "hx-swap": "innerHTML",
                "hx-include": '[name="is_period_same"],[name="is_target_same"],[name="is_forecast_type_same"],[name="period"],[name="target_amount"],[name="forcasts_type"],[name="role"],[name="is_role_based"]',
                "hx-trigger": "change",
            }
        ),
    )

    is_forecast_type_same = forms.BooleanField(
        required=False,
        label=_("Same Forecast Type for All"),
        help_text=_("Apply the same forecast type for all users"),
        widget=forms.CheckboxInput(
            attrs={
                "class": "sr-only peer",
                "hx-post": reverse_lazy("forecast:toggle_condition_fields"),
                "hx-target": "#condition-fields-container",
                "hx-swap": "innerHTML",
                "hx-include": '[name="is_period_same"],[name="is_target_same"],[name="is_forecast_type_same"],[name="period"],[name="target_amount"],[name="forcasts_type"],[name="role"],[name="is_role_based"]',
                "hx-trigger": "change",
            }
        ),
    )

    class Meta:
        """Meta settings for ForecastTargetForm."""

        model = ForecastTarget
        fields = "__all__"
        exclude = ["currency", "current_amount"]
        widgets = {
            "target_amount": forms.NumberInput(
                attrs={"step": "0.01", "min": "0", "placeholder": _("Enter Target")}
            ),
        }

    def __init__(self, *args, **kwargs):
        self.row_id = kwargs.pop("row_id", None)
        super().__init__(*args, **kwargs)

        # Set is_role_based initial value if instance has role
        if self.instance and self.instance.role:
            self.fields["is_role_based"].initial = True

        # Set main form fields (not condition fields) to not required
        # Condition fields are automatically set to required=False by base class
        condition_fields = getattr(self, "condition_fields", [])
        for field_name in ["assigned_to", "period", "forcasts_type", "target_amount"]:
            if field_name in self.fields and field_name not in condition_fields:
                self.fields[field_name].required = False

        # Add HTMX attributes for forcasts_type on main form only
        if "forcasts_type" in self.fields and not self.row_id:
            self.fields["forcasts_type"].widget.attrs.update(
                {
                    "hx-post": reverse_lazy("forecast:update_target_help_text"),
                    "hx-target": "#target_amount_help_text",
                    "hx-swap": "innerHTML",
                    "hx-include": '[name="forcasts_type"]',
                    "hx-trigger": "change",
                }
            )

        if "role" in self.fields:
            self.fields["role"].widget.attrs.update(
                {
                    "hx-post": reverse_lazy("forecast:toggle_role_based"),
                    "hx-target": "#condition-fields-container",
                    "hx-swap": "innerHTML",
                    "hx-include": '[name="role"],[name="is_role_based"],[name="is_period_same"],[name="is_target_same"],[name="is_forecast_type_same"],[name="period"],[name="target_amount"],[name="forcasts_type"]',
                    "hx-trigger": "change",
                }
            )

    def clean_target_amount(self):
        """Validate that target amount is non-negative."""
        target_amount = self.cleaned_data.get("target_amount")
        if target_amount is None:
            return target_amount
        try:
            value = (
                target_amount
                if isinstance(target_amount, (int, float, Decimal))
                else Decimal(str(target_amount))
            )
        except (InvalidOperation, TypeError, ValueError):
            return target_amount
        if value < 0:
            raise ValidationError(_("Target amount cannot be negative."))
        return target_amount

    def clean(self):
        """Validate role-based assignment logic and user-role matching."""
        cleaned_data = super().clean()
        assigned_to = cleaned_data.get("assigned_to")
        role = cleaned_data.get("role")
        is_role_based = cleaned_data.get("is_role_based")

        if is_role_based and not role:
            self.add_error(
                "role", "Role is required when role-based assignment is selected."
            )
        if is_role_based and assigned_to and role:
            if not User.objects.filter(id=assigned_to.id, role=role).exists():
                self.add_error(
                    "assigned_to", "Selected user does not belong to the selected role."
                )

        return cleaned_data


class ForecastTypeForm(HorillaModelForm):
    """Form to create or update forecast types with condition rows."""

    field_order = ["name", "forecast_type", "description"]

    def __init__(self, *args, **kwargs):
        kwargs["condition_model"] = ForecastCondition

        # Set default model_name to "opportunity" if not provided
        if "initial" not in kwargs:
            kwargs["initial"] = {}
        if "model_name" not in kwargs["initial"]:
            request = kwargs.get("request")
            model_name = "opportunity"  # Since forecast is always for opportunities
            if request:
                model_name = (
                    request.GET.get("model_name")
                    or request.POST.get("model_name")
                    or "opportunity"
                )
            kwargs["initial"]["model_name"] = model_name

        super().__init__(*args, **kwargs)

        if not self.model_name:
            self.model_name = "opportunity"

    def clean(self):
        """Process multiple condition rows from form data"""
        cleaned_data = super().clean()

        condition_rows = self._extract_condition_rows()

        cleaned_data["condition_rows"] = condition_rows

        return cleaned_data

    class Meta:
        """Meta settings for ForecastTypeForm."""

        model = ForecastType
        fields = "__all__"
        exclude = [
            "include_pipeline",
            "include_best_case",
            "include_closed",
            "include_commit",
        ]
