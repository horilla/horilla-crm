"""
This module registers Floating, Settings, My Settings, and Main Section menus
for the Horilla CRM Leads app
"""

# First party imports (Horilla)
from horilla.menu import (
    MAIN_CONTENT_HX_ATTRS,
    MAIN_SECTION_HX_ATTRS,
    floating_menu,
    main_section_menu,
    settings_menu,
    sub_section_menu,
)
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import Lead, LeadStatus


@floating_menu.register
class LeadFloating:
    """Floating menu for Lead model"""

    title = Lead()._meta.verbose_name
    url = reverse_lazy("leads:leads_create_single")
    icon = "/assets/icons/leads.svg"
    items = {
        "hx-target": "#modalBox",
        "hx-swap": "innerHTML",
        "onclick": "openModal()",
        "perm": ["leads.add_lead", "leads.add_own_lead"],
    }


@settings_menu.register
class LeadsSettings:
    """Settings menu for Lead module"""

    title = _("Lead")
    icon = "/assets/icons/lead1.svg"
    order = 4
    items = [
        {
            "label": LeadStatus()._meta.verbose_name_plural,
            "url": reverse_lazy("leads:lead_stage_view"),
            "hx-target": "#settings-content",
            "hx-push-url": "true",
            "hx-select": "#leads-status-view",
            "hx-select-oob": "#settings-sidebar",
            "perm": "leads.view_leadstatus",
        },
        {
            "label": _("Assignment Rules"),
            "url": reverse_lazy("leads:leads_assignment_view"),
            "hx-target": "#settings-content",
            "hx-push-url": "true",
            "hx-select": "#lead-assignment-view",
            "hx-select-oob": "#settings-sidebar",
            "perm": "leads.view_leadassignmentrule",
        },
        {
            "label": _("Email to Record"),
            "url": reverse_lazy("leads:mail_to_lead_view"),
            "hx-target": "#settings-content",
            "hx-push-url": "true",
            "hx-select": "#mail-to-lead-view",
            "hx-select-oob": "#settings-sidebar",
            "perm": "leads.view_emailtoleadconfig",
        },
        {
            "label": _("Web to Lead"),
            "url": reverse_lazy("leads:form_builder"),
            "hx-target": "#settings-content",
            "hx-push-url": "true",
            "hx-select": "#lead-form-builder",
            "hx-select-oob": "#settings-sidebar",
            "perm": "leads.add_leadcaptureform",
        },
    ]


@main_section_menu.register
class SalesSection:
    """
    Registers the Sales section in the main sidebar.
    """

    section = "sales"
    name = _("Sales")
    icon = "/assets/icons/sales.svg"
    position = 1
    attrs = MAIN_SECTION_HX_ATTRS


@sub_section_menu.register
class LeadSubSection:
    """
    Registers the lead menu to sub section in the main sidebar.
    """

    # Identity / placement
    section = "sales"
    app_label = "leads"
    position = 1

    # Display
    verbose_name = _("Leads")
    icon = "/assets/icons/leads.svg"

    # Behavior
    url = reverse_lazy("leads:leads_view")
    attrs = MAIN_CONTENT_HX_ATTRS

    # Access control
    perm = ["leads.view_lead", "leads.view_own_lead"]
