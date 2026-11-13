"""Filters for horilla.contrib.dashboard app."""

# First party imports (Horilla)
from horilla.contrib.generics.filters import HorillaFilterSet

# Local imports
from .models import Dashboard, DashboardFolder


class DashboardFilter(HorillaFilterSet):
    """Dashboard Filter"""

    class Meta:
        """Meta class for DashboardFilter"""

        model = Dashboard
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = ["name", "description", "folder__name"]


class DashboardFolderFilter(HorillaFilterSet):
    """Filter set for searching dashboard folders."""

    class Meta:
        """Meta class for DashboardFolderFilter"""

        model = DashboardFolder
        fields = ["name", "description"]
        search_fields = ["name", "description"]
