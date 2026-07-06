"""
Registers the Settings → WhatsApp menu section for the whatsapp app
"""

from horilla.menu import settings_menu

# First party imports (Horilla)
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _


@settings_menu.register
class WhatsAppSettings:
    """Registers the WhatsApp section in the admin Settings sidebar."""

    title = _("WhatsApp")
    icon = "whatsapp/assets/icons/whatsapp.svg"
    order = 5
    items = [
        {
            "label": _("Accounts"),
            "url": reverse_lazy("whatsapp:whatsapp_account_view"),
            "hx-target": "#settings-content",
            "hx-push-url": "true",
            "hx-select": "#whatsapp-account-view",
            "hx-select-oob": "#settings-sidebar",
            "perm": "whatsapp.view_whatsappaccount",
        },
        {
            "label": _("Templates"),
            "url": reverse_lazy("whatsapp:whatsapp_template_view"),
            "hx-target": "#settings-content",
            "hx-push-url": "true",
            "hx-select": "#whatsapp-template-view",
            "hx-select-oob": "#settings-sidebar",
            "perm": "whatsapp.view_whatsapptemplate",
        },
        {
            "label": _("Flows"),
            "url": reverse_lazy("whatsapp:whatsapp_flow_view"),
            "hx-target": "#settings-content",
            "hx-push-url": "true",
            "hx-select": "#whatsapp-flow-view",
            "hx-select-oob": "#settings-sidebar",
            "perm": "whatsapp.view_whatsappflow",
        },
        {
            "label": _("Bot Rules"),
            "url": reverse_lazy("whatsapp:whatsapp_bot_rule_view"),
            "hx-target": "#settings-content",
            "hx-push-url": "true",
            "hx-select": "#whatsapp-bot-rule-view",
            "hx-select-oob": "#settings-sidebar",
            "perm": "whatsapp.view_whatsappbotrule",
        },
    ]
