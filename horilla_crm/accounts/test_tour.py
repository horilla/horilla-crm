"""
Tests for the tours of the accounts app (``horilla_crm/accounts/tour.py``).
"""

# Third-party imports (Django)
from django.test import SimpleTestCase

# First party imports (Horilla)
from horilla.contrib.tour.testing import RelatedListStepsMixin, TourOwnershipTestsMixin


class AccountsTourOwnershipTests(TourOwnershipTestsMixin, SimpleTestCase):
    """The accounts tours come from this app and start by themselves once."""

    MODULE = "horilla_crm.accounts.tour"
    KEYS = (
        "accounts_list",
        "accounts_detail",
    )


class AccountsRelatedListStepTests(RelatedListStepsMixin, SimpleTestCase):
    """Each list of the Related Lists tab is explained by its own step."""

    EXPECTED = {
        "accounts_detail": [
            "Child Accounts",
            "Opportunities",
            "Related Contacts",
            "Partner",
        ],
    }
