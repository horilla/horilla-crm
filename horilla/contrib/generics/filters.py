"""
Filtering utilities for horilla.contrib.generics.

Provides the HorillaFilterSet and operator choices used by generic filtering forms.
"""

# Standard library imports
import logging
from collections import OrderedDict

# Third-party imports (Others)
import django_filters
from django.core.exceptions import FieldDoesNotExist

from horilla.contrib.generics.related_fields import resolve_field_path
from horilla.contrib.generics.search_support import make_name_key

# First party imports (Horilla)
from horilla.db import models
from horilla.db.models import Q
from horilla.utils.translation import gettext_lazy as _

# String-like field types where "empty" means NULL or empty string
STRING_LIKE_FIELDS = (
    models.CharField,
    models.TextField,
    models.EmailField,
    models.URLField,
    models.GenericIPAddressField,
    models.SlugField,
)

# Relative date operators that do not require a value input
RELATIVE_DATE_OPERATORS = (
    "today",
    "yesterday",
    "this_week",
    "this_month",
    "this_year",
    "this_fiscal_period",
    "this_fiscal_quarter",
    "this_fiscal_year",
)


logger = logging.getLogger(__name__)
# Define operator choices by field type
OPERATOR_CHOICES = {
    "text": [
        ("icontains", _("Contains")),
        ("exact", _("Equals")),
        ("ne", _("Not Equals")),
        ("istartswith", _("Starts with")),
        ("iendswith", _("Ends with")),
        ("isnull", _("Is Empty")),
        ("isnotnull", _("Is Not Empty")),
    ],
    "number": [
        ("exact", _("Equals")),
        ("gt", _("Greater than")),
        ("lt", _("Less than")),
        ("gte", _("Greater than or equal")),
        ("lte", _("Less than or equal")),
        ("between", _("Between")),
        ("isnull", _("Is Empty")),
        ("isnotnull", _("Is Not Empty")),
    ],
    "float": [
        ("exact", _("Equals")),
        ("gt", _("Greater than")),
        ("lt", _("Less than")),
        ("gte", _("Greater than or equal")),
        ("lte", _("Less than or equal")),
        ("between", _("Between")),
        ("isnull", _("Is Empty")),
        ("isnotnull", _("Is Not Empty")),
    ],
    "decimal": [
        ("exact", _("Equals")),
        ("gt", _("Greater than")),
        ("lt", _("Less than")),
        ("gte", _("Greater than or equal")),
        ("lte", _("Less than or equal")),
        ("between", _("Between")),
        ("isnull", _("Is Empty")),
        ("isnotnull", _("Is Not Empty")),
    ],
    "date": [
        ("exact", _("Equals")),
        ("gt", _("After")),
        ("lt", _("Before")),
        ("between", _("Between")),
        ("today", _("Today")),
        ("yesterday", _("Yesterday")),
        ("this_week", _("This Week")),
        ("this_month", _("This Month")),
        ("this_year", _("This Year")),
        ("this_fiscal_period", _("This FP")),
        ("this_fiscal_quarter", _("This FQ")),
        ("this_fiscal_year", _("This FY")),
        ("isnull", _("Is Empty")),
        ("isnotnull", _("Is Not Empty")),
    ],
    "datetime": [
        ("exact", _("Equals")),
        ("gt", _("After")),
        ("lt", _("Before")),
        ("between", _("Between")),
        ("today", _("Today")),
        ("yesterday", _("Yesterday")),
        ("this_week", _("This Week")),
        ("this_month", _("This Month")),
        ("this_year", _("This Year")),
        ("this_fiscal_period", _("This FP")),
        ("this_fiscal_quarter", _("This FQ")),
        ("this_fiscal_year", _("This FY")),
        ("isnull", _("Is Empty")),
        ("isnotnull", _("Is Not Empty")),
    ],
    "boolean": [("exact", _("Equals"))],
    "choice": [
        ("exact", _("Equals")),
        ("isnull", _("Is Empty")),
        ("isnotnull", _("Is Not Empty")),
    ],
    "foreignkey": [
        ("exact", _("Equals")),
        ("isnull", _("Is Empty")),
        ("isnotnull", _("Is Not Empty")),
    ],
    "other": [
        ("exact", _("Equals")),
        ("icontains", _("Contains")),
        ("isnull", _("Is Empty")),
        ("isnotnull", _("Is Not Empty")),
    ],
}


