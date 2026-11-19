"""
Contribute custom fields to condition builders and rule engines (e.g. Lead
assignment rules) through ``ConditionFieldProvider``, the generic
condition-field extension seam, instead of generics/core or a
consumer app (e.g. leads) importing custom_fields by name.

See horilla/horilla-crm#45.
"""

# Standard library imports
import logging
from datetime import date, datetime

from django.db.models import Q

# First party imports (Horilla)
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.field_management.models import (
    CustomFieldDefinition,
    CustomFieldValue,
    to_date_value,
    to_datetime_value,
)
from horilla.contrib.field_management.utils.custom_fields import (
    DATE_FIELD_TYPES,
    RELATIVE_DATE_OPERATORS,
    get_custom_field_definitions,
    is_custom_field_name,
    parse_custom_field_pk,
    relative_date_bounds,
    safe_custom_field_label,
)
from horilla.extension.view import ViewExtension
from horilla.utils import timezone

logger = logging.getLogger(__name__)


# Maps custom_fields' own CustomFieldDefinition.FIELD_TYPES to the small,
# custom_fields-agnostic vocabulary condition_widget.py renders widgets from,
# and to a key into horilla.contrib.generics.filters.OPERATOR_CHOICES.
_WIDGET_BY_FIELD_TYPE = {
    "small_text": "text",
    "large_text": "textarea",
    "number": "number",
    "single_choice": "select",
    "choice": "multiselect",
    "date": "date",
    "datetime": "datetime",
}
_OPERATOR_TYPE_BY_FIELD_TYPE = {
    "small_text": "text",
    "large_text": "other",
    "number": "number",
    "single_choice": "choice",
    "choice": "choice",
    "date": "date",
    "datetime": "datetime",
}


class CustomFieldConditionExtension:
    """Exposes user-defined 'cf_<id>' custom fields as condition-builder fields."""

    def owns(self, field_name):
        """Return True when ``field_name`` is a ``cf_*`` custom-field key."""
        return is_custom_field_name(field_name)

    def _get_definition(self, field_name):
        """Load the ``CustomFieldDefinition`` for a ``cf_<id>`` field name."""
        pk = parse_custom_field_pk(field_name)
        if pk is None:
            return None
        return CustomFieldDefinition.objects.filter(pk=pk).first()

    def get_choices(self, model):
        """Return ``(cf_<id>, label)`` pairs for the model's custom fields."""
        return [
            (f"cf_{definition.pk}", safe_custom_field_label(definition))
            for definition in get_custom_field_definitions(model)
        ]

    def get_label(self, field_name):
        """Return the display label for a ``cf_*`` field, or None if missing."""
        definition = self._get_definition(field_name)
        return safe_custom_field_label(definition) if definition else None

    def get_widget_info(self, field_name):
        """Return widget/operator metadata for the condition-value HTMX UI."""
        definition = self._get_definition(field_name)
        if not definition:
            return None
        info = {
            "widget": _WIDGET_BY_FIELD_TYPE.get(definition.field_type, "text"),
            "operator_type": _OPERATOR_TYPE_BY_FIELD_TYPE.get(
                definition.field_type, "text"
            ),
        }
        if definition.field_type in ("single_choice", "choice"):
            info["choices"] = [(c, c) for c in definition.get_choices_list()]
        return info

    def get_value(self, field_name, instance):
        """
        Return the stored custom-field value for rule-engine evaluation.

        Dates come back as ISO ``YYYY-MM-DD`` and datetimes as aware ISO
        strings (with UTC offset), so rule engines can parse and compare
        them rather than matching display text.
        """
        definition = self._get_definition(field_name)
        if not definition:
            logger.warning(
                "Condition field extension: custom field '%s' no longer exists",
                field_name,
            )
            return None
        content_type = HorillaContentType.objects.get_for_model(instance)
        cfv = CustomFieldValue.objects.filter(
            field_definition=definition,
            content_type=content_type,
            object_id=instance.pk,
        ).first()
        if not cfv:
            return ""
        value = cfv.get_value()
        if isinstance(value, list):
            return ",".join(str(item) for item in value)
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return "" if value is None else str(value)

    # Condition operator names used by the rule engines, as filter operators.
    _FILTER_OPERATORS = {
        "equals": "exact",
        "exact": "exact",
        "not_equals": "ne",
        "ne": "ne",
        "contains": "icontains",
        "icontains": "icontains",
        "starts_with": "istartswith",
        "istartswith": "istartswith",
        "ends_with": "iendswith",
        "iendswith": "iendswith",
        "greater_than": "gt",
        "gt": "gt",
        "greater_than_equal": "gte",
        "greater_equal": "gte",
        "gte": "gte",
        "less_than": "lt",
        "lt": "lt",
        "less_than_equal": "lte",
        "less_equal": "lte",
        "lte": "lte",
        "is_empty": "isnull",
        "is_null": "isnull",
        "empty": "isnull",
        "isnull": "isnull",
        "is_not_empty": "isnotnull",
        "is_not_null": "isnotnull",
        "not_empty": "isnotnull",
        "isnotnull": "isnotnull",
        "between": "between",
    }

    def build_condition_q(self, model, field_name, operator, value):
        """
        Return a ``Q`` selecting the records whose custom field matches.

        Used by the queryset-based condition engines (calendar, dashboard,
        forecast). Returns None for operators it can't express.
        """
        from horilla.contrib.field_management.hooks.filter import matching_object_ids

        definition = self._get_definition(field_name)
        if definition is None:
            return None
        text = "" if value is None else str(value)
        if operator == "not_contains":
            match = matching_object_ids(
                model, definition, "icontains", text, None, None
            )
            if match is None:
                return None
            include, ids = match
            return ~Q(pk__in=list(ids)) if include else Q(pk__in=list(ids))
        filter_operator = self._FILTER_OPERATORS.get(operator)
        if filter_operator is None:
            return None
        start = end = None
        if filter_operator == "between":
            bounds = [part.strip() for part in text.split(",")]
            if len(bounds) != 2:
                return None
            start, end = bounds
        match = matching_object_ids(
            model, definition, filter_operator, text, start, end
        )
        if match is None:
            return None
        include, ids = match
        ids = list(ids)
        return Q(pk__in=ids) if include else ~Q(pk__in=ids)


