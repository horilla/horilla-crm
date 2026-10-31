"""
Feature registration for Horilla Mail app.
"""

# First party imports (Horilla)
from horilla.registry.delivery import register_delivery_channel
from horilla.registry.feature import register_feature, register_model_for_feature

# Local imports
from .delivery import MailChannel

register_feature("mail_template", "mail_template_models")

# Automations can send through this app as "Send as Mail".
register_delivery_channel(MailChannel())

register_model_for_feature(
    app_label="mail",
    model_name="HorillaMail",
    features=["export_data"],
)
