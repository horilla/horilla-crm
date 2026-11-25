"""
Tests for the tours of the contacts app (``horilla_crm/contacts/tour.py``).
"""

# Third-party imports (Django)
from django.test import SimpleTestCase

# First party imports (Horilla)
from horilla.contrib.tour.testing import RelatedListStepsMixin, TourOwnershipTestsMixin


class ContactsTourOwnershipTests(TourOwnershipTestsMixin, SimpleTestCase):
    """The contacts tours come from this app and start by themselves once."""

    MODULE = "horilla_crm.contacts.tour"
    KEYS = (
        "contacts_list",
        "contacts_detail",
    )


class ContactsRelatedListStepTests(RelatedListStepsMixin, SimpleTestCase):
    """Each list of the Related Lists tab is explained by its own step."""

    EXPECTED = {
        "contacts_detail": [
            "Child Contacts",
            "Related Campaigns",
            "Related Opportunities",
            "Related Accounts",
        ],
    }
