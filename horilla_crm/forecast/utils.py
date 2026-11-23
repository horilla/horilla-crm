"""
ForecastCalculator Utility for Horilla CRM

Provides automatic calculation, creation, and updating of forecasts
(amount, expected revenue, or quantity) for users and periods based on
opportunity data and forecast targets.

Features:
- Automatic generation and update of forecasts per user/period.
- Supports bulk operations for performance.
- Handles dynamic conditions with logical AND/OR grouping.
- Computes pipeline, best case, commit, closed, and actual values.
- Fetches and applies targets automatically.
- Caches condition queries for efficiency.
"""

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.models import FiscalYearInstance, Period
from horilla.contrib.core.utils import get_allowed_user_ids
from horilla.contrib.generics.forms.condition_fields import get_extension_condition_q
from horilla.db.models import Q, Sum

# Local imports
from horilla_crm.forecast.models import Forecast, ForecastTarget, ForecastType
from horilla_crm.opportunities.models import Opportunity


class ForecastCalculator:
    """
    utility class to automatically calculate and create/update forecasts
    Enhanced to support all forecast types with bulk operations for better performance
    """

    def __init__(self, user=None, fiscal_year=None):
        self.user = user
        self.fiscal_year = fiscal_year or self.get_current_fiscal_year()
        self._conditions_cache = {}  # Cache for forecast conditions

    def get_current_fiscal_year(self):
        """Get current active fiscal year"""
        return FiscalYearInstance.objects.filter(is_current=True).first()

    def bulk_create_missing_forecasts(self, forecast_type, missing_combinations):
        """
        Bulk create missing forecasts instead of individual creation
        """
        if not missing_combinations:
            return

        # Get all required data in bulk
        user_ids = list(set(combo[0] for combo in missing_combinations))
        period_ids = list(set(combo[1] for combo in missing_combinations))

        users_map = {u.id: u for u in User.objects.filter(id__in=user_ids)}
        periods_map = {
            p.id: p
            for p in Period.objects.filter(id__in=period_ids).select_related("quarter")
        }

        # Get targets in bulk
        targets = ForecastTarget.objects.filter(
            assigned_to_id__in=user_ids,
            period_id__in=period_ids,
            forcasts_type=forecast_type,
            is_active=True,
        ).select_related("assigned_to", "period")

        targets_map = {(t.assigned_to_id, t.period_id): t for t in targets}

        # Prepare forecasts for bulk creation
        forecasts_to_create = []
        for user_id, period_id in missing_combinations:
            user = users_map.get(user_id)
            period = periods_map.get(period_id)

            if not user or not period:
                continue

            target = targets_map.get((user_id, period_id))
            target_amount = target.target_amount if target else 0

            forecast = Forecast(
                company=getattr(self.user, "company", None) if self.user else None,
                owner=user,
                forecast_type=forecast_type,
                period=period,
                quarter=period.quarter,
                fiscal_year=period.quarter.fiscal_year,
                name=f"{forecast_type.name} - {period.name}",
                target_amount=(
                    target_amount if not forecast_type.is_quantity_based else 0
                ),
                target_quantity=target_amount if forecast_type.is_quantity_based else 0,
                # Initialize other fields to 0
                pipeline_amount=0 if not forecast_type.is_quantity_based else None,
                best_case_amount=0 if not forecast_type.is_quantity_based else None,
                commit_amount=0 if not forecast_type.is_quantity_based else None,
                closed_amount=0 if not forecast_type.is_quantity_based else None,
                actual_amount=0 if not forecast_type.is_quantity_based else None,
                pipeline_quantity=0 if forecast_type.is_quantity_based else None,
                best_case_quantity=0 if forecast_type.is_quantity_based else None,
                commit_quantity=0 if forecast_type.is_quantity_based else None,
                closed_quantity=0 if forecast_type.is_quantity_based else None,
                actual_quantity=0 if forecast_type.is_quantity_based else None,
            )
            forecasts_to_create.append(forecast)

        # Bulk create forecasts
        if forecasts_to_create:
            created_forecasts = Forecast.objects.bulk_create(
                forecasts_to_create, batch_size=1000
            )

            # Now calculate values for the created forecasts in bulk
            self.bulk_calculate_forecast_values(created_forecasts, forecast_type)

    def bulk_calculate_forecast_values(self, forecasts, forecast_type):
        """
        Calculate forecast values for multiple forecasts in bulk
        """
        if not forecasts:
            return

        # Group forecasts by user and period for efficient querying
        user_period_forecasts = {}
        for forecast in forecasts:
            key = (forecast.owner_id, forecast.period_id)
            user_period_forecasts[key] = forecast

        # Get all opportunities for all users/periods in single query
        user_ids = list(set(f.owner_id for f in forecasts))
        period_data = {}
        for forecast in forecasts:
            if forecast.period_id not in period_data:
                period_data[forecast.period_id] = {
                    "start_date": forecast.period.start_date,
                    "end_date": forecast.period.end_date,
                }

        # Build conditions query once and cache it
        conditions_query = self.get_cached_conditions_query(forecast_type)

        # Get all relevant opportunities in bulk
        opportunities_query = Q(owner_id__in=user_ids)

        # Add date range conditions for all periods
        date_conditions = Q()
        for period_info in period_data.values():
            date_conditions |= Q(
                close_date__range=[period_info["start_date"], period_info["end_date"]]
            )
        opportunities_query &= date_conditions

        if conditions_query:
            opportunities_query &= conditions_query

        opportunities = Opportunity.objects.filter(opportunities_query).values(
            "id",
            "owner_id",
            "close_date",
            "amount",
            "expected_revenue",
            "forecast_category",
            "stage__stage_type",
        )

        # Group forecasts by owner so each opportunity only scans its own
        # owner's periods instead of the full forecast list (users x periods)
        forecasts_by_owner = {}
        for forecast in forecasts:
            forecasts_by_owner.setdefault(forecast.owner_id, []).append(forecast)

        # Group opportunities by user and period
        user_period_opportunities = {}
        for opp in opportunities:
            # Find which period this opportunity belongs to
            for forecast in forecasts_by_owner.get(opp["owner_id"], []):
                if (
                    forecast.period.start_date
                    <= opp["close_date"]
                    <= forecast.period.end_date
                ):
                    key = (opp["owner_id"], forecast.period_id)
                    if key not in user_period_opportunities:
                        user_period_opportunities[key] = []
                    user_period_opportunities[key].append(opp)
                    break

        # Calculate values for each forecast
        forecasts_to_update = []
        for forecast in forecasts:
            key = (forecast.owner_id, forecast.period_id)
            user_opportunities = user_period_opportunities.get(key, [])

            values = self.calculate_values_from_opportunities(
                user_opportunities, forecast_type
            )

            # Update forecast fields based on type
            if forecast_type.is_quantity_based:
                forecast.pipeline_quantity = values["pipeline"]
                forecast.best_case_quantity = values["best_case"]
                forecast.commit_quantity = values["commit"]
                forecast.closed_quantity = values["closed"]
                forecast.actual_quantity = values["actual"]
            else:
                forecast.pipeline_amount = values["pipeline"]
                forecast.best_case_amount = values["best_case"]
                forecast.commit_amount = values["commit"]
                forecast.closed_amount = values["closed"]
                forecast.actual_amount = values["actual"]

            forecasts_to_update.append(forecast)

        # Bulk update forecasts
        if forecasts_to_update:
            fields_to_update = []
            if forecast_type.is_quantity_based:
                fields_to_update = [
                    "pipeline_quantity",
                    "best_case_quantity",
                    "commit_quantity",
                    "closed_quantity",
                    "actual_quantity",
                ]
            else:
                fields_to_update = [
                    "pipeline_amount",
                    "best_case_amount",
                    "commit_amount",
                    "closed_amount",
                    "actual_amount",
                ]

            Forecast.objects.bulk_update(
                forecasts_to_update, fields_to_update, batch_size=1000
            )

    def get_cached_conditions_query(self, forecast_type):
        """
        Cache conditions query to avoid rebuilding for each forecast
        """
        cache_key = f"conditions_{forecast_type.id}"
        if cache_key not in self._conditions_cache:
            self._conditions_cache[cache_key] = self.build_conditions_query(
                forecast_type
            )
        return self._conditions_cache[cache_key]

    def calculate_values_from_opportunities(self, opportunities, forecast_type):
        """
        Calculate values from pre-fetched opportunity data
        """

        if forecast_type.is_quantity_based:
            return self._calculate_quantity_values_from_data(
                opportunities, forecast_type
            )
        if forecast_type.is_revenue_expected_based:
            return self._calculate_expected_amount_values_from_data(
                opportunities, forecast_type
            )
        return self._calculate_amount_values_from_data(opportunities, forecast_type)

    def _calculate_quantity_values_from_data(self, opportunities, forecast_type):
        """Calculate quantity values from opportunity data"""
        values = {
            "pipeline": 0,
            "best_case": 0,
            "commit": 0,
            "closed": 0,
            "actual": 0,
        }

        for opp in opportunities:
            if (
                forecast_type.include_pipeline
                and opp["forecast_category"] == "pipeline"
            ):
                values["pipeline"] += 1
            if (
                forecast_type.include_best_case
                and opp["forecast_category"] == "best_case"
            ):
                values["best_case"] += 1
            if forecast_type.include_commit and opp["forecast_category"] == "commit":
                values["commit"] += 1
            if forecast_type.include_closed and opp["forecast_category"] == "closed":
                values["closed"] += 1
            if opp["stage__stage_type"] == "won":
                values["actual"] += 1

        return values

    def _calculate_expected_amount_values_from_data(self, opportunities, forecast_type):
        """Calculate expected amount values from opportunity data"""
        values = {
            "pipeline": 0,
            "best_case": 0,
            "commit": 0,
            "closed": 0,
            "actual": 0,
        }

        for opp in opportunities:
            expected_revenue = opp["expected_revenue"] or 0
            if (
                forecast_type.include_pipeline
                and opp["forecast_category"] == "pipeline"
            ):
                values["pipeline"] += expected_revenue
            if (
                forecast_type.include_best_case
                and opp["forecast_category"] == "best_case"
            ):
                values["best_case"] += expected_revenue
            if forecast_type.include_commit and opp["forecast_category"] == "commit":
                values["commit"] += expected_revenue
            if forecast_type.include_closed and opp["forecast_category"] == "closed":
                values["closed"] += expected_revenue
            if opp["stage__stage_type"] == "won":
                values["actual"] += expected_revenue

        return values

    def _calculate_amount_values_from_data(self, opportunities, forecast_type):
        """Calculate amount values from opportunity data"""
        values = {
            "pipeline": 0,
            "best_case": 0,
            "commit": 0,
            "closed": 0,
            "actual": 0,
        }

        for opp in opportunities:
            amount = opp["amount"] or 0
            if (
                forecast_type.include_pipeline
                and opp["forecast_category"] == "pipeline"
            ):
                values["pipeline"] += amount
            if (
                forecast_type.include_best_case
                and opp["forecast_category"] == "best_case"
            ):
                values["best_case"] += amount
            if forecast_type.include_commit and opp["forecast_category"] == "commit":
                values["commit"] += amount
            if forecast_type.include_closed and opp["forecast_category"] == "closed":
                values["closed"] += amount
            if opp["stage__stage_type"] == "won":
                values["actual"] += amount

        return values

    # Keep the rest of your existing methods but with optimizations
    def generate_forecasts_for_user(self, user=None, forecast_type=None):
        """Generate/update forecasts for a specific user based on their opportunities"""
        target_user = user or self.user
        if not target_user or not self.fiscal_year:
            return

        if forecast_type:
            forecast_types = [forecast_type]
        else:
            forecast_types = ForecastType.objects.filter(is_active=True)

        periods = Period.objects.filter(quarter__fiscal_year=self.fiscal_year).order_by(
            "period_number"
        )

        for forecast_type_obj in forecast_types:
            for period in periods:
                self.create_or_update_period_forecast(
                    target_user, forecast_type_obj, period
                )

    def create_or_update_period_forecast(self, user, forecast_type, period):
        """Create or update forecast for a specific period automatically"""
        forecast, _created = Forecast.objects.get_or_create(
            company=getattr(user, "company", None),
            owner=user,
            forecast_type=forecast_type,
            period=period,
            quarter=period.quarter,
            fiscal_year=period.quarter.fiscal_year,
            defaults={
                "name": f"{forecast_type.name} - {period.name}",
                "target_amount": self.get_target_for_period(user, period, "amount"),
                "target_quantity": self.get_target_for_period(user, period, "quantity"),
            },
        )

        calculated_data = self.calculate_forecast_values(user, period, forecast_type)

        if forecast_type.is_quantity_based:
            forecast.pipeline_quantity = calculated_data["pipeline"]
            forecast.best_case_quantity = calculated_data["best_case"]
            forecast.commit_quantity = calculated_data["commit"]
            forecast.closed_quantity = calculated_data["closed"]
            forecast.actual_quantity = calculated_data["actual"]

            if not forecast.target_quantity:
                forecast.target_quantity = self.get_target_for_period(
                    user, period, "quantity"
                )

            update_fields = [
                "pipeline_quantity",
                "best_case_quantity",
                "commit_quantity",
                "closed_quantity",
                "actual_quantity",
                "target_quantity",
            ]
        else:
            forecast.pipeline_amount = calculated_data["pipeline"]
            forecast.best_case_amount = calculated_data["best_case"]
            forecast.commit_amount = calculated_data["commit"]
            forecast.closed_amount = calculated_data["closed"]
            forecast.actual_amount = calculated_data["actual"]

            if not forecast.target_amount:
                forecast.target_amount = self.get_target_for_period(
                    user, period, "amount"
                )

            update_fields = [
                "pipeline_amount",
                "best_case_amount",
                "commit_amount",
                "closed_amount",
                "actual_amount",
                "target_amount",
            ]

        forecast.save(update_fields=update_fields)
        return forecast

    def calculate_forecast_values(self, user, period, forecast_type):
        """Calculate forecast values based on opportunities in the period"""
        base_query = Q(
            owner=user, close_date__range=[period.start_date, period.end_date]
        )

        conditions_query = self.get_cached_conditions_query(forecast_type)
        if conditions_query:
            base_query &= conditions_query

        opportunities = Opportunity.objects.filter(base_query)

        if forecast_type.is_quantity_based:
            return self._calculate_quantity_values(opportunities, forecast_type)
        if forecast_type.is_revenue_expected_based:
            return self._calculate_expected_amount_values(opportunities, forecast_type)
        return self._calculate_amount_values(opportunities, forecast_type)

    def build_conditions_query(self, forecast_type):
        """Build Django Q object from horilla_crm.forecastCondition records"""
        conditions = forecast_type.conditions.filter(is_active=True).order_by("order")

        if not conditions.exists():
            return None

        main_query = Q()
        current_group = []
        current_logical_op = "and"

        for condition in conditions:
            condition_q = self.build_single_condition_query(condition)

            if not current_group:
                current_group.append(condition_q)
                current_logical_op = condition.logical_operator
            elif condition.logical_operator == current_logical_op:
                current_group.append(condition_q)
            else:
                if current_group:
                    if current_logical_op == "and":
                        group_query = Q()
                        for cq in current_group:
                            group_query &= cq
                    else:
                        group_query = Q()
                        for cq in current_group:
                            group_query |= cq

                    if not main_query.children and not main_query.negated:
                        main_query = group_query
                    else:
                        main_query &= group_query

                current_group = [condition_q]
                current_logical_op = condition.logical_operator

        if current_group:
            if current_logical_op == "and":
                group_query = Q()
                for cq in current_group:
                    group_query &= cq
            else:
                group_query = Q()
                for cq in current_group:
                    group_query |= cq

            if not main_query.children and not main_query.negated:
                main_query = group_query
            else:
                main_query &= group_query

        return main_query

    def build_single_condition_query(self, condition):
        """Build a single condition query based on field, operator, and value"""
        field = condition.field
        operator = condition.operator
        value = condition.value

        # Fields contributed by other apps (e.g. custom fields) aren't columns.
        extension_q = get_extension_condition_q(Opportunity, field, operator, value)
        if extension_q is not None:
            return extension_q

        operator_map = {
            "equals": {field: value},
            "not_equals": {field: value},
            "contains": {f"{field}__icontains": value},
            "not_contains": {f"{field}__icontains": value},
            "starts_with": {f"{field}__istartswith": value},
            "ends_with": {f"{field}__iendswith": value},
            "greater_than": {f"{field}__gt": self.convert_value(value, field)},
            "greater_than_equal": {f"{field}__gte": self.convert_value(value, field)},
            "less_than": {f"{field}__lt": self.convert_value(value, field)},
            "less_than_equal": {f"{field}__lte": self.convert_value(value, field)},
            "is_empty": {f"{field}__isnull": True},
            "is_not_empty": {f"{field}__isnull": True},
        }

        if operator in ["not_equals", "not_contains"]:
            return ~Q(**operator_map[operator.replace("not_", "")])
        if operator == "is_empty":
            return Q(**{f"{field}__isnull": True}) | Q(**{field: ""})
        if operator == "is_not_empty":
            return ~(Q(**{f"{field}__isnull": True}) | Q(**{field: ""}))
        return Q(**operator_map.get(operator, {field: value}))

    def convert_value(self, value, _field):
        """Convert string value to appropriate type based on field"""
        try:
            if "." in str(value):
                return float(value)
            return int(value)
        except (ValueError, TypeError):
            return value

    def _calculate_quantity_values(self, opportunities, forecast_type):
        """Calculate quantity values (count of deals) by forecast category"""
        values = {
            "pipeline": 0,
            "best_case": 0,
            "commit": 0,
            "closed": 0,
            "actual": 0,
        }

        # Use database aggregation instead of Python loops for better performance
        if forecast_type.include_pipeline:
            values["pipeline"] = opportunities.filter(
                forecast_category="pipeline"
            ).count()
        if forecast_type.include_best_case:
            values["best_case"] = opportunities.filter(
                forecast_category="best_case"
            ).count()
        if forecast_type.include_commit:
            values["commit"] = opportunities.filter(forecast_category="commit").count()
        if forecast_type.include_closed:
            values["closed"] = opportunities.filter(forecast_category="closed").count()

        values["actual"] = opportunities.filter(stage__stage_type="won").count()

        return values

    def _calculate_expected_amount_values(self, opportunities, forecast_type):
        """Calculate expected amount values using expected_revenue field"""
        values = {
            "pipeline": 0,
            "best_case": 0,
            "commit": 0,
            "closed": 0,
            "actual": 0,
        }

        if forecast_type.include_pipeline:
            values["pipeline"] = (
                opportunities.filter(forecast_category="pipeline").aggregate(
                    total=Sum("expected_revenue")
                )["total"]
                or 0
            )

        if forecast_type.include_best_case:
            values["best_case"] = (
                opportunities.filter(forecast_category="best_case").aggregate(
                    total=Sum("expected_revenue")
                )["total"]
                or 0
            )

        if forecast_type.include_commit:
            values["commit"] = (
                opportunities.filter(forecast_category="commit").aggregate(
                    total=Sum("expected_revenue")
                )["total"]
                or 0
            )

        if forecast_type.include_closed:
            values["closed"] = (
                opportunities.filter(forecast_category="closed").aggregate(
                    total=Sum("expected_revenue")
                )["total"]
                or 0
            )

        values["actual"] = (
            opportunities.filter(stage__stage_type="won").aggregate(
                total=Sum("expected_revenue")
            )["total"]
            or 0
        )

        return values

    def _calculate_amount_values(self, opportunities, forecast_type):
        """Calculate actual amount values using amount field"""
        values = {
            "pipeline": 0,
            "best_case": 0,
            "commit": 0,
            "closed": 0,
            "actual": 0,
        }

        if forecast_type.include_pipeline:
            values["pipeline"] = (
                opportunities.filter(forecast_category="pipeline").aggregate(
                    total=Sum("amount")
                )["total"]
                or 0
            )

        if forecast_type.include_best_case:
            values["best_case"] = (
                opportunities.filter(forecast_category="best_case").aggregate(
                    total=Sum("amount")
                )["total"]
                or 0
            )

        if forecast_type.include_commit:
            values["commit"] = (
                opportunities.filter(forecast_category="commit").aggregate(
                    total=Sum("amount")
                )["total"]
                or 0
            )

        if forecast_type.include_closed:
            values["closed"] = (
                opportunities.filter(forecast_category="closed").aggregate(
                    total=Sum("amount")
                )["total"]
                or 0
            )

        values["actual"] = (
            opportunities.filter(stage__stage_type="won").aggregate(
                total=Sum("amount")
            )["total"]
            or 0
        )

        return values

    def get_target_for_period(self, user, period, target_type="amount"):
        """Get target amount or quantity for user in specific period"""
        target = ForecastTarget.objects.filter(
            assigned_to=user, period=period, is_active=True
        ).first()

        if target_type == "quantity":
            return getattr(target, "quantity_target", 0) if target else 0
        return target.target_amount if target else 0

    def bulk_generate_forecasts(self, users=None, periods=None):
        """Bulk generate forecasts for multiple users and periods"""
        if not users:
            users = User.objects.filter(is_active=True)

        if not periods:
            periods = Period.objects.filter(quarter__fiscal_year=self.fiscal_year)

        forecast_types = ForecastType.objects.filter(is_active=True)

        for user in users:
            for forecast_type in forecast_types:
                for period in periods:
                    self.create_or_update_period_forecast(user, forecast_type, period)


