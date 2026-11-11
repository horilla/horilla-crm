"""Views for managing the home page dashboard, including rendering default/dynamic dashboards and saving layout order."""

# Standard library imports
import json
import logging
import re

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.shortcuts import redirect
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView, View
from horilla.web import JsonResponse

from ..get_started import get_onboarding_context

# Local imports
from ..models import Dashboard, DefaultHomeLayoutOrder
from ..utils import (
    DATE_RANGE_CHOICES,
    DefaultDashboardGenerator,
    validate_custom_date_params,
    validate_date_range_request,
)
from ..views import DashboardDetailView

logger = logging.getLogger(__name__)


def _get_default_home_previous_order(user):
    """Return the user's last saved default home layout order, or None if none saved."""

    layout = DefaultHomeLayoutOrder.objects.filter(
        user=user, dashboard__isnull=True
    ).first()
    if layout and isinstance(layout.order, dict):
        return layout.order
    return None


def _build_default_home_order(n_kpi, n_chart, n_table):
    """Return the template default order: KPIs by index, then two charts per table."""

    kpi = [f"default-kpi-{i}" for i in range(n_kpi)]
    blocks = []
    ci, ti = 0, 0
    while ci < n_chart or ti < n_table:
        for _unused in range(2):
            if ci < n_chart:
                blocks.append(f"default-chart-{ci}")
                ci += 1
        if ti < n_table:
            blocks.append(f"default-table-{ti}")
            ti += 1
    return {"kpi": kpi, "chartsAndTables": blocks}


def _get_valid_default_home_layout_ids(user, date_range=None):
    """Return (valid_kpi_ids, valid_block_ids, default_order) from generator counts only."""

    user_company = getattr(user, "company", None)
    generator = DefaultDashboardGenerator(user, user_company, date_range=date_range)
    n_kpi = len(generator.generate_kpi_data())
    n_chart = len(generator.generate_chart_data())
    n_table = len(generator.generate_table_data())
    valid_kpi_ids = {f"default-kpi-{i}" for i in range(n_kpi)}
    valid_block_ids = {f"default-chart-{i}" for i in range(n_chart)} | {
        f"default-table-{i}" for i in range(n_table)
    }
    return (
        valid_kpi_ids,
        valid_block_ids,
        _build_default_home_order(n_kpi, n_chart, n_table),
    )


