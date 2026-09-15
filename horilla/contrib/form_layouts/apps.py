"""
App configuration for the form layouts app.
"""

# First party imports (Horilla)
from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class FormLayoutsConfig(AppLauncher):
    """App configuration class for form layouts."""

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla.contrib.form_layouts"
    label = "form_layouts"
    verbose_name = _("Form Layouts")

    url_prefix = "form-layouts/"
    url_module = "horilla.contrib.form_layouts.urls"
    url_namespace = "form_layouts"

    auto_import_modules = [
        "menu",
        "registration",
        "view_hooks",
    ]
