"""Helper methods for ForecastTypeTabView (create forecasts, trends, enhance data, chart data)."""

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.models import Period
from horilla.utils.translation import gettext_lazy as _

# Local imports
from horilla_crm.forecast.models import Forecast


def get_forecast_chart_data(forecasts, forecast_type):
    """
    Build chart data for forecast analysis: period labels and series
    (Target, Actual, Closed, Commit, Best Case, Pipeline).
    Returns a dict with categories, series, and is_quantity_based for JS/echarts.
    """
    if not forecasts:
        return {
            "categories": [],
            "series": [],
            "stacked_series": [],
            "stacked_category_series": [],
            "forecast_vs_actual": {"categories": [], "target": [], "actual": []},
            "trend": {"categories": [], "target": [], "actual": []},
            "is_quantity_based": forecast_type.is_quantity_based,
        }

    categories = []
    target_data = []
    actual_data = []
    closed_data = []
    commit_data = []
    best_case_data = []
    pipeline_data = []

    for forecast in forecasts:
        if forecast.period:
            fiscal_config = getattr(
                forecast.period.quarter.fiscal_year,
                "fiscal_year_config",
                None,
            )
            if getattr(fiscal_config, "fiscal_year_type", None) == "standard":
                label = _("Period %(num)s") % {
                    "num": forecast.period.get_display_period_number()
                }
            else:
                label = forecast.period.name or ""
        elif forecast.quarter:
            label = forecast.quarter.name or ""
        else:
            label = getattr(forecast.fiscal_year, "name", "")
        categories.append(label)

        if forecast_type.is_quantity_based:
            target_data.append(float(forecast.target_quantity or 0))
            actual_data.append(float(forecast.actual_quantity or 0))
            closed_data.append(float(forecast.closed_quantity or 0))
            commit_data.append(float(forecast.commit_quantity or 0))
            best_case_data.append(float(forecast.best_case_quantity or 0))
            pipeline_data.append(float(forecast.pipeline_quantity or 0))
        else:
            target_data.append(float(forecast.target_amount or 0))
            actual_data.append(float(forecast.actual_amount or 0))
            closed_data.append(float(forecast.closed_amount or 0))
            commit_data.append(float(forecast.commit_amount or 0))
            best_case_data.append(float(forecast.best_case_amount or 0))
            pipeline_data.append(float(forecast.pipeline_amount or 0))

    stacked_series = [
        {"name": _("Target"), "data": target_data},
        {"name": _("Actual"), "data": actual_data},
        {"name": _("Closed"), "data": closed_data},
        {"name": _("Commit"), "data": commit_data},
        {"name": _("Best Case"), "data": best_case_data},
        {"name": _("Pipeline"), "data": pipeline_data},
    ]

    forecast_vs_actual = {
        "categories": categories,
        "target": target_data,
        "actual": actual_data,
    }

    trend = {
        "categories": categories,
        "target": target_data,
        "actual": actual_data,
    }

    stacked_category_series = [
        {"name": _("Closed"), "data": closed_data},
        {"name": _("Commit"), "data": commit_data},
        {"name": _("Best Case"), "data": best_case_data},
        {"name": _("Pipeline"), "data": pipeline_data},
    ]

    return {
        "categories": categories,
        "series": stacked_series,
        "stacked_series": stacked_series,
        "stacked_category_series": stacked_category_series,
        "forecast_vs_actual": forecast_vs_actual,
        "trend": trend,
        "is_quantity_based": forecast_type.is_quantity_based,
    }


