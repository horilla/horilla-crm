"""Configuration for the calendar app in Horilla."""

# First party imports (Horilla)
from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class CalendarConfig(AppLauncher):
    """App configuration class for the Horilla Calendar app."""

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla.contrib.calendar"
    label = "calendar"
    verbose_name = _("Calendar")

    url_prefix = "calendar/"
    url_module = "horilla.contrib.calendar.urls"
    url_namespace = "calendar"

    auto_import_modules = [
        "registration",
        "menu",
        "signals",
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
                "pattern": "/calendar/",
                "view_or_include": "horilla.contrib.calendar.api.urls",
                "name": "calendar_api",
                "namespace": "calendar",
            }
        ]