def get_operator_label(field_type, operator):
    """Operator name as the filter panel's dropdown shows it for ``field_type``."""
    for key, label in OPERATOR_CHOICES.get(field_type, OPERATOR_CHOICES["other"]):
        if key == operator:
            return label
    # Not offered for this type (e.g. an older saved filter): use any list that has it
    for operator_list in OPERATOR_CHOICES.values():
        for key, label in operator_list:
            if key == operator:
                return label
    return operator


class HorillaFilterSet(django_filters.FilterSet):
    """
    Custom FilterSet for Horilla with enhanced search and filtering capabilities.

    Provides field-type-specific operators and boolean value conversion
    for generic filtering across Horilla models.
    """

    search = django_filters.CharFilter(method="filter_search", label="Search")

    @classmethod
    def get_fields(cls):
        """
        Resolve filterset fields the same way django_filters does, but also
        drop any model field with editable=False (e.g. a system-managed
        bookkeeping field like message_id) - django_filters' own ALL_FIELDS
        resolution does not check this, so "fields = '__all__'" would
        otherwise expose such fields as filters/columns.
        """
        fields = super().get_fields()
        model = cls._meta.model
        editable_fields = OrderedDict()
        for name, lookups in fields.items():
            try:
                model_field = model._meta.get_field(name)
            except FieldDoesNotExist:
                editable_fields[name] = lookups
                continue
            if getattr(model_field, "editable", True):
                editable_fields[name] = lookups
        return editable_fields

    @classmethod
    def get_operators_for_field(cls, field_type):
        """Return appropriate operators for a given field type"""
        return OPERATOR_CHOICES.get(field_type, OPERATOR_CHOICES["other"])

    def _get_relative_date_bounds(self, operator):
        """
        Return (start_date, end_date) inclusive bounds for relative date operators.
        Fiscal operators follow the company's fiscal year configuration.
        """
        from horilla.contrib.core.services.relative_dates import (
            get_relative_date_bounds,
        )

        return get_relative_date_bounds(operator)

    def _apply_relative_date_filter(self, queryset, field, operator):
        """Apply today/yesterday/this_week/this_month filters for date/datetime fields."""
        start_date, end_date = self._get_relative_date_bounds(operator)
        if start_date is None:
            return queryset

        model = queryset.model
        field_obj = resolve_field_path(model, field)

        # DateTimeField is a subclass of DateField — check DateTimeField first
        if field_obj is not None and isinstance(field_obj, models.DateTimeField):
            if start_date == end_date:
                return queryset.filter(**{f"{field}__date": start_date})
            return queryset.filter(
                **{f"{field}__date__gte": start_date, f"{field}__date__lte": end_date}
            )

        if start_date == end_date:
            return queryset.filter(**{field: start_date})
        return queryset.filter(
            **{f"{field}__gte": start_date, f"{field}__lte": end_date}
        )

    def _relative_date_q(self, model, field, operator):
        """Build a Q object for today/yesterday/this_week/this_month filters."""
        start_date, end_date = self._get_relative_date_bounds(operator)
        if start_date is None:
            return None

        field_obj = resolve_field_path(model, field)

        # DateTimeField is a subclass of DateField — check DateTimeField first
        if field_obj is not None and isinstance(field_obj, models.DateTimeField):
            if start_date == end_date:
                return Q(**{f"{field}__date": start_date})
            return Q(
                **{f"{field}__date__gte": start_date, f"{field}__date__lte": end_date}
            )

        if start_date == end_date:
            return Q(**{field: start_date})
        return Q(**{f"{field}__gte": start_date, f"{field}__lte": end_date})

    def _convert_boolean_value(self, value, model, field_name):
        """Convert boolean string values to proper format for filtering"""
        if value is None:
            return None

        # Check if the field is a BooleanField
        field = resolve_field_path(model, field_name)
        if isinstance(field, models.BooleanField):
            # Convert lowercase "true"/"false" to proper boolean or capitalized string
            value_str = str(value).lower()
            return {"true": True, "false": False}.get(value_str)

        return value

    def _build_row_q(self, model, field, operator, i, values, start_values, end_values):
        """Build a Q object for a single filter row, or None if it contributes nothing."""
        if operator == "ne":
            value = values[i] if i < len(values) else None
            if value is None:
                return None
            if self._is_datetime_field(model, field) and self._is_date_only(value):
                return ~Q(**{f"{field}__date": value})
            value = self._convert_boolean_value(value, model, field)
            return ~Q(**{field: value})

        if operator == "between":
            start_value = start_values[i] if i < len(start_values) else None
            end_value = end_values[i] if i < len(end_values) else None
            lookup = "__date" if self._is_datetime_field(model, field) else ""
            if start_value and end_value:
                return Q(
                    **{
                        f"{field}{lookup}__gte": start_value,
                        f"{field}{lookup}__lte": end_value,
                    }
                )
            if start_value:
                return Q(**{f"{field}{lookup}__gte": start_value})
            if end_value:
                return Q(**{f"{field}{lookup}__lte": end_value})
            return None

        if operator == "isnull":
            field_obj = resolve_field_path(model, field)
            if isinstance(field_obj, STRING_LIKE_FIELDS):
                return Q(**{f"{field}__isnull": True}) | Q(**{f"{field}__exact": ""})
            return Q(**{f"{field}__isnull": True})

        if operator == "isnotnull":
            field_obj = resolve_field_path(model, field)
            if isinstance(field_obj, STRING_LIKE_FIELDS):
                return ~Q(**{f"{field}__isnull": True}) & ~Q(**{f"{field}__exact": ""})
            return Q(**{f"{field}__isnull": False})

        if operator in RELATIVE_DATE_OPERATORS:
            return self._relative_date_q(model, field, operator)

        value = values[i] if i < len(values) else None
        if value is None:
            return None

        if operator == "exact":
            field_obj = resolve_field_path(model, field)
            is_choice_or_fk = field_obj is not None and (
                bool(field_obj.choices) or field_obj.__class__.__name__ == "ForeignKey"
            )
            if is_choice_or_fk:
                value_list = [v for v in value.split(",") if v]
                if not value_list:
                    return None
                if len(value_list) > 1:
                    return Q(**{f"{field}__in": value_list})
                return Q(**{f"{field}__exact": value_list[0]})

        if self._is_datetime_field(model, field) and self._is_date_only(value):
            # Filtering a datetime field by a plain date: compare the calendar
            # day (in the active/user timezone), not an instant at midnight.
            return Q(**{f"{field}__date__{operator}": value})

        value = self._convert_boolean_value(value, model, field)
        return Q(**{f"{field}__{operator}": value})

    @staticmethod
    def _is_date_only(value):
        """True for a bare ``YYYY-MM-DD`` value with no time part."""
        return "T" not in str(value) and " " not in str(value).strip()

    @staticmethod
    def _is_datetime_field(model, field):
        """True when ``field`` resolves to a DateTimeField on ``model``."""
        return isinstance(resolve_field_path(model, field), models.DateTimeField)

    def filter_queryset(self, queryset):
        """
        Override the default filter_queryset to handle our custom filtering approach.
        Process arrays of fields, operators, and values.
        """
        if hasattr(self, "form") and hasattr(self.form, "cleaned_data"):
            queryset = super().filter_queryset(queryset)

        request = getattr(self, "request", None)
        if not request and hasattr(self, "data") and hasattr(self.data, "_request"):
            request = self.data._request

        if not request:
            return queryset

        fields = self.data.getlist("field", []) or request.GET.getlist("field", [])
        operators = self.data.getlist("operator", []) or request.GET.getlist(
            "operator", []
        )
        values = self.data.getlist("value", []) or request.GET.getlist("value", [])
        start_values = self.data.getlist("start_value", []) or request.GET.getlist(
            "start_value", []
        )
        end_values = self.data.getlist("end_value", []) or request.GET.getlist(
            "end_value", []
        )
        logics = self.data.getlist("logic", []) or request.GET.getlist("logic", [])

        # Build complete set of valid operator keys from OPERATOR_CHOICES.
        valid_operators = {
            op_key
            for op_list in OPERATOR_CHOICES.values()
            for op_key, _label in op_list
        }
        valid_logics = {"AND", "OR"}

        # Retrieve Meta.exclude for this FilterSet, defaulting to empty list.
        excluded_fields = list(
            getattr(getattr(self, "Meta", None), "exclude", []) or []
        )

        model = queryset.model
        combined_q = None

        for i, (field, operator) in enumerate(zip(fields, operators)):
            if not field or not operator:
                continue

            # Reject disallowed operators
            if operator not in valid_operators:
                logger.warning(
                    "filter_queryset: rejected invalid operator %r for field %r",
                    operator,
                    field,
                )
                continue

            # Reject excluded fields (including ORM traversals like password__icontains)
            top_level_field = field.split("__")[0]
            if top_level_field in excluded_fields:
                logger.warning(
                    "filter_queryset: rejected excluded field %r (top-level: %r) on %s",
                    field,
                    top_level_field,
                    model.__name__,
                )
                continue

            try:
                row_q = self._build_row_q(
                    model, field, operator, i, values, start_values, end_values
                )
            except Exception as e:
                logger.error("Filter error for %s %s: %s", field, operator, e)
                continue

            if row_q is None:
                continue

            logic = logics[i] if i < len(logics) else "AND"
            if logic not in valid_logics:
                logic = "AND"

            if combined_q is None:
                # Anchor row: nothing to combine with yet, its own logic is irrelevant.
                combined_q = row_q
            elif logic == "OR":
                combined_q = combined_q | row_q
            else:
                combined_q = combined_q & row_q

        if combined_q is not None:
            queryset = queryset.filter(combined_q)

        search_query = self.data.get("search", "") or request.GET.get("search", "")
        if search_query:
            queryset = self.filter_search(queryset, "search", search_query)

        queryset = self.apply_search_facets(queryset, request)

        return queryset

    @classmethod
    def get_search_field_labels(cls):
        """
        Return ``{lookup: label}`` for ``Meta.search_fields``, in order.

        Labels are the fields' verbose names. Entries that are not fields of the
        model are left out. When the two name fields are both searched (see
        ``get_name_search_key``) they are offered as one "Name" choice. The search box
        of a list uses these as its field choices.
        """
        from horilla.contrib.generics.search_support import (
            build_field_labels,
            combined_name_label,
        )

        search_fields = list(getattr(cls.Meta, "search_fields", []) or [])
        model = getattr(cls.Meta, "model", None)
        if not search_fields or model is None:
            return {}
        labels = build_field_labels(model, search_fields)
        name_key = cls.get_name_search_key()
        split = cls.get_name_split_fields() or []
        choices = {}
        for name in search_fields:
            if name not in labels:
                continue
            if name_key and name in split:
                choices.setdefault(name_key, combined_name_label(model, split))
            else:
                choices[name] = labels[name]
        return choices

    @classmethod
    def get_name_split_fields(cls):
        """
        The two fields a full-name search ("John Mathew") is split across, or ``None``.

        Taken from ``Meta.name_split_fields``, or ``first_name`` and ``last_name``
        when ``Meta.search_fields`` has both.
        """
        meta = cls.Meta
        split = getattr(meta, "name_split_fields", None)
        if not split:
            fields = getattr(meta, "search_fields", []) or []
            if "first_name" in fields and "last_name" in fields:
                split = ["first_name", "last_name"]
        return list(split) if split and len(split) == 2 else None

    @classmethod
    def get_name_search_key(cls):
        """
        The search choice that stands for both name fields, e.g. ``first_name+last_name``.

        ``None`` unless both name fields are in ``Meta.search_fields``.
        """
        split = cls.get_name_split_fields()
        fields = getattr(cls.Meta, "search_fields", []) or []
        if split and all(name in fields for name in split):
            return make_name_key(split)
        return None

    def name_search_q(self, value):
        """``Q`` for a name search: "John Mathew" matches first and last, "John" either."""
        first, second = self.get_name_split_fields()
        text = value.strip()
        if " " in text:
            first_part, second_part = text.split(None, 1)
            return Q(
                **{
                    f"{first}__icontains": first_part,
                    f"{second}__icontains": second_part,
                }
            )
        return Q(**{f"{first}__icontains": text}) | Q(**{f"{second}__icontains": text})

    def build_field_q(self, lookup, value):
        """``Q`` that searches one choice of ``get_search_field_labels`` for ``value``."""
        if lookup == self.get_name_search_key():
            return self.name_search_q(value)
        return Q(**{f"{lookup}__icontains": value})

    def apply_search_facets(self, queryset, request):
        """
        Apply the search chips (``sf=<field>:<text>``, repeated) of the search box.

        ``field`` is ``all``, one of ``Meta.search_fields`` or the combined name choice
        (``get_name_search_key``). Chips on the same field are OR'd; chips on different
        fields are AND'd, so ``Email: gmail`` plus ``Title: acme`` narrows the list.
        Unknown fields are ignored.
        """
        raw = self.data.getlist("sf", []) or request.GET.getlist("sf", [])
        if not raw:
            return queryset

        allowed = set(getattr(self.Meta, "search_fields", []) or [])
        name_key = self.get_name_search_key()
        if name_key:
            allowed.add(name_key)
        groups = {}
        for item in raw:
            field, _sep, text = item.partition(":")
            text = text.strip()
            if not text or (field != "all" and field not in allowed):
                continue
            groups.setdefault(field, []).append(text)

        for field, texts in groups.items():
            group_q = Q()
            for text in texts:
                if field == "all":
                    group_q |= self.build_search_q(text)
                else:
                    group_q |= self.build_field_q(field, text)
            queryset = queryset.filter(group_q)
        return queryset

    def filter_search(self, queryset, name, value):
        """Handle search across specified fields with smart full name matching"""
        if not value or not getattr(self.Meta, "search_fields", []):
            return queryset
        return queryset.filter(self.build_search_q(value))

    def build_search_q(self, value):
        """Build the ``Q`` that searches every ``Meta.search_fields`` entry for ``value``."""
        search_fields = getattr(self.Meta, "search_fields", [])
        if not value or not search_fields:
            return Q()

        name_split_fields = self.get_name_split_fields()

        stripped = value.strip()
        is_split_search = name_split_fields and " " in stripped

        queries = Q()

        if is_split_search:
            parts = stripped.split(None, 1)
            first_part, second_part = parts

            # Only search non-name fields with the full string
            for field in search_fields:
                if field not in name_split_fields:
                    queries |= Q(**{f"{field}__icontains": stripped})

            # Split name search with AND logic
            queries |= Q(
                **{
                    f"{name_split_fields[0]}__icontains": first_part,
                    f"{name_split_fields[1]}__icontains": second_part,
                }
            )
        else:
            # No space — normal search across all fields
            for field in search_fields:
                queries |= Q(**{f"{field}__icontains": value})

        return queries
