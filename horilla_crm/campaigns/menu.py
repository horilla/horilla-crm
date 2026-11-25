"""
This module registers Floating, Settings, My Settings, and Main Section menus
for the Horilla CRM Campaigns app
"""

# First party imports (Horilla)
from horilla.menu import MAIN_CONTENT_HX_ATTRS, floating_menu, sub_section_menu
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import Campaign


@floating_menu.register
class CampaignFloating:
    """
    Campaign Floating Menu
    """

    title = Campaign()._meta.verbose_name
    url = reverse_lazy("campaigns:campaign_single_create")
    icon = "/assets/icons/campaign.svg"
    items = {
        "hx-target": "#modalBox",
        "hx-swap": "innerHTML",
        "onclick": "openModal()",
        "perm": ["campaigns.add_campaign", "campaigns.add_own_campaign"],
    }


@sub_section_menu.register
class CampaignSubSection:
    """
    Registers the campaigns menu to sub section in the main sidebar.
    """

    # Identity / placement
    section = "sales"
    app_label = "campaigns"
    position = 3

    # Display
    verbose_name = _("Campaigns")
    icon = "/assets/icons/campaign.svg"

    # Behavior
    url = reverse_lazy("campaigns:campaign_view")
    attrs = MAIN_CONTENT_HX_ATTRS

    # Access control
    perm = ["campaigns.view_campaign", "campaigns.view_own_campaign"]
