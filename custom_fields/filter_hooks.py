"""
Shared helpers so custom fields appear in Horilla's Filter Records panel
and actually filter the queryset.

Horilla's filter UI only knows about model columns. The functions here are
consumed by two extension registrations, not applied as monkey-patches
themselves:

- ``add_custom_fields_to_field_dicts`` — used by
  ``CustomFieldFilterFieldsExtension`` in ``custom_fields/mixin_extensions.py``
  (``HorillaListFilterFieldsMixin._get_model_fields`` is a bare view mixin,
  never resolved by any per-request extension mechanism, so it is extended
  through ``MixinExtension``/``_inherit_mixin``).
- ``custom_field_row_q`` — used by ``_FilterMethods._build_row_q`` in
  ``custom_fields/filter_extensions.py`` (registered declaratively through
  ``FilterExtension``/``_inherit_filter``).
"""

import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from custom_fields.models import (
    CustomFieldValue,
    parse_choice_values,
    to_date_value,
    to_datetime_value,
)
from custom_fields.utils import (
    RELATIVE_DATE_OPERATORS,
    custom_field_form_name,
    get_custom_field_definitions,
    get_definition_by_form_name,
    relative_date_bounds,
    safe_custom_field_label,
)
from horilla.contrib.core.models import HorillaContentType
from horilla.db.models import Q

logger = logging.getLogger(__name__)

FILTER_TYPE_MAP = {
    "small_text": "text",
    "large_text": "text",
    "number": "decimal",
    "choice": "choice",
    "single_choice": "choice",
    "date": "date",
    "datetime": "datetime",
}


def custom_field_filter_dicts(model, filterset_class=None):
    """Return Horilla filter-field dicts for the model's custom fields."""
    from horilla.contrib.generics.filters import HorillaFilterSet

    getter = HorillaFilterSet.get_operators_for_field
    if filterset_class is not None:
        getter = getattr(filterset_class, "get_operators_for_field", getter)

    field_dicts = []
    for defn in get_custom_field_definitions(model):
        mapped = FILTER_TYPE_MAP.get(defn.field_type, "text")
        choices = []
        if defn.field_type in ("choice", "single_choice"):
            choices = [{"value": c, "label": c} for c in defn.get_choices_list()]
        field_dicts.append(
            {
                "name": custom_field_form_name(defn),
                "type": mapped,
                "verbose_name": safe_custom_field_label(defn),
                "choices": choices,
                "operators": getter(mapped),
                "model": None,
                "app_label": None,
            }
        )
    return field_dicts


def add_custom_fields_to_field_dicts(fields, model, filterset_class=None):
    """Append custom-field dicts onto a Horilla ``_get_model_fields`` list."""
    existing = {item.get("name") for item in fields}
    for extra in custom_field_filter_dicts(model, filterset_class):
        if extra["name"] not in existing:
            fields.append(extra)
            existing.add(extra["name"])
    return fields


def _to_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _filled_values_qs(base, numeric, choice=False):
    if numeric:
        return base.filter(value_number__isnull=False)
    qs = base.exclude(value_text="").exclude(value_text__isnull=True)
    if choice:
        qs = qs.exclude(value_text="[]")
    return qs


def custom_field_row_q(
    model, field_name, operator, i, values, start_values, end_values
):
    """Build a ``Q(pk__in=...)`` (or its inverse) for one custom-field filter row."""
    defn = get_definition_by_form_name(model, field_name)
    if defn is None:
        return None

    value = values[i] if i < len(values) else None
    start_value = start_values[i] if i < len(start_values) else None
    end_value = end_values[i] if i < len(end_values) else None

    match = matching_object_ids(model, defn, operator, value, start_value, end_value)
    if match is None:
        return None
    include, ids = match
    id_list = list(ids)
    if include:
        return Q(pk__in=id_list)
    return ~Q(pk__in=id_list)


