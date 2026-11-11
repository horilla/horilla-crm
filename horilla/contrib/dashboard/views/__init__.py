"""Views for managing dashboard, including list and detail views with component rendering."""

from horilla.contrib.dashboard.views.core import (
    DashboardNavbar,
    DashboardDetailNavbar,
    DashboardDetailView,
    DashboardListView,
)

from horilla.contrib.dashboard.views.home import (
    HomePageView,
    SaveDefaultHomeLayoutOrderView,
    ResetDefaultHomeLayoutOrderView,
)

from horilla.contrib.dashboard.views.onboarding import (
    OnboardingSkipView,
    OnboardingVisibilityView,
)

from horilla.contrib.dashboard.views.component import (
    DashboardComponentTableDataView,
    DashboardComponentFormView,
    ComponentDeleteView,
    AddToDashboardForm,
    ReportToDashboardForm,
    ChartViewToDashboardForm,
    ReorderComponentsView,
)

from horilla.contrib.dashboard.views.folder import (
    DashboardFolderCreate,
    DashboardFolderFavoriteView,
    DashboardFolderListView,
    FolderDetailListView,
    FolderDeleteView,
    MoveDashboardView,
    MoveFolderView,
)

from horilla.contrib.dashboard.views.field_choices import (
    ModuleFieldChoicesView,
    ColumnFieldChoicesView,
    GroupingFieldChoicesView,
    SecondaryGroupingFieldChoicesView,
    MetricFieldChoicesView,
    YAxisMetricFieldChoicesView,
)

from horilla.contrib.dashboard.views.chart import (
    ChartPreviewView,
    DashboardComponentChartView,
)

from horilla.contrib.dashboard.views.dashboard_actions import (
    DashboardDefaultToggleView,
    DashboardFavoriteToggleView,
    DashboardCreateFormView,
    DashboardDeleteView,
    ResetDashboardLayoutOrderView,
)

from horilla.contrib.dashboard.views.favourite import (
    FavouriteDashboardListView,
    FavouriteFolderListView,
)

from horilla.contrib.generics.views.helpers.queryset_utils import (
    get_queryset_for_module,
    apply_conditions,
)


from horilla.contrib.dashboard.views.dashboard_helper import (
    get_kpi_data,
    get_report_chart_data,
    get_chart_data,
    get_table_data,
)

__all__ = [
    # core
    "DashboardNavbar",
    "DashboardDetailNavbar",
    "DashboardDetailView",
    "DashboardListView",
    # home
    "HomePageView",
    "SaveDefaultHomeLayoutOrderView",
    "ResetDefaultHomeLayoutOrderView",
    # components
    "DashboardComponentTableDataView",
    "DashboardComponentFormView",
    "ComponentDeleteView",
    "AddToDashboardForm",
    "ReportToDashboardForm",
    "ChartViewToDashboardForm",
    "ReorderComponentsView",
    # folders
    "DashboardFolderCreate",
    "DashboardFolderFavoriteView",
    "DashboardFolderListView",
    "FolderDetailListView",
    "FolderDeleteView",
    "MoveDashboardView",
    "MoveFolderView",
    # field choices
    "ModuleFieldChoicesView",
    "ColumnFieldChoicesView",
    "GroupingFieldChoicesView",
    "SecondaryGroupingFieldChoicesView",
    "MetricFieldChoicesView",
    "YAxisMetricFieldChoicesView",
    # charts
    "ChartPreviewView",
    "DashboardComponentChartView",
    # dashboard actions
    "DashboardDefaultToggleView",
    "DashboardFavoriteToggleView",
    "DashboardCreateFormView",
    "DashboardDeleteView",
    "ResetDashboardLayoutOrderView",
    # favourites
    "FavouriteDashboardListView",
    "FavouriteFolderListView",
    # helpers (public)
    "get_queryset_for_module",
    "get_kpi_data",
    "get_report_chart_data",
    "get_chart_data",
    "apply_conditions",
    "get_table_data",
]
