"""
Tests for the tours of the leads app (``horilla_crm/leads/tour.py``).
"""

# Third-party imports (Django)
from django.test import SimpleTestCase

# First party imports (Horilla)
from horilla.contrib.tour.testing import RelatedListStepsMixin, TourOwnershipTestsMixin


class LeadsTourOwnershipTests(TourOwnershipTestsMixin, SimpleTestCase):
    """The leads tours come from this app and start by themselves once."""

    MODULE = "horilla_crm.leads.tour"
    KEYS = (
        "leads_list",
        "leads_detail",
    )


class LeadsRelatedListStepTests(RelatedListStepsMixin, SimpleTestCase):
    """Each list of the Related Lists tab is explained by its own step."""

    EXPECTED = {
        "leads_detail": ["Campaigns"],
    }
