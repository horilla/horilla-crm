"""
Offer custom fields in the dashboard component pickers.

The dashboard views and form list a model's columns, and expose
``get_extra_choices(model, purpose)`` for fields that aren't columns. The
extensions here supply the model's custom fields. Their values reach the
component through the reports engine's virtual fields (see
``custom_fields_report.py``), so a chosen ``cf_<id>`` groups, aggregates and
lists like any other field.
"""

import logging

from horilla.contrib.field_management.hooks.detail import custom_field_selector_items
from horilla.contrib.field_management.utils.custom_fields import (
    custom_field_form_name,
    get_custom_field_definitions,
    safe_custom_field_label,
)
from horilla.extension.forms import FormExtension
from horilla.extension.view import ViewExtension

logger = logging.getLogger(__name__)

_PURPOSE_TYPES = {
    "grouping": ("single_choice",),
    "numeric": ("number",),
}


def _picker_choices(model, purpose):
    """``(name, label)`` custom fields suited to a dashboard picker."""
    if model is None:
        return []
    try:
        if purpose not in _PURPOSE_TYPES:
            return [(name, label) for label, name in custom_field_selector_items(model)]
        allowed = _PURPOSE_TYPES[purpose]
        return [
            (custom_field_form_name(defn), str(safe_custom_field_label(defn)))
            for defn in get_custom_field_definitions(model)
            if defn.field_type in allowed
        ]
    except Exception:
        logger.exception("custom_fields: could not list dashboard picker fields")
        return []


class CustomFieldDashboardChoicesExtension(ViewExtension):
    """Custom fields in the dashboard component field-picker views."""

    _inherit_view = (
        "horilla.contrib.dashboard.views.field_choices.ExtraFieldChoicesView"
    )

    def get_extra_choices(self, model, purpose):
        """Picker choices for this purpose, including custom fields."""
        return list(super().get_extra_choices(model, purpose)) + _picker_choices(
            model, purpose
        )


class CustomFieldDashboardFormExtension(FormExtension):
    """Custom fields in the dashboard component form's pickers."""

    _inherit_form = "horilla.contrib.dashboard.forms.DashboardCreateForm"

    def get_extra_choices(self, model, purpose):
        """Form picker choices for this purpose, including custom fields."""
        return list(super().get_extra_choices(model, purpose)) + _picker_choices(
            model, purpose
        )
