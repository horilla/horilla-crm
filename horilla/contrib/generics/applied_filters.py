"""
Applied filters for the navbar's rotating filter slot.

The navbar is rendered by its own view, separate from the list, so it rebuilds a
short summary of the applied filters from the query string. Operator names come
from OPERATOR_CHOICES (through get_operator_label), the same list the filter
panel uses, so the navbar and the panel's chips always say the same thing.
"""

# Standard library imports
import logging
import zlib

# Third-party imports (Django)
from django.utils.dateparse import parse_time

# First party imports (Horilla)
from horilla.apps import apps
from horilla.utils.choices import FIELD_TYPE_MAP
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .filters import get_operator_label
from .related_fields import RELATED_FIELD_SEPARATOR, resolve_field_path
from .search_support import combined_name_label, resolve_lookup_label, split_name_key

logger = logging.getLogger(__name__)

# Dot colours for the filter list, picked from the field name so a field keeps
# its colour from one page load to the next.
FILTER_COLORS = (
    "#E54F38",
    "#8B5CF6",
    "#22C55E",
    "#EC4899",
    "#3B82F6",
    "#14B8A6",
    "#F59E0B",
)

# Colour for the search row, which has no field of its own
SEARCH_COLOR = "#6B7280"

_FOREIGN_KEY_TYPES = ("ForeignKey", "OneToOneField")
_BOOLEAN_TYPES = ("BooleanField", "NullBooleanField")
_DATE_TYPES = ("DateField", "DateTimeField")


def resolve_model(app_label, model_name):
    """Return the model class for ``app_label.model_name``, or ``None``."""
    if not (app_label and model_name):
        return None
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None


def _field_label(model, field, name):
    """Label shown for a filter field, matching the filter panel's field list."""
    if field is None:
        return name.replace(RELATED_FIELD_SEPARATOR, " - ").replace("_", " ")
    if RELATED_FIELD_SEPARATOR in name:
        relation = resolve_field_path(model, name.split(RELATED_FIELD_SEPARATOR)[0])
        if relation is not None:
            return f"{relation.verbose_name} - {field.verbose_name}"
    return str(field.verbose_name)


def _field_type(field):
    """Filter type key (as used by OPERATOR_CHOICES) for a model field."""
    if field is None:
        return "other"
    if field.choices:
        return "choice"
    field_class_name = field.__class__.__name__
    if field_class_name == "ForeignKey":
        return "foreignkey"
    return FIELD_TYPE_MAP.get(field_class_name, "other")


def _display_values(field, raw_value):
    """Readable text for each stored filter value (ids, choice keys, booleans)."""
    if not raw_value:
        return []
    if field is None:
        return [raw_value]
    values = [value for value in raw_value.split(",") if value]
    try:
        if field.choices:
            labels = {str(key): label for key, label in field.flatchoices}
            return [str(labels.get(value, value)) for value in values]
        field_type = field.__class__.__name__
        if field_type in _FOREIGN_KEY_TYPES:
            related = {
                str(obj.pk): str(obj)
                for obj in field.related_model.objects.filter(pk__in=values)
            }
            return [related.get(value, value) for value in values]
        if field_type in _BOOLEAN_TYPES:
            yes_no = {"True": str(_("Yes")), "False": str(_("No"))}
            return [yes_no.get(value, value) for value in values]
    except Exception:  # pylint: disable=broad-exception-caught
        logger.debug("Could not resolve filter value %r", raw_value, exc_info=True)
    return [raw_value]


def _parse_date_or_time(field, raw_value, user):
    """Parse date/time values so the template can format them for the user."""
    if not raw_value or field is None:
        return None
    field_type = field.__class__.__name__
    try:
        if field_type in _DATE_TYPES:
            from horilla.extension.formatting.resolve import get_datetime_formatter

            return get_datetime_formatter().parse_date(raw_value, user=user)
        if field_type == "TimeField":
            return parse_time(raw_value)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.debug("Could not parse filter value %r", raw_value, exc_info=True)
    return None


def _value_at(values, index):
    return values[index] if index < len(values) else None


def build_applied_filter_rows(request, model):
    """
    Return one dict per applied filter, in the order they were applied.

    ``row_id`` is the position in the query string, which is what the existing
    ``remove_filter`` request expects. Searches come last as ``is_search`` rows:
    the plain search (``row_id`` ``"search"``) and each field search from the list's
    search box (``sf=<field>:<text>``, ``row_id`` ``"sf:<position>"``). That request
    accepts both.
    """
    get = request.GET
    fields = get.getlist("field")
    operators = get.getlist("operator")
    values = get.getlist("value")
    start_values = get.getlist("start_value")
    end_values = get.getlist("end_value")
    logics = get.getlist("logic")
    user = getattr(request, "user", None)

    rows = []
    for index, name in enumerate(fields):
        operator = _value_at(operators, index)
        if not name or not operator:
            continue
        field = resolve_field_path(model, name) if model is not None else None
        raw_value = _value_at(values, index)
        start_value = _value_at(start_values, index)
        end_value = _value_at(end_values, index)
        logic = _value_at(logics, index)
        value_list = _display_values(field, raw_value)
        rows.append(
            {
                "row_id": index,
                "color": FILTER_COLORS[zlib.crc32(name.encode()) % len(FILTER_COLORS)],
                "label": _field_label(model, field, name),
                "operator_display": get_operator_label(_field_type(field), operator),
                "value": ", ".join(value_list),
                "value_list": value_list,
                "value_obj": _parse_date_or_time(field, raw_value, user),
                "start_value": start_value,
                "end_value": end_value,
                "start_obj": _parse_date_or_time(field, start_value, user),
                "end_obj": _parse_date_or_time(field, end_value, user),
                "logic": logic if logic in ("AND", "OR") else "AND",
            }
        )

    search = (get.get("search") or "").strip()
    if search:
        rows.append(
            {
                "row_id": "search",
                "is_search": True,
                "color": SEARCH_COLOR,
                "label": str(_("Search")),
                "operator_display": str(_("Contains")),
                "value": search,
                "value_list": [search],
                "value_obj": None,
                "start_value": None,
                "end_value": None,
                "start_obj": None,
                "end_obj": None,
                "logic": "AND",
            }
        )

    # Field searches from the list's search box
    for index, item in enumerate(get.getlist("sf")):
        field_name, _sep, text = item.partition(":")
        text = text.strip()
        if not text:
            continue
        if field_name == "all":
            label = str(_("Search"))
        elif split_name_key(field_name):
            # The combined name choice, e.g. first_name+last_name
            label = combined_name_label(model, split_name_key(field_name))
        else:
            label = (
                resolve_lookup_label(model, field_name) if model is not None else None
            )
            if label is None:
                continue
        rows.append(
            {
                "row_id": f"sf:{index}",
                "is_search": True,
                "color": SEARCH_COLOR,
                "label": label,
                "operator_display": str(_("Contains")),
                "value": text,
                "value_list": [text],
                "value_obj": None,
                "start_value": None,
                "end_value": None,
                "start_obj": None,
                "end_obj": None,
                "logic": "AND",
            }
        )
    return rows


def has_filter_rows(rows):
    """True when at least one row is a real filter (not only a search)."""
    return any(not row.get("is_search") for row in rows)
