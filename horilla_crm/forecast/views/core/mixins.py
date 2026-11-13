"""Data-fetching mixin for ForecastTypeTabView (fiscal year, targets, get_forecast_data)."""

# Standard library imports
import logging
import time

# Third-party imports (Django)
from django.core.cache import cache
from django.core.paginator import Paginator

from horilla.auth.models import User
from horilla.contrib.core.models import Company, FiscalYearInstance, Period

# First party imports (Horilla)
from horilla.db.models import Sum
from horilla.utils.functional import cached_property

# Local imports
from horilla_crm.forecast.models import Forecast, ForecastTarget
from horilla_crm.forecast.utils import ForecastCalculator
from horilla_crm.opportunities.models import Opportunity


class ForecastTypeTabMixin:
    """Mixin with get_forecast_data and fiscal/target/ensure methods."""

    @cached_property
    def get_current_fiscal_year(self):
        """Cache the current fiscal year to avoid repeated queries."""
        return FiscalYearInstance.objects.filter(is_current=True).first()

    @cached_property
    def get_company_for_user(self):
        """Cache the active company for the current user."""
        return (
            self.request.active_company
            if hasattr(self.request, "active_company")
            else Company.objects.filter(id=self.request.user.company_id).first()
        )

    def current_fiscal_year(self):
        """Return the cached current fiscal year."""
        return self.get_current_fiscal_year

    def company_for_user(self):
        """Return the cached active company for the current user."""
        return self.get_company_for_user

    def get_target_for_period_bulk(self, periods, forecast_type, user_id=None):
        """
        Get targets for all periods in bulk to avoid N+1 queries
        """
        if user_id:
            # Get individual targets for specific user
            targets = ForecastTarget.objects.filter(
                is_active=True,
                assigned_to_id=user_id,
                period__in=periods,
                forcasts_type=forecast_type,  # Corrected from forcasts_type
            ).select_related("period", "assigned_to")

            target_map = {target.period_id: target for target in targets}

            # For missing individual targets, check role-based targets
            missing_periods = [p for p in periods if p.id not in target_map]
            if missing_periods:
                try:
                    user = User.objects.get(id=user_id)
                    if hasattr(user, "role") and user.role:
                        role_targets = ForecastTarget.objects.filter(
                            is_active=True,
                            period__in=missing_periods,
                            forcasts_type=forecast_type,  # Corrected from forcasts_type
                            role=user.role,
                            assigned_to__isnull=True,
                        ).select_related("period")

                        for role_target in role_targets:
                            if role_target.period_id not in target_map:
                                target_map[role_target.period_id] = role_target
                except User.DoesNotExist:
                    pass

            return target_map
        all_targets = (
            ForecastTarget.objects.filter(
                is_active=True,
                period__in=periods,
                forcasts_type=forecast_type,  # Corrected from forcasts_type
            )
            .select_related("period", "assigned_to")
            .prefetch_related("role")
        )

        targets_by_period = {}
        for target in all_targets:
            period_id = target.period_id
            if period_id not in targets_by_period:
                targets_by_period[period_id] = []
            targets_by_period[period_id].append(target)

        return targets_by_period

    def get_closed_deals_count_bulk(self, periods, owner_ids=None):
        """
        Count won Opportunities per (owner, period) across all given periods
        in a single query, bucketed in Python since periods are non-overlapping
        date ranges rather than a queryable relation on Opportunity.

        Returns a dict of {(owner_id, period_id): count}.
        """
        if not periods:
            return {}

        query = Opportunity.objects.filter(
            close_date__range=[periods[0].start_date, periods[-1].end_date],
            stage__stage_type="won",
        )
        if owner_ids is not None:
            query = query.filter(owner_id__in=owner_ids)

        sorted_periods = sorted(periods, key=lambda p: p.start_date)
        counts = {}
        for owner_id, close_date in query.values_list("owner_id", "close_date"):
            for period in sorted_periods:
                if period.start_date <= close_date <= period.end_date:
                    key = (owner_id, period.id)
                    counts[key] = counts.get(key, 0) + 1
                    break
        return counts

    def ensure_forecasts_exist(self, forecast_type, fiscal_year):
        """
        Bulk create missing forecasts to reduce database operations.
        Result is cached per (company, forecast_type, fiscal_year) for 5 minutes
        so repeated tab loads within the same session don't re-scan the DB.
        """
        company = self.company_for_user()
        cache_key = (
            f"forecast_exist_{getattr(company, 'id', 0)}"
            f"_{forecast_type.id}_{getattr(fiscal_year, 'id', 0)}"
        )
        if cache.get(cache_key):
            return

        calculator = ForecastCalculator(user=self.request.user, fiscal_year=fiscal_year)

        all_users = []
        all_periods = []
        existing_forecasts = set()
        if company is not None:
            all_users = list(
                User.objects.filter(is_active=True, company=company).values("id")
            )
            all_periods = list(
                Period.all_objects.filter(
                    company=company, quarter__fiscal_year=fiscal_year
                ).values("id")
            )
            existing_forecasts = set(
                Forecast.all_objects.filter(
                    forecast_type=forecast_type,
                    fiscal_year=fiscal_year,
                    company=company,
                ).values_list("owner_id", "period_id")
            )

        missing_forecasts = [
            (user["id"], period["id"])
            for user in all_users
            for period in all_periods
            if (user["id"], period["id"]) not in existing_forecasts
        ]

        if missing_forecasts:
            calculator.bulk_create_missing_forecasts(forecast_type, missing_forecasts)

        # Mark as checked; expire after 5 minutes so new users/periods are picked up
        cache.set(cache_key, True, 300)

    def get_forecast_data(
        self,
        forecast_type,
        fiscal_year,
        user_id=None,
        page=1,
        beginning_period_id=None,
        ending_period_id=None,
    ):
        """
        Multi-year aware forecast data loader.

        If beginning_period_id and ending_period_id are provided and valid, build a
        contiguous range of Periods between them (across all fiscal years). Otherwise
        fall back to all periods of the given fiscal_year.
        """

        _log = logging.getLogger("forecast.perf")
        _t = time.perf_counter()

        all_periods_qs = Period.all_objects.select_related(
            "quarter",
            "quarter__fiscal_year",
            "quarter__fiscal_year__fiscal_year_config",
        ).order_by("quarter__fiscal_year__start_date", "period_number")
        company = self.company_for_user()
        if company is not None:
            all_periods_qs = all_periods_qs.filter(company=company)

        # Build the working period list
        if beginning_period_id and ending_period_id:
            begin_p = all_periods_qs.filter(id=beginning_period_id).first()
            end_p = all_periods_qs.filter(id=ending_period_id).first()

            if begin_p and end_p:
                all_periods = list(all_periods_qs)
                try:
                    start_idx = next(
                        i for i, p in enumerate(all_periods) if p.id == begin_p.id
                    )
                    end_idx = next(
                        i for i, p in enumerate(all_periods) if p.id == end_p.id
                    )
                except StopIteration:
                    start_idx = end_idx = 0

                if start_idx > end_idx:
                    start_idx, end_idx = end_idx, start_idx
                periods_list = all_periods[start_idx : end_idx + 1]
            else:
                # Fallback: just the selected fiscal year's periods
                periods_list = list(
                    all_periods_qs.filter(quarter__fiscal_year=fiscal_year)
                )
        else:
            # No explicit range: all periods of the selected fiscal year
            periods_list = list(all_periods_qs.filter(quarter__fiscal_year=fiscal_year))
        _log.debug(
            "  gfd periods_list build: %.3fs (count=%d)",
            time.perf_counter() - _t,
            len(periods_list),
        )
        _t = time.perf_counter()

        currency_symbol = "USD"
        if company is not None:
            currency_symbol = company.currency

        if not periods_list:
            return []

        targets_data = self.get_target_for_period_bulk(
            periods_list, forecast_type, user_id
        )
        _log.debug("  gfd get_target_for_period_bulk: %.3fs", time.perf_counter() - _t)
        _t = time.perf_counter()

        _period_map = {p.id: p for p in periods_list}
        _period_id_list = [p.id for p in periods_list]
        _fq_base = Forecast.all_objects.filter(
            forecast_type=forecast_type,
            period_id__in=_period_id_list,
            company=company,
        )

        if user_id:
            # SINGLE USER: fetch only this user's rows (small result set)
            closed_deals_counts = self.get_closed_deals_count_bulk(
                periods_list, owner_ids=[user_id]
            )
            _log.debug(
                "  gfd get_closed_deals_count_bulk: %.3fs", time.perf_counter() - _t
            )
            _t = time.perf_counter()

            _value_fields = [
                "id",
                "period_id",
                "owner_id",
                "pipeline_amount",
                "best_case_amount",
                "commit_amount",
                "closed_amount",
                "actual_amount",
                "target_amount",
                "pipeline_quantity",
                "best_case_quantity",
                "commit_quantity",
                "closed_quantity",
                "actual_quantity",
                "target_quantity",
            ]
            forecasts_by_period = {}
            for row in _fq_base.filter(owner_id=user_id).values(*_value_fields):
                f = Forecast()
                for k, v in row.items():
                    setattr(f, k, v)
                f.forecast_type = forecast_type
                f.period = _period_map.get(row["period_id"])
                if f.period:
                    f.quarter = f.period.quarter
                    f.fiscal_year = f.period.quarter.fiscal_year
                forecasts_by_period.setdefault(row["period_id"], []).append(f)

            cached_user = None
            try:
                cached_user = User.objects.select_related("role").get(id=user_id)
                for lst in forecasts_by_period.values():
                    for f in lst:
                        f.owner = cached_user
            except User.DoesNotExist:
                pass
            all_fetched = [f for lst in forecasts_by_period.values() for f in lst]
            _log.debug(
                "  gfd forecast_queryset eval: %.3fs (rows=%d)",
                time.perf_counter() - _t,
                len(all_fetched),
            )
            _t = time.perf_counter()

            trend_data = {}
            if periods_list:
                trend_data = self.get_bulk_trend_data(
                    periods_list,
                    forecast_type,
                    user_id,
                    prefetched_forecasts=all_fetched,
                )
            _log.debug("  gfd get_bulk_trend_data: %.3fs", time.perf_counter() - _t)
            _t = time.perf_counter()
            _log.debug("  gfd user fetch: %.3fs", time.perf_counter() - _t)
            _t = time.perf_counter()

        else:
            # MULTI-USER: aggregate per period in DB (12 rows) + per-user rows only for
            # paginated users — avoids fetching all 6000 rows to Python.
            _suffix = "quantity" if forecast_type.is_quantity_based else "amount"
            _agg_qs = (
                _fq_base.filter(owner__is_active=True)
                .values("period_id")
                .annotate(
                    sum_pipeline=Sum(f"pipeline_{_suffix}"),
                    sum_best_case=Sum(f"best_case_{_suffix}"),
                    sum_commit=Sum(f"commit_{_suffix}"),
                    sum_closed=Sum(f"closed_{_suffix}"),
                    sum_actual=Sum(f"actual_{_suffix}"),
                )
            )
            # period_id → aggregated sums dict (12 rows)
            period_agg = {row["period_id"]: row for row in _agg_qs}

            # period_id → total closed deals across ALL active owners for that period
            _active_owner_ids = list(
                _fq_base.filter(owner__is_active=True)
                .values_list("owner_id", flat=True)
                .distinct()
            )
            _closed_counts_by_owner_period = self.get_closed_deals_count_bulk(
                periods_list, owner_ids=_active_owner_ids
            )
            period_closed_deals_count = {}
            for (owner_id, period_id), count in _closed_counts_by_owner_period.items():
                period_closed_deals_count[period_id] = (
                    period_closed_deals_count.get(period_id, 0) + count
                )
            _log.debug(
                "  gfd get_closed_deals_count_bulk: %.3fs", time.perf_counter() - _t
            )
            _t = time.perf_counter()

            # Users with data ordered by actual desc, then users without data appended after
            _owner_actual = {
                row["owner_id"]: (row["total"] or 0)
                for row in _fq_base.filter(owner__is_active=True)
                .values("owner_id")
                .annotate(total=Sum(f"actual_{_suffix}"))
            }
            _all_users = list(
                User.objects.select_related("role").filter(
                    is_active=True, company=self.get_company_for_user
                )
            )
            users_with_data = sorted(
                [u for u in _all_users if _owner_actual.get(u.id, 0) > 0],
                key=lambda u: _owner_actual.get(u.id, 0),
                reverse=True,
            )
            users_without_data = [
                u for u in _all_users if _owner_actual.get(u.id, 0) <= 0
            ]
            all_active_users = users_with_data + users_without_data

            # Paginate the user list once (same page applies to all periods)
            paginator = Paginator(all_active_users, self.USERS_PER_PAGE)
            try:
                paginated_users_page = paginator.page(page)
            except Exception:
                paginated_users_page = paginator.page(1)
            paginated_user_ids = [u.id for u in paginated_users_page]
            user_lookup = {u.id: u for u in paginated_users_page}

            # Fetch rows only for the paginated users (10 users × 12 periods = 120 rows max)
            _value_fields = [
                "id",
                "period_id",
                "owner_id",
                "pipeline_amount",
                "best_case_amount",
                "commit_amount",
                "closed_amount",
                "actual_amount",
                "target_amount",
                "pipeline_quantity",
                "best_case_quantity",
                "commit_quantity",
                "closed_quantity",
                "actual_quantity",
                "target_quantity",
            ]
            forecasts_by_period_owner = {}
            for row in _fq_base.filter(owner_id__in=paginated_user_ids).values(
                *_value_fields
            ):
                f = Forecast()
                for k, v in row.items():
                    setattr(f, k, v)
                f.forecast_type = forecast_type
                f.period = _period_map.get(row["period_id"])
                if f.period:
                    f.quarter = f.period.quarter
                    f.fiscal_year = f.period.quarter.fiscal_year
                f.owner = user_lookup.get(row["owner_id"])
                forecasts_by_period_owner[(row["period_id"], row["owner_id"])] = f

            _log.debug(
                "  gfd forecast_queryset eval: %.3fs (agg=%d periods, user_rows=%d)",
                time.perf_counter() - _t,
                len(period_agg),
                len(forecasts_by_period_owner),
            )
            _t = time.perf_counter()

            # Aggregate-level trends from DB sums; per-user trends from paginated rows
            paginated_fetched = list(forecasts_by_period_owner.values())
            trend_data = {}
            if periods_list:
                trend_data = self.get_bulk_trend_data(
                    periods_list,
                    forecast_type,
                    user_id=None,
                    prefetched_forecasts=paginated_fetched,
                    period_agg=period_agg,
                )
            _log.debug("  gfd get_bulk_trend_data: %.3fs", time.perf_counter() - _t)
            _t = time.perf_counter()
            _log.debug("  gfd user fetch: %.3fs", time.perf_counter() - _t)
            _t = time.perf_counter()

        period_forecasts = []
        for period in periods_list:
            target_user_id = user_id if user_id else None
            target = self.extract_target_from_bulk(targets_data, period, target_user_id)

            if user_id:
                user_forecasts = forecasts_by_period.get(period.id, [])
                # Create empty forecast for user with no data
                if not user_forecasts and cached_user:
                    empty_forecast = Forecast()
                    empty_forecast.id = f"empty_{period.id}_{user_id}"
                    empty_forecast.period = period
                    empty_forecast.quarter = period.quarter
                    empty_forecast.fiscal_year = period.quarter.fiscal_year
                    empty_forecast.forecast_type = forecast_type
                    empty_forecast.owner = cached_user
                    empty_forecast.owner_id = cached_user.id
                    if forecast_type.is_quantity_based:
                        empty_forecast.target_quantity = (
                            target.target_amount if target else 0
                        )
                        empty_forecast.pipeline_quantity = 0
                        empty_forecast.best_case_quantity = 0
                        empty_forecast.commit_quantity = 0
                        empty_forecast.closed_quantity = 0
                        empty_forecast.actual_quantity = 0
                    else:
                        empty_forecast.target_amount = (
                            target.target_amount if target else 0
                        )
                        empty_forecast.pipeline_amount = 0
                        empty_forecast.best_case_amount = 0
                        empty_forecast.commit_amount = 0
                        empty_forecast.closed_amount = 0
                        empty_forecast.actual_amount = 0
                    user_forecasts = [empty_forecast]

                aggregated_forecast = self.create_aggregated_forecast(
                    period,
                    forecast_type,
                    user_forecasts,
                    currency_symbol,
                    user_id,
                    target,
                    closed_deals_count=closed_deals_counts.get((user_id, period.id), 0),
                )
                period_trend = trend_data.get(period.id, {})
                aggregated_forecast.commit_trend = period_trend.get("commit_trend")
                aggregated_forecast.best_case_trend = period_trend.get(
                    "best_case_trend"
                )
                aggregated_forecast.pipeline_trend = period_trend.get("pipeline_trend")
                aggregated_forecast.closed_trend = period_trend.get("closed_trend")
                aggregated_forecast.commit_change_text = period_trend.get(
                    "commit_change_text", ""
                )
                aggregated_forecast.best_case_change_text = period_trend.get(
                    "best_case_change_text", ""
                )
                aggregated_forecast.pipeline_change_text = period_trend.get(
                    "pipeline_change_text", ""
                )
                aggregated_forecast.closed_change_text = period_trend.get(
                    "closed_change_text", ""
                )
                aggregated_forecast.user_forecasts = []

            else:
                # Build aggregated forecast from DB sums (no Python iteration over all users)
                agg_row = period_agg.get(period.id, {})
                _suffix = "quantity" if forecast_type.is_quantity_based else "amount"

                class _AggProxy:
                    pass

                agg_proxy = _AggProxy()
                setattr(
                    agg_proxy, f"pipeline_{_suffix}", agg_row.get("sum_pipeline") or 0
                )
                setattr(
                    agg_proxy, f"best_case_{_suffix}", agg_row.get("sum_best_case") or 0
                )
                setattr(agg_proxy, f"commit_{_suffix}", agg_row.get("sum_commit") or 0)
                setattr(agg_proxy, f"closed_{_suffix}", agg_row.get("sum_closed") or 0)
                setattr(agg_proxy, f"actual_{_suffix}", agg_row.get("sum_actual") or 0)

                aggregated_forecast = self.create_aggregated_forecast(
                    period,
                    forecast_type,
                    [agg_proxy],
                    currency_symbol,
                    user_id,
                    target,
                    closed_deals_count=period_closed_deals_count.get(period.id, 0),
                )

                user_target_map = {
                    t.assigned_to_id: t for t in targets_data.get(period.id, [])
                }

                period_trend = trend_data.get(period.id, {})
                aggregated_forecast.commit_trend = period_trend.get("commit_trend")
                aggregated_forecast.best_case_trend = period_trend.get(
                    "best_case_trend"
                )
                aggregated_forecast.pipeline_trend = period_trend.get("pipeline_trend")
                aggregated_forecast.closed_trend = period_trend.get("closed_trend")
                aggregated_forecast.commit_change_text = period_trend.get(
                    "commit_change_text", ""
                )
                aggregated_forecast.best_case_change_text = period_trend.get(
                    "best_case_change_text", ""
                )
                aggregated_forecast.pipeline_change_text = period_trend.get(
                    "pipeline_change_text", ""
                )
                aggregated_forecast.closed_change_text = period_trend.get(
                    "closed_change_text", ""
                )

                # Build paginated user forecasts for this period from the small prefetched set
                page_user_forecasts = []
                for u in paginated_users_page:
                    uf = forecasts_by_period_owner.get((period.id, u.id))
                    user_specific_target = user_target_map.get(u.id)
                    if uf is None:
                        uf = Forecast()
                        uf.id = f"empty_{period.id}_{u.id}"
                        uf.period = period
                        uf.quarter = period.quarter
                        uf.fiscal_year = period.quarter.fiscal_year
                        uf.forecast_type = forecast_type
                        uf.owner = u
                        uf.owner_id = u.id
                        if forecast_type.is_quantity_based:
                            uf.target_quantity = (
                                user_specific_target.target_amount
                                if user_specific_target
                                else 0
                            )
                            uf.pipeline_quantity = uf.best_case_quantity = (
                                uf.commit_quantity
                            ) = uf.closed_quantity = uf.actual_quantity = 0
                        else:
                            uf.target_amount = (
                                user_specific_target.target_amount
                                if user_specific_target
                                else 0
                            )
                            uf.pipeline_amount = uf.best_case_amount = (
                                uf.commit_amount
                            ) = uf.closed_amount = uf.actual_amount = 0
                    else:
                        if forecast_type.is_quantity_based:
                            uf.target_quantity = (
                                user_specific_target.target_amount
                                if user_specific_target
                                else 0
                            )
                        else:
                            uf.target_amount = (
                                user_specific_target.target_amount
                                if user_specific_target
                                else 0
                            )
                    page_user_forecasts.append(
                        self.enhance_forecast_data_bulk(
                            uf, currency_symbol, period, forecast_type, trend_data
                        )
                    )

                aggregated_forecast.user_forecasts = page_user_forecasts
                aggregated_forecast.has_next = paginated_users_page.has_next()
                aggregated_forecast.next_page = (
                    paginated_users_page.next_page_number()
                    if paginated_users_page.has_next()
                    else None
                )
                aggregated_forecast.view_id = f"period_{period.id}"

            period_forecasts.append(aggregated_forecast)

        _log.debug("  gfd period loop: %.3fs", time.perf_counter() - _t)
        return period_forecasts
