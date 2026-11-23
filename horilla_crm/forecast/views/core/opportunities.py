"""Forecast opportunities modal view."""

# Standard library imports
from urllib.parse import urlencode

# Third-party imports (Django)
from django.template.loader import render_to_string

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.models import FiscalYearInstance, Period
from horilla.contrib.generics.views import HorillaListView
from horilla.contrib.utils.middlewares import get_active_company
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import HttpNotFound

# Local imports
from horilla_crm.forecast.models import Forecast, ForecastType
from horilla_crm.forecast.utils import get_forecast_owner_scope, resolve_forecast_scope
from horilla_crm.opportunities.models import Opportunity


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "opportunities.view_opportunity",
            "opportunities.view_own_opportunity",
        ],
    ),
    name="dispatch",
)
class ForecastOpportunitiesView(LoginRequiredMixin, View):
    """HTMX-enabled modal view for displaying opportunities categorized by forecast type."""

    def col_attrs(self):
        """Return column attributes for forecast opportunities view."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {}
        if self.request.user.has_perm(
            "opportunities.view_opportunity"
        ) or self.request.user.has_perm("opportunities.view_own_opportunity"):
            attrs = {
                "hx-get": f"{{get_detail_url}}?{query_string}",
                "hx-target": "#mainContent",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "hx-on:click": "closeContentModal()",
                "hx-select": "#mainContent",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }
        return [
            {
                "name": {
                    **attrs,
                }
            }
        ]

    def get(self, request, forecast_id=None, opportunity_type=None):
        """
        Handle GET requests to display opportunities modal content with categorized
        opportunities and list views.
        """
        owner_ids, user_id, allowed = resolve_forecast_scope(
            request.user, request.GET.get("user_id")
        )
        if not allowed:
            return render(request, "403.html")
        has_view_all = request.user.has_perm("opportunities.view_opportunity")
        has_view_own = request.user.has_perm("opportunities.view_own_opportunity")
        try:
            if forecast_id == "total":
                fiscal_year_id = request.GET.get("fiscal_year_id")
                fiscal_year = (
                    FiscalYearInstance.objects.get(id=fiscal_year_id)
                    if fiscal_year_id
                    and FiscalYearInstance.objects.filter(id=fiscal_year_id).exists()
                    else FiscalYearInstance.objects.filter(is_current=True).first()
                )

                class TotalForecastObject:
                    """Pseudo-forecast representing aggregated data across all periods."""

                    def __init__(self, fiscal_year):
                        self.id = "total"
                        self.fiscal_year = fiscal_year
                        self.period = None  # No specific period for total
                        self.forecast_type = ForecastType.objects.filter(
                            id=request.GET.get("forecast_type_id")
                        ).first()

                forecast = TotalForecastObject(fiscal_year)
            else:
                forecast = self.get_forecast_object(forecast_id)

                # view_own users may open forecasts owned by themselves or subordinates
                if owner_ids is not None:
                    if hasattr(forecast, "owner") and forecast.owner:
                        if forecast.owner.id not in owner_ids:
                            return render(request, "403.html")

            company = get_active_company(request)
            currency_symbol = company.currency if company else "USD"

            opportunity_types = [
                {"key": "closed", "display_name": _("Closed")},
                {"key": "committed", "display_name": _("Committed")},
                {"key": "best_case", "display_name": _("Best Case")},
                {"key": "open_pipeline", "display_name": _("Open Pipeline")},
            ]

            page = request.GET.get("page")

            for type_info in opportunity_types:
                if page and type_info["key"] != opportunity_type:
                    continue

                type_info["opportunities"] = self.get_opportunities_by_type(
                    forecast, type_info["key"], user_id
                )
                columns = ["name"]
                if (
                    hasattr(forecast, "forecast_type")
                    and forecast.forecast_type
                    and forecast.forecast_type.is_quantity_based
                ):
                    columns.append("quantity")
                else:
                    columns.append("amount")
                columns.extend(
                    [
                        "close_date",
                        ("Stage", "stage__name"),
                    ]
                )
                if type_info["key"] != "closed":
                    columns.append("probability")

                list_view = HorillaListView(
                    model=Opportunity,
                    view_id=f"forecast-opportunities-{type_info['key']}",
                    search_url=reverse_lazy(
                        "forecast:forecast_opportunities",
                        kwargs={
                            "forecast_id": forecast_id or "total",
                            "opportunity_type": type_info["key"],
                        },
                    ),
                    main_url=reverse_lazy(
                        "forecast:forecast_opportunities",
                        kwargs={
                            "forecast_id": forecast_id or "total",
                            "opportunity_type": type_info["key"],
                        },
                    ),
                    table_width=False,
                    columns=columns,
                    table_height_as_class="h-[400px]",
                    bulk_select_option=False,
                    list_column_visibility=False,
                    bulk_delete_enabled=False,
                    bulk_update_option=False,
                    enable_sorting=False,
                    save_to_list_option=False,
                    apply_pinned_view_default=False,
                )

                list_view.get_queryset = lambda ti=type_info: ti[
                    "opportunities"
                ].select_related("stage")
                no_record_msg = (
                    f"There are no '{type_info['display_name']}' opportunities "
                    "for this period."
                )
                list_view.request = request
                list_view.object_list = type_info["opportunities"]
                list_view.no_record_msg = no_record_msg
                list_view.col_attrs = self.col_attrs()
                list_context = list_view.get_context_data()

                if page and type_info["key"] == opportunity_type:
                    return render(request, "list_view.html", list_context)

                type_info["list_view_html"] = render_to_string(
                    "list_view.html", list_context, request=request
                )

            opportunities = self.get_opportunities_by_type(
                forecast, opportunity_type, user_id
            )

            context = {
                "opportunities": opportunities,
                "opportunity_type": opportunity_type,
                "opportunity_types": opportunity_types,
                "forecast": forecast,
                "currency_symbol": currency_symbol,
                "forecast_type": (
                    forecast.forecast_type
                    if hasattr(forecast, "forecast_type")
                    else None
                ),
                "user_id": user_id,
                "fiscal_year_id": request.GET.get("fiscal_year_id"),
                "has_view_all": has_view_all,
                "has_view_own": has_view_own,
            }

            return render(request, "forecast_opportunities_modal_content.html", context)

        except Exception as e:
            raise HttpNotFound(e) from e

    def get_forecast_object(self, forecast_id):
        """
        Generate tab configuration for each active forecast type in the company.
        Returns list of tab dictionaries with title, URL, target, and ID.
        """
        fiscal_year_id = self.request.GET.get("fiscal_year_id")
        fiscal_year = (
            FiscalYearInstance.objects.get(id=fiscal_year_id)
            if fiscal_year_id
            and FiscalYearInstance.objects.filter(id=fiscal_year_id).exists()
            else FiscalYearInstance.objects.filter(is_current=True).first()
        )

        if forecast_id.startswith("period_"):
            period_id = forecast_id.replace("period_", "")
            period = get_object_or_404(
                Period, id=period_id, quarter__fiscal_year=fiscal_year
            )

            class ForecastObject:
                """Pseudo-forecast constructed from a period for aggregated views."""

                def __init__(self, period):
                    self.id = forecast_id
                    self.period = period
                    self.quarter = period.quarter
                    self.fiscal_year = period.quarter.fiscal_year
                    self.forecast_type = (
                        period.forecast_type
                        if hasattr(period, "forecast_type")
                        else None
                    )

            return ForecastObject(period)

        try:
            forecast = get_object_or_404(
                Forecast, id=forecast_id, fiscal_year=fiscal_year
            )
        except Exception as e:
            raise HttpNotFound(e) from e

        return forecast

    def get_opportunities_by_type(self, forecast, opportunity_type, user_id=None):
        """
        Get opportunities based on the type requested
        """
        base_queryset = self.get_base_opportunity_queryset(forecast, user_id)

        if opportunity_type == "closed":
            return base_queryset.filter(stage__stage_type="won").select_related(
                "account", "stage"
            )

        if opportunity_type == "committed":
            return base_queryset.filter(
                forecast_category="commit", stage__stage_type="open"
            ).select_related("account", "stage")

        if opportunity_type == "best_case":
            return base_queryset.filter(
                forecast_category__in=["best_case", "commit"], stage__stage_type="open"
            ).select_related("account", "stage")

        if opportunity_type == "open_pipeline":
            return base_queryset.filter(
                forecast_category="pipeline", stage__stage_type="open"
            ).select_related("account", "stage")

        return base_queryset.none()

    def get_base_opportunity_queryset(self, forecast, user_id=None):
        """
        Get base queryset for opportunities in this forecast period or all periods for 'total'
        """
        owner_ids = get_forecast_owner_scope(self.request.user)

        if forecast.id == "total":
            # For total, include all opportunities in the fiscal year
            queryset = Opportunity.objects.filter(
                close_date__gte=forecast.fiscal_year.start_date,
                close_date__lte=forecast.fiscal_year.end_date,
            )
        else:
            queryset = Opportunity.objects.filter(
                close_date__gte=forecast.period.start_date,
                close_date__lte=forecast.period.end_date,
            )

        # Enforce view_own scope (self plus subordinates), then the chosen user
        if owner_ids is not None:
            queryset = queryset.filter(owner_id__in=owner_ids)
        if user_id:
            queryset = queryset.filter(owner_id=user_id)

        if (
            hasattr(forecast, "id")
            and not str(forecast.id).startswith("period_")
            and not forecast.id == "total"
            and hasattr(forecast, "owner")
            and forecast.owner
        ):
            queryset = queryset.filter(owner=forecast.owner)

        return queryset