class ForecastTypeTabHelpersMixin:
    """Mixin with create_* and trend/enhance helpers for ForecastTypeTabView."""

    def create_empty_user_forecast_with_owner(
        self, period, forecast_type, user_id, currency_symbol, target=None
    ):
        """
        Create a placeholder forecast for a user
        with no data - returns actual forecast object.
        """
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None

        # Create an actual Forecast object (not saved to DB) with proper attributes
        forecast = Forecast()
        forecast.id = f"empty_{period.id}_{user_id}"
        forecast.period = period
        forecast.quarter = period.quarter
        forecast.fiscal_year = period.quarter.fiscal_year
        forecast.forecast_type = forecast_type
        forecast.owner = user
        forecast.owner_id = user.id  # Ensure owner_id is set

        # Set target and other fields based on forecast type
        if target and forecast_type.is_quantity_based:
            forecast.target_quantity = target.target_amount
            forecast.pipeline_quantity = 0
            forecast.best_case_quantity = 0
            forecast.commit_quantity = 0
            forecast.closed_quantity = 0
            forecast.actual_quantity = 0
            forecast.gap_quantity = forecast.target_quantity
        elif target:
            forecast.target_amount = target.target_amount
            forecast.pipeline_amount = 0
            forecast.best_case_amount = 0
            forecast.commit_amount = 0
            forecast.closed_amount = 0
            forecast.actual_amount = 0
            forecast.gap_amount = forecast.target_amount
        else:
            if forecast_type.is_quantity_based:
                forecast.target_quantity = 0
                forecast.pipeline_quantity = 0
                forecast.best_case_quantity = 0
                forecast.commit_quantity = 0
                forecast.closed_quantity = 0
                forecast.actual_quantity = 0
                forecast.gap_quantity = 0
            else:
                forecast.target_amount = 0
                forecast.pipeline_amount = 0
                forecast.best_case_amount = 0
                forecast.commit_amount = 0
                forecast.closed_amount = 0
                forecast.actual_amount = 0
                forecast.gap_amount = 0

        forecast.performance_percentage = 0
        forecast.gap_percentage = 0
        forecast.closed_percentage = 0
        forecast.closed_deals_count = 0
        forecast.currency_symbol = currency_symbol

        return forecast

    def extract_target_from_bulk(self, targets_data, period, user_id):
        """Helper to extract target from bulk loaded data"""
        if user_id:
            target = targets_data.get(period.id)
            if target:
                return target
            return None

        period_targets = targets_data.get(period.id, [])
        total_target = sum(target.target_amount for target in period_targets)

        if total_target > 0:

            class AggregatedTarget:
                """Wrapper for summed target amounts from multiple period targets."""

                def __init__(self, target_amount):
                    self.target_amount = target_amount

            return AggregatedTarget(total_target)
        return None

    def calculate_trend_direction(self, current, previous):
        """Helper to calculate trend direction"""
        if current > previous:
            return "up"
        if current < previous:
            return "down"
        return None

    def format_change_text(
        self, current, previous, period_name, is_quantity_based, currency
    ):
        """Helper to format change text"""
        if current == previous:
            return f"No change from {period_name}"

        change = abs(current - previous)
        direction = "increased" if current > previous else "decreased"
        unit = "deals" if is_quantity_based else currency or "USD"

        return f"{direction.title()} by {change:,.0f} {unit} from {period_name}"

    def get_user_specific_trend_data(
        self, user_id, period_id, previous_period_id, user_period_data, forecast_type
    ):
        """
        Calculate trend data for a specific user between two periods
        """
        user_data = user_period_data.get(user_id, {})
        current_data = user_data.get(
            period_id, {"commit": 0, "best_case": 0, "pipeline": 0, "closed": 0}
        )
        previous_data = user_data.get(
            previous_period_id,
            {"commit": 0, "best_case": 0, "pipeline": 0, "closed": 0},
        )

        # Look up the previous period name from user_period_data (already in memory)
        # to avoid a per-call DB query.
        previous_period_name = ""
        for owner_data in user_period_data.values():
            period_entry = owner_data.get(previous_period_id)
            if period_entry and period_entry.get("name"):
                previous_period_name = period_entry["name"]
                break
        if not previous_period_name:
            _prev = Period.objects.filter(id=previous_period_id).values("name").first()
            previous_period_name = _prev["name"] if _prev else ""

        return {
            "commit_trend": self.calculate_trend_direction(
                current_data["commit"], previous_data["commit"]
            ),
            "best_case_trend": self.calculate_trend_direction(
                current_data["best_case"], previous_data["best_case"]
            ),
            "pipeline_trend": self.calculate_trend_direction(
                current_data["pipeline"], previous_data["pipeline"]
            ),
            "closed_trend": self.calculate_trend_direction(
                current_data["closed"], previous_data["closed"]
            ),
            "commit_change_text": self.format_change_text(
                current_data["commit"],
                previous_data["commit"],
                previous_period_name,
                forecast_type.is_quantity_based,
                self.get_company_for_user.currency,
            ),
            "best_case_change_text": self.format_change_text(
                current_data["best_case"],
                previous_data["best_case"],
                previous_period_name,
                forecast_type.is_quantity_based,
                self.get_company_for_user.currency,
            ),
            "pipeline_change_text": self.format_change_text(
                current_data["pipeline"],
                previous_data["pipeline"],
                previous_period_name,
                forecast_type.is_quantity_based,
                self.get_company_for_user.currency,
            ),
            "closed_change_text": self.format_change_text(
                current_data["closed"],
                previous_data["closed"],
                previous_period_name,
                forecast_type.is_quantity_based,
                self.get_company_for_user.currency,
            ),
        }

    def get_bulk_trend_data(
        self,
        periods,
        forecast_type,
        user_id=None,
        prefetched_forecasts=None,
        period_agg=None,
    ):
        """
        Build period-over-period trend data.
        - prefetched_forecasts: list of Forecast objects (single-user path) — no extra query.
        - period_agg: dict of period_id → DB aggregation row (multi-user path) — no extra query.
        - Falls back to a DB query only when neither is provided.
        """
        if len(periods) < 2:
            return {}

        field_suffix = "quantity" if forecast_type.is_quantity_based else "amount"

        period_data = {}
        user_period_data = {}

        if period_agg is not None:
            # Multi-user path: period-level totals come from DB aggregation sums (no query).
            # Per-user data for expanded rows comes from prefetched_forecasts when provided.
            for p in periods:
                row = period_agg.get(p.id, {})
                period_data[p.id] = {
                    "period_number": p.period_number,
                    "commit": float(row.get("sum_commit") or 0),
                    "best_case": float(row.get("sum_best_case") or 0),
                    "pipeline": float(row.get("sum_pipeline") or 0),
                    "closed": float(row.get("sum_closed") or 0),
                }
            # Build per-user data from paginated rows so expanded user rows get real trends
            if prefetched_forecasts:
                period_map = {p.id: p for p in periods}
                all_rows = []
                for f in prefetched_forecasts:
                    p = period_map.get(f.period_id)
                    all_rows.append(
                        {
                            "period_id": f.period_id,
                            "period__period_number": p.period_number if p else 0,
                            "period__name": p.name if p else "",
                            "owner_id": f.owner_id,
                            f"commit_{field_suffix}": getattr(
                                f, f"commit_{field_suffix}", 0
                            ),
                            f"best_case_{field_suffix}": getattr(
                                f, f"best_case_{field_suffix}", 0
                            ),
                            f"pipeline_{field_suffix}": getattr(
                                f, f"pipeline_{field_suffix}", 0
                            ),
                            f"closed_{field_suffix}": getattr(
                                f, f"closed_{field_suffix}", 0
                            ),
                        }
                    )
            else:
                all_rows = []
        elif prefetched_forecasts is not None:
            # Single-user path: build from already-fetched objects — zero extra DB queries
            period_map = {p.id: p for p in periods}
            all_rows = []
            for f in prefetched_forecasts:
                p = period_map.get(f.period_id)
                all_rows.append(
                    {
                        "period_id": f.period_id,
                        "period__period_number": p.period_number if p else 0,
                        "period__name": p.name if p else "",
                        "owner_id": f.owner_id,
                        f"commit_{field_suffix}": getattr(
                            f, f"commit_{field_suffix}", 0
                        ),
                        f"best_case_{field_suffix}": getattr(
                            f, f"best_case_{field_suffix}", 0
                        ),
                        f"pipeline_{field_suffix}": getattr(
                            f, f"pipeline_{field_suffix}", 0
                        ),
                        f"closed_{field_suffix}": getattr(
                            f, f"closed_{field_suffix}", 0
                        ),
                    }
                )
        else:
            query_params = {
                "forecast_type": forecast_type,
                "period__in": periods,
            }
            if user_id:
                query_params["owner_id"] = user_id

            all_rows = Forecast.objects.filter(**query_params).values(
                "period_id",
                "period__period_number",
                "period__name",
                "owner_id",
                (
                    "commit_quantity"
                    if forecast_type.is_quantity_based
                    else "commit_amount"
                ),
                (
                    "best_case_quantity"
                    if forecast_type.is_quantity_based
                    else "best_case_amount"
                ),
                (
                    "pipeline_quantity"
                    if forecast_type.is_quantity_based
                    else "pipeline_amount"
                ),
                (
                    "closed_quantity"
                    if forecast_type.is_quantity_based
                    else "closed_amount"
                ),
            )

        for forecast in all_rows:
            period_id = forecast["period_id"]
            owner_id = forecast["owner_id"]

            # When period_agg is provided, period_data already holds the correct
            # DB-aggregated totals (across all active users) from above — adding
            # the paginated-user rows again here would double-count them.
            if period_agg is None:
                if period_id not in period_data:
                    period_data[period_id] = {
                        "period_number": forecast["period__period_number"],
                        "commit": 0,
                        "best_case": 0,
                        "pipeline": 0,
                        "closed": 0,
                    }

                period_data[period_id]["commit"] += float(
                    forecast.get(f"commit_{field_suffix}", 0) or 0
                )
                period_data[period_id]["best_case"] += float(
                    forecast.get(f"best_case_{field_suffix}", 0) or 0
                )
                period_data[period_id]["pipeline"] += float(
                    forecast.get(f"pipeline_{field_suffix}", 0) or 0
                )
                period_data[period_id]["closed"] += float(
                    forecast.get(f"closed_{field_suffix}", 0) or 0
                )

            if owner_id not in user_period_data:
                user_period_data[owner_id] = {}

            if period_id not in user_period_data[owner_id]:
                user_period_data[owner_id][period_id] = {
                    "period_number": forecast["period__period_number"],
                    "name": forecast.get("period__name", ""),
                    "commit": 0,
                    "best_case": 0,
                    "pipeline": 0,
                    "closed": 0,
                }

            user_period_data[owner_id][period_id]["commit"] = float(
                forecast.get(f"commit_{field_suffix}", 0) or 0
            )
            user_period_data[owner_id][period_id]["best_case"] = float(
                forecast.get(f"best_case_{field_suffix}", 0) or 0
            )
            user_period_data[owner_id][period_id]["pipeline"] = float(
                forecast.get(f"pipeline_{field_suffix}", 0) or 0
            )
            user_period_data[owner_id][period_id]["closed"] = float(
                forecast.get(f"closed_{field_suffix}", 0) or 0
            )

        # Calculate trends
        trend_results = {}
        sorted_periods = sorted(periods, key=lambda p: p.start_date)

        for i, period in enumerate(sorted_periods):
            if i == 0:  # First period has no previous data
                continue

            current_data = period_data.get(
                period.id, {"commit": 0, "best_case": 0, "pipeline": 0, "closed": 0}
            )
            previous_period = sorted_periods[i - 1]
            previous_data = period_data.get(
                previous_period.id,
                {"commit": 0, "best_case": 0, "pipeline": 0, "closed": 0},
            )

            # Period-level trends (for main aggregated row)
            trend_results[period.id] = {
                "commit_trend": self.calculate_trend_direction(
                    current_data["commit"], previous_data["commit"]
                ),
                "best_case_trend": self.calculate_trend_direction(
                    current_data["best_case"], previous_data["best_case"]
                ),
                "pipeline_trend": self.calculate_trend_direction(
                    current_data["pipeline"], previous_data["pipeline"]
                ),
                "closed_trend": self.calculate_trend_direction(
                    current_data["closed"], previous_data["closed"]
                ),
                "commit_change_text": self.format_change_text(
                    current_data["commit"],
                    previous_data["commit"],
                    previous_period.name,
                    forecast_type.is_quantity_based,
                    self.get_company_for_user.currency,
                ),
                "best_case_change_text": self.format_change_text(
                    current_data["best_case"],
                    previous_data["best_case"],
                    previous_period.name,
                    forecast_type.is_quantity_based,
                    self.get_company_for_user.currency,
                ),
                "pipeline_change_text": self.format_change_text(
                    current_data["pipeline"],
                    previous_data["pipeline"],
                    previous_period.name,
                    forecast_type.is_quantity_based,
                    self.get_company_for_user.currency,
                ),
                "closed_change_text": self.format_change_text(
                    current_data["closed"],
                    previous_data["closed"],
                    previous_period.name,
                    forecast_type.is_quantity_based,
                    self.get_company_for_user.currency,
                ),
                "user_data": user_period_data,
                "previous_period_id": previous_period.id,
                "previous_period_name": previous_period.name,
            }

        return trend_results

    def enhance_forecast_data_bulk(
        self,
        forecast,
        currency_symbol,
        period=None,
        forecast_type=None,
        trend_data=None,
    ):
        """
        FIXED: Enhanced forecast data with proper individual user trend handling
        """
        gap_to_target = (
            (forecast.target_quantity - forecast.actual_quantity)
            if forecast.forecast_type.is_quantity_based
            and hasattr(forecast, "target_quantity")
            and forecast.target_quantity
            and forecast.actual_quantity
            else (
                (forecast.target_amount - forecast.actual_amount)
                if hasattr(forecast, "target_amount")
                and forecast.target_amount
                and forecast.actual_amount
                else 0
            )
        )

        is_on_track = (
            forecast.actual_quantity >= forecast.commit_quantity
            if forecast.forecast_type.is_quantity_based
            and forecast.actual_quantity
            and forecast.commit_quantity
            else (
                forecast.actual_amount >= forecast.commit_amount
                if forecast.actual_amount and forecast.commit_amount
                else False
            )
        )

        forecast.gap_to_target = gap_to_target
        forecast.is_on_track = is_on_track
        forecast.currency_symbol = currency_symbol

        if (
            trend_data
            and period
            and period.id in trend_data
            and hasattr(forecast, "owner")
            and forecast.owner
        ):
            period_trend_data = trend_data[period.id]

            if (
                "user_data" in period_trend_data
                and "previous_period_id" in period_trend_data
            ):
                user_data = period_trend_data["user_data"].get(forecast.owner.id, {})
                previous_period_id = period_trend_data["previous_period_id"]

                current_user_data = user_data.get(
                    period.id, {"commit": 0, "best_case": 0, "pipeline": 0, "closed": 0}
                )
                previous_user_data = user_data.get(
                    previous_period_id,
                    {"commit": 0, "best_case": 0, "pipeline": 0, "closed": 0},
                )

                forecast.commit_trend = self.calculate_trend_direction(
                    current_user_data["commit"], previous_user_data["commit"]
                )
                forecast.best_case_trend = self.calculate_trend_direction(
                    current_user_data["best_case"], previous_user_data["best_case"]
                )
                forecast.pipeline_trend = self.calculate_trend_direction(
                    current_user_data["pipeline"], previous_user_data["pipeline"]
                )
                forecast.closed_trend = self.calculate_trend_direction(
                    current_user_data["closed"], previous_user_data["closed"]
                )

                previous_period_name = period_trend_data.get("previous_period_name", "")
                if previous_period_name:
                    forecast.commit_change_text = self.format_change_text(
                        current_user_data["commit"],
                        previous_user_data["commit"],
                        previous_period_name,
                        forecast_type.is_quantity_based,
                        self.get_company_for_user.currency,
                    )
                    forecast.best_case_change_text = self.format_change_text(
                        current_user_data["best_case"],
                        previous_user_data["best_case"],
                        previous_period_name,
                        forecast_type.is_quantity_based,
                        self.get_company_for_user.currency,
                    )
                    forecast.pipeline_change_text = self.format_change_text(
                        current_user_data["pipeline"],
                        previous_user_data["pipeline"],
                        previous_period_name,
                        forecast_type.is_quantity_based,
                        self.get_company_for_user.currency,
                    )
                    forecast.closed_change_text = self.format_change_text(
                        current_user_data["closed"],
                        previous_user_data["closed"],
                        previous_period_name,
                        forecast_type.is_quantity_based,
                        self.get_company_for_user.currency,
                    )
                else:
                    forecast.commit_change_text = ""
                    forecast.best_case_change_text = ""
                    forecast.pipeline_change_text = ""
                    forecast.closed_change_text = ""
            else:
                # Use period-level trends as fallback
                forecast.commit_trend = period_trend_data.get("commit_trend")
                forecast.best_case_trend = period_trend_data.get("best_case_trend")
                forecast.pipeline_trend = period_trend_data.get("pipeline_trend")
                forecast.closed_trend = period_trend_data.get("closed_trend")
                forecast.commit_change_text = period_trend_data.get(
                    "commit_change_text", ""
                )
                forecast.best_case_change_text = period_trend_data.get(
                    "best_case_change_text", ""
                )
                forecast.pipeline_change_text = period_trend_data.get(
                    "pipeline_change_text", ""
                )
                forecast.closed_change_text = period_trend_data.get(
                    "closed_change_text", ""
                )
        else:
            # No trend data available
            forecast.commit_trend = None
            forecast.best_case_trend = None
            forecast.pipeline_trend = None
            forecast.closed_trend = None
            forecast.commit_change_text = ""
            forecast.best_case_change_text = ""
            forecast.pipeline_change_text = ""
            forecast.closed_change_text = ""

        return forecast

    def create_empty_user_forecast(
        self, period, forecast_type, user_id, currency_symbol, target=None
    ):
        """Create a placeholder forecast for a user with no data."""

        class EmptyUserForecast:
            """Placeholder forecast with zero values for users without data."""

            def __init__(self):
                self.id = f"empty_{period.id}_{user_id}"
                self.period = period
                self.quarter = period.quarter
                self.fiscal_year = period.quarter.fiscal_year
                self.forecast_type = forecast_type
                self.currency_symbol = currency_symbol
                self.owner = User.objects.get(id=user_id)

                if target and forecast_type.is_quantity_based:
                    self.target_quantity = target.target_amount
                    self.pipeline_quantity = 0
                    self.best_case_quantity = 0
                    self.commit_quantity = 0
                    self.closed_quantity = 0
                    self.actual_quantity = 0
                    self.gap_quantity = self.target_quantity
                elif target:
                    self.target_amount = target.target_amount
                    self.pipeline_amount = 0
                    self.best_case_amount = 0
                    self.commit_amount = 0
                    self.closed_amount = 0
                    self.actual_amount = 0
                    self.gap_amount = self.target_amount
                else:
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

        empty_forecast = EmptyUserForecast()
        aggregated_forecast = self.create_aggregated_forecast(
            period, forecast_type, [empty_forecast], currency_symbol, user_id, target
        )
        aggregated_forecast.user_forecasts = []
        return aggregated_forecast

    def build_period_role_rows(
        self,
        period,
        forecast_type,
        currency_symbol,
        role_nodes,
        role_sums,
        role_targets,
        role_drift=None,
    ):
        """
        Team totals per role for one period.

        ``role_nodes`` comes from ``build_forecast_role_tree``. ``role_sums`` maps
        ``(period_id, role_id)`` to that role's own summed measures and
        ``role_targets`` to its summed targets. A node's row adds up its whole subtree,
        so a manager's role includes the roles below it. ``role_drift`` maps
        ``(period_id, role_id)`` to the role total that was entered for that role and
        what its targets add up to now, so a row can flag when they differ.
        """
        suffix = "quantity" if forecast_type.is_quantity_based else "amount"
        measures = ("pipeline", "best_case", "commit", "closed", "actual")

        class AggregatedTarget:
            """Summed target for a role's subtree."""

            def __init__(self, target_amount):
                self.target_amount = target_amount

        class _Totals:
            """Summed measures for a role's subtree."""

        rows = []
        for node in role_nodes:
            totals = _Totals()
            for measure in measures:
                setattr(
                    totals,
                    f"{measure}_{suffix}",
                    sum(
                        (
                            role_sums.get((period.id, role_id), {}).get(measure) or 0
                            for role_id in node["subtree_ids"]
                        ),
                        0,
                    ),
                )
            target = sum(
                (
                    role_targets.get((period.id, role_id)) or 0
                    for role_id in node["subtree_ids"]
                ),
                0,
            )
            row = self.create_aggregated_forecast(
                period,
                forecast_type,
                [totals],
                currency_symbol,
                None,
                AggregatedTarget(target) if target > 0 else None,
            )
            row.role_id = node["id"]
            row.role_name = node["name"]
            row.depth = node["depth"]
            row.parent_role_id = node["parent_id"]
            row.user_count = node["user_count"]
            row.own_users = node["own_users"]
            row.role_target = (role_drift or {}).get((period.id, node["id"]))
            row.has_children = node["has_children"]
            rows.append(row)
        return rows

    def create_aggregated_forecast(
        self,
        period,
        forecast_type,
        user_forecasts,
        currency_symbol,
        _user_id=None,
        target=None,
        closed_deals_count=0,
    ):
        """Create aggregated forecast with optimized calculations and target integration."""

        class AggregatedForecast:
            """
            Aggregated forecast data for a SINGLE period, combining data
            from multiple users for that specific period.
            """

            def __init__(self):
                self.id = f"period_{period.id}"
                self.period = period
                self.quarter = period.quarter
                self.fiscal_year = period.quarter.fiscal_year
                self.forecast_type = forecast_type
                self.currency_symbol = currency_symbol
                self.commit_trend = None
                self.best_case_trend = None
                self.pipeline_trend = None
                self.closed_trend = None
                self.commit_change_text = ""
                self.best_case_change_text = ""
                self.pipeline_change_text = ""
                self.closed_change_text = ""

                # Initialize pagination attributes for multi-user view
                self.has_next = False
                self.next_page = None
                self.view_id = None
                self.user_forecasts = []
                self.role_rows = []

                if target and forecast_type.is_quantity_based:
                    self.target_quantity = (
                        target.target_amount if hasattr(target, "target_amount") else 0
                    )
                    self.pipeline_quantity = 0
                    self.best_case_quantity = 0
                    self.commit_quantity = 0
                    self.closed_quantity = 0
                    self.actual_quantity = 0
                    self.gap_quantity = 0
                elif target:
                    self.target_amount = (
                        target.target_amount if hasattr(target, "target_amount") else 0
                    )
                    self.pipeline_amount = 0
                    self.best_case_amount = 0
                    self.commit_amount = 0
                    self.closed_amount = 0
                    self.actual_amount = 0
                    self.gap_amount = 0
                else:
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

        aggregated = AggregatedForecast()
        aggregated.closed_deals_count = closed_deals_count

        if user_forecasts:
            if forecast_type.is_quantity_based:
                aggregated.pipeline_quantity = sum(
                    f.pipeline_quantity or 0 for f in user_forecasts
                )
                aggregated.best_case_quantity = sum(
                    f.best_case_quantity or 0 for f in user_forecasts
                )
                aggregated.commit_quantity = sum(
                    f.commit_quantity or 0 for f in user_forecasts
                )
                aggregated.closed_quantity = sum(
                    f.closed_quantity or 0 for f in user_forecasts
                )
                aggregated.actual_quantity = sum(
                    f.actual_quantity or 0 for f in user_forecasts
                )

                if aggregated.target_quantity > 0:
                    aggregated.gap_quantity = (
                        aggregated.target_quantity - aggregated.actual_quantity
                    )
                    aggregated.performance_percentage = (
                        aggregated.actual_quantity / aggregated.target_quantity
                    ) * 100
                    aggregated.gap_percentage = (
                        aggregated.gap_quantity / aggregated.target_quantity
                    ) * 100
                    aggregated.closed_percentage = (
                        aggregated.closed_quantity / aggregated.target_quantity
                    ) * 100
            else:
                aggregated.pipeline_amount = sum(
                    f.pipeline_amount or 0 for f in user_forecasts
                )
                aggregated.best_case_amount = sum(
                    f.best_case_amount or 0 for f in user_forecasts
                )
                aggregated.commit_amount = sum(
                    f.commit_amount or 0 for f in user_forecasts
                )
                aggregated.closed_amount = sum(
                    f.closed_amount or 0 for f in user_forecasts
                )
                aggregated.actual_amount = sum(
                    f.actual_amount or 0 for f in user_forecasts
                )

                if aggregated.target_amount > 0:
                    aggregated.gap_amount = (
                        aggregated.target_amount - aggregated.actual_amount
                    )
                    aggregated.performance_percentage = (
                        aggregated.actual_amount / aggregated.target_amount
                    ) * 100
                    aggregated.gap_percentage = (
                        aggregated.gap_amount / aggregated.target_amount
                    ) * 100
                    aggregated.closed_percentage = (
                        aggregated.closed_amount / aggregated.target_amount
                    ) * 100

        return aggregated
