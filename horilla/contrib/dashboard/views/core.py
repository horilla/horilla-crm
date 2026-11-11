"""Views for managing dashboard, including list and detail views with component rendering."""

# Standard library imports
import logging
from urllib.parse import urlencode, urlparse

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin, login_redirect
from horilla.contrib.generics.mixins import RecentlyViewedMixin
from horilla.contrib.generics.views import HorillaListView, HorillaNavView
from horilla.contrib.utils.middlewares import _thread_local
from horilla.db.models import Case, When
from horilla.shortcuts import get_object_or_404, redirect, render
from horilla.urls import reverse, reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.functional import cached_property
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView
from horilla.web import HttpNotFound, HttpResponse, RefreshResponse

# Local imports
from ..filters import DashboardFilter, DashboardFolderFilter
from ..models import Dashboard, DashboardComponent, DefaultHomeLayoutOrder
from ..utils import (
    DATE_RANGE_CHOICES,
    validate_custom_date_params,
    validate_date_range_request,
)
from .dashboard_helper import get_chart_data, get_kpi_data, get_table_data

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required(["dashboard.view_dashboard", "dashboard.view_own_dashboard"]),
    name="dispatch",
)
class DashboardNavbar(LoginRequiredMixin, HorillaNavView):
    """Navigation bar for dashboard with folder filtering."""

    search_url = reverse_lazy("dashboard:dashboard_list_view")
    main_url = reverse_lazy("dashboard:dashboard_list_view")
    filterset_class = DashboardFilter
    one_view_only = True
    filter_option = False
    reload_option = False
    model_name = "Dashboard"
    model_app_label = "dashboard"
    search_option = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        request = getattr(_thread_local, "request", None)
        title = request.GET.get("title")
        # One navbar serves every dashboard page: search the list of the current page
        pk = request.GET.get("pk")
        if pk and pk.isdigit():
            url = reverse(
                "dashboard:dashboard_folder_detail_list", kwargs={"pk": int(pk)}
            )
            self.filterset_class = DashboardFolderFilter
        elif title == "Favourite Dashboards":
            url = reverse("dashboard:dashboard_favourite_list_view")
        elif title == "Folders":
            url = reverse("dashboard:dashboard_folder_list_view")
            self.filterset_class = DashboardFolderFilter
        elif title == "Favourite Folders":
            url = reverse("dashboard:folder_favourite_list_view")
            self.filterset_class = DashboardFolderFilter
        else:
            url = reverse("dashboard:dashboard_list_view")
        self.search_url = url
        self.main_url = url

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        title = self.request.GET.get("title", "Dashboards")
        context["nav_title"] = _(title)
        return context

    @cached_property
    def new_button(self):
        """Button for creating new dashboard"""
        if self.request.user.has_perm(
            "dashboard.add_dashboard"
        ) or self.request.user.has_perm("dashboard.add_own_dashboard"):
            return {
                "title": _("New Dashboard"),
                "url": f"""{reverse_lazy("dashboard:dashboard_create")}""",
                "attrs": {"id": "dashboard-create"},
            }
        return None

    @cached_property
    def second_button(self):
        """Button for creating dashboard folder"""
        if self.request.user.has_perm(
            "dashboard.add_dashboardfolder"
        ) or self.request.user.has_perm("dashboard.add_own_dashboardfolder"):
            return {
                "title": _("New Folder"),
                "url": f"{reverse_lazy('dashboard:dashboard_folder_create')}?pk={self.request.GET.get('pk', '')}",
                "attrs": {"id": "dashboard-folder-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required(["dashboard.view_dashboard", "dashboard.view_own_dashboard"]),
    name="dispatch",
)
class DashboardDetailNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar for dashboard detail (back, title, Add components, Reorder/Save/Cancel)."""

    search_url = reverse_lazy("dashboard:dashboard_list_view")
    main_url = reverse_lazy("dashboard:dashboard_list_view")
    one_view_only = True
    all_view_types = False
    filter_option = False
    reload_option = False
    search_option = False
    navbar_indication = True
    model_name = "Dashboard"
    model_app_label = "dashboard"
    extra_actions_template = "dashboard_detail_nav_actions.html"

    def _dashboard(self):
        if not hasattr(self, "_dashboard_obj"):
            try:
                pk = int(self.request.GET.get("dashboard", ""))
            except (TypeError, ValueError):
                pk = None
            self._dashboard_obj = Dashboard.objects.filter(pk=pk).first()
        return self._dashboard_obj

    def get_navbar_indication_attrs(self):
        previous_url = self.request.GET.get("previous_url", "")
        if not previous_url.startswith("/") or previous_url.startswith("//"):
            previous_url = str(reverse_lazy("dashboard:dashboard_list_view"))
        return {
            "hx-get": previous_url,
            "hx-target": "#mainContent",
            "hx-select-oob": "#sideMenuContainer",
            "hx-swap": "outerHTML",
            "hx-select": "#mainContent",
            "hx-push-url": "true",
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dashboard = self._dashboard()
        if dashboard:
            context["nav_title"] = dashboard.name
            context["has_components"] = DashboardComponent.objects.filter(
                dashboard=dashboard, is_active=True
            ).exists()
        return context

    @cached_property
    def new_button(self):
        """Primary: add a component to the dashboard (opens modal)."""
        dashboard = self._dashboard()
        if not dashboard or not dashboard.can_add_component(self.request.user):
            return None
        return {
            "title": _("Add Components"),
            "url": reverse_lazy("dashboard:component_create"),
            "attrs": {"id": "addComponentBtn"},
        }


@method_decorator(
    permission_required_or_denied(
        ["dashboard.view_dashboard", "dashboard.view_own_dashboard"]
    ),
    name="dispatch",
)
class DashboardListView(LoginRequiredMixin, HorillaListView):
    """List view for dashboard with filtering and actions."""

    model = Dashboard
    template_name = "dashboard_list_view.html"
    view_id = "dashboard-list"
    filterset_class = DashboardFilter
    search_url = reverse_lazy("dashboard:dashboard_list_view")
    main_url = reverse_lazy("dashboard:dashboard_list_view")
    max_visible_actions = 5
    bulk_select_option = False
    sorting_target = f"#tableview-{view_id}"

    @cached_property
    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        if self.request.user.has_perm(
            "dashboard.add_dashboard"
        ) or self.request.user.has_perm("dashboard.add_own_dashboard"):
            return {
                "title": _("New Dashboard"),
                "url": f"""{reverse_lazy("dashboard:dashboard_create")}""",
                "attrs": 'id="dashboard-create"',
            }
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = _("Dashboards")
        return context

    columns = ["name", "description", "folder", ("is_default", "is_default_col")]

    @cached_property
    def action_method(self):
        """Determine if action column should be shown based on user permissions."""
        action_method = ""
        if (
            self.request.user.has_perm("dashboard.change_dashboard")
            or self.request.user.has_perm("dashboard.delete_dashboard")
            or self.request.user.has_perm("dashboard.view_own_dashboard")
        ):
            action_method = "actions"
        return action_method

    @cached_property
    def col_attrs(self):
        """Define attributes for columns, including action column if applicable."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {}
        if self.request.user.has_perm(
            "dashboard.view_dashboard"
        ) or self.request.user.has_perm("dashboard.view_own_dashboard"):
            attrs = {
                "hx-get": f"{{get_detail_view_url}}?{query_string}",
                "hx-target": "#mainContent",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
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


@method_decorator(
    permission_required_or_denied(
        ["dashboard.view_dashboard", "dashboard.view_own_dashboard"]
    ),
    name="dispatch",
)
class DashboardDetailView(RecentlyViewedMixin, TemplateView):
    """
    Render the detail view of dashboard page with support for KPIs, charts, and tables.
    """

    model = Dashboard

    def get_template_names(self):
        """
        Return template based on whether this is accessed from home
        """
        section = self.request.GET.get("section")
        is_home = self.request.GET.get("is_home") == "true"
        is_default = (
            self.object.is_default if hasattr(self, "object") and self.object else False
        )

        if section == "home" and is_home and is_default:
            return ["home/home.html"]
        return ["dashboard_detail_view.html"]

    def get_object(self):
        """Retrieve the dashboard object based on the primary key in the URL."""
        if not hasattr(self, "_object"):
            self._object = get_object_or_404(self.model, pk=self.kwargs.get("pk"))
        return self._object

    def get(self, request, *args, **kwargs):
        """Check ownership or view_dashboard permission and date range; then render dashboard."""
        self.object = self.get_object()
        if not self.model.objects.filter(
            dashboard_owner_id=self.request.user, pk=self.kwargs["pk"]
        ).first() and not self.request.user.has_perm("dashboard.view_dashboard"):
            return render(self.request, "403.html")

        redirect_url = validate_date_range_request(request)
        if redirect_url:
            return redirect(redirect_url)

        return super().get(request, *args, **kwargs)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return login_redirect(request)
        try:
            self.object = self.get_object()
        except Exception as e:
            if request.headers.get("HX-Request") == "true":
                messages.error(self.request, e)
                return RefreshResponse(request)
            raise HttpNotFound(e) from e
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        """Handle POST request for exporting table data from the first table component."""
        dashboard = self.get_object()
        components = DashboardComponent.objects.filter(
            dashboard=dashboard, is_active=True, component_type="table_data"
        ).order_by("sequence")

        for component in components:
            model, table_context = get_table_data(component, request)
            if model:
                list_view = HorillaListView(
                    view_id=f"dashboard_component_{component.id}",
                    model=model,
                    request=request,
                    search_url=f"{reverse_lazy('dashboard:dashboard_detail_view', kwargs={'pk': component.dashboard_id})}",
                    main_url=reverse_lazy(
                        "dashboard:dashboard_detail_view",
                        kwargs={"pk": component.dashboard_id},
                    ),
                    columns=table_context.get("columns", []),
                    bulk_export_option=True,
                )
                list_view.object_list = table_context.get(
                    "queryset", model.objects.none()
                )
                return list_view.post(request, *args, **kwargs)

        return HttpResponse("No table component found to handle export", status=400)

    def get_context_data(self, **kwargs):
        """Add section, layout, components, and dashboard context for the detail view template."""
        context = super().get_context_data(**kwargs)

        section = self.request.GET.get("section")
        is_home = self.request.GET.get("is_home") == "true"
        is_default = self.object.is_default
        is_home_view = section == "home" and is_home and is_default

        dashboard = self.get_object()
        components_qs = DashboardComponent.objects.filter(
            dashboard=dashboard, is_active=True
        ).order_by("sequence")

        layout = DefaultHomeLayoutOrder.objects.filter(
            user=self.request.user, dashboard=dashboard
        ).first()
        if layout and isinstance(layout.order, dict):
            order = layout.order
            kpi_ids = order.get("kpi", [])
            component_ids = order.get("components", [])

            if kpi_ids:
                kpi_order = Case(
                    *[
                        When(
                            id=int(id_val) if isinstance(id_val, str) else id_val,
                            then=pos,
                        )
                        for pos, id_val in enumerate(kpi_ids)
                    ]
                )
                components_qs = components_qs.annotate(kpi_order_field=kpi_order)

            if component_ids:
                comp_order = Case(
                    *[
                        When(
                            id=int(id_val) if isinstance(id_val, str) else id_val,
                            then=pos,
                        )
                        for pos, id_val in enumerate(component_ids)
                    ]
                )
                components_qs = components_qs.annotate(comp_order_field=comp_order)

            if kpi_ids and component_ids:
                components_qs = components_qs.order_by(
                    "kpi_order_field", "comp_order_field", "sequence"
                )
            elif kpi_ids:
                components_qs = components_qs.order_by("kpi_order_field", "sequence")
            elif component_ids:
                components_qs = components_qs.order_by("comp_order_field", "sequence")

        user_has_custom_dashboard_layout = bool(
            layout and isinstance(layout.order, dict)
        )
        components = components_qs

        kpi_data = []
        for component in components.filter(component_type="kpi"):
            kpi = get_kpi_data(component, self.request)
            if kpi:
                kpi_data.append(kpi)

        chart_data = []
        for component in components.filter(component_type="chart"):
            chart = get_chart_data(component, self.request)
            if chart:
                chart_data.append(chart)

        table_contexts = {}
        for component in components.filter(component_type="table_data"):
            model, table_context = get_table_data(component, self.request)
            if model:
                table_contexts[component.id] = table_context

        session_referer_key = f"dashboard_detail_referer_{dashboard.pk}"
        current_referer = self.request.META.get("HTTP_REFERER")
        hx_current_url = self.request.headers.get("HX-Current-URL")
        stored_referer = self.request.session.get(session_referer_key)

        if stored_referer:
            stored_parsed = urlparse(stored_referer)
            stored_referer = stored_parsed.path + (
                f"?{stored_parsed.query}" if stored_parsed.query else ""
            )

        if hx_current_url:
            hx_parsed = urlparse(hx_current_url)
            hx_path = hx_parsed.path
            if hx_path != self.request.path:
                hx_relative = hx_path + (
                    f"?{hx_parsed.query}" if hx_parsed.query else ""
                )
                self.request.session[session_referer_key] = hx_relative
                previous_url = hx_relative
            else:
                previous_url = stored_referer or reverse_lazy(
                    "dashboard:dashboard_list_view"
                )

        elif stored_referer:
            previous_url = stored_referer
        elif current_referer and self.request.get_host() in current_referer:
            referer_parsed = urlparse(current_referer)
            referer_path = referer_parsed.path
            if referer_path != self.request.path:
                referer_relative = referer_path + (
                    f"?{referer_parsed.query}" if referer_parsed.query else ""
                )
                previous_url = referer_relative
                self.request.session[session_referer_key] = referer_relative
            else:
                previous_url = reverse_lazy("dashboard:dashboard_list_view")
        else:
            previous_url = reverse_lazy("dashboard:dashboard_list_view")

        context["previous_url"] = previous_url

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

        base_url = self.request.build_absolute_uri(self.request.path).split("?")[0]
        query_params = self.request.GET.copy()
        query_params.pop("date_range", None)
        query_params.pop("date_from", None)
        query_params.pop("date_to", None)
        base_query = query_params.urlencode()
        date_range_base_url = f"{base_url}?{base_query}" if base_query else base_url

        context.update(
            {
                "current_obj": dashboard,
                "dashboard": dashboard,
                "components": components,
                "has_components": components.exists(),
                "user_has_custom_dashboard_layout": user_has_custom_dashboard_layout,
                "kpi_data": kpi_data,
                "chart_data": chart_data,
                "table_contexts": table_contexts,
                "view_id": "dashboard_components",
                "is_home_view": is_home_view,
                "section": section,
                "is_home": is_home,
                "date_range": date_range,
                "date_range_choices": DATE_RANGE_CHOICES,
                "date_range_base_url": date_range_base_url,
                "date_from": date_from,
                "date_to": date_to,
            }
        )

        return context
