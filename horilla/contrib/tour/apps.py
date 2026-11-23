"""
AppLauncher for the horilla.contrib.tour app
"""

# First party imports (Horilla)
from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class TourConfig(AppLauncher):
    """App configuration class for horilla.contrib.tour."""

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla.contrib.tour"
    label = "tour"
    verbose_name = _("Product Tour")

    js_files = "tour/assets/js/tour.js"

    url_prefix = "tour/"
    url_module = "horilla.contrib.tour.urls"
    url_namespace = "tour"

    auto_import_modules = [
        "registration",
        "menu",
        "tour",
        "settings_tour",
    ]
