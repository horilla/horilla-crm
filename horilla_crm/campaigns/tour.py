"""
Tours of the Campaigns app: the list page and a single campaign.

Picked up through ``"tour"`` in this app's ``auto_import_modules``, like ``menu.py``.
The list and detail steps come from ``horilla.contrib.tour.presets`` (shared by every
CRM app) with Campaigns wording on top, so a first-time user learns what a campaign is
as well as where the buttons are.

A step whose element is missing (no permission, a field hidden by the form layout, an
empty list) is skipped, so the tours stay correct when a company changes its layout.
"""

# First party imports (Horilla)
from horilla.contrib.tour.presets import detail_page_steps, list_page_steps
from horilla.contrib.tour.registry import Tour
from horilla.utils.translation import gettext_lazy as _

CAMPAIGN_VIEW_PERMS = ["campaigns.view_campaign", "campaigns.view_own_campaign"]
CAMPAIGN_LIST_URL = "campaigns:campaign_view"
CREATE_BUTTON = "campaign-create"
FIRST_CAMPAIGN = "#data-container-campaign-list tr:first-child td[hx-get]"


class CampaignsListTour(Tour):
    """The Campaigns list page."""

    key = "campaigns_list"
    title = _("Working with the Campaigns List")
    description = _(
        "Find your marketing campaigns, switch layouts, select rows and "
        "add a new campaign."
    )
    group = _("Campaigns")
    icon = "/assets/icons/campaign.svg"
    order = 220
    match = (CAMPAIGN_LIST_URL,)
    ready = "#navBar h3"
    permission = CAMPAIGN_VIEW_PERMS
    auto_start = True
    steps = list_page_steps(
        view_id="campaign-list",
        create_id=CREATE_BUTTON,
        record_plural=_("campaigns"),
        intro=_("A campaign is a marketing effort, like an email, webinar or ad."),
        create_body=_("Add a new campaign here. A short form opens."),
    )


class CampaignsDetailTour(Tour):
    """A single campaign."""

    key = "campaigns_detail"
    title = _("Inside a Campaign")
    description = _(
        "The summary, status and tabs of a campaign: activity, members, "
        "related opportunities, notes and history."
    )
    group = _("Campaigns")
    icon = "/assets/icons/campaign.svg"
    order = 222
    match = ("campaigns:campaign_detail_view",)
    open_with = {"from": CAMPAIGN_LIST_URL, "click": FIRST_CAMPAIGN}
    # Not the header card: that is hidden while the tabs are expanded.
    ready = "#detailViewport"
    permission = CAMPAIGN_VIEW_PERMS
    auto_start = True
    steps = detail_page_steps(
        intro=_("One campaign in full: its dates, status and linked records."),
        stages_body=_(
            "The campaign's status: New, Planned, In Progress, Completed or Aborted. Click one to update it."
        ),
        related_lists=[
            (
                "members",
                _("Campaign Members"),
                _("The leads and contacts you are reaching."),
            ),
            (
                "child_campaigns",
                _("Child Campaigns"),
                _("Smaller campaigns that belong to this one."),
            ),
            (
                "opportunities",
                _("Related Opportunities"),
                _("Deals this campaign helped create."),
            ),
        ],
    )
