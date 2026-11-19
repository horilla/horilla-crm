"""
Offer custom fields to the reports engine as virtual fields.

The reports engine resolves computed "virtual fields" (values added with
``queryset.annotate()``) for column pickers, filters, groupings, previews,
exports and dashboard components. ``ReportFieldProvider`` is its extension
seam for fields that come from the current request rather than a static
registration. This ``ViewExtension`` supplies every custom field the current
user can see for the model, as a ``cf_<id>`` virtual field whose annotation
reads the value from ``CustomFieldValue``. Because it is resolved per request,
new, renamed and deleted fields, company scoping and field permissions apply
immediately in every worker process.
"""

import logging

from django.db.models import OuterRef, Subquery, TextField, Value
from django.db.models.functions import Replace

from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.field_management.models import CustomFieldValue
from horilla.contrib.field_management.utils.custom_fields import (
    custom_field_form_name,
    get_custom_field_definitions,
    safe_custom_field_label,
)
from horilla.contrib.reports.utils import VirtualField
from horilla.contrib.utils.middlewares import get_current_request
from horilla.extension.view import ViewExtension

logger = logging.getLogger(__name__)

_CACHE_ATTR = "_report_custom_virtual_fields"


def _annotation(definition, content_type):
    """The annotation exposing one custom field's value to reports."""
    column = {
        "number": "value_number",
        "date": "value_date",
        "datetime": "value_datetime",
    }.get(definition.field_type, "value_text")
    stored = Subquery(
        CustomFieldValue.all_objects.filter(
            content_type=content_type,
            field_definition=definition,
            object_id=OuterRef("pk"),
        ).values(column)[:1]
    )
    if column != "value_text":
        return stored
    # Choices are stored as a JSON list ('["a", "b"]'); show them as "a, b".
    kind = TextField()
    text = Replace(stored, Value('","'), Value(", "), output_field=kind)
    text = Replace(text, Value('["'), Value(""), output_field=kind)
    return Replace(text, Value('"]'), Value(""), output_field=kind)


def _build_virtual_fields(model_class):
    content_type = HorillaContentType.objects.get_for_model(model_class)
    fields = {}
    for definition in get_custom_field_definitions(model_class):
        name = custom_field_form_name(definition)
        options = (
            [(option, option) for option in definition.get_choices_list()]
            if definition.field_type == "single_choice"
            else None
        )
        fields[name] = VirtualField(
            name,
            safe_custom_field_label(definition),
            _annotation(definition, content_type),
            choices=options,
            show_in_detail=True,
        )
    return fields


class CustomFieldReportFieldProviderExtension(ViewExtension):
    """Custom fields as report virtual fields."""

    _inherit_view = "horilla.contrib.reports.utils.ReportFieldProvider"

    def get_virtual_fields(self, model_class):
        """Report virtual fields, including this model's custom fields."""
        fields = dict(super().get_virtual_fields(model_class))
        try:
            request = get_current_request()
            cache = getattr(request, _CACHE_ATTR, None) if request else None
            key = model_class._meta.label_lower
            if cache is not None and key in cache:
                fields.update(cache[key])
                return fields
            custom = _build_virtual_fields(model_class)
            if request is not None:
                if cache is None:
                    cache = {}
                    setattr(request, _CACHE_ATTR, cache)
                cache[key] = custom
            fields.update(custom)
        except Exception:
            logger.exception("custom_fields: could not provide report fields")
        return fields
