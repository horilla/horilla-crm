"""
Forms for Horilla Core application.

This module contains Django form classes used across the Horilla Core app
"""

# Standard library imports
import logging

# Third-party imports (Django)
from django import forms
from django.contrib.auth.password_validation import validate_password

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.generics.forms import (
    CheckboxGridSelectMultiple,
    DayQuickFillWidget,
    HorillaModelForm,
    PasswordInputWithEye,
)

# First-party imports (Horilla)
from horilla.urls import reverse_lazy
from horilla.utils.choices import DAY_LABELS, SHORT_TO_DAY_PREFIX, WEEK_ORDER
from horilla.utils.html import format_html
from horilla.utils.translation import gettext_lazy as _

from ..models import BusinessHour, FiscalYear, Holiday

# Local / relative imports
from .day_time_cards import style_day_time_cards

logger = logging.getLogger(__name__)


class FiscalYearForm(HorillaModelForm):
    """Form class for FiscalYear model."""

    field_order = [
        "fiscal_year_type",
        "start_date_month",
        "display_year_based_on",
        "start_date_day",
        "format_type",
        "year_based_format",
        "quarter_based_format",
        "week_start_day",
        "number_weeks_by",
        "period_display_option",
        "company",
    ]

    class Meta:
        """Meta options for FiscalYearForm."""

        model = FiscalYear
        fields = "__all__"
        keep_on_form = ["company"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Get fiscal_year_type and format_type from POST or instance
        fiscal_year_type = (
            self.data.get("fiscal_year_type")
            if self.data
            else getattr(self.instance, "fiscal_year_type", None)
        )

        format_type = (
            self.data.get("format_type")
            if self.data
            else getattr(self.instance, "format_type", None)
        )

        if fiscal_year_type == "standard":
            # For standard type, start_date_day is optional
            self.fields["start_date_day"].required = False
            self.initial["start_date_day"] = None

        elif fiscal_year_type == "custom":
            self.fields["format_type"].required = True
            self.fields["start_date_month"].required = True
            self.fields["display_year_based_on"].required = True
            self.fields["start_date_day"].required = True
            self.fields["week_start_day"].required = True
            self.fields["number_weeks_by"].required = True
            self.fields["period_display_option"].required = True

            # Based on format_type, require specific format fields
            if format_type == "year_based":
                self.fields["year_based_format"].required = True
                self.fields["quarter_based_format"].required = False
            elif format_type == "quarter_based":
                self.fields["quarter_based_format"].required = True
                self.fields["year_based_format"].required = False


class HolidayForm(HorillaModelForm):
    """Form class for Holiday model."""

    class Meta:
        """Meta options for HolidayForm."""

        model = Holiday
        fields = "__all__"
        exclude = [
            "is_active",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
            "additional_info",
            "company",
        ]
        widgets = {
            "all_users": forms.CheckboxInput(
                attrs={
                    "id": "id_all_users",
                    "hx-trigger": "change",
                    "hx-target": "#holiday-form-view-container",
                    "hx-swap": "outerHTML",
                    "hx-include": "#holiday-form-view",
                }
            ),
            "is_recurring": forms.CheckboxInput(
                attrs={
                    "id": "id_is_recurring",
                    "hx-trigger": "change",
                    "hx-target": "#holiday-form-view-container",
                    "hx-swap": "outerHTML",
                    "hx-include": "#holiday-form-view",
                }
            ),
            "frequency": forms.Select(
                attrs={
                    "id": "id_frequency",
                    "hx-trigger": "change",
                    "hx-target": "#holiday-form-view-container",
                    "hx-swap": "outerHTML",
                    "hx-include": "#holiday-form-view",
                }
            ),
            "monthly_repeat_type": forms.Select(
                attrs={
                    "id": "id_monthly_repeat_type",
                    "hx-trigger": "change",
                    "hx-target": "#holiday-form-view-container",
                    "hx-swap": "outerHTML",
                    "hx-include": "#holiday-form-view",
                }
            ),
            "yearly_repeat_type": forms.Select(
                attrs={
                    "id": "id_yearly_repeat_type",
                    "hx-trigger": "change",
                    "hx-target": "#holiday-form-view-container",
                    "hx-swap": "outerHTML",
                    "hx-include": "#holiday-form-view",
                }
            ),
            "weekly_days": CheckboxGridSelectMultiple(),
        }

    FIELD_HELP_TEXTS = {
        "frequency": _("How often the holiday repeats: weekly, monthly or yearly."),
        "recurs_every_weeks": _("Repeat every this many weeks. 1 means every week."),
        "weekly_days": _("Days of the week the holiday falls on in each repeat."),
        "monthly_repeat_type": _(
            "On Day repeats on a fixed date each month. On the repeats on a "
            "weekday, such as the 2nd Monday."
        ),
        "monthly_day_of_month": _("Day of the month (1-31) the holiday falls on."),
        "monthly_interval": _("Repeat every this many months. 1 means every month."),
        "monthly_day_of_week": _("Weekday the holiday falls on, for example Monday."),
        "monthly_week_of_month": _(
            "Which occurrence of that weekday in the month, for example 2 for "
            "the 2nd Monday."
        ),
        "yearly_repeat_type": _(
            "On every repeats on a fixed date each year. On the repeats on a "
            "weekday of a month, such as the 2nd Monday of July."
        ),
        "yearly_month": _("Month of the year the holiday falls in."),
        "yearly_day_of_month": _("Day of the month (1-31) the holiday falls on."),
        "yearly_day_of_week": _("Weekday the holiday falls on, for example Monday."),
        "yearly_week_of_month": _(
            "Which occurrence of that weekday in the month, for example 2 for "
            "the 2nd Monday."
        ),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name, text in self.FIELD_HELP_TEXTS.items():
            if name in self.fields and not self.fields[name].help_text:
                self.fields[name].help_text = text

        instance = self.instance
        initial = self.data or self.initial

        base_url = (
            f"/holiday-update-form/{instance.pk}?toggle_all_users=true"
            if instance and instance.pk
            else "/holiday-create-form/?toggle_all_users=true"
        )
        for name in (
            "all_users",
            "is_recurring",
            "frequency",
            "monthly_repeat_type",
            "yearly_repeat_type",
        ):
            if name in self.fields:
                self.fields[name].widget.attrs["hx-get"] = base_url

        def hide_fields(field_list, nullify=False):
            for name in field_list:
                if name in self.fields:
                    self.fields[name].widget = forms.HiddenInput(
                        attrs={"required": False}
                    )
                    if nullify:
                        self.fields[name].initial = None
                        if self.data:
                            self.data = self.data.copy()
                            self.data[name] = None

        # All users logic
        if self.fields.get("specific_users") and initial.get("all_users"):
            hide_fields(["specific_users"], nullify=True)
        elif self.fields.get("specific_users"):
            self.fields["specific_users"].required = True

        # Not recurring? Hide all recurrence-related fields
        is_recurring = bool(initial.get("is_recurring"))
        frequency = initial.get("frequency", "")
        if not is_recurring:
            hide_fields(
                [
                    "frequency",
                    "recurs_every_weeks",
                    "weekly_days",
                    "monthly_repeat_type",
                    "monthly_day_of_month",
                    "monthly_interval",
                    "monthly_day_of_week",
                    "monthly_week_of_month",
                    "yearly_repeat_type",
                    "yearly_month",
                    "yearly_day_of_month",
                    "yearly_day_of_week",
                    "yearly_week_of_month",
                ],
                nullify=True,
            )
        else:
            if frequency != "weekly":
                hide_fields(["recurs_every_weeks", "weekly_days"], nullify=True)

            if frequency != "monthly":
                hide_fields(
                    [
                        "monthly_repeat_type",
                        "monthly_day_of_month",
                        "monthly_interval",
                        "monthly_day_of_week",
                        "monthly_week_of_month",
                    ],
                    nullify=True,
                )

            elif frequency == "monthly":
                monthly_repeat_type = initial.get("monthly_repeat_type", "")

                if not monthly_repeat_type:
                    hide_fields(["monthly_day_of_month"], nullify=True)

                if monthly_repeat_type != "day_of_month":
                    hide_fields(["monthly_interval"], nullify=True)

                if monthly_repeat_type != "weekday_of_month":
                    hide_fields(
                        ["monthly_day_of_week", "monthly_week_of_month"], nullify=True
                    )

            if frequency != "yearly":
                hide_fields(
                    [
                        "yearly_repeat_type",
                        "yearly_month",
                        "yearly_day_of_month",
                        "yearly_day_of_week",
                        "yearly_week_of_month",
                    ],
                    nullify=True,
                )

            elif frequency == "yearly":
                yearly_repeat_type = initial.get("yearly_repeat_type", "")

                if not yearly_repeat_type:
                    hide_fields(["yearly_month"], nullify=True)

                if yearly_repeat_type != "day_of_month":
                    hide_fields(["yearly_day_of_month"], nullify=True)

                if yearly_repeat_type != "weekday_of_month":
                    hide_fields(
                        ["yearly_day_of_week", "yearly_week_of_month"], nullify=True
                    )

    def clean(self):
        cleaned_data = super().clean()

        if "weekly_days" in self.errors:
            choices = self.fields["weekly_days"].choices
            valid = [c[0] for c in choices]
            label_to_value = {str(c[1]): c[0] for c in choices}
            values = cleaned_data.get("weekly_days")
            if not isinstance(values, list):
                values = self.data.getlist("weekly_days") if self.data else []

            values = [label_to_value.get(v, v) for v in values]
            if values and all(v in valid for v in values):
                del self.errors["weekly_days"]
                cleaned_data["weekly_days"] = values

        def clear_fields(field_list):
            for field in field_list:
                if field in cleaned_data:
                    cleaned_data[field] = None

        is_recurring = cleaned_data.get("is_recurring")
        frequency = cleaned_data.get("frequency")
        repeat_type = cleaned_data.get("monthly_repeat_type")

        if not is_recurring:
            clear_fields(
                [
                    "frequency",
                    "recurs_every_weeks",
                    "weekly_days",
                    "monthly_repeat_type",
                    "monthly_day_of_month",
                    "monthly_interval",
                    "monthly_day_of_week",
                    "monthly_week_of_month",
                ]
            )
        else:
            if frequency != "weekly":
                clear_fields(["recurs_every_weeks", "weekly_days"])

            if frequency != "monthly":
                clear_fields(
                    [
                        "monthly_repeat_type",
                        "monthly_day_of_month",
                        "monthly_interval",
                        "monthly_day_of_week",
                        "monthly_week_of_month",
                    ]
                )
            else:
                if repeat_type != "day_of_month":
                    clear_fields(["monthly_interval"])
                if repeat_type != "weekday_of_month":
                    clear_fields(["monthly_day_of_week", "monthly_week_of_month"])
                if not repeat_type:
                    clear_fields(["monthly_day_of_month"])

        return cleaned_data


class BusinessHourHolidayForm(HorillaModelForm):
    """Form to link existing all-users holidays to a business hour."""

    class Meta:
        """Meta options for BusinessHourHolidayForm."""

        model = BusinessHour
        fields = ["holidays"]
        widgets = {"holidays": forms.SelectMultiple()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = self.instance
        if instance and instance.pk:
            already_linked = instance.holidays.values_list("id", flat=True)
            self.fields["holidays"].queryset = (
                Holiday.objects.filter(company_id=instance.company_id, all_users=True)
                .exclude(id__in=already_linked)
                .order_by("start_date", "name")
            )
            # Clear pre-selected tags — this is an add form, not edit
            self.fields["holidays"].widget.attrs["data-initial"] = ""
        else:
            self.fields["holidays"].queryset = Holiday.objects.none()
        self.fields["holidays"].required = True

    def _get_fresh_queryset(self, field_name, related_model):
        if field_name == "holidays":
            instance = self.instance
            if instance and instance.pk:
                already_linked = instance.holidays.values_list("id", flat=True)
                return Holiday.objects.filter(
                    company_id=instance.company_id, all_users=True
                ).exclude(id__in=already_linked)
            return Holiday.objects.none()
        return super()._get_fresh_queryset(field_name, related_model)

    def _save_m2m(self):
        selected = self.cleaned_data.get("holidays", [])
        if selected:
            self.instance.holidays.add(*selected)


class BusinessHourForm(HorillaModelForm):
    """Form class for BusinessHour model."""

    # UI-only helper (not a model field, never saved): bulk-fills the per-day
    # start/end inputs shown for "Different hours every day".
    day_quick_fill = forms.CharField(
        required=False,
        label=_("Quick fill"),
        widget=DayQuickFillWidget(),
    )

    class Meta:
        """Meta options for BusinessHourForm."""

        model = BusinessHour
        fields = [
            "company",
            "name",
            "time_zone",
            "business_hour_type",
            "timing_type",
            "week_days",
            "default_start_time",
            "default_end_time",
            "monday_start",
            "monday_end",
            "tuesday_start",
            "tuesday_end",
            "wednesday_start",
            "wednesday_end",
            "thursday_start",
            "thursday_end",
            "friday_start",
            "friday_end",
            "saturday_start",
            "saturday_end",
            "sunday_start",
            "sunday_end",
            "is_active",
        ]
        exclude = [
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
            "additional_info",
        ]

        widgets = {
            "name": forms.TextInput(attrs={"placeholder": _("e.g. US Business Hours")}),
            "business_hour_type": forms.Select(
                attrs={
                    "id": "id_business_hour_type",
                    "hx-trigger": "change",
                    "hx-target": "#business-hour-form-view-container",
                    "hx-swap": "outerHTML",
                    "hx-include": "#business-hour-form-view",
                }
            ),
            "timing_type": forms.Select(
                attrs={
                    "id": "id_timing_type",
                    "hx-trigger": "change",
                    "hx-target": "#business-hour-form-view-container",
                    "hx-swap": "outerHTML",
                    "hx-include": "#business-hour-form-view",
                }
            ),
            "week_days": CheckboxGridSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = self.instance
        initial = self.data or self.initial

        base_url = (
            f"/business-hour-update-form/{instance.pk}?toggle_data=true"
            if instance and instance.pk
            else "/business-hour-create-form/?toggle_data=true"
        )

        for name in ("business_hour_type", "timing_type"):
            if name in self.fields:
                self.fields[name].widget.attrs["hx-get"] = base_url

        def hide_fields(field_list, nullify=False):
            for name in field_list:
                if name in self.fields:
                    self.fields[name].widget = forms.HiddenInput(
                        attrs={"required": False}
                    )
                    if nullify:
                        self.fields[name].initial = None
                        if self.data:
                            self.data = self.data.copy()
                            self.data[name] = None

        DAY_FIELDS = [
            "monday_start",
            "monday_end",
            "tuesday_start",
            "tuesday_end",
            "wednesday_start",
            "wednesday_end",
            "thursday_start",
            "thursday_end",
            "friday_start",
            "friday_end",
            "saturday_start",
            "saturday_end",
            "sunday_start",
            "sunday_end",
        ]

        style_day_time_cards(self.fields)

        # Show the quick-fill helper right above the per-day inputs
        ordered = [n for n in self.fields if n != "day_quick_fill"]
        ordered.insert(ordered.index("monday_start"), "day_quick_fill")
        self.order_fields(ordered)

        DAY_UI_FIELDS = DAY_FIELDS + ["day_quick_fill"]
        DEFAULT_FIELDS = ["default_start_time", "default_end_time"]
        TIMING_FIELDS = DEFAULT_FIELDS + ["timing_type"] + DAY_UI_FIELDS

        business_hour_type = initial.get("business_hour_type", "")
        custom_timing_type = initial.get("timing_type", "")

        if business_hour_type != "24_5" and not (
            business_hour_type == "custom" and custom_timing_type == "same"
        ):
            hide_fields(["week_days"], nullify=True)

        if business_hour_type != "custom":
            hide_fields(TIMING_FIELDS, nullify=True)
        else:
            custom_timing_type = initial.get("timing_type", "")
            if custom_timing_type != "same":
                hide_fields(DEFAULT_FIELDS, nullify=True)
            if custom_timing_type != "different":
                hide_fields(DAY_UI_FIELDS, nullify=True)

    def clean(self):
        cleaned_data = super().clean()

        company = cleaned_data.get("company")
        if company and cleaned_data and not self.instance.pk:
            cid = getattr(company, "id", None) or company
            limit = getattr(BusinessHour, "BUSINESS_HOUR_PER_COMPANY_LIMIT", 1)
            if BusinessHour.objects.filter(company_id=cid).count() >= limit:
                self.add_error(
                    None,
                    _("You can only add one business hour per company."),
                )

        if "week_days" in self.errors:
            choices = self.fields["week_days"].choices
            valid = [c[0] for c in choices]
            label_to_value = {str(c[1]): c[0] for c in choices}
            values = cleaned_data.get("week_days")
            if not isinstance(values, list):
                values = self.data.getlist("week_days") if self.data else []

            values = [label_to_value.get(v, v) for v in values]
            if values and all(v in valid for v in values):
                del self.errors["week_days"]
                cleaned_data["week_days"] = values

        def clear_fields(field_list):
            for field in field_list:
                cleaned_data[field] = None

        if cleaned_data.get("business_hour_type") != "custom":
            clear_fields(["timing_type"])

        if cleaned_data.get("business_hour_type") == "24_7":
            cleaned_data["week_days"] = [
                "sun",
                "mon",
                "tue",
                "wed",
                "thu",
                "fri",
                "sat",
            ]

        if cleaned_data.get("business_hour_type") == "24_5":
            week_days = cleaned_data.get("week_days") or []
            if len(week_days) > 5:
                self.add_error(
                    "week_days",
                    _("You can select a maximum of 5 days for 24x5 business hours."),
                )

        if cleaned_data.get("business_hour_type") == "custom":
            if cleaned_data.get("timing_type") == "same":
                week_days = cleaned_data.get("week_days") or []
                default_start = cleaned_data.get("default_start_time")
                default_end = cleaned_data.get("default_end_time")

                # Map short codes to full field names
                for short_code in week_days:
                    day = SHORT_TO_DAY_PREFIX.get(short_code)
                    if day:
                        cleaned_data[f"{day}_start"] = default_start
                        cleaned_data[f"{day}_end"] = default_end

            if cleaned_data.get("timing_type") == "different":
                week_days_selected = []
                for short, full in SHORT_TO_DAY_PREFIX.items():
                    start = cleaned_data.get(f"{full}_start")
                    end = cleaned_data.get(f"{full}_end")
                    if start and end:
                        week_days_selected.append(short)
                    elif start or end:
                        # A half-filled day would otherwise be silently saved as closed
                        self.add_error(
                            f"{full}_end" if start else f"{full}_start",
                            _("Enter both start and end time, or leave both empty."),
                        )

                cleaned_data["week_days"] = week_days_selected

        return cleaned_data


class RegionalFormattingForm(HorillaModelForm):
    """Form class for updating user's regional formatting settings."""

    field_order = [
        "date_format",
        "time_format",
        "date_time_format",
        "language",
        "time_zone",
        "currency",
        "number_format",
    ]

    fieldsets = (
        (
            _("Date Time Format"),
            {
                "fields": (
                    "date_time_format",
                    "date_format",
                    "time_format",
                ),
            },
        ),
        (
            _("Language and Time Zone"),
            {
                "fields": (
                    "language",
                    "time_zone",
                ),
            },
        ),
        (
            _("Currency"),
            {
                "fields": (
                    "currency",
                    "number_format",
                ),
            },
        ),
    )

    class Meta:
        """Meta options for RegionalFormattingForm."""

        model = User
        fields = [
            "date_format",
            "time_format",
            "date_time_format",
            "language",
            "time_zone",
            "currency",
            "number_format",
        ]

    def __init__(self, *args, **kwargs):
        """Set HTMX attributes on fields for auto-save on change."""
        super().__init__(*args, **kwargs)

        hx_post_url = reverse_lazy("core:regional_formating_view")

        for field in self.fields.values():
            if not isinstance(field.widget, forms.HiddenInput):
                field.widget.attrs.update(
                    {
                        "hx-post": hx_post_url,
                        "hx-trigger": "change",
                        "hx-target": "#messages-container",
                        "hx-swap": "innerHTML",
                        "hx-select": "#messages-container",
                    }
                )


class ChangePasswordForm(forms.Form):
    """Form for changing user password"""

    current_password = forms.CharField(
        widget=PasswordInputWithEye(attrs={"placeholder": _("Enter Current Password")}),
        label=_("Current Password"),
    )
    new_password = forms.CharField(
        widget=PasswordInputWithEye(attrs={"placeholder": _("Enter New Password")}),
        label=_("New Password"),
    )
    confirm_password = forms.CharField(
        widget=PasswordInputWithEye(attrs={"placeholder": _("Confirm Your Password")}),
        label=_("Confirm New Password"),
    )

    def __init__(self, user, *args, **kwargs):
        """Store user for current-password validation."""
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        """Validate that the current password is correct."""
        current_password = self.cleaned_data.get("current_password")
        if not self.user.check_password(current_password):
            self.add_error("current_password", _("Current password is incorrect."))
        return current_password

    def clean_new_password(self):
        """Validate new password using Django's password validators."""
        new_password = self.cleaned_data.get("new_password")
        if new_password:
            validate_password(new_password, user=self.user)
        return new_password

    def clean(self):
        """Validate new and confirm password match; ensure new differs from current."""
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password")
        confirm_password = cleaned_data.get("confirm_password")
        current_password = cleaned_data.get("current_password")

        if new_password and confirm_password:
            if new_password != confirm_password:
                self.add_error(
                    "confirm_password",
                    _("Confirm password and new password must be match"),
                )

            if current_password and new_password == current_password:
                self.add_error(
                    "new_password",
                    _("New password must be different from current password."),
                )

        return cleaned_data
