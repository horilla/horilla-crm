"""
Filters for the Accounts app.

This module defines filter classes used to search and filter Account records.
"""

# First party imports (Horilla)
from horilla.contrib.core.mixins import OwnerFiltersetMixin
from horilla.contrib.generics.filters import HorillaFilterSet

# Local imports
from .models import Account


# Define your accounts filters here
class AccountFilter(OwnerFiltersetMixin, HorillaFilterSet):
    """
    Filter configuration for Account model.
    Allows searching and filtering on specific fields.
    """

    class Meta:
        """Filter options for the Account model."""

        model = Account
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = [
            "name",
            "account_number",
            "site",
            "website",
            "contact_number",
            "billing_city",
        ]
