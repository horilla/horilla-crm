"""
Forms for managing company details, including multi-step forms for onboarding and single forms for editing company information.
"""

# Standard library imports
import logging

# Third-party imports (Django)
from django import forms

# First party imports (Horilla)
from horilla.contrib.generics.forms import HorillaModelForm, HorillaMultiStepForm

# First-party imports (Horilla)
from horilla.urls import reverse_lazy
from horilla.utils.choices import (
    get_subdivision_choices,
    limit_language_choices,
    resolve_subdivision_choice,
)
from horilla.utils.translation import gettext_lazy as _

# Local / relative imports
from ..mixins import OwnerQuerysetMixin
from ..models import Company

logger = logging.getLogger(__name__)

# Currency management settings are edited on the Currencies settings tab,
# not when creating or editing a company.
CURRENCY_SETTINGS_FIELDS = [
    "auto_fetch_exchange_rate",
    "keep_rate_history",
    "exchange_rate_source",
    "rates_last_refreshed",
    "auto_update_rates",
    "rate_refresh_frequency",
    "rate_change_alert_percent",
    "currency_rounding",
    "currency_display",
    "currency_symbol_position",
]


class CompanyMultistepFormClass(OwnerQuerysetMixin, HorillaMultiStepForm):
    """Form class for company model"""

    boolean_labels = {
        "activate_multiple_currencies": (_("Enable"), _("Disable")),
    }

    class Meta:
        """Meta options for CompanyMultistepFormClass."""

        model = Company
        fields = "__all__"
        exclude = CURRENCY_SETTINGS_FIELDS

    step_fields = {
        1: [
            "icon",
            "name",
            "email",
            "website",
            "contact_number",
            "fax",
        ],
        2: [
            "annual_revenue",
            "no_of_employees",
            "hq",
        ],
        3: [
            "country",
            "state",
            "city",
            "zip_code",
            "language",
            "time_zone",
        ],
        4: [
            "currency",
            "time_format",
            "date_format",
            "date_time_format",
            "activate_multiple_currencies",
        ],
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["country"].widget.attrs.update(
            {
                "hx-get": reverse_lazy("core:get_country_subdivisions"),
                "hx-target": "#id_state",
                "hx-trigger": "change",
                "hx-swap": "innerHTML",
            }
        )
        self.fields["state"] = forms.ChoiceField(
            choices=[],
            label=self._meta.model._meta.get_field("state").verbose_name,
            required=False,
            widget=forms.Select(
                attrs={"id": "id_state", "class": "js-example-basic-single headselect"}
            ),
        )

        if "country" in self.data:
            country_code = self.data.get("country")
            self.fields["state"].choices = get_subdivision_choices(country_code)
        elif self.instance.pk and self.instance.country:
            self.fields["state"].choices = get_subdivision_choices(
                self.instance.country.code
            )
            self.fields["state"].initial = resolve_subdivision_choice(
                self.fields["state"].choices, self.instance.state
            )

        limit_language_choices(self)


class CompanyFormClass(HorillaModelForm):
    """Form class for Company model."""

    boolean_labels = {
        "activate_multiple_currencies": (_("Enable"), _("Disable")),
    }

    class Meta:
        """Meta options for CompanyFormClass."""

        model = Company
        fields = [
            "name",
            "icon",
            "email",
            "contact_number",
            "country",
            "no_of_employees",
            "annual_revenue",
            "currency",
            "activate_multiple_currencies",
        ]


class CompanyFormClassSingle(HorillaModelForm):
    """Form class for Company model with all fields."""

    boolean_labels = {
        "activate_multiple_currencies": (_("Enable"), _("Disable")),
    }

    field_order = [
        "icon",
        "name",
        "email",
        "website",
        "contact_number",
        "fax",
        "annual_revenue",
        "no_of_employees",
        "country",
        "state",
        "city",
        "zip_code",
        "language",
        "time_zone",
        "currency",
        "time_format",
        "date_format",
        "date_time_format",
        "hq",
        "activate_multiple_currencies",
    ]

    class Meta:
        """Meta options for CompanyFormClassSingle."""

        model = Company
        fields = "__all__"
        exclude = CURRENCY_SETTINGS_FIELDS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["country"].widget.attrs.update(
            {
                "hx-get": reverse_lazy("core:get_country_subdivisions"),
                "hx-target": "#id_state",
                "hx-trigger": "change",
                "hx-swap": "innerHTML",
            }
        )

        self.fields["state"] = forms.ChoiceField(
            choices=[],
            label=self._meta.model._meta.get_field("state").verbose_name,
            required=False,
            widget=forms.Select(
                attrs={"id": "id_state", "class": "js-example-basic-single headselect"}
            ),
        )

        if "country" in self.data:
            country_code = self.data.get("country")
            self.fields["state"].choices = get_subdivision_choices(country_code)
        elif self.instance.pk and self.instance.country:
            self.fields["state"].choices = get_subdivision_choices(
                self.instance.country.code
            )
            self.fields["state"].initial = resolve_subdivision_choice(
                self.fields["state"].choices, self.instance.state
            )

        limit_language_choices(self)

    def clean(self):
        """Re-validate the language multi-select the generic form check rejects."""
        cleaned_data = super().clean()

        # The generic form validation compares the whole selection with a single
        # choice, so a valid multi-select is flagged (same as business-hour week_days).
        if "language" in self.errors:
            field = self.fields["language"]
            values = (
                self.data.getlist("language")
                if hasattr(self.data, "getlist")
                else self.data.get("language", [])
            )
            try:
                cleaned_data["language"] = field.clean(values)
            except forms.ValidationError:
                pass
            else:
                del self.errors["language"]

        return cleaned_data


class CompanyDetailsInlineForm(CompanyFormClassSingle):
    """Form used by the Details tab to edit the company profile in place."""

    fieldsets = (
        (
            _("Branch Information"),
            {
                "fields": (
                    "icon",
                    "name",
                    "email",
                    "website",
                    "contact_number",
                    "fax",
                    "no_of_employees",
                    "annual_revenue",
                )
            },
        ),
        (
            _("Address"),
            {"fields": ("country", "state", "city", "zip_code")},
        ),
        (
            _("Localization"),
            {"fields": ("time_zone", "language", "currency")},
        ),
    )

    class Meta:
        """Meta options for CompanyDetailsInlineForm."""

        model = Company
        fields = [
            "icon",
            "name",
            "email",
            "website",
            "contact_number",
            "fax",
            "no_of_employees",
            "annual_revenue",
            "city",
            "state",
            "country",
            "zip_code",
            "time_zone",
            "language",
            "currency",
        ]
