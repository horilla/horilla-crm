"""
This module defines the financial models for the Horilla platform
"""

# Standard library imports
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

# Third-party imports (Django)
from dateutil.relativedelta import relativedelta
from djmoney.settings import CURRENCY_CHOICES

from horilla.contrib.utils.methods import render_template

# First party imports (Horilla)
from horilla.db import models
from horilla.urls import reverse_lazy
from horilla.utils.choices import DAY_CHOICES, MONTH_CHOICES
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .base import Company, HorillaCoreModel


class MultipleCurrency(HorillaCoreModel):
    """
    Multiple Currency model
    """

    CACHE_NAMESPACE = "core.default_currency"

    currency = models.CharField(
        max_length=20,
        choices=CURRENCY_CHOICES,
        blank=True,
        null=True,
        help_text=_("Select your preferred currency"),
        verbose_name=_("Currency"),
    )
    conversion_rate = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        help_text=_("conversion rate from default currency"),
        verbose_name=_("Conversion Rate"),
    )
    decimal_places = models.IntegerField(default=2, verbose_name=_("Decimal Places"))
    is_default = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_("Default Currency"),
        help_text=_("Mark this currency as the default for the system"),
    )

    class Meta:
        """
        Meta options for the MultipleCurrency model.
        """

        verbose_name = _("Multiple Currency")
        verbose_name_plural = _("Multiple Currencies")

    def __str__(self):
        return str(self.currency)

    def get_currency_code(self):
        """
        Return currency code
        """
        return self.currency

    def save(self, *args, **kwargs):
        """
        Fixed save method to prevent recursion
        """

        # Prevent infinite recursion
        if hasattr(self, "_saving"):
            return super().save(*args, **kwargs)

        self._saving = True
        try:
            if self.is_default:
                MultipleCurrency.all_objects.filter(
                    company=self.company, is_default=True
                ).exclude(pk=self.pk).update(is_default=False)
                if self.company and self.company.currency != self.currency:
                    Company.objects.filter(pk=self.company.pk).update(
                        currency=self.currency
                    )
                    self.company.currency = self.currency

            super().save(*args, **kwargs)
            self.invalidate_default_currency_cache(self.company_id)
            return None

        finally:
            del self._saving

    def delete(self, *args, **kwargs):
        """Delete and drop the per-company default-currency cache entry."""
        company_id = self.company_id
        super().delete(*args, **kwargs)
        self.invalidate_default_currency_cache(company_id)

    @classmethod
    def invalidate_default_currency_cache(cls, company_id):
        """Drop the cached default currency for ``company_id``."""
        from horilla.contrib.utils.company_settings_cache import (
            invalidate_company_setting,
        )

        invalidate_company_setting(cls.CACHE_NAMESPACE, company_id)

    def get_conversion_rate_for_date(self, conversion_date=None):
        """
        Get the conversion rate for a specific date.
        If no date provided, use today's date.
        First checks DatedConversionRate, falls back to static conversion_rate.

        Args:
            conversion_date: The date to get the conversion rate for

        Returns:
            Decimal: The conversion rate
        """
        if conversion_date is None:
            conversion_date = date.today()

        # Try to get dated conversion rate
        dated_rate = (
            DatedConversionRate.objects.filter(
                company=self.company, currency=self, start_date__lte=conversion_date
            )
            .order_by("-start_date")
            .first()
        )

        if dated_rate:
            # Check if this rate is still valid (no newer rate exists before conversion_date)
            return dated_rate.conversion_rate

        # Fall back to static conversion rate
        return self.conversion_rate

    def format_amount(self, amount, user=None):
        """
        Format amount according to the currency's decimal places and the
        viewing user's preferred number format (HorillaUser.number_format).

        Supported formats:
        - western_format: 1,234,567.89 (comma thousand separator, dot decimal)
        - european_format: 1.234.567,89 (dot thousand separator, comma decimal)
        - space_format: 1 234 567,89 (space thousand separator, comma decimal)
        - indian_format: 12,34,567.89 (Indian grouping style)
        """
        if amount is None:
            # Return zero with correct decimal places
            if self.decimal_places <= 0:
                return "0"
            return "0." + "0" * self.decimal_places

        amount = Decimal(str(amount))
        quantize_string = "0." + "0" * self.decimal_places
        formatted_amount = amount.quantize(
            Decimal(quantize_string), rounding=ROUND_HALF_UP
        )

        number_format = getattr(user, "number_format", None) or "western_format"

        if number_format == "indian_format":
            amount_str = str(formatted_amount)
            parts = amount_str.split(".")
            integer_part = parts[0]
            decimal_part = parts[1] if len(parts) > 1 else "0" * self.decimal_places

            is_negative = integer_part.startswith("-")
            if is_negative:
                integer_part = integer_part[1:]

            if len(integer_part) > 3:
                last_three = integer_part[-3:]
                remaining = integer_part[:-3]
                groups = []
                while remaining:
                    groups.append(remaining[-2:])
                    remaining = remaining[:-2]
                grouped = ",".join(reversed(groups))
                integer_part = grouped + "," + last_three

            result = f"{integer_part}.{decimal_part}" if decimal_part else integer_part
            return f"-{result}" if is_negative else result

        # Western grouping (thousands of 3) as the common base
        western = f"{formatted_amount:,.{self.decimal_places}f}"

        if number_format == "european_format":
            # dot as thousand separator, comma as decimal
            return western.replace(",", "X").replace(".", ",").replace("X", ".")

        if number_format == "space_format":
            # space as thousand separator, comma as decimal
            return western.replace(",", " ").replace(".", ",")

        # western_format (default)
        return western

    def display_with_symbol(self, amount, user=None):
        """Display amount with currency symbol - Example: USD 100.00"""
        formatted = self.format_amount(amount, user=user)
        return f"{self.currency} {formatted}"

    def convert_from_default(self, amount, conversion_date=None):
        """
        Convert amount from default currency to this currency.
        Uses dated conversion rate if available.

        Args:
            amount: Amount to convert
            conversion_date: Date for conversion rate lookup
        """
        if amount is None:
            return Decimal("0")

        rate = self.get_conversion_rate_for_date(conversion_date)
        return Decimal(str(amount)) * rate

    def convert_to_default(self, amount, conversion_date=None):
        """
        Convert amount from this currency to default currency.
        Uses dated conversion rate if available.

        Args:
            amount: Amount to convert
            conversion_date: Date for conversion rate lookup
        """
        if amount is None:
            return Decimal("0")

        rate = self.get_conversion_rate_for_date(conversion_date)
        if rate == 0:
            return Decimal("0")

        return Decimal(str(amount)) / rate

    @staticmethod
    def get_default_currency(company):
        """Get the default currency for a company (cached per company)."""
        from horilla.contrib.utils.company_settings_cache import (
            get_or_set_company_setting,
        )
        from horilla.contrib.utils.middlewares import _thread_local

        if not company:
            return None

        company_id = getattr(company, "pk", company)
        request = getattr(_thread_local, "request", None)
        cache_attr = "_default_currency_cache"
        if request is not None:
            cached = getattr(request, cache_attr, None)
            if cached is None:
                cached = {}
                setattr(request, cache_attr, cached)
            if company_id in cached:
                return cached[company_id]

        try:
            currency = get_or_set_company_setting(
                MultipleCurrency.CACHE_NAMESPACE,
                company_id,
                lambda: MultipleCurrency.all_objects.filter(
                    company_id=company_id, is_default=True
                ).first(),
            )
        except Exception:
            currency = None

        if request is not None:
            cached[company_id] = currency
        return currency

    @staticmethod
    def get_user_currency(user):
        """Get user's preferred currency - falls back to company default"""
        if not user or not user.is_authenticated:
            return None

        if hasattr(user, "currency") and user.currency:
            return user.currency

        if hasattr(user, "company") and user.company:
            return MultipleCurrency.get_default_currency(user.company)

        return None

    def is_default_col(self):
        """Returns the rendered HTML for the is_default column in the list view."""
        total_currencies = MultipleCurrency.objects.count()
        html = render_template(
            "multiple_currency/is_default_col.html",
            {"instance": self, "total_currencies": total_currencies},
        )
        return html

    def get_edit_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy("core:edit_currency", kwargs={"pk": self.pk})

    def get_delete_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy("core:delete_currency", kwargs={"pk": self.pk})


