"""
Forecast Views Module

This package provides forecast dashboard, type tab and opportunities views.
Submodules: dashboard, type_tab, opportunities.
"""

# Local imports
from horilla_crm.forecast.views.core.dashboard import (
    ForecastNavbarView,
    ForecastTabView,
    ForecastView,
)
from horilla_crm.forecast.views.core.opportunities import ForecastOpportunitiesView
from horilla_crm.forecast.views.core.type_tab import (
    ForecastChartsModalView,
    ForecastRoleUsersView,
    ForecastTypeTabView,
)

__all__ = [
    "ForecastView",
    "ForecastNavbarView",
    "ForecastTabView",
    "ForecastTypeTabView",
    "ForecastChartsModalView",
    "ForecastOpportunitiesView",
    "ForecastRoleUsersView",
]
