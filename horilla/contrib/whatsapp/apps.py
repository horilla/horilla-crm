"""
App configuration for the whatsapp app.
"""

from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class WhatsappConfig(AppLauncher):
    """
    Configuration class for the whatsapp app in Horilla.
    """

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla.contrib.whatsapp"
    label = "whatsapp"
    verbose_name = _("Whatsapp")

    url_prefix = "whatsapp/"
    url_module = "horilla.contrib.whatsapp.urls"
    url_namespace = "whatsapp"

    auto_import_modules = [
        "registration",
        "signals",
        "menu",
        "view_extensions",
        "automation_extensions",
        "engine",
    ]

    celery_schedule_module = "celery_schedules"
    celery_schedule_variable = "WHATSAPP_BEAT_SCHEDULE"

    def get_api_paths(self):
        """
        Return API path configurations for this app.
        """
        return [
            {
                "pattern": "whatsapp/",
                "view_or_include": "horilla.contrib.whatsapp.api.urls",
                "name": "whatsapp_api",
                "namespace": "whatsapp",
            }
        ]
