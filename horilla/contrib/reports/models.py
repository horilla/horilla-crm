"""Models for reports and folders used by `horilla.contrib.reports`.

Includes `Report` and `ReportFolder` models with helper properties
for presentation and serialization used by the reports UI.
"""

# Standard library imports
import json

# Third-party imports (Django)
from django.conf import settings

from horilla.contrib.core.models import HorillaContentType, HorillaCoreModel
from horilla.contrib.reports.utils import (
    _virtual_fields_for,
    get_report_related_fields,
    resolve_report_field,
)
from horilla.contrib.utils.methods import render_template

# First party imports (Horilla)
from horilla.db import models
from horilla.registry.limiters import limit_content_types
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _


class ReportFolder(HorillaCoreModel):
    """Model representing a folder for organizing reports."""

    name = models.CharField(max_length=200, verbose_name=_("Folder Name"))
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        verbose_name=_("Folder"),
    )
    is_favourite = models.BooleanField(default=False)
    report_folder_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="report_folders",
        verbose_name=_("Folder Owner"),
    )

    OWNER_FIELDS = ["report_folder_owner"]

    class Meta:
        """Meta options for ReportFolder."""

        verbose_name = _("Report Folder")
        verbose_name_plural = _("Report Folders")

    def __str__(self):
        """Return the folder name as its string representation."""
        return str(self.name)

    def get_item_type(self):
        """Return a short label describing the item type (Folder)."""
        return _("Folder")

    def get_detail_view_url(self):
        """
        This method to get detail view url
        """
        return reverse_lazy("reports:report_folder_detail", kwargs={"pk": self.pk})

    def actions(self):
        """
        This method for get custom column for action.
        """

        return render_template(
            path="reports/folder_actions.html",
            context={"instance": self},
        )

    def actions_detail(self):
        """
        This method for get custom column for action.
        """

        return render_template(
            path="reports/folder_actions_detail.html",
            context={"instance": self},
        )