_CUSTOM_FIELD_CONDITIONS = CustomFieldConditionExtension()


class CustomFieldConditionProviderExtension(ViewExtension):
    """
    Supply custom fields to the condition builders and rule engines through
    ``ConditionFieldProvider``, Horilla's extension seam for condition fields
    that aren't model columns.
    """

    _inherit_view = (
        "horilla.contrib.generics.forms.condition_fields.ConditionFieldProvider"
    )

    def owns(self, field_name):
        """Whether this name is a custom field this provider handles."""
        return _CUSTOM_FIELD_CONDITIONS.owns(field_name) or super().owns(field_name)

    def get_choices(self, model):
        """Condition-field choices, including this model's custom fields."""
        return list(super().get_choices(model)) + _CUSTOM_FIELD_CONDITIONS.get_choices(
            model
        )

    def get_label(self, field_name):
        """Label for a custom field, or the parent provider's label."""
        if _CUSTOM_FIELD_CONDITIONS.owns(field_name):
            return _CUSTOM_FIELD_CONDITIONS.get_label(field_name)
        return super().get_label(field_name)

    def get_value(self, field_name, instance):
        """Stored value of a custom field on this instance."""
        if _CUSTOM_FIELD_CONDITIONS.owns(field_name):
            return _CUSTOM_FIELD_CONDITIONS.get_value(field_name, instance)
        return super().get_value(field_name, instance)

    def get_widget_info(self, field_name):
        """Widget description for a custom condition field."""
        if _CUSTOM_FIELD_CONDITIONS.owns(field_name):
            return _CUSTOM_FIELD_CONDITIONS.get_widget_info(field_name)
        return super().get_widget_info(field_name)

    def build_condition_q(self, model, field_name, operator, value):
        """Query for a custom-field condition, or the parent provider's query."""
        if _CUSTOM_FIELD_CONDITIONS.owns(field_name):
            return _CUSTOM_FIELD_CONDITIONS.build_condition_q(
                model, field_name, operator, value
            )
        return super().build_condition_q(model, field_name, operator, value)

    def evaluate_condition(self, field_name, instance, operator, value):
        """Whether this instance meets a custom-field condition."""
        if _date_field_definition(field_name) is not None:
            return evaluate_date_criterion(field_name, operator, value, instance)
        return super().evaluate_condition(field_name, instance, operator, value)


