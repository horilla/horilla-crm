"""Filters for ScoringRule model."""

from horilla.contrib.generics.filters import HorillaFilterSet
from horilla_crm.scoring_rules.models import ScoringRule


class ScoringRuleFilter(HorillaFilterSet):
    """Filter set for scoring rules."""

    class Meta:  # pylint: disable=missing-class-docstring
        model = ScoringRule
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = ["name", "description"]