def matching_object_ids(model, defn, operator, value, start_value, end_value):
    """
    Return ``(include, object_ids)`` for a custom-field filter.

    ``include`` True means ``Q(pk__in=ids)``; False means ``~Q(pk__in=ids)``.
    """
    ct = HorillaContentType.objects.get_for_model(model)
    base = CustomFieldValue.objects.filter(content_type=ct, field_definition=defn)
    if defn.field_type in ("date", "datetime"):
        return _matching_date_object_ids(
            base, defn.field_type, operator, value, start_value, end_value
        )
    numeric = defn.field_type == "number"
    choice = defn.field_type == "choice"
    value_key = "value_number" if numeric else "value_text"
    filled = _filled_values_qs(base, numeric, choice=choice)

    if operator == "isnull":
        return (False, filled.values_list("object_id", flat=True))
    if operator == "isnotnull":
        return (True, filled.values_list("object_id", flat=True))

    if choice and operator in ("exact", "ne"):
        if value in (None, ""):
            return None
        wanted = [item for item in str(value).split(",") if item]
        matching_ids = []
        for object_id, stored in base.values_list("object_id", "value_text"):
            selected = parse_choice_values(stored)
            if any(item in selected for item in wanted):
                matching_ids.append(object_id)
        if operator == "exact":
            return (True, matching_ids)
        return (False, matching_ids)

    if operator == "between":
        if not numeric:
            return None
        qs = filled
        start_num = _to_decimal(start_value) if start_value not in (None, "") else None
        end_num = _to_decimal(end_value) if end_value not in (None, "") else None
        if start_num is None and end_num is None:
            return None
        if start_num is not None:
            qs = qs.filter(value_number__gte=start_num)
        if end_num is not None:
            qs = qs.filter(value_number__lte=end_num)
        return (True, qs.values_list("object_id", flat=True))

    if operator == "ne":
        if value in (None, ""):
            return None
        if numeric:
            number = _to_decimal(value)
            if number is None:
                return None
            equal_ids = filled.filter(value_number=number).values_list(
                "object_id", flat=True
            )
        else:
            equal_ids = base.filter(value_text=value).values_list(
                "object_id", flat=True
            )
        return (False, equal_ids)

    if value in (None, ""):
        return None

    if operator == "exact":
        if numeric:
            number = _to_decimal(value)
            if number is None:
                return None
            qs = filled.filter(value_number=number)
        else:
            value_list = [item for item in str(value).split(",") if item]
            if not value_list:
                return None
            if len(value_list) > 1:
                qs = base.filter(value_text__in=value_list)
            else:
                qs = base.filter(value_text__exact=value_list[0])
        return (True, qs.values_list("object_id", flat=True))

    lookup_suffix = {
        "icontains": "icontains",
        "istartswith": "istartswith",
        "iendswith": "iendswith",
        "gt": "gt",
        "lt": "lt",
        "gte": "gte",
        "lte": "lte",
    }.get(operator)
    if not lookup_suffix:
        return None

    filter_value = _to_decimal(value) if numeric else value
    if numeric and filter_value is None:
        return None
    qs = (filled if numeric else base).filter(
        **{f"{value_key}__{lookup_suffix}": filter_value}
    )
    return (True, qs.values_list("object_id", flat=True))


def _matching_date_object_ids(
    base, field_type, operator, value, start_value, end_value
):
    """
    Return ``(include, object_ids)`` for a date or datetime custom-field filter.

    Datetimes are compared by calendar day (in the active timezone) when the
    filter value is a bare date, and to the minute otherwise — the precision
    of a ``datetime-local`` input.
    """
    is_datetime = field_type == "datetime"
    column = "value_datetime" if is_datetime else "value_date"
    filled = base.filter(**{f"{column}__isnull": False})

    if operator == "isnull":
        return (False, filled.values_list("object_id", flat=True))
    if operator == "isnotnull":
        return (True, filled.values_list("object_id", flat=True))

    if operator in RELATIVE_DATE_OPERATORS:
        start, end = relative_date_bounds(operator)
        day_column = f"{column}__date" if is_datetime else column
        qs = filled.filter(**{f"{day_column}__gte": start, f"{day_column}__lte": end})
        return (True, qs.values_list("object_id", flat=True))

    if operator == "between":
        start_q = _date_bound_q(column, is_datetime, start_value, lower=True)
        end_q = _date_bound_q(column, is_datetime, end_value, lower=False)
        if start_q is None and end_q is None:
            return None
        qs = filled
        for bound in (start_q, end_q):
            if bound is not None:
                qs = qs.filter(bound)
        return (True, qs.values_list("object_id", flat=True))

    if operator not in ("exact", "ne", "gt", "lt", "gte", "lte"):
        return None
    exact_q = _date_exact_q(column, is_datetime, value)
    if exact_q is None:
        return None
    if operator in ("exact", "ne"):
        ids = filled.filter(exact_q).values_list("object_id", flat=True)
        return (operator == "exact", ids)
    bound_q = _date_bound_q(
        column,
        is_datetime,
        value,
        lower=operator in ("gt", "gte"),
        inclusive=operator in ("gte", "lte"),
    )
    return (True, filled.filter(bound_q).values_list("object_id", flat=True))


def _is_bare_date(value):
    return to_date_value(value) is not None and len(str(value).strip()) <= 10


def _date_exact_q(column, is_datetime, value):
    """``Q`` matching the day (date / bare-date value) or the minute (datetime)."""
    if value in (None, ""):
        return None
    if not is_datetime or _is_bare_date(value):
        day = to_date_value(value)
        if day is None:
            return None
        return Q(**{f"{column}__date" if is_datetime else column: day})
    moment = to_datetime_value(value)
    if moment is None:
        return None
    start = moment.replace(second=0, microsecond=0)
    return Q(**{f"{column}__gte": start, f"{column}__lt": start + timedelta(minutes=1)})


def _date_bound_q(column, is_datetime, value, lower, inclusive=True):
    """
    ``Q`` for one side of a range. ``lower`` means "on/after ``value``".

    A bare date on a datetime column covers that whole day, so
    ``between 2026-01-01 and 2026-01-31`` includes the evening of the 31st.
    A full datetime covers its whole minute.
    """
    if value in (None, ""):
        return None
    if not is_datetime or _is_bare_date(value):
        day = to_date_value(value)
        if day is None:
            return None
        key = f"{column}__date" if is_datetime else column
        lookup = ("gt", "gte") if lower else ("lt", "lte")
        return Q(**{f"{key}__{lookup[inclusive]}": day})
    moment = to_datetime_value(value)
    if moment is None:
        return None
    minute_start = moment.replace(second=0, microsecond=0)
    minute_end = minute_start + timedelta(minutes=1)
    if lower:
        return Q(**{f"{column}__gte": minute_start if inclusive else minute_end})
    return Q(**{f"{column}__lt": minute_end if inclusive else minute_start})
