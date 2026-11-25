"""
Tests for the tours of the campaigns app (``horilla_crm/campaigns/tour.py``).
"""

# Third-party imports (Django)
from django.test import SimpleTestCase

# First party imports (Horilla)
from horilla.contrib.tour.registry import _registry
from horilla.contrib.tour.testing import RelatedListStepsMixin, TourOwnershipTestsMixin


class CampaignsTourOwnershipTests(TourOwnershipTestsMixin, SimpleTestCase):
    """The campaigns tours come from this app and start by themselves once."""

    MODULE = "horilla_crm.campaigns.tour"
    KEYS = (
        "campaigns_list",
        "campaigns_detail",
    )


class CampaignTourTests(SimpleTestCase):
    """The Campaigns tours explain campaigns in the campaigns' own words."""

    def test_list_and_detail_use_campaign_wording(self):
        """The list and detail tours say what a campaign is, not a generic record."""
        intro = str(_registry["campaigns_list"].steps[0].body)
        self.assertIn("marketing", intro)
        stages = {
            str(step.title): str(step.body)
            for step in _registry["campaigns_detail"].steps
        }
        self.assertIn("Aborted", stages["Stages"])
        self.assertIn("Campaign Members", stages)


class CampaignsRelatedListStepTests(RelatedListStepsMixin, SimpleTestCase):
    """Each list of the Related Lists tab is explained by its own step."""

    EXPECTED = {
        "campaigns_detail": [
            "Campaign Members",
            "Child Campaigns",
            "Related Opportunities",
        ],
    }
