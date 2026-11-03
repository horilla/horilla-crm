"""
Fiscal year service module for managing fiscal year operations.

This module provides the FiscalYearService class which handles:
- Creating and managing fiscal year configurations
- Generating fiscal years, quarters, and periods
- Managing fiscal year transitions and updates
- Validating fiscal year configurations
"""

# Standard library imports
from datetime import datetime, timedelta

# Third-party imports (Others)
from dateutil.relativedelta import relativedelta

# First party imports (Horilla)
from horilla.apps import apps
from horilla.db import transaction
from horilla.db.models import CASCADE
from horilla.utils import timezone

# Local imports
from ..models import FiscalYear


def fast_cascade_delete(queryset):
    """
    Delete ``queryset`` and everything cascading from it with one SQL DELETE per
    table instead of loading every row, which is slow for forecasts and targets.
    Falls back to the normal delete when a relation is not a plain cascade.
    """
    model = queryset.model
    relations = list(model._meta.related_objects)
    if any(rel.on_delete is not CASCADE or rel.many_to_many for rel in relations):
        queryset.delete()
        return
    for rel in relations:
        children = rel.related_model._base_manager.filter(
            **{f"{rel.field.name}__in": queryset.values("pk")}
        )
        fast_cascade_delete(children)
    queryset._raw_delete(queryset.db)


