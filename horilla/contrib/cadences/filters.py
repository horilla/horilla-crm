"""
Filters for the cadences app
"""

# First party imports (Horilla)
from horilla.contrib.core.mixins import OwnerFiltersetMixin
from horilla.contrib.generics.filters import HorillaFilterSet

# Local imports
from .models import Cadence


class CadenceFilter(OwnerFiltersetMixin, HorillaFilterSet):
    """
    cadence filter
    """

    class Meta:
        """
        meta class for Review Process Filter
        """

        model = Cadence
        fields = "__all__"
        exclude = ["additional_info", "id", "review_fields"]
        search_fields = ["name", "description", "module__model"]
