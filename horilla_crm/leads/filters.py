"""Filters for Lead and LeadStatus models."""

# First party imports (Horilla)
from horilla.contrib.core.mixins import OwnerFiltersetMixin
from horilla.contrib.generics.filters import HorillaFilterSet

# Local imports
from .models import Lead, LeadAssignmentRule, LeadStatus


class LeadFilter(OwnerFiltersetMixin, HorillaFilterSet):
    """Lead Filter"""

    class Meta:
        """Meta class for LeadFilter"""

        model = Lead
        fields = "__all__"
        exclude = [
            "additional_info",
            "is_convert",
            "message_id",
            "converted_contact",
            "converted_opportunity",
            "converted_at",
        ]
        search_fields = [
            "title",
            "first_name",
            "last_name",
            "email",
            "contact_number",
            "lead_company",
            "city",
        ]


class LeadStatusFilter(HorillaFilterSet):
    """LeadStatus Filter"""

    class Meta:
        """Meta class for LeadStatusFilter"""

        model = LeadStatus
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = ["name"]


class LeadAssignmentFilter(HorillaFilterSet):
    """Lead Assignment Filter"""

    class Meta:
        """Meta class for Lead Assignment Filter"""

        model = LeadAssignmentRule
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = ["name", "description"]