class HomePageView(LoginRequiredMixin, TemplateView):
    """View to render the home page, showing default or dynamic dashboard."""

    template_name = "home/home.html"

    def get(self, request, *args, **kwargs):
        """Validate date range, then render default or dynamic dashboard as home."""
        redirect_url = validate_date_range_request(request)
        if redirect_url:
            return redirect(redirect_url)

        try:
            default_dashboard = Dashboard.get_default_dashboard(request.user)

            if default_dashboard:
                return self.render_dashboard_as_home(request, default_dashboard)
        except ImportError:
            logger.warning("Dashboard model not found")

        return self.render_dynamic_default_dashboard(request)

    def render_dashboard_as_home(self, request, dashboard):
        """Render the specified dashboard as the home page."""
        try:
            detail_view = DashboardDetailView()
            detail_view.request = request
            detail_view.object = dashboard
            detail_view.kwargs = {"pk": dashboard.pk}

            mutable_get = request.GET.copy()
            mutable_get["section"] = "home"
            mutable_get["is_home"] = "true"
            if "date_range" in request.GET:
                mutable_get["date_range"] = request.GET["date_range"]
            if "date_from" in request.GET:
                mutable_get["date_from"] = request.GET["date_from"]
            if "date_to" in request.GET:
                mutable_get["date_to"] = request.GET["date_to"]
            request.GET = mutable_get

            context = detail_view.get_context_data(object=dashboard)
            template_name = detail_view.get_template_names()[0]

            return self.render_to_response(context, template_name=template_name)
        except ImportError:
            return self.render_dynamic_default_dashboard(request)

    def render_dynamic_default_dashboard(self, _request):
        """Render a dynamic default dashboard on the home page."""
        context = self.get_dynamic_default_context()
        return self.render_to_response(context, template_name="home/home.html")

    def get_dynamic_default_context(self):
        """Generate context data for a dynamic default dashboard."""
        context = super().get_context_data()

        user_company = getattr(self.request.user, "company", None)
        date_range = self.request.GET.get("date_range")
        if date_range == "all":
            date_range = None
        date_from = self.request.GET.get("date_from")
        date_to = self.request.GET.get("date_to")
        date_range, date_from, date_to = validate_custom_date_params(
            date_range, date_from, date_to
        )
        if date_range is None:
            date_from = None
            date_to = None

        generator = DefaultDashboardGenerator(
            self.request.user,
            user_company,
            date_range=date_range,
            date_from=date_from,
            date_to=date_to,
        )

        kpi_data = generator.generate_kpi_data()
        kpi_data.sort(key=lambda k: k.get("title", ""))
        for id, data in enumerate(kpi_data):
            data["order"] = id

        chart_data = generator.generate_chart_data()
        table_data = generator.generate_table_data()

        user_dashboards = []
        try:
            user_dashboards = Dashboard.objects.filter(
                dashboard_owner=self.request.user, is_active=True
            ).order_by("-created_at")[:5]
        except ImportError:
            pass

        base_url = self.request.build_absolute_uri(self.request.path).split("?")[0]
        query_params = self.request.GET.copy()
        query_params.pop("date_range", None)
        query_params.pop("date_from", None)
        query_params.pop("date_to", None)
        base_query = query_params.urlencode()
        date_range_base_url = f"{base_url}?{base_query}" if base_query else base_url

        default_home_order = {}
        user_has_custom_default_home_layout = False
        try:
            layout_order = DefaultHomeLayoutOrder.objects.filter(
                user=self.request.user, dashboard__isnull=True
            ).first()
            if layout_order and isinstance(layout_order.order, dict):
                default_home_order = layout_order.order
                template_default_order = _build_default_home_order(
                    len(kpi_data), len(chart_data or []), len(table_data or [])
                )
                user_has_custom_default_home_layout = (
                    default_home_order != template_default_order
                )
        except Exception:
            pass

        default_home_blocks = []
        chart_list = list(enumerate(chart_data)) if chart_data else []
        table_list = list(enumerate(table_data)) if table_data else []
        ci, ti = 0, 0
        while ci < len(chart_list) or ti < len(table_list):
            for _unused in range(2):
                if ci < len(chart_list):
                    idx, ch = chart_list[ci]
                    default_home_blocks.append(
                        {
                            "type": "chart",
                            "chart_index": idx,
                            "data": ch,
                        }
                    )
                    ci += 1
            if ti < len(table_list):
                idx, tb = table_list[ti]
                default_home_blocks.append(
                    {
                        "type": "table",
                        "table_index": idx,
                        "data": tb,
                    }
                )
                ti += 1

        if default_home_order:
            kpi_order = default_home_order.get("kpi", [])
            charts_tables_order = default_home_order.get("chartsAndTables", [])

            try:
                if kpi_order and kpi_data:
                    kpi_dict = {f"default-kpi-{kpi['order']}": kpi for kpi in kpi_data}
                    kpi_data = [kpi_dict[key] for key in kpi_order if key in kpi_dict]

                # Reorder charts and tables
                if charts_tables_order and default_home_blocks:
                    blocks_dict = {}
                    for block in default_home_blocks:
                        if block["type"] == "chart":
                            key = f"default-chart-{block['chart_index']}"
                        else:
                            key = f"default-table-{block['table_index']}"
                        blocks_dict[key] = block

                    default_home_blocks = [
                        blocks_dict[key]
                        for key in charts_tables_order
                        if key in blocks_dict
                    ]
            except TypeError:
                logger.warning(
                    "Invalid default home layout order for user %s (unhashable type). Resetting.",
                    self.request.user,
                )
                DefaultHomeLayoutOrder.objects.filter(
                    user=self.request.user, dashboard__isnull=True
                ).delete()
                user_has_custom_default_home_layout = False
                messages.error(
                    self.request,
                    _(
                        "Your saved layout order was invalid and has been reset. "
                        "Please reorder the dashboard again if needed."
                    ),
                )
                default_home_order = {}

        context.update(
            {
                "is_default_home": True,
                "is_dynamic_dashboard": True,
                "kpi_data": kpi_data,
                "chart_data": chart_data,
                "table_data": table_data,
                "default_home_blocks": default_home_blocks,
                "user_dashboards": user_dashboards,
                "has_dashboards": bool(user_dashboards),
                "show_create_dashboard_prompt": True,
                "available_models_count": len(generator.models),
                "date_range": date_range,
                "date_range_choices": DATE_RANGE_CHOICES,
                "date_range_base_url": date_range_base_url,
                "date_from": date_from,
                "date_to": date_to,
                "default_home_layout_order": default_home_order,
                "user_has_custom_default_home_layout": user_has_custom_default_home_layout,
            }
        )
        context.update(get_onboarding_context(self.request))

        return context

    def render_to_response(self, context, template_name=None, **response_kwargs):
        """Render with optional override of template_name."""
        if template_name:
            self.template_name = template_name
        return super().render_to_response(context, **response_kwargs)


