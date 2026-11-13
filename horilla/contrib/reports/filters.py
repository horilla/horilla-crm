"""Filter definitions for the `horilla.contrib.reports` app."""

# First party imports (Horilla)
from horilla.contrib.generics.filters import HorillaFilterSet

# Local imports
from .models import Report, ReportFolder  # Ensure your Report model is imported


class ReportFilter(HorillaFilterSet):
    """Filter set for filtering reports by various fields."""

    class Meta:
        """Meta options for ReportFilter."""

        model = Report
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = ["name", "folder__name"]


class ReportFolderFilter(HorillaFilterSet):
    """Filter set for searching report folders."""

    class Meta:
        """Meta options for ReportFolderFilter."""

        model = ReportFolder
        fields = ["name"]
        search_fields = ["name"]
