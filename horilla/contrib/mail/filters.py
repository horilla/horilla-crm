"""Filter classes for mail models."""

# First party imports (Horilla)
from horilla.contrib.generics.filters import HorillaFilterSet

# Local imports
from .models import (
    HorillaMail,
    HorillaMailConfiguration,
    HorillaMailTemplate,
    IncomingMail,
)

# Define your mail filters here


class HorillaMailServerFilter(HorillaFilterSet):
    """Filter set for HorillaMailConfiguration model."""

    class Meta:
        """Meta class for HorillaMailServerFilter."""

        model = HorillaMailConfiguration
        fields = "__all__"
        exclude = ["additional_info", "token"]
        search_fields = ["host", "username", "from_email", "display_name"]


class HorillaMailTemplateFilter(HorillaFilterSet):
    """Filter set for HorillaMailTemplate model."""

    class Meta:
        """Meta class for HorillaMailTemplateFilter."""

        model = HorillaMailTemplate
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = ["title", "subject"]


class HorillaMailHistoryFilter(HorillaFilterSet):
    """Filter set for HorillaMail history list."""

    class Meta:
        """Meta class for HorillaMailHistoryFilter."""

        model = HorillaMail
        fields = "__all__"
        exclude = [
            "body",
            "rendered_body",
            "rendered_subject",
            "tracking_uid",
            "mail_status_message",
            "content_type",
            "object_id",
            "additional_info",
        ]
        search_fields = ["subject", "to", "cc"]


class IncomingMailFilter(HorillaFilterSet):
    """Filter set for IncomingMail list."""

    class Meta:
        """Meta class for IncomingMailFilter."""

        model = IncomingMail
        fields = "__all__"
        exclude = [
            "body",
            "cc",
            "message_id",
            "in_reply_to",
            "references",
            "additional_info",
        ]
        search_fields = ["sender_email", "sender_name", "subject"]
