"""
This module is responsible for registering the notification template feature in the Horilla framework. It imports the necessary function to register the feature and then registers the "notification_template" feature with its corresponding models."
"""

# First party imports (Horilla)
from horilla.registry.delivery import register_delivery_channel
from horilla.registry.feature import register_feature, register_models_for_feature

# Local imports
from .delivery import NotificationChannel

register_feature("notification_template", "notification_template_models")

# Automations can send through this app as "Send as Notification".
register_delivery_channel(NotificationChannel())

# Personal preferences/logs: ignored in the delete dependency dialog.
register_models_for_feature(
    models=[
        ("notifications", "Notification"),
        ("notifications", "NotificationSoundPreference"),
    ],
    features=["delete_dependency"],
)