class DatedConversionRate(HorillaCoreModel):
    """
    Model to store dated conversion rates for a currency and company.
    """

    currency = models.ForeignKey(
        MultipleCurrency,
        on_delete=models.CASCADE,
        related_name="dated_conversion_rates",
        verbose_name=_("Currency"),
    )
    conversion_rate = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        help_text=_("Conversion rate from default currency"),
        verbose_name=_("Conversion Rate"),
    )
    start_date = models.DateField(
        verbose_name=_("Start Date"),
        help_text=_("The date from which this conversion rate is effective"),
    )

    class Meta:
        """
        Meta options for the DatedConversionRate model.
        """

        verbose_name = _("Dated Conversion Rate")
        verbose_name_plural = _("Dated Conversion Rates")
        unique_together = (
            "company",
            "currency",
            "start_date",
        )  # Prevent duplicate rates for same currency and date
        ordering = ["currency", "start_date"]

    def __str__(self):
        return f"{self.currency} - {self.conversion_rate} from {self.start_date}"

    def get_edit_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy("core:edit_dated_conversion_rate", kwargs={"pk": self.pk})

    def get_delete_url(self):
        """
        This method to get delete url
        """
        return reverse_lazy("core:delete_dated_conversion_rate", kwargs={"pk": self.pk})

    def get_end_date(self):
        """
        Returns the end date for this rate, which is the start date of the next rate for the same currency and company,
        or None if this is the latest rate.
        """
        next_rate = (
            DatedConversionRate.objects.filter(
                company=self.company,
                currency=self.currency,
                start_date__gt=self.start_date,
            )
            .order_by("start_date")
            .first()
        )
        return next_rate.start_date if next_rate else None

    def save(self, *args, **kwargs):
        """
        Validate that the start_date doesn't overlap inappropriately.
        """
        # Check for existing rates with same currency and company
        existing_rates = DatedConversionRate.objects.filter(
            company=self.company, currency=self.currency
        ).exclude(pk=self.pk)

        for rate in existing_rates:
            if rate.start_date == self.start_date:
                raise ValueError(
                    f"A conversion rate for {self.currency} already exists on {self.start_date}."
                )

        super().save(*args, **kwargs)


