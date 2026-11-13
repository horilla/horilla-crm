"""
filters module for Activity model to enable filtering based on various fields.
"""

# First party imports (Horilla)
from horilla.contrib.core.mixins import OwnerFiltersetMixin
from horilla.contrib.generics.filters import HorillaFilterSet

# Local imports
from .models import Activity


class ActivityFilter(OwnerFiltersetMixin, HorillaFilterSet):
    """
    ActivityFilter class for filtering Activity model instances.
    """

    class Meta:
        """
        meta class for ActivityFilter
        """

        model = Activity
        fields = "__all__"
        exclude = ["additional_info", "id", "external_participants"]
        search_fields = [
            "subject",
            "title",
            "activity_type",
            "location",
            "description",
            "owner__first_name",
            "owner__last_name",
        ]
        name_split_fields = ["owner__first_name", "owner__last_name"]
