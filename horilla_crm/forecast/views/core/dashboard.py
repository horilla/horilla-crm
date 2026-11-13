"""

Django class-based views for managing and displaying sales forecast data in Horilla CRM.
Features: Period-based forecasts, trend analysis, user/aggregated views, optimized queries.
"""

# Third-party imports (Django)
from django.core.cache import cache

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.auth.models import User
from horilla.contrib.core.models import FiscalYearInstance, Period
from horilla.contrib.core.services.fiscal_year_service import FiscalYearService
from horilla.contrib.generics.views import HorillaTabView
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.views.generic import TemplateView

# Local imports
from horilla_crm.forecast.models import ForecastType


class ForecastView(LoginRequiredMixin, TemplateView):
    """Main forecast dashboard view with fiscal year and user filtering capabilities."""

    template_name = "forecast_view.html"

    def get_context_data(self, **kwargs):
        """Prepare forecast dashboard context with fiscal-year navigation metadata."""
        context = super().get_context_data(**kwargs)

        company = (
            self.request.active_company
            if hasattr(self.request, "active_company") and self.request.active_company
            else (
                self.request.user.company
                if hasattr(self.request.user, "company")
                else None
            )
        )

        forcast_types = (
            ForecastType.all_objects.filter(company=company)
            if company
            else ForecastType.all_objects.none()
        )
        type_count = forcast_types.count()
        fiscal_years = (
            FiscalYearInstance.all_objects.filter(company=company)
            if company
            else FiscalYearInstance.all_objects.none()
        )
        current_instance = fiscal_years.filter(is_current=True).first()

        fiscal_year_id = self.request.GET.get("fiscal_year_id")
        user_id = self.request.GET.get("user_id")

        selected_instance = current_instance
        if fiscal_year_id:
            try:
                selected_instance = FiscalYearInstance.objects.get(id=fiscal_year_id)
            except FiscalYearInstance.DoesNotExist:
                selected_instance = current_instance

        query_params = self.request.GET.copy()
        query_string = query_params.urlencode() if query_params else ""

        context.update(
            {
                # Users dropdown is still permission-driven elsewhere; keep all active users for now.
                "users": User.objects.filter(is_active=True),
                "fiscal_years": fiscal_years,
                "current_instance": current_instance,
                "selected_instance": selected_instance,
                "previous_instance": None,
                "next_instance": None,
                "user_id": user_id,
                "fiscal_year_id": fiscal_year_id,
                "query_string": query_string,
                "type_count": type_count,
            }
        )

        if fiscal_years and selected_instance:
            instances_list = list(fiscal_years)
            try:
                current_index = instances_list.index(selected_instance)
                if current_index > 0:
                    context["previous_instance"] = instances_list[current_index - 1]
                if current_index < len(instances_list) - 1:
                    context["next_instance"] = instances_list[current_index + 1]
            except ValueError:
                pass

        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class ForecastNavbarView(LoginRequiredMixin, TemplateView):
    """Dynamically load forecast navbar/filters."""

    template_name = "forecast_navbar.html"

    def get_context_data(self, **kwargs):
        """Build navbar/filter context including permissions and period range defaults."""
        context = super().get_context_data(**kwargs)

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
            fy_cache_key = f"fy_check_{company.id}"
            if not cache.get(fy_cache_key):
                FiscalYearService.check_and_update_fiscal_years(company=company)
                cache.set(fy_cache_key, True, 600)

        # Forecast page is always active-company scoped.
        forcast_types = (
            ForecastType.all_objects.filter(company=company)
            if company
            else ForecastType.all_objects.none()
        )
        type_count = forcast_types.count()
        fiscal_years = (
            FiscalYearInstance.all_objects.filter(company=company)
            if company
            else FiscalYearInstance.all_objects.none()
        )
        current_instance = fiscal_years.filter(is_current=True).first()

        fiscal_year_id = self.request.GET.get("fiscal_year_id")
        user_id = self.request.GET.get("user_id")

        selected_instance = current_instance
        if fiscal_year_id:
            try:
                selected_instance = FiscalYearInstance.objects.get(id=fiscal_year_id)
            except FiscalYearInstance.DoesNotExist:
                selected_instance = current_instance

        query_params = self.request.GET.copy()
        query_string = query_params.urlencode() if query_params else ""
        periods_qs = Period.all_objects.select_related(
            "quarter",
            "quarter__fiscal_year",
            "quarter__fiscal_year__fiscal_year_config",
        ).order_by("quarter__fiscal_year__start_date", "period_number")
        if company:
            periods_qs = periods_qs.filter(company=company)
        periods = list(periods_qs)

        beginning_period_id = self.request.GET.get("beginning_period_id") or None
        ending_period_id = self.request.GET.get("ending_period_id") or None

        # If user hasn't chosen a range yet, default to the full range of the selected fiscal year
        if (
            selected_instance
            and periods
            and (not beginning_period_id or not ending_period_id)
        ):
            fy_periods = [
                p
                for p in periods
                if getattr(p.quarter.fiscal_year, "id", None) == selected_instance.id
            ]
            if fy_periods:
                if not beginning_period_id:
                    beginning_period_id = str(fy_periods[0].id)
                if not ending_period_id:
                    ending_period_id = str(fy_periods[-1].id)

        period_range_begin = None
        period_range_end = None
        if periods and beginning_period_id and ending_period_id:
            period_range_begin = next(
                (p for p in periods if str(p.id) == str(beginning_period_id)), None
            )
            period_range_end = next(
                (p for p in periods if str(p.id) == str(ending_period_id)), None
            )

        # Ending-period choices: only periods at or after the selected beginning period
        ending_periods = periods
        if periods and beginning_period_id:
            try:
                begin_idx = next(
                    i
                    for i, p in enumerate(periods)
                    if str(p.id) == str(beginning_period_id)
                )
                ending_periods = periods[begin_idx:]
            except StopIteration:
                ending_periods = periods

        # Check permissions
        has_view_all = self.request.user.has_perm("opportunities.view_opportunity")
        has_view_own = self.request.user.has_perm("opportunities.view_own_opportunity")

        # Determine user list and default selection based on permissions
        if has_view_all:
            # User can view all opportunities - show all users
            users = User.objects.filter(is_active=True)
            show_all_users_option = True
            # If no user_id is specified, don't force one (show all by default)
            if not user_id:
                user_id = None
        elif has_view_own:
            # User can only view their own opportunities - restrict to current user only
            users = User.objects.filter(id=self.request.user.id, is_active=True)
            show_all_users_option = False
            # Force user_id to be the current user
            user_id = str(self.request.user.pk)
        else:
            # No permission - empty queryset
            users = User.objects.none()
            show_all_users_option = False
            user_id = None

        context.update(
            {
                "users": users,
                "fiscal_years": fiscal_years,
                "current_instance": current_instance,
                "selected_instance": selected_instance,
                "user_id": user_id,
                "fiscal_year_id": fiscal_year_id,
                "query_string": query_string,
                "type_count": type_count,
                "show_all_users_option": show_all_users_option,
                "has_view_all": has_view_all,
                "has_view_own": has_view_own,
                "periods": periods,
                "beginning_period_id": beginning_period_id,
                "ending_period_id": ending_period_id,
                "period_range_begin": period_range_begin,
                "period_range_end": period_range_end,
                "ending_periods": ending_periods,
            }
        )

        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class ForecastTabView(LoginRequiredMixin, HorillaTabView):
    """Tabbed interface view for organizing different forecast types within a company."""

    view_id = "forecast-tab-view"
    background_class = "rounded-md"
    tab_class = "h-[calc(_100vh_-_270px_)] overflow-x-auto custom-scroll"

    def setup(self, request, *args, **kwargs):
        """Initialize tab configuration before rendering the tab view."""
        super().setup(request, *args, **kwargs)
        self.tabs = self.get_forecast_tabs()

    def get_forecast_tabs(self):
        """Generate tab configuration for each active forecast type with URLs and IDs."""
        tabs = []
        company = None
        if self.request.user.is_authenticated:
            company = (
                self.request.active_company
                if self.request.active_company
                else self.request.user.company
            )
        # Forecast page is always active-company scoped, even if "show all companies" is enabled globally.
        forecast_types = (
            ForecastType.all_objects.filter(is_active=True, company=company).order_by(
                "created_at"
            )
            if company
            else ForecastType.all_objects.none()
        )

        for index, forecast_type in enumerate(forecast_types, 1):
            url = reverse_lazy(
                "forecast:forecast_type_tab_view", kwargs={"pk": forecast_type.id}
            )
            tab = {
                "title": forecast_type.name or f"Forecast {index}",
                "url": url,
                "target": f"forecast-{forecast_type.id}-content",
                "id": f"forecast-{forecast_type.id}-view",
            }
            tabs.append(tab)
        return tabs
