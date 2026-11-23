"""Aggregate view modules for the `horilla_crm.forecast.views` package."""

# Local imports
from horilla_crm.forecast.views.core import (
    ForecastChartsModalView,
    ForecastRoleUsersView,
    ForecastView,
    ForecastNavbarView,
    ForecastTabView,
    ForecastTypeTabView,
    ForecastOpportunitiesView,
)

from horilla_crm.forecast.views.forecast_target import (
    ForecastTargetView,
    ForecastTargetFiltersView,
    ForecastTargetNavbar,
    ForecastTargetListView,
    ForecastTargetFormView,
    ToggleRoleBasedView,
    ToggleConditionFieldsView,
    UpdateTargetHelpTextView,
    UpdateForecastTarget,
    ForecastTargetDeleteView,
    ForecastRoleTargetUsersView,
    ForecastRoleTotalEditView,
)

from horilla_crm.forecast.views.forecast_type import (
    ForecastTypeView,
    ForecastTypeNavbar,
    ForecastTypeListView,
    ForecastTypeFormView,
    ForecastTypeDeleteView,
)

__all__ = [
    # core
    "ForecastView",
    "ForecastNavbarView",
    "ForecastTabView",
    "ForecastTypeTabView",
    "ForecastChartsModalView",
    "ForecastOpportunitiesView",
    "ForecastRoleUsersView",
    # forecast_target
    "ForecastTargetView",
    "ForecastTargetFiltersView",
    "ForecastTargetNavbar",
    "ForecastTargetListView",
    "ForecastTargetFormView",
    "ToggleRoleBasedView",
    "ToggleConditionFieldsView",
    "UpdateTargetHelpTextView",
    "UpdateForecastTarget",
    "ForecastTargetDeleteView",
    "ForecastRoleTargetUsersView",
    "ForecastRoleTotalEditView",
    # forecast_type
    "ForecastTypeView",
    "ForecastTypeNavbar",
    "ForecastTypeListView",
    "ForecastTypeFormView",
    "ForecastTypeDeleteView",
]