class Report(HorillaCoreModel):
    """Model to represent a report in the system."""

    CHART_TYPES = [
        ("column", _("Column Chart")),
        ("line", _("Line Chart")),
        ("pie", _("Pie Chart")),
        ("funnel", _("Funnel")),
        ("bar", _("Bar Chart")),
        ("donut", _("Donut")),
        ("stacked_vertical", _("Stacked Vertical Chart")),
        ("stacked_horizontal", _("Stacked Horizontal Chart")),
        ("scatter", _("Scatter Chart")),
        ("treemap", _("Treemap")),
        ("area", _("Area Chart")),
        ("heatmap", _("Heatmap")),
        ("sankey", _("Sankey")),
        ("radar", _("Radar Chart")),
    ]
    report_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reports",
        verbose_name=_("Report Owner"),
    )

    name = models.CharField(max_length=200, verbose_name=_("Report Name"))
    module = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        verbose_name=_("Module"),
        limit_choices_to=limit_content_types("report_models"),
    )
    folder = models.ForeignKey(
        ReportFolder,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_("Folder"),
    )

    selected_columns = models.TextField(blank=True)
    row_groups = models.TextField(blank=True)
    column_groups = models.TextField(blank=True)
    aggregate_columns = models.TextField(blank=True)
    filters = models.TextField(blank=True)

    chart_type = models.CharField(max_length=20, choices=CHART_TYPES, default="bar")
    chart_field = models.CharField(
        max_length=200, blank=True, null=True, verbose_name=_("Chart Field")
    )
    chart_field_stacked = models.CharField(
        max_length=200, blank=True, null=True, verbose_name=_("Secondary Field")
    )
    chart_value_field = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        verbose_name=_("Value Field (Y-axis)"),
    )

    is_favourite = models.BooleanField(default=False)
    shared_with = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="shared_reports"
    )

    OWNER_FIELDS = ["report_owner"]

    class Meta:
        """Meta options for Report."""

        verbose_name = _("Report")
        verbose_name_plural = _("Reports")

    def __str__(self):
        """Return the report name as its string representation."""
        return str(self.name)

    def get_item_type(self):
        """Return a short label describing the item type (Report)."""
        return _("Report")

    @property
    def model_class(self):
        """Get the actual model class from ContentType"""
        return self.module.model_class()

    @property
    def module_verbose_name(self):
        """Return the verbose name of the module's model"""
        model = self.model_class
        return model._meta.verbose_name

    @property
    def selected_columns_list(self):
        """Get selected columns as list"""
        if self.selected_columns:
            return [
                col.strip() for col in self.selected_columns.split(",") if col.strip()
            ]
        return []

    @property
    def row_groups_list(self):
        """Get row groups as list"""
        if self.row_groups:
            return [
                group.strip() for group in self.row_groups.split(",") if group.strip()
            ]
        return []

    @property
    def column_groups_list(self):
        """Get column groups as list"""
        if self.column_groups:
            return [
                group.strip()
                for group in self.column_groups.split(",")
                if group.strip()
            ]
        return []

    @property
    def aggregate_columns_dict(self):
        """Get aggregate columns as a list of dictionaries with validated structure"""
        if not self.aggregate_columns:
            return []

        try:
            data = json.loads(self.aggregate_columns)
            # Convert single dict to list for backward compatibility
            if isinstance(data, dict):
                data = [data]
            elif not isinstance(data, list):
                return []

            # Validate each item has 'field' and 'aggfunc' keys
            validated_data = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                # Ensure 'field' and 'aggfunc' exist, provide defaults if missing
                if "field" not in item or not item["field"]:
                    continue  # Skip invalid entries
                item.setdefault(
                    "aggfunc", "sum"
                )  # Default to 'sum' if 'aggfunc' missing
                validated_data.append(item)

            return validated_data
        except (json.JSONDecodeError, TypeError):
            return []

    @property
    def filters_dict(self):
        """Get filters as dictionary"""
        if self.filters:
            try:
                return json.loads(self.filters)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    def get_available_fields(self):
        """Get all non-JSON fields from the selected model"""
        if not self.model_class:
            return []

        fields_info = []
        excluded_field_types = [
            "JSONField",
            "TextField",
            "BinaryField",
            "FileField",
            "ImageField",
        ]

        for field in self.model_class._meta.get_fields():
            # Skip reverse relations and excluded field types
            if hasattr(field, "related_model") and field.related_model:
                continue
            # Skip id/pk and non-editable fields in report detail
            if field.name in ("id", "pk"):
                continue
            if not getattr(field, "editable", True):
                continue

            field_type = field.__class__.__name__
            if field_type in excluded_field_types:
                continue

            if hasattr(field, "verbose_name"):
                fields_info.append(
                    {
                        "name": field.name,
                        "verbose_name": str(field.verbose_name),
                        "type": field_type,
                        "is_relation": hasattr(field, "related_model"),
                        "is_numeric": field_type
                        in [
                            "IntegerField",
                            "FloatField",
                            "DecimalField",
                            "BigIntegerField",
                        ],
                        "choices": getattr(field, "choices", None),
                    }
                )

        for name, virtual_field in _virtual_fields_for(self.model_class).items():
            fields_info.append(
                {
                    "name": name,
                    "verbose_name": str(virtual_field.verbose_name),
                    "type": "VirtualField",
                    "is_relation": False,
                    "is_numeric": True,
                    "choices": None,
                }
            )

        return fields_info

    def get_available_grouping_fields(self):
        """Get direct fields first, then one level of related-field paths (e.g. "stage__stage_type").

        Used for filter/row-group/column-group pickers, which (unlike plain
        column selection) may traverse a single forward ForeignKey/OneToOne
        relation to reach a scalar field on the related model. Direct fields
        on the report's own model are listed before any related-field entries.
        """
        if not self.model_class:
            return []

        excluded_field_types = [
            "JSONField",
            "TextField",
            "BinaryField",
            "FileField",
            "ImageField",
        ]
        numeric_field_types = [
            "IntegerField",
            "FloatField",
            "DecimalField",
            "BigIntegerField",
        ]

        # Never expose these through a related-field path (e.g. owner__password)
        sensitive_field_names = {
            "password",
            "last_login",
            "date_joined",
            "is_superuser",
            "is_staff",
            "user_permissions",
            "groups",
            "token",
            "secret",
            "api_key",
        }

        def _is_excluded(field):
            if field.name in ("id", "pk"):
                return True
            if not getattr(field, "editable", True):
                return True
            return field.__class__.__name__ in excluded_field_types

        direct_fields = []
        related_fields = []
        for field in self.model_class._meta.get_fields():
            if field.many_to_many or field.one_to_many:
                continue
            if _is_excluded(field):
                continue

            is_relation = isinstance(field, (models.ForeignKey, models.OneToOneField))
            if is_relation:
                direct_fields.append(
                    {
                        "name": field.name,
                        "verbose_name": str(field.verbose_name),
                        "type": field.__class__.__name__,
                        "is_relation": True,
                        "is_numeric": False,
                        "choices": None,
                    }
                )
                related_model = field.related_model
                # Django's ContentType internals (app label, model name) are
                # not meaningful report fields.
                if related_model._meta.label in (
                    "contenttypes.ContentType",
                    "core.HorillaContentType",
                ):
                    continue
                # Only relations the report model registers are expanded, and only
                # with the fields registered for them.
                useful_names = set(
                    get_report_related_fields(
                        self.model_class, field.name, related_model
                    )
                )
                for related_field in related_model._meta.get_fields():
                    if related_field.many_to_many or related_field.one_to_many:
                        continue
                    if related_field.name not in useful_names:
                        continue
                    # A related model's own FKs (e.g. owner -> role) are listed
                    # as leaves; credentials/permission internals never are.
                    if related_field.name in sensitive_field_names:
                        continue
                    if _is_excluded(related_field):
                        continue
                    if not hasattr(related_field, "verbose_name"):
                        continue
                    related_fields.append(
                        {
                            "name": f"{field.name}__{related_field.name}",
                            "verbose_name": f"{field.verbose_name} - {related_field.verbose_name}",
                            "type": related_field.__class__.__name__,
                            "is_relation": False,
                            "is_numeric": related_field.__class__.__name__
                            in numeric_field_types,
                            "choices": getattr(related_field, "choices", None),
                        }
                    )
                continue

            if hasattr(field, "verbose_name"):
                direct_fields.append(
                    {
                        "name": field.name,
                        "verbose_name": str(field.verbose_name),
                        "type": field.__class__.__name__,
                        "is_relation": False,
                        "is_numeric": field.__class__.__name__ in numeric_field_types,
                        "choices": getattr(field, "choices", None),
                    }
                )

        for name, virtual_field in _virtual_fields_for(self.model_class).items():
            direct_fields.append(
                {
                    "name": name,
                    "verbose_name": str(virtual_field.verbose_name),
                    "type": "VirtualField",
                    "is_relation": False,
                    "is_numeric": True,
                    "choices": None,
                }
            )

        return direct_fields + related_fields

    def get_available_columns_choices(self):
        """Get available columns as choices for the multiple select field"""
        fields = self.get_available_fields()
        return [
            (field["name"], f"{field['verbose_name']} ({field['name']})")
            for field in fields
        ]

    def get_detail_view_url(self):
        """
        This method to get detail view url
        """

        return reverse_lazy("reports:report_detail", kwargs={"pk": self.pk})

    def get_field_choices(self, field_name):
        """Get choices for a choice field or related objects for a foreign key."""
        try:
            field = resolve_report_field(self.model_class, field_name)
            if hasattr(field, "choices") and field.choices:
                return [
                    {"value": value, "display": display}
                    for value, display in field.choices
                ]
            if hasattr(field, "related_model") and field.related_model:
                related_objects = field.related_model.objects.all()
                # Honour the field's own limit_choices_to (e.g. Activity's
                # related content type only offers models registered for it).
                if hasattr(field, "get_limit_choices_to"):
                    limit = field.get_limit_choices_to()
                    if limit:
                        related_objects = related_objects.complex_filter(limit)
                return [
                    {"value": obj.pk, "display": str(obj)} for obj in related_objects
                ]
            return []
        except Exception:
            return []

    def is_choice_or_foreign_key_field(self, field_name):
        """Check if a field is a choice field or foreign key."""
        try:
            field = resolve_report_field(self.model_class, field_name)
            return (hasattr(field, "choices") and field.choices) or (
                hasattr(field, "related_model") and field.related_model
            )
        except Exception:
            return False

    def actions(self):
        """
        This method for get custom column for action.
        """

        return render_template(
            path="reports/actions.html",
            context={"instance": self},
        )

    def actions_detail(self):
        """
        This method for get custom column for action.
        """

        return render_template(
            path="reports/actions.html",
            context={"instance": self},
        )
