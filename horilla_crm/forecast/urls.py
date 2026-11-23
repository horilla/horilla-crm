"""
URL configuration for the forecast app.
"""

# First party imports (Horilla)
from horilla.urls import path

# Local imports
from horilla_crm.forecast import views

app_name = "forecast"

urlpatterns = [
    path("forecast-view/", views.ForecastView.as_view(), name="forecast_view"),
    path(
        "forecast-navbar-view/",
        views.ForecastNavbarView.as_view(),
        name="forecast_navbar_view",
    ),
    path(
        "forecast-tab-view/", views.ForecastTabView.as_view(), name="forecast_tab_view"
    ),
    path(
        "forecast-type-tab-view/<int:pk>/",
        views.ForecastTypeTabView.as_view(),
        name="forecast_type_tab_view",
    ),
    path(
        "forecast-role-users/",
        views.ForecastRoleUsersView.as_view(),
        name="forecast_role_users",
    ),
    path(
        "forecast-role-target-users/",
        views.ForecastRoleTargetUsersView.as_view(),
        name="forecast_role_target_users",
    ),
    path(
        "forecast-role-total-edit/",
        views.ForecastRoleTotalEditView.as_view(),
        name="forecast_role_total_edit",
    ),
    path(
        "forecast-charts-modal/",
        views.ForecastChartsModalView.as_view(),
        name="forecast_charts_modal",
    ),
    path(
        "opportunities/<str:forecast_id>/<str:opportunity_type>/",
        views.ForecastOpportunitiesView.as_view(),
        name="forecast_opportunities",
    ),
    path(
        "forecast-target-view/",
        views.ForecastTargetView.as_view(),
        name="forecast_target_view",
    ),
    path(
        "forecast-target-nav-view/",
        views.ForecastTargetNavbar.as_view(),
        name="forecast_target_nav_view",
    ),
    path(
        "forecast-target-filters-view/",
        views.ForecastTargetFiltersView.as_view(),
        name="forecast_target_filters_view",
    ),
    path(
        "forecast-target-list-view/",
        views.ForecastTargetListView.as_view(),
        name="forecast_target_list_view",
    ),
    path(
        "forecast-target-form-view/",
        views.ForecastTargetFormView.as_view(),
        name="forecast_target_form_view",
    ),
    path(
        "toggle-role-based/",
        views.ToggleRoleBasedView.as_view(),
        name="toggle_role_based",
    ),
    path(
        "toggle-condition-fields/",
        views.ToggleConditionFieldsView.as_view(),
        name="toggle_condition_fields",
    ),
    path(
        "update-target-help-text/",
        views.UpdateTargetHelpTextView.as_view(),
        name="update_target_help_text",
    ),
    path(
        "forecast-target-update-form-view/<int:pk>/",
        views.UpdateForecastTarget.as_view(),
        name="forecast_target_update_form_view",
    ),
    path(
        "forecast-target-delete-view/<int:pk>/",
        views.ForecastTargetDeleteView.as_view(),
        name="forecast_target_delete_view",
    ),
    path(
        "forecast-type-view/",
        views.ForecastTypeView.as_view(),
        name="forecast_type_view",
    ),
    path(
        "forecast-type-nav-view/",
        views.ForecastTypeNavbar.as_view(),
        name="forecast_type_nav_view",
    ),
    path(
        "forecast-type-list-view/",
        views.ForecastTypeListView.as_view(),
        name="forecast_type_list_view",
    ),
    path(
        "forecast-type-create-form-view/",
        views.ForecastTypeFormView.as_view(),
        name="forecast_type_create_form_view",
    ),
    path(
        "forecast-type-update-form-view/<int:pk>/",
        views.ForecastTypeFormView.as_view(),
        name="forecast_type_update_form_view",
    ),
    path(
        "forecast-type-delete-view/<int:pk>/",
        views.ForecastTypeDeleteView.as_view(),
        name="forecast_type_delete_view",
    ),
]
