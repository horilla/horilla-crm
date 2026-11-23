"""
This module defines the RecycleBin and RecycleBinPolicy models for soft-deletion and
retention policies in the Horilla platform.
"""

# Standard library imports
import json
from datetime import date, datetime, timedelta

# Django imports
# Third-party imports (Django)
from django.conf import settings

from horilla.contrib.utils.middlewares import _thread_local, get_active_company
from horilla.db import models
from horilla.urls import reverse_lazy

# First party imports (Horilla)
from horilla.utils import timezone
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .base import Company, CompanyFilteredManager


class RecycleBin(models.Model):
    """
    Model to store soft-deleted records with their serialized data.
    """

    model_name = models.CharField(max_length=255, verbose_name=_("Model Name"))
    record_id = models.CharField(max_length=255)
    data = models.TextField()
    deleted_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Deleted At"))
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recycle_delete",
        verbose_name=_("Deleted By"),
    )
    company = models.ForeignKey(
        "Company",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Company"),
    )
    objects = CompanyFilteredManager()

    class Meta:
        """
        Meta options for the RecycleBin model.
        """

        verbose_name = _("Recycle Bin")
        verbose_name_plural = _("Recycle Bin")

    def __str__(self):
        return f"{self.model_name} ({self.record_id}) - Deleted at {self.deleted_at}"

    def get_model_display_name(self):
        """
        Returns just the model name in a human-readable format
        """
        model_part = self.model_name.split(".")[-1]

        return "".join(word.title() for word in model_part.split("_"))

    def record_name(self):
        """
        Returns a display-friendly name for the deleted object,
        extracted from the serialized JSON data.
        """

        data = json.loads(self.data)

        if "__str__" in data and data["__str__"]:
            return data["__str__"]
        return None

    def get_delete_url(self):
        """
        this method to get delete url
        """
        return reverse_lazy("core:recycle_bin_delete", kwargs={"pk": self.pk})

    def get_restore_url(self):
        """
        this method to get delete url
        """
        return reverse_lazy("core:recycle_bin_restore", kwargs={"pk": self.pk})

    def serialize_data(self, obj):
        """
        Serialize the object data to JSON, handling non-serializable types.
        """

        data = {}
        try:
            data["__str__"] = str(obj)
        except Exception:
            data["__str__"] = None

        for field in obj._meta.fields:
            if field.name in ["id"]:
                continue
            value = getattr(obj, field.name, None)

            if value is not None:
                if isinstance(value, (datetime, date)):
                    value = value.isoformat()
                elif field.is_relation:
                    value = value.pk if value else None
                elif isinstance(value, (bytes, bytearray)):
                    value = value.decode("utf-8", errors="ignore")
                elif not isinstance(value, (str, int, float, bool, type(None))):
                    value = str(value)
                data[field.name] = value
            else:
                data[field.name] = None
        self.data = json.dumps(data)

    @classmethod
    def create_from_instance(cls, instance, user=None):
        """
        Create a soft-deleted record from a model instance.
        """
        soft_record = cls(
            model_name=f"{instance._meta.app_label}.{instance._meta.model_name}",
            record_id=str(instance.pk),
            deleted_by=user,
        )
        soft_record.serialize_data(instance)
        request = getattr(_thread_local, "request", None)
        soft_record.company = get_active_company(request)

        soft_record.save()
        return soft_record


class RecycleBinPolicy(models.Model):
    """
    Model to store retention policy for RecycleBin records per company.
    """

    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name="recycle_bin_policy",
        verbose_name=_("Company"),
    )
    retention_days = models.PositiveIntegerField(
        default=30, verbose_name=_("Retention Period (days)")
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))
    objects = CompanyFilteredManager()

    class Meta:
        """
        Meta options for the RecycleBinPolicy model.
        """

        verbose_name = _("Recycle Bin Policy")
        verbose_name_plural = _("Recycle Bin Policies")

    def save(self, *args, **kwargs):
        """Set company from request active_company before saving."""
        request = getattr(_thread_local, "request", None)
        self.company = get_active_company(request)
        super().save(*args, **kwargs)

    def __str__(self):
        if not self.retention_days:
            return f"{self.company.name} - No expiry"
        return f"{self.company.name} - {self.retention_days} days"

    def is_expired(self, deleted_at):
        """
        Check if a deleted_at timestamp exceeds the retention period.
        """
        if not self.retention_days:
            return False

        retention_period = timezone.now() - timedelta(days=self.retention_days)
        return deleted_at < retention_period
