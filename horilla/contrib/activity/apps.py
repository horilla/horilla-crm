"""App configuration for the activity module."""

# First party imports (Horilla)
from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class ActivityConfig(AppLauncher):
    """
    Configuration class for the Activity app in Horilla.
    """

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla.contrib.activity"
    label = "activity"
    verbose_name = _("Activity")

    url_prefix = "activity/"
    url_module = "horilla.contrib.activity.urls"
    url_namespace = "activity"

    auto_import_modules = [
        "registration",
        "methods",
        "dashboard",
        "menu",
        "signals",
        "tour",
    ]

    celery_schedule_module = "celery_schedules"

    demo_data = {
        "files": [
            (32, "load_data/activity.json"),
        ],
        "order": 7,
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
                "pattern": "/activity/",
                "view_or_include": "horilla.contrib.activity.api.urls",
                "name": "activity_api",
                "namespace": "activity",
            }
        ]