class FiscalYearService:
    """
    Service class for handling fiscal year operations including:
    - Creating default configurations
    - Generating fiscal years, quarters, and periods
    - Managing fiscal year transitions
    """

    @staticmethod
    def get_or_create_company_configuration(company):
        """
        Safely get or create fiscal year configuration
        """
        try:
            return FiscalYear.objects.get(company=company)
        except FiscalYear.DoesNotExist:
            config = FiscalYear(
                company=company,
                fiscal_year_type="standard",
                start_date_month="january",
                start_date_day=1,
                display_year_based_on="starting_year",
            )
            config.save()
            return config

    @staticmethod
    def generate_fiscal_years(config, years_ahead=1):
        """
        Generate current and next fiscal years based on configuration
        """
        FiscalYearInstance = apps.get_model("core", "FiscalYearInstance")
        _Quarter = apps.get_model("core", "Quarter")
        _Period = apps.get_model("core", "Period")

        current_year = timezone.now().year
        years_to_generate = [current_year, current_year + 1]

        month_number = {
            "january": 1,
            "february": 2,
            "march": 3,
            "april": 4,
            "may": 5,
            "june": 6,
            "july": 7,
            "august": 8,
            "september": 9,
            "october": 10,
            "november": 11,
            "december": 12,
        }.get(config.start_date_month.lower(), 1)

        with transaction.atomic():
            # Delete inside the transaction so a failed rebuild rolls back and
            # keeps the previous instances instead of leaving none.
            fast_cascade_delete(
                FiscalYearInstance.all_objects.filter(company=config.company)
            )
            previous_end_date = None

            for i, year in enumerate(years_to_generate):
                # For the first year, use the configured start date
                if i == 0:
                    start_date = datetime(
                        year, month_number, config.start_date_day
                    ).date()
                else:
                    # For subsequent years, start the day after the previous year ends
                    start_date = previous_end_date + timedelta(days=1)

                if config.fiscal_year_type == "standard":
                    end_date = start_date + relativedelta(years=1) - timedelta(days=1)
                else:
                    end_date = start_date + relativedelta(years=1) - timedelta(days=2)

                if config.display_year_based_on == "starting_year":
                    name = f"FY {year}"
                else:
                    name = f"FY {year + 1}"

                fiscal_year, created = FiscalYearInstance.objects.get_or_create(
                    company=config.company,
                    fiscal_year_config=config,
                    start_date=start_date,
                    defaults={
                        "end_date": end_date,
                        "name": name,
                        "is_current": year == current_year,
                        "is_active": True,
                    },
                )

                if not created:
                    fiscal_year.company = config.company
                    fiscal_year.end_date = end_date
                    fiscal_year.name = name
                    fiscal_year.is_current = year == current_year
                    fiscal_year.save()

                # Store the end date for the next iteration
                previous_end_date = end_date

                # Generate quarters - PASS periods_info here
                periods_info = config.get_periods_by_format()
                FiscalYearService._generate_quarters(config, fiscal_year, periods_info)

    @staticmethod
    def _generate_quarters(config, fiscal_year, periods_info):
        """
        Generate quarters for a fiscal year
        """
        Quarter = apps.get_model("core", "Quarter")

        quarter_durations = FiscalYearService._calculate_quarter_dates(
            fiscal_year.start_date, fiscal_year.end_date, config, periods_info
        )

        # Track total periods created across all quarters
        cumulative_period_count = 0

        for i, (q_start, q_end) in enumerate(quarter_durations, start=1):
            quarter_name = f"Q{i}"

            quarter, created = Quarter.objects.get_or_create(
                company=fiscal_year.company,
                fiscal_year=fiscal_year,
                quarter_number=i,
                defaults={
                    "name": quarter_name,
                    "start_date": q_start,
                    "end_date": q_end,
                    "is_active": True,
                },
            )

            if not created:
                quarter.company = fiscal_year.company
                quarter.start_date = q_start
                quarter.end_date = q_end
                quarter.save()

            # Generate periods for this quarter and update the cumulative count
            cumulative_period_count = FiscalYearService._generate_periods(
                config, quarter, periods_info, cumulative_period_count
            )

    @staticmethod
    def _calculate_quarter_dates(start_date, end_date, config=None, periods_info=None):
        """
        Calculate quarter dates based on fiscal year configuration
        """
        quarters = []

        if config and config.format_type == "quarter_based":
            quarter_duration = 91  # 13 weeks * 7 days
            current_start = start_date

            for i in range(4):
                if i < 3:
                    current_end = current_start + timedelta(days=quarter_duration - 1)
                else:
                    current_end = end_date

                quarters.append((current_start, current_end))
                current_start = current_end + timedelta(days=1)

        elif config and config.format_type == "year_based":
            if periods_info:
                current_start = start_date

                for quarter_num in range(1, 5):
                    quarter_periods = FiscalYearService._get_quarter_periods(
                        config, quarter_num, periods_info
                    )

                    # Each period in year-based is 4 weeks = 28 days
                    quarter_days = quarter_periods * 28

                    if quarter_num < 4:
                        current_end = current_start + timedelta(days=quarter_days - 1)
                    else:
                        # Last quarter ends at fiscal year end
                        current_end = end_date

                    quarters.append((current_start, current_end))
                    current_start = current_end + timedelta(days=1)

        else:
            current_start = start_date

            for i in range(4):
                if i < 3:
                    current_end = (
                        current_start + relativedelta(months=3) - timedelta(days=1)
                    )
                else:
                    current_end = end_date

                quarters.append((current_start, current_end))
                current_start = current_end + timedelta(days=1)

        return quarters

    @staticmethod
    def _generate_periods(config, quarter, periods_info, starting_period_number):
        """
        Generate periods for a quarter based on configuration.
        Period numbers start from 1 for each fiscal year and increment sequentially.

        Args:
            config: Fiscal year configuration
            quarter: Quarter instance
            periods_info: Period configuration details
            starting_period_number: The period number to start from (cumulative count from previous quarters)

        Returns:
            The updated cumulative period count after creating this quarter's periods
        """
        Period = apps.get_model("core", "Period")

        # Get the number of periods for this quarter based on configuration
        quarter_periods = FiscalYearService._get_quarter_periods(
            config, quarter.quarter_number, periods_info
        )

        # Special handling for STANDARD fiscal year:
        # periods should align with calendar months, not equal day splits.
        if config.fiscal_year_type == "standard":
            current_start = quarter.start_date

            for i in range(1, quarter_periods + 1):
                # Calculate natural month end for the current_start month
                month_end = current_start + relativedelta(months=1) - timedelta(days=1)

                # For all but the last period in the quarter, stop at month end
                # For the last period, ensure we don't go past the quarter end date
                if i < quarter_periods and month_end < quarter.end_date:
                    current_end = month_end
                else:
                    current_end = quarter.end_date

                fiscal_year_period_number = starting_period_number + i

                # Name period based on month name and year (e.g., "January 2026")
                period_name = f"{current_start.strftime('%B')} {current_start.year}"

                try:
                    period = Period.objects.get(
                        company=quarter.company,
                        quarter=quarter,
                        period_number=fiscal_year_period_number,
                    )
                    period.name = period_name
                    period.start_date = current_start
                    period.end_date = current_end
                    period.save(skip_auto_calculation=True)
                except Period.DoesNotExist:
                    period = Period(
                        company=quarter.company,
                        quarter=quarter,
                        period_number=fiscal_year_period_number,
                        name=period_name,
                        start_date=current_start,
                        end_date=current_end,
                        is_active=True,
                    )
                    period.save(skip_auto_calculation=True)

                current_start = current_end + timedelta(days=1)

        # Handle quarter-based formats (4-4-5, 4-5-4, 5-4-4)
        elif (
            config.format_type == "quarter_based"
            and "weeks_per_period_pattern" in periods_info
        ):
            weeks_pattern = periods_info["weeks_per_period_pattern"]
            current_start = quarter.start_date

            for i, weeks in enumerate(weeks_pattern, 1):
                period_days = weeks * 7
                current_end = current_start + timedelta(days=period_days - 1)

                # Last period in quarter ends at quarter end date
                if i == len(weeks_pattern):
                    current_end = quarter.end_date

                # Period number within the fiscal year (incremental)
                fiscal_year_period_number = starting_period_number + i

                # Name based on fiscal year period number
                period_name = f"Period {fiscal_year_period_number}"

                # Create or update period with explicit period_number
                try:
                    period = Period.objects.get(
                        company=quarter.company,
                        quarter=quarter,
                        period_number=fiscal_year_period_number,
                    )
                    # Update existing period
                    period.name = period_name
                    period.start_date = current_start
                    period.end_date = current_end
                    period.save(skip_auto_calculation=True)
                except Period.DoesNotExist:
                    # Create new period with explicit save to bypass auto-calculation
                    period = Period(
                        company=quarter.company,
                        quarter=quarter,
                        period_number=fiscal_year_period_number,
                        name=period_name,
                        start_date=current_start,
                        end_date=current_end,
                        is_active=True,
                    )
                    period.save(skip_auto_calculation=True)

                current_start = current_end + timedelta(days=1)

        # Handle year-based formats
        else:
            if config.format_type == "year_based":
                # For year-based, each period is 4 weeks = 28 days
                period_duration = 28
            else:
                # Fallback: divide quarter equally
                quarter_duration = (quarter.end_date - quarter.start_date).days + 1
                period_duration = quarter_duration // quarter_periods

            current_start = quarter.start_date

            for i in range(1, quarter_periods + 1):
                if i < quarter_periods:
                    current_end = current_start + timedelta(days=period_duration - 1)
                else:
                    # Last period ends at quarter end
                    current_end = quarter.end_date

                # Period number within the fiscal year (incremental)
                fiscal_year_period_number = starting_period_number + i

                # Name based on fiscal year period number
                period_name = f"Period {fiscal_year_period_number}"

                # Create or update period with explicit period_number
                try:
                    period = Period.objects.get(
                        company=quarter.company,
                        quarter=quarter,
                        period_number=fiscal_year_period_number,
                    )
                    # Update existing period
                    period.name = period_name
                    period.start_date = current_start
                    period.end_date = current_end
                    period.save(skip_auto_calculation=True)
                except Period.DoesNotExist:
                    # Create new period with explicit save to bypass auto-calculation
                    period = Period(
                        company=quarter.company,
                        quarter=quarter,
                        period_number=fiscal_year_period_number,
                        name=period_name,
                        start_date=current_start,
                        end_date=current_end,
                        is_active=True,
                    )
                    period.save(skip_auto_calculation=True)

                current_start = current_end + timedelta(days=1)

        # Return the updated cumulative count
        return starting_period_number + quarter_periods

    @staticmethod
    def _get_quarter_periods(config, quarter_number, periods_info):
        """
        Get the number of periods for a specific quarter
        """
        # Use the property methods or direct calculation
        return periods_info.get(f"quarter_{quarter_number}_periods", 3)

    @staticmethod
    def get_current_fiscal_year(company):
        """
        Get the current fiscal year for a company
        """
        FiscalYearInstance = apps.get_model("core", "FiscalYearInstance")
        try:
            return FiscalYearInstance.objects.get(company=company, is_current=True)
        except FiscalYearInstance.DoesNotExist:
            return None

    @staticmethod
    def get_current_quarter(company):
        """
        Get the current quarter for a company
        """
        Quarter = apps.get_model("core", "Quarter")
        current_date = timezone.now().date()

        try:
            return Quarter.objects.get(
                company=company,
                start_date__lte=current_date,
                end_date__gte=current_date,
            )
        except Quarter.DoesNotExist:
            return None

    @staticmethod
    def get_current_period(company):
        """
        Get the current period for a company
        """
        Period = apps.get_model("core", "Period")
        current_date = timezone.now().date()

        try:
            return Period.objects.get(
                company=company,
                start_date__lte=current_date,
                end_date__gte=current_date,
            )
        except Period.DoesNotExist:
            return None

    @staticmethod
    def regenerate_fiscal_years(config):
        """
        Regenerate all fiscal years for a configuration
        Useful when format changes
        """
        FiscalYearInstance = apps.get_model("core", "FiscalYearInstance")

        # Delete existing instances and related data
        FiscalYearInstance.objects.filter(fiscal_year_config=config).delete()

        # Regenerate
        FiscalYearService.generate_fiscal_years(config)

    @staticmethod
    def validate_fiscal_year_config(config):
        """
        Validate fiscal year configuration
        """
        errors = []

        if config.fiscal_year_type == "custom":
            if not config.format_type:
                errors.append("Format type is required for custom fiscal year")

            if config.format_type == "year_based" and not config.year_based_format:
                errors.append(
                    "Year based format is required when format type is year_based"
                )

            if (
                config.format_type == "quarter_based"
                and not config.quarter_based_format
            ):
                errors.append(
                    "Quarter based format is required when format type is quarter_based"
                )

        if not config.start_date_month:
            errors.append("Start date month is required")

        if (
            not config.start_date_day
            or config.start_date_day < 1
            or config.start_date_day > 31
        ):
            errors.append("Start date day must be between 1 and 31")

        return errors

    @staticmethod
    def check_and_update_fiscal_years(company=None):
        """
        Check and update fiscal years automatically.
        This method:
        1. Checks if current fiscal year has ended
        2. Updates is_current flag if needed
        3. Creates next fiscal year if it doesn't exist
        4. Generates quarters and periods for new fiscal years

        Args:
            company: Optional company instance. If None, checks all companies.

        Returns:
            dict with update results
        """
        FiscalYearInstance = apps.get_model("core", "FiscalYearInstance")
        FiscalYear = apps.get_model("core", "FiscalYear")

        results = {"updated": [], "created": []}

        # Get fiscal year configs to check
        if company:
            configs = FiscalYear.objects.filter(company=company)
        else:
            configs = FiscalYear.objects.all()

        current_date = timezone.now().date()

        for config in configs:
            current_fy = FiscalYearInstance.objects.filter(
                fiscal_year_config=config, is_current=True
            ).first()

            if not current_fy:
                continue

            # Check if current fiscal year has ended
            if current_date > current_fy.end_date:
                # Mark current fiscal year as not current
                current_fy.is_current = False
                current_fy.save()

                # Find next fiscal year
                next_fy = (
                    FiscalYearInstance.objects.filter(
                        fiscal_year_config=config, start_date__gt=current_fy.end_date
                    )
                    .order_by("start_date")
                    .first()
                )

                if next_fy:
                    # Ensure no other fiscal years are marked as current for this config
                    FiscalYearInstance.objects.filter(
                        fiscal_year_config=config
                    ).exclude(id=next_fy.id).update(is_current=False)
                    # Mark next fiscal year as current
                    next_fy.is_current = True
                    next_fy.save()
                    results["updated"].append(next_fy)
                    current_fy = next_fy
                else:
                    # Create next fiscal year if it doesn't exist (year has changed)
                    new_fy = FiscalYearService.create_next_fiscal_year_instance(
                        config, current_fy.end_date
                    )
                    if new_fy:
                        # Ensure no other fiscal years are marked as current for this config
                        FiscalYearInstance.objects.filter(
                            fiscal_year_config=config
                        ).exclude(id=new_fy.id).update(is_current=False)
                        new_fy.is_current = True
                        new_fy.save()
                        results["created"].append(new_fy)
                        results["updated"].append(new_fy)
                        current_fy = new_fy

            # Always ensure next fiscal year exists (create in advance for planning)
            # This allows users to view and plan for the next fiscal year at any time
            next_fy_exists = FiscalYearInstance.objects.filter(
                fiscal_year_config=config, start_date__gt=current_fy.end_date
            ).exists()

            if not next_fy_exists:
                # Create next fiscal year in advance
                new_fy = FiscalYearService.create_next_fiscal_year_instance(
                    config, current_fy.end_date
                )
                if new_fy:
                    results["created"].append(new_fy)

            # After ensuring fiscal years are correct, update Quarter/Period is_current flags
            if current_fy and config.company:
                FiscalYearService._update_current_quarter_and_period(
                    config.company, current_fy, current_date
                )

        return results

    @staticmethod
    def _update_current_quarter_and_period(company, fiscal_year_instance, current_date):
        """
        Ensure that Quarter.is_current and Period.is_current reflect the given date.

        This is used by check_and_update_fiscal_years so that templates and views
        relying on is_current always see an up-to-date "current" flag.
        """
        Quarter = apps.get_model("core", "Quarter")
        Period = apps.get_model("core", "Period")

        # Update current quarter within this fiscal year
        quarters_qs = Quarter.objects.filter(
            company=company, fiscal_year=fiscal_year_instance
        )

        current_quarter = quarters_qs.filter(
            start_date__lte=current_date, end_date__gte=current_date
        ).first()

        if current_quarter:
            # Mark only this quarter as current
            quarters_qs.exclude(id=current_quarter.id).update(is_current=False)
            if not current_quarter.is_current:
                current_quarter.is_current = True
                current_quarter.save(update_fields=["is_current"])
        else:
            # No matching quarter – clear flags for safety
            quarters_qs.update(is_current=False)

        # Update current period across all quarters in this fiscal year
        periods_qs = Period.objects.filter(
            company=company, quarter__fiscal_year=fiscal_year_instance
        )

        current_period = periods_qs.filter(
            start_date__lte=current_date, end_date__gte=current_date
        ).first()

        if current_period:
            periods_qs.exclude(id=current_period.id).update(is_current=False)
            if not current_period.is_current:
                current_period.is_current = True
                current_period.save(update_fields=["is_current"])
        else:
            periods_qs.update(is_current=False)

    @staticmethod
    def create_next_fiscal_year_instance(config, current_end_date):
        """
        Create a new fiscal year instance with quarters and periods.
        This is a complete implementation that generates all required data.

        Args:
            config: FiscalYear configuration
            current_end_date: End date of the current fiscal year

        Returns:
            Created FiscalYearInstance or None
        """
        FiscalYearInstance = apps.get_model("core", "FiscalYearInstance")

        new_start_date = current_end_date + timedelta(days=1)

        if config.fiscal_year_type == "standard":
            new_end_date = new_start_date + relativedelta(years=1) - timedelta(days=1)
        else:
            new_end_date = new_start_date + relativedelta(years=1) - timedelta(days=2)

        if config.display_year_based_on == "starting_year":
            year_name = new_start_date.year
        else:
            year_name = new_end_date.year

        if config.display_year_based_on == "starting_year":
            name = f"FY {year_name}"
        else:
            name = f"FY {year_name + 1}"

        # Check if fiscal year already exists
        existing_fy = FiscalYearInstance.objects.filter(
            fiscal_year_config=config, start_date=new_start_date
        ).first()

        if existing_fy:
            return existing_fy

        # Create new fiscal year instance
        fiscal_year = FiscalYearInstance.objects.create(
            fiscal_year_config=config,
            company=config.company,
            start_date=new_start_date,
            end_date=new_end_date,
            name=name,
            is_current=False,
            is_active=True,
        )

        # Generate quarters and periods for the new fiscal year
        periods_info = config.get_periods_by_format()
        FiscalYearService._generate_quarters(config, fiscal_year, periods_info)

        return fiscal_year
