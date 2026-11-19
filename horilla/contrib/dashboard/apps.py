"""App configuration for dashboard app."""

# First party imports (Horilla)
from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class DashboardConfig(AppLauncher):
    """
    HorillaDashboardConfig App Configuration
    """

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla.contrib.dashboard"
    label = "dashboard"
    verbose_name = _("Dashboard")

    url_prefix = "dashboard/"
    url_module = "horilla.contrib.dashboard.urls"
    url_namespace = "dashboard"

    auto_import_modules = [
        "registration",
        "signals",
        "menu",
        "tour",
    ]

    demo_data = {
        "files": [
            (28, "load_data/dashboard.json"),
        ],
        "order": 7,
        "configurable": False,
    }

    # Define API paths for this app
    def get_api_paths(self):
        """
        Return API path configurations for this app.

        Returns:
            list: List of dictionaries containing path configuration
        """
        return [
            {
                "pattern": "/dashboard/",
                "view_or_include": "horilla.contrib.dashboard.api.urls",
                "name": "dashboard_api",
                "namespace": "dashboard",
            }
        ]
