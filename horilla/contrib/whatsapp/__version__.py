"""
Version information for the whatsapp app
"""

from horilla.utils.translation import gettext_lazy as _

__version__ = "1.0.0"
__module_name__ = "Whatsapp"
__description__ = _(
    "WhatsApp Business messaging for records, with company accounts, "
    "live chat on the Activity tab, templates, flows, bot rules, and an "
    "automation delivery channel."
)
__icon__ = "whatsapp/assets/icons/whatsapp.svg"

__1_0_0__ = _(
    "Add live chat updates, an Activity tab, a connection test and an "
    "automation delivery channel. Template variables can use a record's "
    "related contacts. The bot does not greet a Flow reply, keywords match "
    "whole words, and chat messages send in the background. List pages use "
    "the field-aware search."
)
