"""
Offer choice-type custom fields in the list view quick filters, through
``ListExtension``/``_inherit_list`` on the shared ``HorillaListView`` base
(resolved for every concrete list view, like the custom-field list context
extension).

Quick filters only know model columns, so list views expose three hooks for
other fields (``get_extra_quick_filter_fields`` / ``..._choices`` /
``apply_extra_quick_filter``). Single Choice and Multiple Choice custom fields
are supplied through them, and filtered with the same matcher the Filter
Records panel uses.
"""

import logging

from horilla.contrib.field_management.hooks.filter import matching_object_ids
from horilla.contrib.field_management.utils.custom_fields import (
    custom_field_form_name,
    get_custom_field_definitions,
    is_custom_field_name,
    safe_custom_field_label,
)
from horilla.extension.list import ListExtension

logger = logging.getLogger(__name__)

_CHOICE_TYPES = ("choice", "single_choice")


def _choice_definitions(view):
    """``{cf_<id>: definition}`` for choice custom fields, minus exclusions."""
    exclude = set(getattr(view, "exclude_quick_filter_fields", []))
    try:
        return {
            custom_field_form_name(d): d
            for d in get_custom_field_definitions(view.model)
            if d.field_type in _CHOICE_TYPES
            and custom_field_form_name(d) not in exclude
        }
    except Exception:
        logger.exception("custom_fields: could not load quick filter fields")
        return {}


class CustomFieldQuickFilterExtension(ListExtension):
    """Quick filter support for choice custom fields on every list view."""

    _inherit_list = "horilla.contrib.generics.views.list.HorillaListView"

    def get_extra_quick_filter_fields(self):
        """Choice custom fields offered as quick filters."""
        fields = list(super().get_extra_quick_filter_fields())
        for name, defn in _choice_definitions(self).items():
            fields.append(
                {
                    "name": name,
                    "verbose_name": str(safe_custom_field_label(defn)),
                    "type": "choice",
                }
            )
        return fields

    def get_extra_quick_filter_choices(self, field_name):
        """Choices for a custom quick-filter field."""
        if not is_custom_field_name(field_name):
            return super().get_extra_quick_filter_choices(field_name)
        defn = _choice_definitions(self).get(field_name)
        if defn is None:
            return []
        return [{"value": c, "label": c} for c in defn.get_choices_list()]

    def apply_extra_quick_filter(self, queryset, field_name, value):
        """Restrict the queryset to rows whose custom field has this value."""
        if not is_custom_field_name(field_name):
            return super().apply_extra_quick_filter(queryset, field_name, value)
        defn = _choice_definitions(self).get(field_name)
        value = (value or "").strip()
        if defn is None or value not in defn.get_choices_list():
            return queryset
        try:
            match = matching_object_ids(self.model, defn, "exact", value, None, None)
        except Exception:
            logger.exception("custom_fields: quick filter %s failed", field_name)
            return queryset
        if match is None:
            return queryset
        include, ids = match
        ids = list(ids)
        return queryset.filter(pk__in=ids) if include else queryset.exclude(pk__in=ids)