def get_forecast_owner_scope(user):
    """
    Return the set of owner ids whose forecasts ``user`` may see.

    ``None`` means unrestricted (``view_opportunity``, which superusers hold).
    With only ``view_own_opportunity`` the scope is the user plus everyone in
    subordinate roles, resolved by ``get_allowed_user_ids``. A user with no
    subordinates therefore sees exactly their own forecast, as before.
    No forecast permission gives an empty set.
    """
    if user.has_perm("opportunities.view_opportunity"):
        return None
    if user.has_perm("opportunities.view_own_opportunity"):
        return set(get_allowed_user_ids(user))
    return set()


def resolve_forecast_scope(user, user_id=None):
    """
    Validate a requested ``user_id`` against the user's forecast scope.

    Returns ``(owner_ids, user_id, allowed)``:
    - ``owner_ids``: scope set, or ``None`` when unrestricted.
    - ``user_id``: the id to filter on as a string, or ``None`` for the
      combined view over ``owner_ids``.
    - ``allowed``: ``False`` when the request must be rejected (403).
    """
    scope = get_forecast_owner_scope(user)
    if scope is None:
        return None, (str(user_id) if user_id else None), True
    if not scope:
        return scope, None, False
    if user_id:
        try:
            requested = int(user_id)
        except (TypeError, ValueError):
            return scope, None, False
        if requested not in scope:
            return scope, None, False
        return scope, str(requested), True
    if len(scope) == 1:
        return scope, str(user.pk), True
    return scope, None, True


