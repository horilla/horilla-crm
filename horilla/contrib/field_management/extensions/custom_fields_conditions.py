"""
Offer custom fields in condition field dropdowns, through view / form
extensions.

The condition builders list a model's columns. The view below builds its own
list and exposes ``get_extra_field_choices`` for fields that aren't columns.
The extension here adds the model's custom fields. The automation form and view
use the generic builder, which already includes custom fields.
"""

import logging

from horilla.contrib.field_management.hooks.detail import custom_field_selector_items
from horilla.extension.view import ViewExtension

logger = logging.getLogger(__name__)


def _custom_field_choices(model):
    """``(value, label)`` pairs for the model's custom fields."""
    try:
        return [(name, label) for label, name in custom_field_selector_items(model)]
    except Exception:
        logger.exception("custom_fields: could not list condition fields")
        return []


class CustomFieldModelFieldChoicesExtension(ViewExtension):
    """Custom fields in the generic condition field dropdown."""

    _inherit_view = "horilla.contrib.generics.views.helpers.condition_widget.GetModelFieldChoicesView"

    def get_extra_field_choices(self, model):
        return list(super().get_extra_field_choices(model)) + _custom_field_choices(
            model
        )
