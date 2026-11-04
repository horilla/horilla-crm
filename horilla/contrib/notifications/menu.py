"""
This module registers Floating, Settings, My Settings, and Main Section menus
for the Horilla platform Notifications app
"""

from horilla.menu import settings_menu

# First party imports (Horilla)
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import NotificationTemplate


@settings_menu.register
class NotificationSettings:
    """Settings menu for Notification module"""

    title = _("Notifications")
    icon = "/assets/icons/notification.svg"
    order = 4
    items = [
        {
            "label": NotificationTemplate()._meta.verbose_name_plural,
            "url": reverse_lazy("notifications:notification_template_view"),
            "hx-target": "#settings-content",
            "hx-push-url": "true",
            "hx-select": "#notification-template-view",
            "hx-select-oob": "#settings-sidebar",
            "perm": "notifications.view_notificationtemplate",
        },
    ]
