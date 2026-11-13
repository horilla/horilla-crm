"""Views for managing favourite dashboards and folders."""

# Standard library imports
import logging
from urllib.parse import urlencode

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import HorillaListView
from horilla.urls import reverse_lazy
from horilla.utils.decorators import method_decorator, permission_required_or_denied
from horilla.utils.functional import cached_property
from horilla.utils.translation import gettext_lazy as _

# Local imports
from ..filters import DashboardFilter, DashboardFolderFilter
from ..models import Dashboard, DashboardFolder

logger = logging.getLogger(__name__)


@method_decorator(
    permission_required_or_denied(
        ["dashboard.view_dashboard", "dashboard.view_own_dashboard"]
    ),
    name="dispatch",
)
class FavouriteDashboardListView(LoginRequiredMixin, HorillaListView):
    """List view for favourite dashboard."""

    model = Dashboard
    template_name = "favourite_dashboard.html"
    view_id = "favourite-dashboard-list"
    filterset_class = DashboardFilter
    search_url = reverse_lazy("dashboard:dashboard_favourite_list_view")
    main_url = reverse_lazy("dashboard:dashboard_favourite_list_view")
    bulk_select_option = False
    sorting_target = f"#tableview-{view_id}"

    @cached_property
    def action_method(self):
        """Determine if action buttons should be displayed based on user permissions."""
        action_method = ""
        if self.request.user.has_perm(
            "dashboard.change_dashboard"
        ) or self.request.user.has_perm("dashboard.delete_dashboard"):
            action_method = "actions"

        return action_method

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = _("Favourite Dashboards")
        return context

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(favourited_by=self.request.user)
        return queryset

    columns = ["name", "description", "folder"]

    @cached_property
    def col_attrs(self):
        """Define attributes for columns, including HTMX attributes for interactivity."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {}
        if self.request.user.has_perm("dashboard.view_dashboard"):
            attrs = {
                "hx-get": f"{{get_detail_view_url}}?{query_string}",
                "hx-target": "#mainContent",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "hx-select": "#mainContent",
            }
        return [
            {
                "name": {
                    "style": "cursor:pointer",
                    "class": "hover:text-primary-600",
                    **attrs,
                }
            }
        ]


@method_decorator(
    permission_required_or_denied(
        [
            "dashboard.view_dashboardfolder",
            "dashboard.view_own_dashboardfolder",
        ]
    ),
    name="dispatch",
)
class FavouriteFolderListView(HorillaListView):
    """List view for favourite dashboard folders."""

    template_name = "favourite_folder.html"
    model = DashboardFolder
    view_id = "favourite-folder-list-view"
    filterset_class = DashboardFolderFilter
    search_url = reverse_lazy("dashboard:folder_favourite_list_view")
    main_url = reverse_lazy("dashboard:folder_favourite_list_view")
    bulk_select_option = False
    sorting_target = f"#tableview-{view_id}"

    @cached_property
    def action_method(self):
        """Determine if action buttons should be displayed based on user permissions."""
        action_method = ""
        if (
            self.request.user.has_perm("dashboard.change_dashboardfolder")
            or self.request.user.has_perm("dashboard.delete_dashboardfolder")
            or self.request.user.has_perm("dashboard.change_dashboard")
            or self.request.user.has_perm("dashboard.delete_dashboard")
        ):
            action_method = "actions"

        return action_method

    columns = ["name"]

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(parent_folder=None, favourited_by=self.request.user)
        return queryset

    @cached_property
    def col_attrs(self):
        """Define attributes for columns, including HTMX attributes for interactivity."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {}
        if self.request.user.has_perm("dashboard.view_dashboardfolder"):
            attrs = {
                "hx-get": f"{{get_detail_view_url}}?{query_string}",
                "hx-target": "#mainContent",
                "hx-swap": "outerHTML",
                "hx-select": "#mainContent",
                "hx-push-url": "true",
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Favourite Folders"
        return context
