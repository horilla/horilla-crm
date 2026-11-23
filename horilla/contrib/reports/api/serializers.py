"""
Serializers for horilla.contrib.reports models
"""

# Third-party imports (Django)
from rest_framework import serializers

# First party imports (Horilla)
from horilla.api.mixins import CompanyScopedSerializerMixin
from horilla.contrib.core.api.serializers import HorillaUserSerializer
from horilla.contrib.utils.middlewares import get_active_company

# Local imports
from ..models import Report, ReportFolder


class ReportFolderSerializer(CompanyScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for ReportFolder model"""

    report_folder_owner_details = HorillaUserSerializer(
        source="report_folder_owner", read_only=True
    )

    class Meta:
        """Meta options for ReportFolderSerializer."""

        model = ReportFolder
        fields = "__all__"


class ReportSerializer(CompanyScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for Report model"""

    report_owner_details = HorillaUserSerializer(source="report_owner", read_only=True)
    folder_details = ReportFolderSerializer(source="folder", read_only=True)

    class Meta:
        """Meta options for ReportSerializer."""

        model = Report
        fields = "__all__"

    def validate_shared_with(self, users):
        """Reject sharing a report with users outside its own company."""
        # `company` is forced by CompanyScopedSerializerMixin.validate(),
        # which runs after per-field validators, so fall back to the same
        # active_company/user.company resolution here rather than trusting
        # a (possibly attacker-supplied) `company` in initial_data --
        # otherwise a report could be shared cross-tenant, leaking its
        # filters/column definitions (and potentially data) to a user in a
        # different company.
        request = self.context.get("request")
        company = None
        if request is not None and hasattr(request, "user"):
            company = get_active_company(request)
        if company is None:
            company = getattr(self.instance, "company", None)
        if company is not None:
            outside = [u for u in users if getattr(u, "company_id", None) != company.id]
            if outside:
                raise serializers.ValidationError(
                    "Cannot share a report with users outside its company."
                )
        return users