class FiscalYear(HorillaCoreModel):
    """
    Model for managing fiscal year configurations
    """

    fiscal_year_type = models.CharField(
        max_length=20,
        choices=[
            ("standard", _("Standard Fiscal Year")),
            ("custom", _("Custom Fiscal Year")),
        ],
        verbose_name=_("Fiscal Year Type"),
    )
    format_type = models.CharField(
        max_length=20,
        choices=[
            ("year_based", _("Year Based")),
            ("quarter_based", _("Quarter Based")),
        ],
        verbose_name=_("Format"),
        null=True,
        blank=True,
    )
    quarter_based_format = models.CharField(
        max_length=50,
        choices=[
            (
                "4-4-5",
                _(
                    "4-4-5 In each quarter, Period 1 has 4 weeks, Period 2 has 4 weeks, Period 3 has 5 weeks"
                ),
            ),
            (
                "4-5-4",
                _(
                    "4-5-4 In each quarter, Period 1 has 4 weeks, Period 2 has 5 weeks, Period 3 has 4 weeks"
                ),
            ),
            (
                "5-4-4",
                _(
                    "5-4-4 In each quarter, Period 1 has 5 weeks, Period 2 has 4 weeks, Period 3 has 4 weeks"
                ),
            ),
        ],
        blank=True,
        null=True,
        verbose_name=_("Quarter Based Format"),
    )
    year_based_format = models.CharField(
        max_length=50,
        choices=[
            (
                "3-3-3-4",
                _(
                    "3-3-3-4 Quarter 1 has 3 Periods, Quarter 2 has 3 Periods, Quarter 3 has 3 Periods, Quarter 4 has 4 Periods"
                ),
            ),
            (
                "3-3-4-3",
                _(
                    "3-3-4-3 Quarter 1 has 3 Periods, Quarter 2 has 3 Periods, Quarter 3 has 4 Periods, Quarter 4 has 3 Periods"
                ),
            ),
            (
                "3-4-3-3",
                _(
                    "3-4-3-3 Quarter 1 has 3 Periods, Quarter 2 has 4 Periods, Quarter 3 has 3 Periods, Quarter 4 has 3 Periods"
                ),
            ),
            (
                "4-3-3-3",
                _(
                    "4-3-3-3 Quarter 1 has 4 Periods, Quarter 2 has 3 Periods, Quarter 3 has 3 Periods, Quarter 4 has 3 Periods"
                ),
            ),
        ],
        blank=True,
        null=True,
        verbose_name=_("Year Based Format"),
    )

    start_date_month = models.CharField(
        max_length=20,
        choices=MONTH_CHOICES,
        verbose_name=_("Start Date Month"),
    )
    start_date_day = models.PositiveIntegerField(
        default=1, verbose_name=_("Start Date Day")
    )
    week_start_day = models.CharField(
        max_length=20,
        choices=DAY_CHOICES,
        verbose_name=_("Week Start Day"),
        blank=True,
        null=True,
    )
    display_year_based_on = models.CharField(
        max_length=20,
        choices=[
            ("starting_year", _("Starting Year")),
            ("ending_year", _("Ending Year")),
        ],
        verbose_name=_("Display Fiscal Year Based On"),
        default="starting_year",
    )
    number_weeks_by = models.CharField(
        max_length=20,
        choices=[
            ("year", _("Year")),
            ("quarter", _("Quarter")),
            ("period", _("Period")),
        ],
        verbose_name=_("Number Weeks By"),
        blank=True,
        null=True,
    )
    period_display_option = models.CharField(
        max_length=20,
        choices=[
            ("number_by_year", _("Number by Year")),
            ("number_by_quarter", _("Number by Quarter")),
        ],
        verbose_name=_("Period Display Option"),
        blank=True,
        null=True,
    )

    def get_month_ranges(self):
        """Calculate month ranges for quarters based on start_date_month"""
        if not self.start_date_month:
            return []

        months = [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ]
        start_index = months.index(self.start_date_month)
        quarter_ranges = []

        for _i in range(4):
            quarter_start = months[start_index % 12]
            quarter_end = months[(start_index + 2) % 12]
            quarter_ranges.append(
                f"{quarter_start.capitalize()} - {quarter_end.capitalize()}"
            )
            start_index = (start_index + 3) % 12

        return quarter_ranges

    def get_periods_by_format(self):
        """
        Return periods per year and per quarter based on the selected format.
        This is now the single source of truth for all period calculations.
        """
        base_config = {
            "number_weeks_by": self.number_weeks_by,
            "period_display_option": self.period_display_option,
            "month_ranges": self.get_month_ranges() if self.start_date_month else [],
        }

        if self.fiscal_year_type == "standard":
            return {
                "periods_per_year": 12,
                "quarter_1_periods": 3,
                "quarter_2_periods": 3,
                "quarter_3_periods": 3,
                "quarter_4_periods": 3,
                "weeks_per_period": 4,
                **base_config,
            }
        if (
            self.fiscal_year_type == "custom"
            and self.format_type == "year_based"
            and self.year_based_format
        ):
            periods = self.year_based_format.split("-")
            periods = [int(p) for p in periods]
            total_periods = sum(periods)

            return {
                "periods_per_year": total_periods,
                "quarter_1_periods": periods[0],
                "quarter_2_periods": periods[1],
                "quarter_3_periods": periods[2],
                "quarter_4_periods": periods[3],
                "weeks_per_period": 4,
                **base_config,
            }
        if (
            self.fiscal_year_type == "custom"
            and self.format_type == "quarter_based"
            and self.quarter_based_format
        ):
            weeks = self.quarter_based_format.split("-")
            weeks = [int(w) for w in weeks]

            return {
                # Always 12 for quarter-based (3 per quarter)
                "periods_per_year": 12,
                "quarter_1_periods": 3,
                "quarter_2_periods": 3,
                "quarter_3_periods": 3,
                "quarter_4_periods": 3,
                "weeks_per_period_pattern": weeks,
                "total_weeks_per_quarter": sum(weeks),
                **base_config,
            }

        # Fallback to standard if no specific format
        return {
            "periods_per_year": 12,
            "quarter_1_periods": 3,
            "quarter_2_periods": 3,
            "quarter_3_periods": 3,
            "quarter_4_periods": 3,
            "weeks_per_period": 4,
            **base_config,
        }

    STRUCTURE_FIELDS = (
        "fiscal_year_type",
        "format_type",
        "quarter_based_format",
        "year_based_format",
        "start_date_month",
        "start_date_day",
        "display_year_based_on",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._structure_snapshot = self.get_structure_snapshot()

    def get_structure_snapshot(self):
        """
        Values that decide the stored years, quarters and periods. Week start
        day, number weeks by and period display option only affect the calendar
        preview, which is computed on the fly, so they are not tracked.
        """
        return tuple(self.__dict__.get(name) for name in self.STRUCTURE_FIELDS)

    def structure_changed(self):
        """True when a structural field differs from the value loaded from the database."""
        return self.get_structure_snapshot() != self._structure_snapshot

    def save(self, *args, **kwargs):
        """Override save to handle format-specific logic"""
        if self.fiscal_year_type == "standard":
            # Clear custom format fields for standard type
            self.format_type = None
            self.year_based_format = None
            self.quarter_based_format = None
            self.week_start_day = None
            self.number_weeks_by = None
            self.period_display_option = None
            # Standard years always start on the 1st; the form hides the day,
            # so a value left over from a custom year must not be kept.
            self.start_date_day = 1

        super().save(*args, **kwargs)

    def __str__(self):
        current_year = datetime.now().year
        return f"{self.get_start_date_month_display()} {self.start_date_day} - {current_year}"

    class Meta:
        """
        Meta options for the FiscalYear model.
        """

        verbose_name = _("Fiscal Year")
        verbose_name_plural = _("Fiscal Years")
        constraints = [
            models.UniqueConstraint(
                fields=["company"], name="unique_fiscal_year_per_company"
            )
        ]


class FiscalYearInstance(HorillaCoreModel):
    """
    Represents an actual fiscal year instance based on configuration
    """

    fiscal_year_config = models.ForeignKey(
        FiscalYear,
        on_delete=models.CASCADE,
        related_name="year_instances",
        verbose_name=_("Fiscal Year Configuration"),
    )
    start_date = models.DateField(verbose_name=_("Start Date"))
    end_date = models.DateField(verbose_name=_("End Date"))
    name = models.CharField(max_length=100, verbose_name=_("Fiscal Year Name"))
    is_current = models.BooleanField(default=False, verbose_name=_("Is Current"))

    def __str__(self):
        return str(self.name)

    class Meta:
        """
        Meta options for the FiscalYearInstance model.
        """

        verbose_name = _("Fiscal Year Instance")
        verbose_name_plural = _("Fiscal Year Instances")


class Quarter(HorillaCoreModel):
    """
    Represents a quarter within a fiscal year
    """

    fiscal_year = models.ForeignKey(
        FiscalYearInstance,
        on_delete=models.CASCADE,
        related_name="quarters",
        verbose_name=_("Fiscal Year"),
    )
    name = models.CharField(max_length=100, verbose_name=_("Quarter Name"))
    quarter_number = models.PositiveIntegerField(verbose_name=_("Quarter Number"))
    start_date = models.DateField(verbose_name=_("Start Date"))
    end_date = models.DateField(verbose_name=_("End Date"))
    is_current = models.BooleanField(default=False, verbose_name=_("Is Current"))

    def __str__(self):
        return f"{self.fiscal_year.name} - {self.name}"

    class Meta:
        """
        Meta options for the Quarter model.
        """

        verbose_name = _("Quarter")
        verbose_name_plural = _("Quarters")


class Period(HorillaCoreModel):
    """
    Represents a period within a quarter
    """

    quarter = models.ForeignKey(
        Quarter,
        on_delete=models.CASCADE,
        related_name="periods",
        verbose_name=_("Quarter"),
    )
    name = models.CharField(max_length=100, verbose_name=_("Period Name"))
    period_number = models.PositiveIntegerField(verbose_name=_("Period Number"))
    start_date = models.DateField(verbose_name=_("Start Date"))
    end_date = models.DateField(verbose_name=_("End Date"))
    is_current = models.BooleanField(default=False, verbose_name=_("Is Current"))

    def get_period_number_in_quarter(self):
        """
        Calculate the period number within the quarter dynamically
        """
        periods_in_quarter = Period.objects.filter(quarter=self.quarter).order_by(
            "period_number"
        )

        for index, period in enumerate(periods_in_quarter, 1):
            if period.id == self.id:
                return index
        return 1  # Fallback

    def get_display_period_number(self):
        """
        Get the period number based on the fiscal year's period_display_option
        """
        fiscal_config = self.quarter.fiscal_year.fiscal_year_config

        if fiscal_config.period_display_option == "number_by_quarter":
            return self.get_period_number_in_quarter()

        return self.period_number

    def save(self, *args, **kwargs):
        """
        Override save to set period number and dates based on fiscal year type.
        Period numbers start from 1 for each fiscal year.
        """
        # Skip auto-calculation if period_number is already set (e.g., from service)
        skip_auto_calculation = kwargs.pop("skip_auto_calculation", False)

        if (
            not self.pk and not skip_auto_calculation
        ):  # Only for new instances without explicit number
            fiscal_config = self.quarter.fiscal_year.fiscal_year_config

            if fiscal_config.fiscal_year_type == "standard":
                # For standard type, create periods based on calendar months
                self._create_standard_period()
            else:
                # For custom type, use the existing logic
                self._create_custom_period()

        super().save(*args, **kwargs)

        # Update name after saving (when we have an ID)
        if not hasattr(self, "_name_updated"):
            self._update_period_name()

    def _create_standard_period(self):
        """
        Create period for standard fiscal year type based on calendar months.
        Period numbers start from 1 for each fiscal year.
        """

        fiscal_config = self.quarter.fiscal_year.fiscal_year_config
        fiscal_year = self.quarter.fiscal_year

        # Calculate period number within THIS fiscal year only
        existing_periods_in_year = Period.objects.filter(
            quarter__fiscal_year=fiscal_year
        ).count()

        self.period_number = existing_periods_in_year + 1

        # Get the start month index
        months = [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ]
        start_month_index = months.index(fiscal_config.start_date_month.lower())

        # Calculate the month for this period
        period_month_index = (start_month_index + self.period_number - 1) % 12

        # Determine the year for this period
        if period_month_index < start_month_index:
            # We've crossed into the next calendar year
            period_year = fiscal_year.start_date.year + 1
        else:
            period_year = fiscal_year.start_date.year

        # Set start date to first day of the month
        self.start_date = datetime(
            year=period_year,
            month=period_month_index + 1,
            day=fiscal_config.start_date_day,
        ).date()

        # Set end date to last day of the month
        next_month = self.start_date + relativedelta(months=1)
        self.end_date = next_month - timedelta(days=1)

        # Set period name as month name
        self.name = f"{months[period_month_index].capitalize()} {period_year}"

    def _create_custom_period(self):
        """
        Create period for custom fiscal year type.
        Period numbers start from 1 for each fiscal year.
        """
        _fiscal_config = self.quarter.fiscal_year.fiscal_year_config

        # Only count periods in previous quarters within THIS fiscal year
        previous_quarters = Quarter.objects.filter(
            fiscal_year=self.quarter.fiscal_year,
            quarter_number__lt=self.quarter.quarter_number,
        )

        periods_before_this_quarter = Period.objects.filter(
            quarter__in=previous_quarters
        ).count()

        # Count existing periods in current quarter
        existing_periods_in_current_quarter = Period.objects.filter(
            quarter=self.quarter
        ).count()

        # Period number within the fiscal year (starts from 1)
        self.period_number = (
            periods_before_this_quarter + existing_periods_in_current_quarter + 1
        )

    def _update_period_name(self):
        """
        Update period name based on fiscal year type and display option
        """
        fiscal_config = self.quarter.fiscal_year.fiscal_year_config

        if fiscal_config.fiscal_year_type == "standard":
            # For standard type, name is already set in _create_standard_period
            return

        # For custom type, use period numbering
        if fiscal_config.period_display_option == "number_by_quarter":
            new_name = f"Period {self.get_period_number_in_quarter()}"
        else:  # 'number_by_year' or default
            new_name = f"Period {self.period_number}"

        if self.name != new_name:
            self.name = new_name
            self._name_updated = True
            super().save(update_fields=["name"])

    def __str__(self):
        fiscal_config = self.quarter.fiscal_year.fiscal_year_config
        display_number = self.get_display_period_number()

        if fiscal_config.period_display_option == "number_by_quarter":
            return f"{self.quarter.fiscal_year.name} - {self.quarter.name} - Period {display_number}"

        return f"{self.quarter.fiscal_year.name} - Period {display_number}"

    class Meta:
        """
        Meta options for the Period model.
        """

        verbose_name = _("Period")
        verbose_name_plural = _("Periods")
