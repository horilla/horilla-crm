"""
App configuration for the cadences app.
"""

# First party imports (Horilla)
from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class CadencesConfig(AppLauncher):
    """
    Configuration class for the cadences app in Horilla.
    """

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla.contrib.cadences"
    label = "cadences"
    verbose_name = _("Cadences")

    url_prefix = "cadences/"
    url_module = "horilla.contrib.cadences.urls"
    url_namespace = "cadences"

    auto_import_modules = [
        "registration",
        "signals",
        "menu",
        "view_extensions",
    ]

    celery_schedule_module = "celery_schedules"
