"""Forecast type tab view (period-by-period data, trends, targets, chart analysis)."""

# Third-party imports (Django)
from django.contrib import messages
from django.core.cache import cache

from horilla.contrib.core.models import FiscalYearInstance, Period
from horilla.contrib.core.services.fiscal_year_service import FiscalYearService

# First party imports (Horilla)
from horilla.db.models import Sum
from horilla.shortcuts import get_object_or_404, render
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.views.generic import TemplateView
from horilla.web import ScriptResponse

# Local imports
from horilla_crm.forecast.models import Forecast, ForecastType
from horilla_crm.forecast.views.core.helpers import (
    ForecastTypeTabHelpersMixin,
    get_forecast_chart_data,
)
from horilla_crm.forecast.views.core.mixins import ForecastTypeTabMixin


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class ForecastTypeTabView(
    ForecastTypeTabMixin, ForecastTypeTabHelpersMixin, TemplateView
):
    """
    Detailed forecast view displaying period-by-period data with trends, targets,
    and performance metrics for a specific forecast type.
    """

    template_name = "forecast_type_view.html"
    USERS_PER_PAGE = 10

    def get(self, request, *args, **kwargs):
        """Enforce ownership permissions and render forecast type tab content."""
        user_id = request.GET.get("user_id")
        has_view_all = request.user.has_perm("opportunities.view_opportunity")
        has_view_own = request.user.has_perm("opportunities.view_own_opportunity")

        if has_view_own and not has_view_all:
            if user_id and user_id != str(request.user.pk):
                return render(request, "403.html")
            if not user_id:
                request.GET = request.GET.copy()
                request.GET["user_id"] = str(request.user.pk)

        context = self.get_context_data(**kwargs)
        if context.get("error"):
            return ScriptResponse(reload=True)

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Assemble forecast type tab context for table and chart rendering."""
        import logging
        import time

        _log = logging.getLogger("forecast.perf")
        _t0 = time.perf_counter()

        context = super().get_context_data(**kwargs)
        forecast_type_id = kwargs.get("pk")
        try:
            forecast_type = get_object_or_404(
                ForecastType, id=forecast_type_id, is_active=True
            )
        except Exception as e:
            messages.error(self.request, str(e))
            context["error"] = True
            return context
        _log.debug("PERF forecast_type fetch: %.3fs", time.perf_counter() - _t0)
        _t1 = time.perf_counter()

        # Automatically check and update fiscal years before displaying
        company = (
            self.request.active_company
            if hasattr(self.request, "active_company") and self.request.active_company
            else (
                self.request.user.company
                if hasattr(self.request.user, "company")
                else None
            )
        )
        if company:
            fy_cache_key = f"fy_check_{getattr(company, 'id', 0)}"
            if not cache.get(fy_cache_key):
                FiscalYearService.check_and_update_fiscal_years(company=company)
                cache.set(fy_cache_key, True, 600)
        _log.debug("PERF fiscal_year_service: %.3fs", time.perf_counter() - _t1)
        _t1 = time.perf_counter()

        fiscal_year_id = self.request.GET.get("fiscal_year_id")
        fiscal_year = None
        if fiscal_year_id:
            try:
                fiscal_year = FiscalYearInstance.objects.get(id=fiscal_year_id)
            except FiscalYearInstance.DoesNotExist:
                fiscal_year = None
        if not fiscal_year:
            fiscal_year = self.current_fiscal_year()
        _log.debug("PERF fiscal_year fetch: %.3fs", time.perf_counter() - _t1)
        _t1 = time.perf_counter()

        self.ensure_forecasts_exist(forecast_type, fiscal_year)
        _log.debug("PERF ensure_forecasts_exist: %.3fs", time.perf_counter() - _t1)
        _t1 = time.perf_counter()

        # Get user_id - this will be current user if they only have view_own permission
        user_id = self.request.GET.get("user_id")

        # Additional permission check
        has_view_all = self.request.user.has_perm("opportunities.view_opportunity")
        has_view_own = self.request.user.has_perm("opportunities.view_own_opportunity")

        # If user only has view_own, ensure they can only see their own data
        if has_view_own and not has_view_all:
            if not user_id or user_id != str(self.request.user.pk):
                user_id = str(self.request.user.pk)

        page = self.request.GET.get("page", 1)
        beginning_period_id = self.request.GET.get("beginning_period_id") or None
        ending_period_id = self.request.GET.get("ending_period_id") or None
        forecasts = self.get_forecast_data(
            forecast_type,
            fiscal_year,
            user_id,
            page,
            beginning_period_id=beginning_period_id,
            ending_period_id=ending_period_id,
        )
        _log.debug("PERF get_forecast_data: %.3fs", time.perf_counter() - _t1)
        _t1 = time.perf_counter()

        # Calculate totals for all periods
        forecast_totals = self.calculate_forecast_totals(forecasts, forecast_type)
        _log.debug("PERF calculate_totals: %.3fs", time.perf_counter() - _t1)
        _t1 = time.perf_counter()

        company = self.company_for_user()
        currency_symbol = "USD"
        if company is not None:
            currency_symbol = company.currency

        # Construct search_url and search_params for HTMX
        search_url = self.request.path
        search_params = self.request.GET.copy()
        if "page" in search_params:
            del search_params["page"]
        search_params = search_params.urlencode()

        title = (
            f"{forecast_type.get_forecast_type_display} Forecast for {fiscal_year.name}"
        )

        forecast_chart_data = get_forecast_chart_data(forecasts, forecast_type)

        context.update(
            {
                "forecast_type": forecast_type,
                "fiscal_year": fiscal_year,
                "forecasts": forecasts,
                "forecast_totals": forecast_totals,
                "currency_symbol": currency_symbol,
                "user_id": user_id,
                "title": title,
                "search_url": search_url,
                "search_params": search_params,
                "has_view_all": has_view_all,
                "has_view_own": has_view_own,
                "forecast_chart_data": forecast_chart_data,
            }
        )
        _log.debug("PERF get_context_data TOTAL: %.3fs", time.perf_counter() - _t0)
        return context

    def calculate_forecast_totals(self, forecasts, forecast_type):
        """Calculate totals across all periods for the forecast data."""

        class ForecastTotals:
            """
            Aggregated totals across ALL forecasts (all users, all periods)
            for display in the totals row at the bottom of the table.
            """

            def __init__(self):
                self.forecast_type = forecast_type
                if forecast_type.is_quantity_based:
                    self.target_quantity = 0
                    self.pipeline_quantity = 0
                    self.best_case_quantity = 0
                    self.commit_quantity = 0
                    self.closed_quantity = 0
                    self.actual_quantity = 0
                    self.gap_quantity = 0
                else:
                    self.target_amount = 0
                    self.pipeline_amount = 0
                    self.best_case_amount = 0
                    self.commit_amount = 0
                    self.closed_amount = 0
                    self.actual_amount = 0
                    self.gap_amount = 0

                self.performance_percentage = 0
                self.gap_percentage = 0
                self.closed_percentage = 0
                self.closed_deals_count = 0

        totals = ForecastTotals()

        if not forecasts:
            return totals

        for forecast in forecasts:
            if forecast_type.is_quantity_based:
                totals.target_quantity += getattr(forecast, "target_quantity", 0) or 0
                totals.pipeline_quantity += (
                    getattr(forecast, "pipeline_quantity", 0) or 0
                )
                totals.best_case_quantity += (
                    getattr(forecast, "best_case_quantity", 0) or 0
                )
                totals.commit_quantity += getattr(forecast, "commit_quantity", 0) or 0
                totals.closed_quantity += getattr(forecast, "closed_quantity", 0) or 0
                totals.actual_quantity += getattr(forecast, "actual_quantity", 0) or 0
            else:
                totals.target_amount += getattr(forecast, "target_amount", 0) or 0
                totals.pipeline_amount += getattr(forecast, "pipeline_amount", 0) or 0
                totals.best_case_amount += getattr(forecast, "best_case_amount", 0) or 0
                totals.commit_amount += getattr(forecast, "commit_amount", 0) or 0
                totals.closed_amount += getattr(forecast, "closed_amount", 0) or 0
                totals.actual_amount += getattr(forecast, "actual_amount", 0) or 0

            totals.closed_deals_count += getattr(forecast, "closed_deals_count", 0) or 0

        # Calculate derived metrics
        if forecast_type.is_quantity_based:
            totals.gap_quantity = totals.target_quantity - totals.actual_quantity
            if totals.target_quantity > 0:
                totals.performance_percentage = (
                    totals.actual_quantity / totals.target_quantity
                ) * 100
                totals.gap_percentage = (
                    totals.gap_quantity / totals.target_quantity
                ) * 100
                totals.closed_percentage = (
                    totals.closed_quantity / totals.target_quantity
                ) * 100
        else:
            totals.gap_amount = totals.target_amount - totals.actual_amount
            if totals.target_amount > 0:
                totals.performance_percentage = (
                    totals.actual_amount / totals.target_amount
                ) * 100
                totals.gap_percentage = (totals.gap_amount / totals.target_amount) * 100
                totals.closed_percentage = (
                    totals.closed_amount / totals.target_amount
                ) * 100

        return totals


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class ForecastChartsModalView(
    ForecastTypeTabMixin, ForecastTypeTabHelpersMixin, TemplateView
):
    """HTMX view that returns chart analysis HTML for the content modal."""

    template_name = "forecast_charts_modal_content.html"
    USERS_PER_PAGE = (
        10  # required by get_forecast_data mixin (paginates user list per period)
    )

    def get_context_data(self, **kwargs):
        """Build modal context with chart analysis for the selected forecast filters."""
        context = super().get_context_data(**kwargs)
        forecast_type_id = self.request.GET.get("forecast_type_id")
        fiscal_year_id = self.request.GET.get("fiscal_year_id")
        user_id = self.request.GET.get("user_id")

        if not forecast_type_id or not fiscal_year_id:
            context["forecast_chart_data"] = None
            context["currency_symbol"] = "USD"
            return context

        try:
            forecast_type = get_object_or_404(
                ForecastType, id=forecast_type_id, is_active=True
            )
        except Exception:
            context["forecast_chart_data"] = None
            context["currency_symbol"] = "USD"
            return context

        try:
            fiscal_year = FiscalYearInstance.objects.get(id=fiscal_year_id)
        except FiscalYearInstance.DoesNotExist:
            fiscal_year = self.current_fiscal_year()

        if not fiscal_year:
            context["forecast_chart_data"] = None
            company = self.company_for_user()
            context["currency_symbol"] = "USD"
            if company is not None:
                context["currency_symbol"] = company.currency
            return context

        company = (
            self.request.active_company
            if hasattr(self.request, "active_company") and self.request.active_company
            else (
                self.request.user.company
                if hasattr(self.request.user, "company")
                else None
            )
        )
        if company:
            fy_cache_key = f"fy_check_{getattr(company, 'id', 0)}"
            if not cache.get(fy_cache_key):
                FiscalYearService.check_and_update_fiscal_years(company=company)
                cache.set(fy_cache_key, True, 600)

        has_view_all = self.request.user.has_perm("opportunities.view_opportunity")
        has_view_own = self.request.user.has_perm("opportunities.view_own_opportunity")
        if has_view_own and not has_view_all:
            user_id = str(self.request.user.pk)

        beginning_period_id = self.request.GET.get("beginning_period_id") or None
        ending_period_id = self.request.GET.get("ending_period_id") or None

        # Build period list
        periods_qs = Period.all_objects.select_related(
            "quarter",
            "quarter__fiscal_year",
            "quarter__fiscal_year__fiscal_year_config",
        ).order_by("quarter__fiscal_year__start_date", "period_number")
        company = self.company_for_user()
        if company is not None:
            periods_qs = periods_qs.filter(company=company)

        if beginning_period_id and ending_period_id:
            begin_p = periods_qs.filter(id=beginning_period_id).first()
            end_p = periods_qs.filter(id=ending_period_id).first()
            if begin_p and end_p:
                all_p = list(periods_qs)
                try:
                    si = next(i for i, p in enumerate(all_p) if p.id == begin_p.id)
                    ei = next(i for i, p in enumerate(all_p) if p.id == end_p.id)
                except StopIteration:
                    si = ei = 0
                if si > ei:
                    si, ei = ei, si
                periods_list = all_p[si : ei + 1]
            else:
                periods_list = list(periods_qs.filter(quarter__fiscal_year=fiscal_year))
        else:
            periods_list = list(periods_qs.filter(quarter__fiscal_year=fiscal_year))

        # Aggregate sums per period in one query — chart needs totals only, not user rows
        suffix = "quantity" if forecast_type.is_quantity_based else "amount"
        fq = Forecast.all_objects.filter(
            forecast_type=forecast_type,
            period_id__in=[p.id for p in periods_list],
            company=company,
            owner__is_active=True,
        )
        if user_id:
            fq = fq.filter(owner_id=user_id)

        agg_rows = {
            row["period_id"]: row
            for row in fq.values("period_id").annotate(
                sum_pipeline=Sum(f"pipeline_{suffix}"),
                sum_best_case=Sum(f"best_case_{suffix}"),
                sum_commit=Sum(f"commit_{suffix}"),
                sum_closed=Sum(f"closed_{suffix}"),
                sum_actual=Sum(f"actual_{suffix}"),
                sum_target=Sum(f"target_{suffix}"),
            )
        }

        class _ChartProxy:
            pass

        chart_forecasts = []
        for p in periods_list:
            row = agg_rows.get(p.id, {})
            obj = _ChartProxy()
            obj.period = p
            obj.quarter = p.quarter
            obj.fiscal_year = p.quarter.fiscal_year
            obj.forecast_type = forecast_type
            setattr(obj, f"target_{suffix}", float(row.get("sum_target") or 0))
            setattr(obj, f"actual_{suffix}", float(row.get("sum_actual") or 0))
            setattr(obj, f"closed_{suffix}", float(row.get("sum_closed") or 0))
            setattr(obj, f"commit_{suffix}", float(row.get("sum_commit") or 0))
            setattr(obj, f"best_case_{suffix}", float(row.get("sum_best_case") or 0))
            setattr(obj, f"pipeline_{suffix}", float(row.get("sum_pipeline") or 0))
            chart_forecasts.append(obj)

        forecast_chart_data = get_forecast_chart_data(chart_forecasts, forecast_type)
        company = self.company_for_user()
        currency_symbol = "USD"
        if company is not None:
            currency_symbol = company.currency

        context["forecast_chart_data"] = forecast_chart_data
        context["currency_symbol"] = currency_symbol
        return context
