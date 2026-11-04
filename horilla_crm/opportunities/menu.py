"""
This module registers Floating, Settings, My Settings, and Main Section menus
for the Horilla CRM Opportunities app
"""

# First party imports (Horilla)
from horilla.menu import (
    MAIN_CONTENT_HX_ATTRS,
    floating_menu,
    my_settings_menu,
    settings_menu,
    sub_section_menu,
)
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import Opportunity, OpportunitySettings, OpportunityStage


@sub_section_menu.register
class OpportunitiesSubSection:
    """
    Registers the opportunities menu to sub section in the main sidebar.
    """

    # Identity / placement
    section = "sales"
    app_label = "opportunities"
    position = 3

    # Display
    verbose_name = _("Opportunities")
    icon = "/assets/icons/opportunities.svg"

    # Behavior
    url = reverse_lazy("opportunities:opportunities_view")
    attrs = MAIN_CONTENT_HX_ATTRS

    # Access control
    perm = [
        "opportunities.view_opportunity",
        "opportunities.view_own_opportunity",
    ]


@floating_menu.register
class OpportunitiesFloating:
    """Floating menu configuration for the Opportunity model."""

    title = Opportunity()._meta.verbose_name
    url = reverse_lazy("opportunities:opportunity_single_create")
    icon = "/assets/icons/opportunities.svg"
    items = {
        "hx-target": "#modalBox",
        "hx-swap": "innerHTML",
        "onclick": "openModal()",
        "perm": ["opportunities.add_opportunity", "opportunities.add_own_opportunity"],
    }


@my_settings_menu.register
class OpportunityTeamSettings:
    """'My Settings' menu entry for Opportunity Teams."""

    title = _("Opportunity Team")
    url = reverse_lazy("opportunities:opportunity_team_view")
    active_urls = [
        "opportunities:opportunity_team_view",
        "opportunities:opportunity_team_detail_view",
    ]
    order = 5
    attrs = {
        "hx-boost": "true",
        "hx-target": "#my-settings-content",
        "hx-push-url": "true",
        "hx-select": "#opportunity-team-view",
        "hx-select-oob": "#my-settings-sidebar",
    }
    condition = staticmethod(OpportunitySettings.is_team_selling_enabled)


@settings_menu.register
class OpportunitiesSettings:
    """Settings menu entries for the Opportunities module."""

    title = _("Opportunity")
    icon = "/assets/icons/oppor.svg"
    order = 5
    items = [
        {
            "label": OpportunityStage()._meta.verbose_name_plural,
            "url": reverse_lazy("opportunities:opportunity_stage_view"),
            "hx-target": "#settings-content",
            "hx-push-url": "true",
            "hx-select": "#opportunity-stage-view",
            "hx-select-oob": "#settings-sidebar",
            "perm": "opportunities.view_opportunitystage",
        },
        {
            "label": _("Opportunity Team Settings"),
            "url": reverse_lazy("opportunities:team_selling_setup"),
            "hx-target": "#settings-content",
            "hx-push-url": "true",
            "hx-select": "#opportunity-team-settings",
            "hx-select-oob": "#settings-sidebar",
            "perm": "opportunities.view_opportunitysettings",
        },
        {
            "label": _("Opportunity Split Settings"),
            "url": reverse_lazy("opportunities:opportunity_split_view"),
            "hx-target": "#settings-content",
            "hx-push-url": "true",
            "hx-select": "#opportunity-split-view",
            "hx-select-oob": "#settings-sidebar",
            "perm": "opportunities.view_opportunitysplittype",
            "condition": staticmethod(OpportunitySettings.is_team_selling_enabled),
        },
        {
            "label": _("Big Deal Alerts"),
            "url": reverse_lazy("opportunities:big_deal_alert_view"),
            "hx-target": "#settings-content",
            "hx-push-url": "true",
            "hx-select": "#big-deal-alert-view",
            "hx-select-oob": "#settings-sidebar",
            "perm": "automations.view_horillaautomation",
        },
    ]
