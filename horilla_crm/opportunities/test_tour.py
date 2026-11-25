"""
Tests for the tours of the opportunities app (``horilla_crm/opportunities/tour.py``).
"""

# Third-party imports (Django)
from django.test import SimpleTestCase

# First party imports (Horilla)
from horilla.contrib.tour.testing import RelatedListStepsMixin, TourOwnershipTestsMixin


class OpportunitiesTourOwnershipTests(TourOwnershipTestsMixin, SimpleTestCase):
    """The opportunities tours come from this app and start by themselves once."""

    MODULE = "horilla_crm.opportunities.tour"
    KEYS = (
        "opportunities_list",
        "opportunities_detail",
    )


class OpportunitiesRelatedListStepTests(RelatedListStepsMixin, SimpleTestCase):
    """Each list of the Related Lists tab is explained by its own step."""

    EXPECTED = {
        "opportunities_detail": ["Contact Roles", "Opportunity Team"],
    }
