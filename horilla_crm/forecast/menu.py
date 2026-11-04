"""
This module registers Floating, Settings, My Settings, and Main Section menus
for the Horilla CRM Forecast app
"""

# First party imports (Horilla)
from horilla.menu import MAIN_CONTENT_HX_ATTRS, settings_menu, sub_section_menu
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import ForecastTarget, ForecastType


@sub_section_menu.register
class ForecastsSubSection:
    """
    Registers the forecast menu to sub section in the main sidebar.
    """

    # Identity / placement
    section = "sales"
    app_label = "forecast"
    position = 4

    # Display
    verbose_name = _("Forecast")
    icon = "/assets/icons/forecast.svg"

    # Behavior
    url = reverse_lazy("forecast:forecast_view")
    attrs = MAIN_CONTENT_HX_ATTRS

    # Access control
    perm = [
        "opportunities.view_opportunity",
        "opportunities.view_own_opportunity",
    ]


@settings_menu.register
class ForecastSettings:
    """Settings menu entries for the Forecast module."""

    title = _("Forecast")
    icon = "/assets/icons/growth.svg"
    order = 6
    items = [
        {
            "label": ForecastType()._meta.verbose_name_plural,
            "url": reverse_lazy("forecast:forecast_type_view"),
            "hx-target": "#settings-content",
            "hx-push-url": "true",
            "hx-select": "#forecast-type-view",
            "hx-select-oob": "#settings-sidebar",
            "perm": "forecast.view_forecasttype",
        },
        {
            "label": ForecastTarget()._meta.verbose_name_plural,
            "url": reverse_lazy("forecast:forecast_target_view"),
            "hx-target": "#settings-content",
            "hx-push-url": "true",
            "hx-select": "#forecast-target-view",
            "hx-select-oob": "#settings-sidebar",
            "perm": "forecast.view_forecasttarget",
        },
    ]