def _date_field_definition(field_name):
    """Return the Date / Date and Time definition for ``cf_<id>``, else None."""
    if not is_custom_field_name(field_name):
        return None
    pk = parse_custom_field_pk(field_name)
    if pk is None:
        return None
    return CustomFieldDefinition.objects.filter(
        pk=pk, field_type__in=DATE_FIELD_TYPES
    ).first()


def render_date_condition_value_widget(
    view, field_name, row_id, existing_value="", existing_operator=""
):
    """
    Render date pickers for a custom date condition row, or None to defer.

    Uses the condition-widget view's own ``_render_date*`` helpers, so the
    inputs are identical to a model date field's (and get the Jalali picker
    the same way). Operators with no value (empty, today, …) are left to
    Horilla, which renders no input for them.
    """
    if existing_operator in ("isnull", "isnotnull", *RELATIVE_DATE_OPERATORS):
        return None
    definition = _date_field_definition(field_name)
    if definition is None:
        return None
    is_date = definition.field_type == "date"
    if existing_operator == "between":
        parts = [p.strip() for p in (existing_value or "").split(",", 1)]
        start = parts[0] if parts else ""
        end = parts[1] if len(parts) > 1 else ""
        if is_date:
            return view._render_date_between_input(row_id, start, end)
        return view._render_datetime_between_input(row_id, start, end)
    if is_date:
        return view._render_date_input(row_id, existing_value)
    return view._render_datetime_input(row_id, existing_value)


def _to_criterion_target(field_type, raw):
    """
    Parse a condition value: a ``date``, or for datetime fields an aware
    ``datetime`` truncated to the minute — or a ``date`` when ``raw`` is a
    bare ``YYYY-MM-DD`` (compared by calendar day). None when invalid.
    """
    text = str(raw or "").strip()
    if not text:
        return None
    if field_type == "date" or len(text) <= 10:
        return to_date_value(text)
    moment = to_datetime_value(text)
    return moment.replace(second=0, microsecond=0) if moment else None


def evaluate_date_criterion(field_name, operator, value, instance):
    """
    Evaluate a rule criterion on a custom Date / Date and Time field by value.

    Returns None when ``field_name`` is not such a field, so the caller falls
    back to the rule engine's own (text/number) comparison. Supports the
    date operators the condition builder offers — equals, after, before,
    between, today/yesterday/this week/this month, empty/not empty — plus
    ``ne``/``gte``/``lte``. Datetimes compare to the minute, or by local day
    against a bare date. Stored values are Gregorian, as are the values the
    (Jalali or Gregorian) pickers submit.
    """
    definition = _date_field_definition(field_name)
    if definition is None:
        return None
    content_type = HorillaContentType.objects.get_for_model(instance)
    cfv = CustomFieldValue.objects.filter(
        field_definition=definition,
        content_type=content_type,
        object_id=instance.pk,
    ).first()
    actual = cfv.get_value() if cfv else None

    if operator == "isnull":
        return actual is None
    if operator == "isnotnull":
        return actual is not None
    if actual is None:
        return False
    if definition.field_type == "datetime":
        actual = timezone.localtime(actual).replace(second=0, microsecond=0)
        actual_day = actual.date()
    else:
        actual_day = actual

    if operator in RELATIVE_DATE_OPERATORS:
        start, end = relative_date_bounds(operator)
        return start <= actual_day <= end

    def matches(op, raw_target):
        target = _to_criterion_target(definition.field_type, raw_target)
        if target is None:
            return False
        left = actual if isinstance(target, datetime) else actual_day
        return {
            "exact": left == target,
            "ne": left != target,
            "gt": left > target,
            "gte": left >= target,
            "lt": left < target,
            "lte": left <= target,
        }[op]

    value = value or ""
    if operator == "between":
        parts = [p.strip() for p in value.split(",", 1)]
        start = parts[0] if parts else ""
        end = parts[1] if len(parts) > 1 else ""
        if not start and not end:
            return False
        return (not start or matches("gte", start)) and (not end or matches("lte", end))
    if operator in ("exact", "ne", "gt", "gte", "lt", "lte"):
        return matches(operator, value)
    return False
