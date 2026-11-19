"""
Test-only model for the mobile tests.

It lives in the tests package on purpose: ``horilla.contrib.mobile`` itself
has no models and no migrations, and its tests never import ``horilla_crm``.
``tests/base.py`` creates its table for the tests that use it.
"""

# Third-party imports (Django)
from django.conf import settings

from horilla.contrib.core.models import HorillaCoreModel

# First party imports (Horilla)
from horilla.db import models
from horilla.urls import reverse


class MobileTestRecord(HorillaCoreModel):
    """A record with a name, two phones, an email, a status and an owner."""

    STATUS_CHOICES = [
        ("new", "New"),
        ("contacted", "Contacted"),
        ("won", "Won"),
    ]

    name = models.CharField(max_length=100, verbose_name="Name")
    phone = models.CharField(max_length=40, blank=True, verbose_name="Phone")
    mobile_phone = models.CharField(
        max_length=40, blank=True, verbose_name="Mobile phone"
    )
    email = models.EmailField(blank=True, verbose_name="Email")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="new", verbose_name="Status"
    )
    city = models.CharField(max_length=50, blank=True, verbose_name="City")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="Owner",
    )

    OWNER_FIELDS = ["owner"]

    class Meta:
        """Meta."""

        app_label = "mobile"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_detail_url(self):
        """Desktop detail page, served by ``tests/urls.py``."""
        return reverse("mobile_test_record_detail", args=[self.pk])
