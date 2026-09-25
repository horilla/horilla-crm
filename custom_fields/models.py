"""Models for Custom Field definitions and per-record values."""

import json
from datetime import date, datetime

from django.utils.dateparse import parse_date, parse_datetime

from horilla.contrib.core.models import HorillaContentType, HorillaCoreModel
from horilla.db import models
from horilla.urls import reverse_lazy
from horilla.utils import timezone
from horilla.utils.translation import gettext_lazy as _


def parse_choice_values(stored):
    """Return selected Multiple Choice values from stored text or a list."""
    if stored in (None, ""):
        return []
    if isinstance(stored, (list, tuple, set)):
        return [str(item) for item in stored if item not in (None, "")]
    text = str(stored).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item not in (None, "")]
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return [text]


def serialize_choice_values(val):
    """Store Multiple Choice selections as a JSON list (legacy singles still parse)."""
    items = parse_choice_values(val)
    if not items:
        return ""
    return json.dumps(items, ensure_ascii=False)


def format_choice_display(val):
    """Join selected choices for detail, list, export, and inline display."""
    return ", ".join(parse_choice_values(val))


def to_date_value(val):
    """
    Return a Gregorian ``date`` from a date, datetime, or ISO string, else None.

    Date inputs always post ISO ``YYYY-MM-DD``; the Jalali picker converts
    Shamsi selections back to Gregorian before submit, so no calendar
    conversion is needed here.
    """
    if val in (None, ""):
        return None
    if isinstance(val, datetime):
        return timezone.localtime(val).date() if timezone.is_aware(val) else val.date()
    if isinstance(val, date):
        return val
    text = str(val).strip()
    try:
        return parse_date(text) or _date_from_datetime_text(text)
    except ValueError:
        return None


def _date_from_datetime_text(text):
    parsed = to_datetime_value(text)
    return timezone.localtime(parsed).date() if parsed else None


def to_datetime_value(val):
    """
    Return an aware ``datetime`` from a datetime, date, or ISO string, else None.

    Naive values (e.g. ``datetime-local`` input ``YYYY-MM-DDTHH:MM``) are read
    in the active timezone, matching how Django forms clean ``DateTimeField``.
    """
    if val in (None, ""):
        return None
    if isinstance(val, datetime):
        parsed = val
    elif isinstance(val, date):
        parsed = datetime(val.year, val.month, val.day)
    else:
        text = str(val).strip()
        try:
            parsed = parse_datetime(text)
            if parsed is None:
                day = parse_date(text)
                parsed = datetime(day.year, day.month, day.day) if day else None
        except ValueError:
            return None
        if parsed is None:
            return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


class CustomFieldDefinition(HorillaCoreModel):
    """
    Defines a user-created custom field attached to a specific model
    (currently Lead or Opportunity).
    """

    FIELD_TYPES = [
        ("small_text", _("Small Text")),
        ("large_text", _("Large Text")),
        ("number", _("Number")),
        ("choice", _("Multiple Choice")),
        ("single_choice", _("Single Choice")),
        ("date", _("Date")),
        ("datetime", _("Date and Time")),
    ]

    content_type = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        verbose_name=_("Model"),
    )
    name = models.CharField(max_length=255, verbose_name=_("Field Name"))
    field_type = models.CharField(
        max_length=20, choices=FIELD_TYPES, verbose_name=_("Field Type")
    )
    is_required = models.BooleanField(default=False, verbose_name=_("Required"))
    choices = models.TextField(
        blank=True,
        help_text=_("Comma-separated list of choices (only for Multiple Choice type)"),
        verbose_name=_("Choices"),
    )
    order = models.PositiveIntegerField(default=0, verbose_name=_("Display Order"))

    class Meta:
        """Ordering and uniqueness for custom field definitions per company."""

        ordering = ["order", "pk"]
        unique_together = [("content_type", "name", "company")]
        verbose_name = _("Custom Field")
        verbose_name_plural = _("Custom Fields")

    def __str__(self):
        return self.name

    def get_edit_url(self):
        """Return the HTMX edit URL for this definition."""
        return reverse_lazy("custom_fields:edit", kwargs={"pk": self.pk})

    def get_delete_url(self):
        """Return the HTMX delete URL for this definition."""
        return reverse_lazy("custom_fields:delete", kwargs={"pk": self.pk})

    def get_choices_list(self):
        """Return choice options as a stripped list of strings."""
        if not self.choices:
            return []
        return [c.strip() for c in self.choices.split(",") if c.strip()]


