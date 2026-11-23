"""App configuration for the forecast module."""

# First party imports (Horilla)
from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class ForecastConfig(AppLauncher):
    """Forecast App Configuration"""

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_crm.forecast"
    verbose_name = _("Forecast")

    url_prefix = "crm/forecast/"
    url_module = "horilla_crm.forecast.urls"
    url_namespace = "forecast"

    auto_import_modules = [
        "registration",
        "signals",
        "menu",
        "tour",
    ]

    demo_data = {
        "files": [
            (7, "load_data/forecast_type.json"),
        ],
        "order": 4,
        "configurable": False,
    }

    def get_api_paths(self):
        """
        Return API path configurations for this app.

        Returns:
            list: List of dictionaries containing path configuration
        """
        return [
            {
                "pattern": "crm/forecast/",
                "view_or_include": "horilla_crm.forecast.api.urls",
                "name": "horilla_crm_forecast_api",
                "namespace": "horilla_crm_forecast",
            }
        ]
