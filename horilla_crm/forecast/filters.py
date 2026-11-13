"""
Filters for the forecast app.

This module defines filter classes used to search and filter forecast records.
"""

# First party imports (Horilla)
from horilla.contrib.generics.filters import HorillaFilterSet

# Local imports
from horilla_crm.forecast.models import ForecastTarget, ForecastType


class ForecastTargetFilter(HorillaFilterSet):
    """
    Filter class for ForecastTarget model
    """

    class Meta:
        """Filter options for the ForecastTarget model."""

        model = ForecastTarget
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = [
            "target_amount",
            "assigned_to__first_name",
            "assigned_to__last_name",
            "role__role_name",
        ]
        name_split_fields = ["assigned_to__first_name", "assigned_to__last_name"]


class ForecastTypeFilter(HorillaFilterSet):
    """
    Filter class for ForecastType model
    """

    class Meta:
        """Filter options for the ForecastType model."""

        model = ForecastType
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = ["name", "description"]
