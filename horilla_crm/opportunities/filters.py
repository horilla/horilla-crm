"""
Filters for the Opportunities module.

Provides filtering and search capabilities for Opportunity-related models
using HorillaFilterSet. Each filter class allows filtering all fields
(except 'additional_info') and provides specific search fields.
"""

# First party imports (Horilla)
from horilla.contrib.core.mixins import OwnerFiltersetMixin
from horilla.contrib.generics.filters import HorillaFilterSet

# Local imports
from horilla_crm.opportunities.models import (
    DefaultOpportunityMember,
    Opportunity,
    OpportunityStage,
    OpportunityTeam,
)


class OpportunityFilter(OwnerFiltersetMixin, HorillaFilterSet):
    """Filter for Opportunity model with search on 'name'."""

    class Meta:
        """Meta options for OpportunityFilter."""

        model = Opportunity
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = [
            "name",
            "account__name",
            "email",
            "order_number",
            "next_step",
            "description",
        ]


class OpportunityStageFilter(HorillaFilterSet):
    """Filter for OpportunityStage model with search on 'name'."""

    class Meta:
        """Meta options for OpportunityStageFilter."""

        model = OpportunityStage
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = ["name"]


class OpportunityTeamFilter(HorillaFilterSet):
    """Filter for OpportunityTeam model with search on 'team_name'."""

    class Meta:
        """Meta options for OpportunityTeamFilter."""

        model = OpportunityTeam
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = ["team_name", "description"]


class OpportunityTeamMembersFilter(HorillaFilterSet):
    """Filter for DefaultOpportunityMember model with search on user names."""

    class Meta:
        """Meta options for OpportunityTeamMembersFilter."""

        model = DefaultOpportunityMember
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = [
            "user__first_name",
            "user__last_name",
            "team__team_name",
        ]
        name_split_fields = ["user__first_name", "user__last_name"]
