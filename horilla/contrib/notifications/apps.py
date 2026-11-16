"""
Django app configuration for horilla.contrib.notifications.

This module defines the application configuration for the notifications app,
including URL registration and signal imports.
"""

# First party imports (Horilla)
from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class NotificationsConfig(AppLauncher):
    """
    Application configuration for horilla.contrib.notifications app.

    This class configures the notifications app, including:
    - App metadata (name, verbose_name)
    - URL pattern registration
    - Signal handler imports
    - API path configurations
    """

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla.contrib.notifications"
    label = "notifications"
    verbose_name = _("Notifications")

    url_prefix = "notifications/"
    url_module = "horilla.contrib.notifications.urls"
    url_namespace = "notifications"

    auto_import_modules = [
        "registration",
        "signals",
        "menu",
    ]

    def get_api_paths(self):
        """
        Return API path configurations for this app.

        Returns:
            list: List of dictionaries containing path configuration
        """
        return [
            {
                "pattern": "notifications/",
                "view_or_include": "horilla.contrib.notifications.api.urls",
                "name": "notifications_api",
                "namespace": "notifications",
            }
        ]
