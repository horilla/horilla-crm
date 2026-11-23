"""
App configuration for the Reports module in Horilla.
Handles app metadata and auto-registering URLs.
"""

# First party imports (Horilla)
from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class ReportsConfig(AppLauncher):
    """
    App configuration class for the Reports module in Horilla.
    """

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla.contrib.reports"
    label = "reports"
    verbose_name = _("Reports")

    url_prefix = "reports/"
    url_module = "horilla.contrib.reports.urls"
    url_namespace = "reports"

    auto_import_modules = [
        "registration",
        "signals",
        "menu",
        "tour",
    ]

    def get_api_paths(self):
        """
        Return API path configurations for this app.

        Returns:
            list: List of dictionaries containing path configuration
        """
        return [
            {
                "pattern": "reports/",
                "view_or_include": "horilla.contrib.reports.api.urls",
                "name": "reports_api",
                "namespace": "reports",
            }
        ]
