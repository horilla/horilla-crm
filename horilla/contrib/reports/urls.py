"""URL patterns for the `horilla.contrib.reports` app."""

# First party imports (Horilla)
from horilla.urls import path

# Local imports
from . import views

app_name = "reports"

urlpatterns = [
    path(
        "reports-list-view/", views.ReportsListView.as_view(), name="reports_list_view"
    ),
    path(
        "favourite-reports-list-view/",
        views.FavouriteReportsListView.as_view(),
        name="favourite_reports_list_view",
    ),
    path(
        "favourite-folder-list-view/",
        views.FavouriteReportFolderListView.as_view(),
        name="favourite_folder_list_view",
    ),
    path("reports-nav-view/", views.ReportNavbar.as_view(), name="reports_nav_view"),
    path(
        "report-detail/<int:pk>/",
        views.ReportDetailView.as_view(),
        name="report_detail",
    ),
    path(
        "report-filtered/<int:pk>/",
        views.ReportDetailFilteredView.as_view(),
        name="report_detail_filtered",
    ),
    # Report update views - new preview functionality
    path(
        "report-update/<int:pk>/",
        views.ReportUpdateView.as_view(),
        name="report_update",
    ),
    path(
        "save-changes/<int:pk>/",
        views.SaveReportChangesView.as_view(),
        name="save_report_changes",
    ),
    path(
        "discard-changes/<int:pk>/",
        views.DiscardReportChangesView.as_view(),
        name="discard_report_changes",
    ),
    # Column management - updated with preview
    path("add-column/<int:pk>/", views.AddColumnView.as_view(), name="add_column"),
    path(
        "remove-column/<int:pk>/",
        views.RemoveColumnView.as_view(),
        name="remove_column",
    ),
    # Row group management - updated with preview
    path(
        "toggle-row-group/<int:pk>/",
        views.ToggleRowGroupView.as_view(),
        name="toggle_row_group",
    ),
    path(
        "remove-row-group/<int:pk>/",
        views.RemoveRowGroupView.as_view(),
        name="remove_row_group",
    ),
    # Column group management - updated with preview
    path(
        "toggle-column-group/<int:pk>/",
        views.ToggleColumnGroupView.as_view(),
        name="toggle_column_group",
    ),
    path(
        "remove-column-group/<int:pk>/",
        views.RemoveColumnGroupView.as_view(),
        name="remove_column_group",
    ),
    # Aggregate management - updated with preview
    path(
        "toggle-aggregate/<int:pk>/",
        views.ToggleAggregateView.as_view(),
        name="toggle_aggregate",
    ),
    path(
        "update-aggregate-function/<int:pk>/",
        views.UpdateAggregateFunctionView.as_view(),
        name="update_aggregate_function",
    ),
    path(
        "remove-aggregate-column/<int:pk>/",
        views.RemoveAggregateColumnView.as_view(),
        name="remove_aggregate_column",
    ),
    # Filter management - updated with preview
    path(
        "add-filter-field/<int:pk>/",
        views.AddFilterFieldView.as_view(),
        name="add_filter_field",
    ),
    path(
        "update-filter-operator/<int:pk>/",
        views.UpdateFilterOperatorView.as_view(),
        name="update_filter_operator",
    ),
    path(
        "update-filter-value/<int:pk>/",
        views.UpdateFilterValueView.as_view(),
        name="update_filter_value",
    ),
    path(
        "apply-filters/<int:pk>/",
        views.ApplyFiltersView.as_view(),
        name="apply_filters",
    ),
    path(
        "filter-row/<int:pk>/",
        views.ReportFilterRowView.as_view(),
        name="filter_row",
    ),
    path(
        "filter-row-body/<int:pk>/",
        views.ReportFilterRowBodyView.as_view(),
        name="filter_row_body",
    ),
    path(
        "remove-filter/<int:pk>/",
        views.RemoveFilterView.as_view(),
        name="remove_filter",
    ),
    path(
        "update-filter-logic/<int:pk>/",
        views.UpdateFilterLogicView.as_view(),
        name="update_filter_logic",
    ),
    path(
        "close-panel/<int:pk>/",
        views.CloseReportPanelView.as_view(),
        name="close_report_panel",
    ),
    path(
        "search-fields/<int:pk>/",
        views.SearchAvailableFieldsView.as_view(),
        name="search_available_fields",
    ),
    path(
        "change-chart-type/<int:pk>/",
        views.ChangeChartTypeView.as_view(),
        name="change_chart_type",
    ),
    path(
        "change-chart-field/<int:pk>/",
        views.ChangeChartFieldView.as_view(),
        name="change_chart_field",
    ),
    path("create-report/", views.CreateReportView.as_view(), name="create_report"),
    path(
        "get-module-columns-htmx/",
        views.GetModuleColumnsHTMXView.as_view(),
        name="get_module_columns_htmx",
    ),
    path("create-folder/", views.CreateFolderView.as_view(), name="create_folder"),
    path(
        "update-folder/<int:pk>/",
        views.CreateFolderView.as_view(),
        name="update_folder",
    ),
    path(
        "report-folder-list/",
        views.ReportFolderListView.as_view(),
        name="report_folder_list",
    ),
    path(
        "report-folder-detail/<int:pk>/",
        views.ReportFolderDetailView.as_view(),
        name="report_folder_detail",
    ),
    path(
        "mark-folder-favourite/<int:pk>/",
        views.MarkFolderAsFavouriteView.as_view(),
        name="mark_folder_favourite",
    ),
    path(
        "mark-report-favourite/<int:pk>/",
        views.MarkReportAsFavouriteView.as_view(),
        name="mark_report_favourite",
    ),
    path(
        "update-report/<int:pk>/",
        views.UpdateReportView.as_view(),
        name="update_report",
    ),
    path(
        "delete-report/<int:pk>/",
        views.ReportDeleteView.as_view(),
        name="delete_report",
    ),
    path(
        "delete-folder/<int:pk>/",
        views.FolderDeleteView.as_view(),
        name="delete_folder",
    ),
    path(
        "move-report-to-folder/<int:pk>/",
        views.MoveReportView.as_view(),
        name="move_report_to_folder",
    ),
    path(
        "move-folder-to-folder/<int:pk>/",
        views.MoveFolderView.as_view(),
        name="move_folder_to_folder",
    ),
    path("export/<int:pk>/", views.ReportExportView.as_view(), name="report_export"),
    path(
        "load-default-reports/",
        views.LoadDefaultReportsModalView.as_view(),
        name="load_default_reports",
    ),
    path(
        "create-selected-default-reports/",
        views.CreateSelectedDefaultReportsView.as_view(),
        name="create_selected_default_reports",
    ),
]