class SaveDefaultHomeLayoutOrderView(LoginRequiredMixin, View):
    """Save default home page layout order (KPIs, charts, tables) for the current user."""

    def _error_response(self, request, message, previous_order):
        messages.error(request, message)
        return JsonResponse(
            {
                "success": False,
                "message": message,
                "order": previous_order,
            }
        )

    def post(self, request, *args, **kwargs):
        """Validate and save default home KPI/charts order; return JSON success or error."""
        previous_order = _get_default_home_previous_order(request.user)

        try:
            # ---- Parse request body ----
            if request.content_type and "application/json" in request.content_type:
                body = json.loads(request.body or "{}")
            else:
                body = request.POST.dict()

            order_data = body.get("order")
            if not isinstance(order_data, dict):
                order_data = {}

            # ---- Required keys validation ----
            if "kpi" not in order_data:
                return self._error_response(
                    request, _("KPI data is missing in the request"), previous_order
                )

            if "chartsAndTables" not in order_data:
                return self._error_response(
                    request,
                    _("Charts and tables data is missing in the request"),
                    previous_order,
                )

            kpi = order_data.get("kpi")
            charts_and_tables = order_data.get("chartsAndTables")

            # ---- Type validation ----
            if not isinstance(kpi, list):
                return self._error_response(
                    request,
                    _("KPI data is invalid. Expected a list"),
                    previous_order,
                )

            if not isinstance(charts_and_tables, list):
                return self._error_response(
                    request,
                    _("Charts and tables data is invalid. Expected a list"),
                    previous_order,
                )

            # ---- Empty validation ----
            if not kpi:
                return self._error_response(
                    request, _("KPI order is empty."), previous_order
                )

            if not charts_and_tables:
                return self._error_response(
                    request,
                    _("Charts and tables order cannot be empty."),
                    previous_order,
                )

            kpi_pattern = re.compile(r"^default-kpi-\d+$")
            if not all(isinstance(i, str) and kpi_pattern.match(i) for i in kpi):
                return self._error_response(
                    request, _("Invalid KPI id in order."), previous_order
                )

            block_pattern = re.compile(r"^default-(?:chart|table)-\d+$")
            if not all(
                isinstance(i, str) and block_pattern.match(i) for i in charts_and_tables
            ):
                return self._error_response(
                    request,
                    _("Invalid chart or table id in order."),
                    previous_order,
                )

            date_range = body.get("date_range") or request.GET.get("date_range")
            if date_range == "all":
                date_range = None
            valid_kpi_ids, valid_block_ids, default_order = (
                _get_valid_default_home_layout_ids(request.user, date_range=date_range)
            )
            kpi_set = set(kpi)
            if kpi_set != valid_kpi_ids or len(kpi) != len(valid_kpi_ids):
                return self._error_response(
                    request,
                    _(
                        "Invalid KPI order: IDs must match the current default home KPIs."
                    ),
                    previous_order,
                )
            charts_tables_set = set(charts_and_tables)
            if charts_tables_set != valid_block_ids or len(charts_and_tables) != len(
                valid_block_ids
            ):
                return self._error_response(
                    request,
                    _(
                        "Invalid charts/tables order: IDs must match the current default home charts and tables."
                    ),
                    previous_order,
                )

            order = {
                "kpi": kpi,
                "chartsAndTables": charts_and_tables,
            }

            is_custom_layout = order != default_order
            if not is_custom_layout:
                DefaultHomeLayoutOrder.objects.filter(
                    user=request.user, dashboard__isnull=True
                ).delete()
            else:
                DefaultHomeLayoutOrder.objects.update_or_create(
                    user=request.user,
                    dashboard=None,
                    defaults={"order": order},
                )

            messages.success(request, _("Layout order saved successfully"))
            return JsonResponse(
                {
                    "success": True,
                    "message": _("Layout order saved."),
                    "is_custom": is_custom_layout,
                }
            )

        except Exception as e:
            messages.error(request, e)
            return JsonResponse(
                {"success": False, "message": str(e), "order": previous_order}
            )


class ResetDefaultHomeLayoutOrderView(LoginRequiredMixin, View):
    """Remove the current user's saved default home layout order and revert to template default."""

    def post(self, request, *args, **kwargs):
        """Delete user's default home layout order and return JSON response."""
        try:
            DefaultHomeLayoutOrder.objects.filter(
                user=request.user, dashboard__isnull=True
            ).delete()
            messages.success(self.request, _("Layout reset to default."))
            return JsonResponse(
                {"success": True, "message": _("Layout reset to default.")}
            )
        except Exception as e:
            messages.error(self.request, e)
            return JsonResponse({"success": False, "message": str(e)})
