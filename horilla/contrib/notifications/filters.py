"""Filter classes for notification template models."""

# First party imports (Horilla)
from horilla.contrib.generics.filters import HorillaFilterSet

# Local imports
from .models import NotificationTemplate

# Define your notifications filters here


class NotificationTemplateFilter(HorillaFilterSet):
    """Filter set for HorillaMailTemplate model."""

    class Meta:
        """Meta class for HorillaMailTemplateFilter."""

        model = NotificationTemplate
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = ["title", "message", "content_type__model"]