class CustomFieldValue(HorillaCoreModel):
    """
    Stores the value of a custom field for a specific object instance.
    """

    field_definition = models.ForeignKey(
        CustomFieldDefinition,
        on_delete=models.CASCADE,
        related_name="values",
        verbose_name=_("Field Definition"),
    )
    content_type = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        verbose_name=_("Model"),
    )
    object_id = models.PositiveIntegerField(verbose_name=_("Object ID"))

    value_text = models.TextField(blank=True, default="", verbose_name=_("Value"))
    value_number = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name=_("Numeric Value"),
    )
    value_date = models.DateField(null=True, blank=True, verbose_name=_("Date Value"))
    value_datetime = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Date and Time Value")
    )

    class Meta:
        """One value per definition and target object."""

        unique_together = [("field_definition", "content_type", "object_id")]
        verbose_name = _("Custom Field Value")
        verbose_name_plural = _("Custom Field Values")

    def __str__(self):
        return f"{self.field_definition.name}: {self.get_display_value()}"

    def get_value(self):
        """Return the typed Python value for this field's type."""
        field_type = self.field_definition.field_type
        if field_type == "number":
            return self.value_number
        if field_type == "date":
            return self.value_date
        if field_type == "datetime":
            return self.value_datetime
        if field_type == "choice":
            return parse_choice_values(self.value_text)
        if field_type == "single_choice":
            values = parse_choice_values(self.value_text)
            return values[0] if values else ""
        return self.value_text

    def get_display_value(self):
        """Return a user-facing string for list/detail display."""
        if self.field_definition.field_type in ("choice", "single_choice"):
            return format_choice_display(self.value_text)
        value = self.get_value()
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return "" if value is None else str(value)

    def set_value(self, val):
        """Store ``val`` in the column for this field type and clear the others."""
        from decimal import Decimal, InvalidOperation

        field_type = self.field_definition.field_type
        self.value_text = ""
        self.value_number = None
        self.value_date = None
        self.value_datetime = None
        if field_type == "number":
            try:
                self.value_number = Decimal(str(val)) if val not in (None, "") else None
            except (InvalidOperation, ValueError):
                self.value_number = None
        elif field_type == "date":
            self.value_date = to_date_value(val)
        elif field_type == "datetime":
            self.value_datetime = to_datetime_value(val)
        elif field_type in ("choice", "single_choice"):
            self.value_text = serialize_choice_values(val)
        else:
            self.value_text = str(val) if val is not None else ""


# Django and Horilla store these on auth.Permission.name. Groups & Permissions
# gettext's perm.name for extra actions, and titles the row with verbose_name.
PERMISSION_UI_NAMES = (
    _("Can add Custom Field"),
    _("Can change Custom Field"),
    _("Can delete Custom Field"),
    _("Can view Custom Field"),
    _("Can create own Custom Field"),
    _("Can change own Custom Field"),
    _("Can delete own Custom Field"),
    _("Can view own Custom Field"),
    _("Can add Custom Field Value"),
    _("Can change Custom Field Value"),
    _("Can delete Custom Field Value"),
    _("Can view Custom Field Value"),
    _("Can create own Custom Field Value"),
    _("Can change own Custom Field Value"),
    _("Can delete own Custom Field Value"),
    _("Can view own Custom Field Value"),
)
