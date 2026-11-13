"""
Filters for the contacts app.

This module defines filter classes used to search and filter contact records.
"""

# First party imports (Horilla)
from horilla.contrib.core.mixins import OwnerFiltersetMixin
from horilla.contrib.generics.filters import HorillaFilterSet

# Local imports
from .models import Contact


class ContactFilter(OwnerFiltersetMixin, HorillaFilterSet):
    """
    Filter class for contact model
    """

    class Meta:
        """Filter options for the Contact model."""

        model = Contact
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = [
            "title",
            "first_name",
            "last_name",
            "email",
            "contact_number",
            "address_city",
        ]