def get_assignable_target_user_ids(user):
    """
    Return the user ids ``user`` may set forecast targets for.

    ``None`` means no restriction: superusers, anyone with
    ``view_opportunity`` (who already see every forecast), and users with
    no forecast permission at all, such as a settings admin, so existing
    setups keep working. Only a user holding just ``view_own_opportunity``
    is limited to users in subordinate roles, never themselves: a manager
    sets their reports' targets, and their own comes from the manager above.
    """
    if (
        user.is_superuser
        or user.has_perm("opportunities.view_opportunity")
        or not user.has_perm("opportunities.view_own_opportunity")
    ):
        return None
    return set(get_allowed_user_ids(user)) - {user.pk}


def build_forecast_role_tree(roles, user_counts):
    """
    Lay out the role hierarchy for the forecast table.

    ``roles`` is an iterable of ``(id, name, parent_id)``; ``user_counts`` maps a
    role id (``None`` for users with no role) to the number of in-scope users in it.

    Returns a depth-first list of nodes, each a dict with ``id``, ``name``,
    ``parent_id`` (the nearest shown ancestor), ``depth``, ``subtree_ids`` (the role
    and every role below it), ``own_users`` (users in the role itself),
    ``user_count`` (users in the subtree) and ``has_children``. A role is shown when it has users of its own or branches into
    two or more populated roles; others are skipped, so a manager sees their own role
    as the top row instead of the empty roles above it.
    """
    names, parent_of, children = {}, {}, {}
    for role_id, name, parent_id in roles:
        names[role_id] = name
        parent_of[role_id] = parent_id
    for role_id in sorted(names, key=lambda r: (str(names[r]).lower(), r)):
        children.setdefault(parent_of[role_id], []).append(role_id)

    def descendants(role_id, seen):
        ids = [role_id]
        for child in children.get(role_id, []):
            if child not in seen:
                seen.add(child)
                ids.extend(descendants(child, seen))
        return ids

    populated = {}

    def has_users(role_id, seen=()):
        if role_id in populated:
            return populated[role_id]
        if role_id in seen:  # a role cycle must not recurse forever
            return False
        found = user_counts.get(role_id, 0) > 0
        for child in children.get(role_id, []):
            found = has_users(child, seen + (role_id,)) or found
        populated[role_id] = found
        return found

    nodes = []

    def walk(role_id, depth, shown_parent, visited):
        if role_id in visited or not has_users(role_id):
            return
        visited = visited | {role_id}
        populated_children = [c for c in children.get(role_id, []) if has_users(c)]
        show = user_counts.get(role_id, 0) > 0 or len(populated_children) >= 2
        if show:
            subtree = descendants(role_id, {role_id})
            nodes.append(
                {
                    "id": role_id,
                    "name": names[role_id],
                    "parent_id": shown_parent,
                    "depth": depth,
                    "subtree_ids": subtree,
                    "own_users": user_counts.get(role_id, 0),
                    "user_count": sum(user_counts.get(r, 0) for r in subtree),
                }
            )
            depth, shown_parent = depth + 1, role_id
        for child in children.get(role_id, []):
            walk(child, depth, shown_parent, visited)

    roots = [
        r
        for r in sorted(names, key=lambda r: (str(names[r]).lower(), r))
        if parent_of[r] is None or parent_of[r] not in names
    ]
    for root in roots:
        walk(root, 0, None, frozenset())

    if user_counts.get(None, 0) > 0:
        nodes.append(
            {
                "id": None,
                "name": None,
                "parent_id": None,
                "depth": 0,
                "subtree_ids": [None],
                "own_users": user_counts[None],
                "user_count": user_counts[None],
            }
        )
    for node in nodes:
        node["has_children"] = any(
            other["parent_id"] == node["id"] and other is not node
            for other in nodes
            if node["id"] is not None
        )
    return nodes
