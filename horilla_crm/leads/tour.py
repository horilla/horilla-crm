"""
Tours of the Leads app: the list page and a single lead.

Picked up through ``"tour"`` in this app's ``auto_import_modules``, like ``menu.py``.
The steps come from ``horilla.contrib.tour.presets`` (shared by every CRM app);
only the ids differ. To add another app (accounts, contacts, ...) give it a
``tour.py`` like this one with that app's ``view_id`` and create-button id.
"""

# First party imports (Horilla)
from horilla.contrib.tour.presets import detail_page_steps, list_page_steps
from horilla.contrib.tour.registry import Tour
from horilla.utils.translation import gettext_lazy as _

LEAD_VIEW_PERMS = ["leads.view_lead", "leads.view_own_lead"]
LEAD_LIST_URL = "leads:leads_view"
FIRST_LEAD = "#data-container-leads-list tr:first-child td[hx-get]"


class LeadsListTour(Tour):
    """The Leads list page."""

    key = "leads_list"
    title = _("Working with the Leads list")
    description = _(
        "Search, filter, switch layouts, select rows and take actions on your leads."
    )
    group = _("Leads")
    icon = "/assets/icons/leads.svg"
    order = 200
    match = (LEAD_LIST_URL,)
    ready = "#navBar h3"
    permission = LEAD_VIEW_PERMS
    auto_start = True
    steps = list_page_steps(
        view_id="leads-list", create_id="lead-create", record_plural=_("leads")
    )


class LeadsDetailTour(Tour):
    """A single lead."""

    key = "leads_detail"
    title = _("Inside a lead")
    description = _(
        "The summary, stages and tabs of a lead: activity, related "
        "records, notes and history."
    )
    group = _("Leads")
    icon = "/assets/icons/leads.svg"
    order = 202
    match = ("leads:leads_detail",)
    open_with = {"from": LEAD_LIST_URL, "click": FIRST_LEAD}
    # Not the header card: that is hidden while the tabs are expanded.
    ready = "#detailViewport"
    permission = LEAD_VIEW_PERMS
    auto_start = True
    steps = detail_page_steps()
