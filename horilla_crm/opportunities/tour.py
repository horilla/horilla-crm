"""
Tours of the Opportunities app: the list page, and a single opportunity.

Picked up through ``"tour"`` in this app's ``auto_import_modules``, like ``menu.py``.
The list and detail steps come from ``horilla.contrib.tour.presets`` (shared by every
CRM app) with Opportunities wording on top. A step whose element is missing (no
permission, a field hidden by the form layout, an empty list) is skipped.
"""

# First party imports (Horilla)
from horilla.contrib.tour.presets import detail_page_steps, list_page_steps
from horilla.contrib.tour.registry import Tour
from horilla.utils.translation import gettext_lazy as _

OPPORTUNITY_VIEW_PERMS = [
    "opportunities.view_opportunity",
    "opportunities.view_own_opportunity",
]
OPPORTUNITY_LIST_URL = "opportunities:opportunities_view"
CREATE_BUTTON = "opportunity-create"
FIRST_OPPORTUNITY = "#data-container-opportunity-container tr:first-child td[hx-get]"


class OpportunitiesListTour(Tour):
    """The Opportunities list page."""

    key = "opportunities_list"
    title = _("Working with the Opportunities List")
    description = _(
        "Find your deals, switch layouts, select rows and add a new " "opportunity."
    )
    group = _("Opportunities")
    icon = "/assets/icons/opportunities.svg"
    order = 210
    match = (OPPORTUNITY_LIST_URL,)
    ready = "#navBar h3"
    permission = OPPORTUNITY_VIEW_PERMS
    auto_start = True
    steps = list_page_steps(
        view_id="opportunity-container",
        create_id=CREATE_BUTTON,
        record_plural=_("opportunities"),
        intro=_("An opportunity is a deal you are working to win."),
        create_body=_("Add a new opportunity here. A short form opens."),
    )


class OpportunitiesDetailTour(Tour):
    """A single opportunity."""

    key = "opportunities_detail"
    title = _("Inside an Opportunity")
    description = _(
        "The summary, stages and tabs of a deal: activity, related records, "
        "notes and history."
    )
    group = _("Opportunities")
    icon = "/assets/icons/opportunities.svg"
    order = 212
    match = ("opportunities:opportunity_detail_view",)
    open_with = {"from": OPPORTUNITY_LIST_URL, "click": FIRST_OPPORTUNITY}
    # Not the header card: that is hidden while the tabs are expanded.
    ready = "#detailViewport"
    permission = OPPORTUNITY_VIEW_PERMS
    auto_start = True
    steps = detail_page_steps(
        intro=_("One deal in full: its value, stage and linked records."),
        stages_body=_(
            "Each stage is a step in your sales process. Click one to move the deal forward."
        ),
        related_lists=[
            (
                "contact",
                _("Contact Roles"),
                _("The people involved in the deal and the role each plays."),
            ),
            (
                "opportunity_team_members",
                _("Opportunity Team"),
                _("Colleagues who work on this deal with you."),
            ),
        ],
    )
