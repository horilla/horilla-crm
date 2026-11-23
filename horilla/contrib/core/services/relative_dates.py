"""
Relative date ranges for list filters.

* today / yesterday / this_week (Mon-Sun) / this_month / this_year are calendar based.
* this_fiscal_year / this_fiscal_quarter / this_fiscal_period follow the company's
  fiscal year configuration. Without a fiscal year they match nothing.
"""

from calendar import monthrange
from datetime import date, timedelta

from django.apps import apps

from horilla.contrib.utils.middlewares import get_active_company
from horilla.utils import timezone

FISCAL_DATE_OPERATORS = (
    "this_fiscal_period",
    "this_fiscal_quarter",
    "this_fiscal_year",
)
_MONTH_NUMBER = {
    name: i
    for i, name in enumerate(
        [
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
        ],
        start=1,
    )
}


def _get_config(company):
    if company is None:
        return None
    FiscalYear = apps.get_model("core", "FiscalYear")
    return FiscalYear.objects.filter(company=company).first()


def _clamp_day(year, month, day):
    return date(year, month, min(day, monthrange(year, month)[1]))


def _fiscal_year_bounds(config, today):
    FiscalYearInstance = apps.get_model("core", "FiscalYearInstance")
    instance = FiscalYearInstance.objects.filter(
        fiscal_year_config=config, start_date__lte=today, end_date__gte=today
    ).first()
    if instance:
        return instance.start_date, instance.end_date

    month = _MONTH_NUMBER.get((config.start_date_month or "").lower())
    if not month:
        return None
    start = _clamp_day(today.year, month, config.start_date_day or 1)
    if start > today:
        start = _clamp_day(today.year - 1, month, config.start_date_day or 1)
    end = _clamp_day(start.year + 1, month, config.start_date_day or 1) - timedelta(
        days=1
    )
    return start, end


def _period_bounds(config, today):
    Period = apps.get_model("core", "Period")
    period = Period.objects.filter(
        quarter__fiscal_year__fiscal_year_config=config,
        start_date__lte=today,
        end_date__gte=today,
    ).first()
    return (period.start_date, period.end_date) if period else None


def _quarter_bounds(config, today):
    Quarter = apps.get_model("core", "Quarter")
    quarter = Quarter.objects.filter(
        fiscal_year__fiscal_year_config=config,
        start_date__lte=today,
        end_date__gte=today,
    ).first()
    return (quarter.start_date, quarter.end_date) if quarter else None


def get_relative_date_bounds(operator, company=None):
    """Return inclusive ``(start, end)`` dates for a relative date operator."""
    today = timezone.localdate()
    if operator == "today":
        return today, today
    if operator == "yesterday":
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    if operator == "this_week":
        week_start = today - timedelta(days=today.weekday())
        return week_start, week_start + timedelta(days=6)
    if operator == "this_month":
        last_day = monthrange(today.year, today.month)[1]
        return today.replace(day=1), today.replace(day=last_day)
    if operator == "this_year":
        return date(today.year, 1, 1), date(today.year, 12, 31)

    if operator not in FISCAL_DATE_OPERATORS:
        return None, None

    # Empty range (start > end) so nothing matches when no fiscal data exists.
    no_match = (date(9999, 12, 31), date(1, 1, 1))
    config = _get_config(company or get_active_company())
    if config is None:
        return no_match
    if operator == "this_fiscal_year":
        return _fiscal_year_bounds(config, today) or no_match
    if operator == "this_fiscal_quarter":
        return _quarter_bounds(config, today) or no_match
    return _period_bounds(config, today) or no_match
