"""
Horilla generics app configuration.

This module defines the AppLauncher for the horilla.contrib.generics application and performs
application startup tasks such as URL registration and signal imports.
"""

# First party imports (Horilla)
from horilla.apps import AppLauncher


class GenericsConfig(AppLauncher):
    """App configuration for horilla.contrib.generics application."""

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla.contrib.generics"
    label = "generics"

    url_prefix = "generics/"
    url_module = "horilla.contrib.generics.urls"
    url_namespace = "generics"

    auto_import_modules = ["signals", "checks"]
