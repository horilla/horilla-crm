"""
Forms for managing multiple currencies and conversion rates in the company settings.
"""

# Standard library imports
import logging

# Third-party imports (Django)
from django import forms

from horilla.contrib.utils.middlewares import _thread_local, get_active_company

# First-party imports (Horilla)
from horilla.utils.translation import gettext_lazy as _

# Local / relative imports
from ..models import DatedConversionRate, MultipleCurrency

logger = logging.getLogger(__name__)


class CurrencyForm(forms.Form):
    """Form to add a new currency for the company."""

    currency = forms.ModelChoiceField(
        queryset=MultipleCurrency.objects.none(),
        empty_label=_("Select a currency"),
        label=_("New Currency"),
        required=True,
    )

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        request = getattr(_thread_local, "request", None)
        company = get_active_company(request)
        if company:
            self.fields["currency"].queryset = MultipleCurrency.objects.filter(
                company=company
            ).exclude(is_default=True)


class ConversionRateForm(forms.Form):
    """Form to update conversion rates and change default currency."""

    new_default_currency = forms.ModelChoiceField(
        queryset=MultipleCurrency.objects.none(),
        empty_label=_("Select a new default currency"),
        label=_("Change Default Currency"),
        required=False,
    )

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        request = getattr(_thread_local, "request", None)
        company = get_active_company(request) if request else company
        if company:
            current_default = MultipleCurrency.objects.filter(
                company=company, is_default=True
            ).first()
            other_currencies = MultipleCurrency.objects.filter(company=company).exclude(
                is_default=True
            )
            self.fields["new_default_currency"].queryset = (
                MultipleCurrency.objects.filter(company=company)
            )
            for currency in other_currencies:
                self.fields[f"conversion_rate_{currency.currency}"] = (
                    forms.DecimalField(
                        label=f"1 {current_default.currency if current_default else ''} = (conversion rate to {currency.currency})",
                        max_digits=10,
                        decimal_places=6,
                        required=True,
                        initial=currency.conversion_rate,
                    )
                )


class DatedConversionRateForm(forms.Form):
    """Form to add dated conversion rates for multiple currencies."""

    start_date = forms.DateField(
        label=_("Start Date"),
        help_text=_("Effective date for these conversion rates"),
        widget=forms.DateInput(attrs={"type": "date"}),
        required=True,
    )

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        if company:
            current_default = MultipleCurrency.objects.filter(
                company=company, is_default=True
            ).first()
            other_currencies = MultipleCurrency.objects.filter(company=company).exclude(
                is_default=True
            )
            for currency in other_currencies:
                self.fields[f"conversion_rate_{currency.currency}"] = (
                    forms.DecimalField(
                        label=f"1 {current_default.currency if current_default else ''} = (conversion rate to {currency.currency})",
                        max_digits=10,
                        decimal_places=6,
                        required=True,
                        initial=currency.conversion_rate,  # Initialize with the static rate as a fallback
                    )
                )

    def clean(self):
        """Validate conversion rates and start_date; check for duplicate DatedConversionRate."""
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        if start_date and self.company:
            for field_name in self.fields:
                if field_name.startswith("conversion_rate_"):
                    currency_code = field_name.replace("conversion_rate_", "")
                    # Get the MultipleCurrency object for the currency code
                    try:
                        currency_obj = MultipleCurrency.objects.get(
                            company=self.company, currency=currency_code
                        )
                    except MultipleCurrency.DoesNotExist:
                        self.add_error(
                            field_name,
                            f"Currency {currency_code} does not exist for this company.",
                        )
                        continue
                    # Check for existing DatedConversionRate with the same currency and start date
                    if DatedConversionRate.objects.filter(
                        company=self.company,
                        currency=currency_obj,  # Use the MultipleCurrency object
                        start_date=start_date,
                    ).exists():
                        self.add_error(
                            field_name,
                            f"A conversion rate for {currency_code} on {start_date} already exists.",
                        )
        return cleaned_data
