"""Template tags and filters for report rendering and aggregation helpers used in report templates."""

# Standard library imports
from decimal import Decimal
from urllib.parse import urlencode

# Third-party imports (Django)
from django import template
from django.template.defaultfilters import floatformat
from django.urls import reverse
from django.utils.safestring import mark_safe

from horilla.contrib.core.models import MultipleCurrency
from horilla.contrib.reports.utils import (
    NO_VALUE_OPERATORS,
    get_report_filter_field_type,
    get_report_filter_operators,
    resolve_report_field,
)
from horilla.db.models import (
    BigIntegerField,
    DecimalField,
    FloatField,
    IntegerField,
    PositiveIntegerField,
    PositiveSmallIntegerField,
    SmallIntegerField,
)

# First party imports (Horilla)
from horilla.utils.html import escape

register = template.Library()


@register.simple_tag
def pivot_sort_header(
    report, label, sort_field, current_sort_field, current_sort_direction
):
    """Render a clickable pivot column header that sorts the pivot table by
    this column (row label or any Count/aggregate column) via a full
    report-detail reload. Toggles asc/desc when clicking the active column.
    """
    if current_sort_field == sort_field:
        next_direction = "desc" if current_sort_direction == "asc" else "asc"
        arrow = " &#9650;" if current_sort_direction == "asc" else " &#9660;"
    else:
        next_direction = "asc"
        arrow = ""

    base_url = reverse("reports:report_detail", kwargs={"pk": report.pk})
    query = urlencode({"pivot_sort": sort_field, "pivot_direction": next_direction})
    url = f"{base_url}?{query}"

    return mark_safe(
        f'<a href="#" hx-get="{escape(url)}" hx-target="#report-content" '
        f'hx-select="#report-content" hx-swap="outerHTML" '
        f'hx-indicator="#loading-indicator" class="cursor-pointer select-none">'
        f"{escape(label)}{arrow}</a>"
    )


@register.filter
def get_item(dictionary, key):
    """Get item from dictionary using key."""
    if not dictionary or not isinstance(dictionary, dict):
        return None
    return dictionary.get(key)


@register.filter
def dict_sum(value):
    """Sum the values in a dictionary."""
    if not value or not isinstance(value, dict):
        return 0
    return sum(
        float(v)
        for v in value.values()
        if v is not None and isinstance(v, (int, float, Decimal))
    )


def _round_for_display(value):
    """Round to 2 decimals, keeping whole numbers as plain ints (a Count of
    220 displays as 220, not 220.0)."""
    rounded = round(float(value), 2)
    return int(rounded) if rounded == int(rounded) else rounded


def _format_number_with_commas(value):
    """Round to 2 decimals (int display for whole numbers) and add thousands
    separators, e.g. 12728980.99 -> "12,728,980.99", 220 -> "220"."""
    rounded = _round_for_display(value)
    if isinstance(rounded, int):
        return f"{rounded:,}"
    return f"{rounded:,.2f}"


@register.filter
def pivot_number(value):
    """Format a pivot table numeric value for display: rounded to 2 decimals
    (whole numbers shown with no decimal point) and thousands-separated,
    e.g. 12728980.99 -> "12,728,980.99", 220 -> "220", 220.0 -> "220".
    Non-numeric values (dates, labels, "0" placeholder) pass through as-is.
    """
    if isinstance(value, str):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return value
    if not isinstance(value, (int, float, Decimal)):
        return value
    return _format_number_with_commas(value)


def _currency_field_for_column(model_class, column_name, aggregate_columns):
    """If column_name is an aggregate over a field in model_class's
    CURRENCY_FIELDS, return that field name; otherwise None."""
    currency_fields = getattr(model_class, "CURRENCY_FIELDS", None)
    if not currency_fields:
        return None
    for agg in aggregate_columns or []:
        if agg.get("name") == column_name and agg.get("field") in currency_fields:
            return agg["field"]
    return None


def _resolve_report_currency(model_class_or_report, user):
    """Get the (default_currency, user_currency) MultipleCurrency pair for a
    report's company/user, same lookup get_currency_display_value uses."""
    company = getattr(user, "company", None) if user else None
    default_currency = MultipleCurrency.get_default_currency(company)
    user_currency = MultipleCurrency.get_user_currency(user)
    return default_currency, user_currency


def _format_pivot_value(value, column_name, model_class, aggregate_columns, user):
    """Format a single pivot value: MultipleCurrency-formatted (per the
    project's configured western/European/Indian/scientific style and
    company/user currency) when column_name aggregates a CURRENCY_FIELDS
    field on model_class; otherwise plain comma-separated number.
    """
    if not isinstance(value, (int, float, Decimal)):
        return value

    if model_class is not None and _currency_field_for_column(
        model_class, column_name, aggregate_columns
    ):
        default_currency, user_currency = _resolve_report_currency(model_class, user)
        if default_currency:
            if not user_currency or user_currency.pk == default_currency.pk:
                return default_currency.display_with_symbol(value, user=user)
            converted = user_currency.convert_from_default(value)
            return (
                f"{default_currency.display_with_symbol(value, user=user)} "
                f"({user_currency.display_with_symbol(converted, user=user)})"
            )

    return _format_number_with_commas(value)


@register.simple_tag(takes_context=True)
def pivot_currency_number(context, value, column_name):
    """Format a pivot value as currency when column_name is an aggregate over
    a CURRENCY_FIELDS field on the report's model; otherwise falls back to
    plain comma formatting."""
    if isinstance(value, str):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return value

    report = context.get("report")
    aggregate_columns = context.get("aggregate_columns")
    model_class = getattr(report, "model_class", None) if report else None
    request = context.get("request")
    user = getattr(request, "user", None) if request else None

    return _format_pivot_value(value, column_name, model_class, aggregate_columns, user)


@register.filter
def column_sum(pivot_table, column):
    """Sum the values for a specific column across all rows."""
    if not pivot_table or not isinstance(pivot_table, dict):
        return 0
    total = 0
    for row in pivot_table.values():
        if row and isinstance(row, dict):
            value = row.get(column, 0)
            if isinstance(value, (int, float, Decimal)):
                total += float(value)
    return _format_number_with_commas(total)


@register.simple_tag(takes_context=True)
def column_total(context, pivot_table, column, aggregate_columns=None):
    """Compute a pivot column's Total-row value, reapplying the column's own
    aggregate function (avg/min/max/sum) instead of always summing per-row
    values — summing six per-group averages is not the same as the overall
    average. "Count" (no matching aggregate entry) always sums. Formatted as
    currency (if this column aggregates a CURRENCY_FIELDS field) or plain
    comma-separated number.
    """
    if not pivot_table or not isinstance(pivot_table, dict):
        return 0

    values = [
        float(row.get(column, 0))
        for row in pivot_table.values()
        if row
        and isinstance(row, dict)
        and isinstance(row.get(column), (int, float, Decimal))
    ]
    if not values:
        return 0

    aggfunc = "sum"
    for agg in aggregate_columns or []:
        if agg.get("name") == column:
            aggfunc = agg.get("function", "sum")
            break

    if aggfunc == "avg":
        total = sum(values) / len(values)
    elif aggfunc == "min":
        total = min(values)
    elif aggfunc == "max":
        total = max(values)
    else:
        total = sum(values)

    report = context.get("report")
    model_class = getattr(report, "model_class", None) if report else None
    request = context.get("request")
    user = getattr(request, "user", None) if request else None

    return _format_pivot_value(total, column, model_class, aggregate_columns, user)


@register.filter
def total_sum(pivot_table):
    """Sum all values in the pivot table."""
    if not pivot_table or not isinstance(pivot_table, dict):
        return 0
    return sum(dict_sum(row) for row in pivot_table.values() if row)


def _values_for_column(group_items, column_name):
    """Collect the raw numeric values for column_name across a list of items."""
    values = []
    for item in group_items:
        if isinstance(item, dict):
            item_values = item.get("values", {})
            if isinstance(item_values, dict):
                value = item_values.get(column_name, 0)
                if isinstance(value, (int, float, Decimal)):
                    values.append(float(value))
    return values


def _aggregate_values(values, aggfunc):
    """Reapply aggfunc (avg/min/max/sum) across already-aggregated per-row
    values, instead of always summing them (summing per-row averages is not
    the same as the overall average)."""
    if not values:
        return 0
    if aggfunc == "avg":
        return sum(values) / len(values)
    if aggfunc == "min":
        return min(values)
    if aggfunc == "max":
        return max(values)
    return sum(values)


def _aggfunc_for_column(aggregate_columns, column_name):
    for agg in aggregate_columns or []:
        if agg.get("name") == column_name:
            return agg.get("function", "sum")
    return "sum"


@register.simple_tag(takes_context=True)
def get_column_subtotal(context, group_items, column_name, aggregate_columns=None):
    """Calculate a subtotal for a specific column within a group, reapplying
    the column's own aggregate function (avg/min/max/sum). Formatted as
    currency (if this column aggregates a CURRENCY_FIELDS field) or plain
    comma-separated number."""
    values = _values_for_column(group_items, column_name)
    aggfunc = _aggfunc_for_column(aggregate_columns, column_name)
    total = _aggregate_values(values, aggfunc)

    report = context.get("report")
    model_class = getattr(report, "model_class", None) if report else None
    request = context.get("request")
    user = getattr(request, "user", None) if request else None
    return _format_pivot_value(total, column_name, model_class, aggregate_columns, user)


@register.simple_tag(takes_context=True)
def get_grand_column_total(
    context, hierarchical_data, column_name, aggregate_columns=None
):
    """Calculate the grand total for a specific column across all groups,
    reapplying the column's own aggregate function. Formatted as currency
    (if this column aggregates a CURRENCY_FIELDS field) or plain
    comma-separated number."""
    if not isinstance(hierarchical_data, dict):
        return 0
    values = []
    for group in hierarchical_data.get("groups", []):
        if isinstance(group, dict):
            values.extend(_values_for_column(group.get("items", []), column_name))
    aggfunc = _aggfunc_for_column(aggregate_columns, column_name)
    total = _aggregate_values(values, aggfunc)

    report = context.get("report")
    model_class = getattr(report, "model_class", None) if report else None
    request = context.get("request")
    user = getattr(request, "user", None) if request else None
    return _format_pivot_value(total, column_name, model_class, aggregate_columns, user)


@register.filter
def zip_lists(value, arg):
    """
    Zip two iterables together for use in template loops.
    """
    if not hasattr(value, "__iter__") or not hasattr(arg, "__iter__"):
        return []
    return list(zip(value, arg))


@register.filter
def attr(obj, attr_name):
    """Dynamically access an attribute of an object by name."""
    try:
        return getattr(obj, attr_name)
    except AttributeError:
        return None


@register.filter
def split(value, delimiter):
    """Split a string by delimiter."""
    if not value:
        return []
    return str(value).split(delimiter)


@register.filter
def mul(value, multiplier):
    """Multiply a value by a multiplier."""
    try:
        return float(value) * float(multiplier)
    except (ValueError, TypeError):
        return 0


@register.filter
def add(value, arg):
    """Add arg to value."""
    try:
        return float(value) + float(arg)
    except (ValueError, TypeError):
        return value


@register.filter
def subtract(value, arg):
    """Subtract arg from value."""
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return value


@register.filter
def divide(value, arg):
    """Divide value by arg."""
    try:
        return float(value) / float(arg)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0


@register.filter
def percentage(value, total):
    """Calculate percentage of value from total."""
    try:
        if float(total) == 0:
            return 0
        return (float(value) / float(total)) * 100
    except (ValueError, TypeError):
        return 0


@register.filter
def format_number(value, decimal_places=2):
    """Format number with specified decimal places."""
    try:
        return floatformat(float(value), decimal_places)
    except (ValueError, TypeError):
        return value


@register.filter
def is_first(value, loop_info):
    """Check if this is the first item in a loop."""
    return getattr(loop_info, "first", False)


@register.filter
def is_last(value, loop_info):
    """Check if this is the last item in a loop."""
    return getattr(loop_info, "last", False)


@register.filter
def get_level1_rowspan(level1_group):
    """Calculate rowspan for level 1 group in 3-level hierarchy."""
    if not isinstance(level1_group, dict):
        return 1

    level2_groups = level1_group.get("level2_groups", [])
    total_rows = 0

    for level2_group in level2_groups:
        if isinstance(level2_group, dict):
            level3_items = level2_group.get("level3_items", [])
            total_rows += len(level3_items) + 1  # +1 for level2 subtotal

    return total_rows + 1  # +1 for level1 total


@register.filter
def get_level2_rowspan(level2_group):
    """Calculate rowspan for level 2 group in 3-level hierarchy."""
    if not isinstance(level2_group, dict):
        return 1

    level3_items = level2_group.get("level3_items", [])
    return len(level3_items)


@register.filter
def count_items_in_group(group):
    """Count total items in a hierarchical group."""
    if not isinstance(group, dict):
        return 0

    items = group.get("items", [])
    return len(items)


@register.filter
def group_by_level1(column_hierarchy):
    """Group column hierarchy by level 1."""
    if not column_hierarchy:
        return []

    grouped = {}
    for item in column_hierarchy:
        if isinstance(item, dict):
            level1 = item.get("level1")
            if level1 not in grouped:
                grouped[level1] = []
            grouped[level1].append(item)

    return [{"grouper": k, "list": v} for k, v in grouped.items()]


@register.filter
def get_colspan(level1_items):
    """Get colspan for level 1 header."""
    return len(level1_items) if level1_items else 1


@register.simple_tag
def calculate_three_level_rowspan(
    level1_group, current_level2_index, current_level3_index
):
    """Calculate rowspan for three-level hierarchy."""
    if current_level2_index == 0 and current_level3_index == 0:
        # This is the first item in level1 group
        total_items = 0
        level2_groups = level1_group.get("level2_groups", [])
        for level2_group in level2_groups:
            level3_items = level2_group.get("level3_items", [])
            total_items += len(level3_items) + 1  # +1 for subtotal row
        return total_items + 1  # +1 for grand total row
    return None


@register.simple_tag
def calculate_level2_rowspan(level2_group, current_level3_index):
    """Calculate rowspan for level 2 in three-level hierarchy."""
    if current_level3_index == 0:
        level3_items = level2_group.get("level3_items", [])
        return len(level3_items)
    return None


@register.filter
def default_if_none(value, default):
    """Return default if value is None."""
    return default if value is None else value


@register.filter
def safe_int(value):
    """Safely convert value to int."""
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return 0


@register.filter
def safe_float(value):
    """Safely convert value to float."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


@register.filter
def display_value(value):
    """Display value with proper formatting."""
    if value is None:
        return "-"
    if isinstance(value, (int, float, Decimal)):
        if value == 0:
            return "0"
        return floatformat(value, 2) if value != int(value) else str(int(value))
    return str(value)


@register.filter
def is_numeric(value):
    """Check if value is numeric."""
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False


@register.filter
def sum_list(value_list):
    """Sum a list of values."""
    if not value_list:
        return 0
    total = 0
    for value in value_list:
        if isinstance(value, (int, float, Decimal)):
            total += float(value)
    return total


# @register.filter
# def zip_lists(value, arg):
# """
# Zip two iterables together for use in template loops.
# """
# if not hasattr(value, '__iter__') or not hasattr(arg, '__iter__'):
# return []
# return list(zip(value, arg))


@register.filter
def in_list(value, arg):
    """Check if a value is in a comma-separated list."""
    return value in arg.split(",")


@register.filter
def get_field_verbose_name(field_name, model_class):
    """Get verbose name for a field"""
    try:
        field = resolve_report_field(model_class, field_name)
        if "__" in field_name:
            # Prefix the relation (e.g. "Activity Owner - Role") so identical
            # related fields (owner / created by / meeting host) stay distinguishable.
            relation = model_class._meta.get_field(field_name.split("__", 1)[0])
            return f"{relation.verbose_name} - {field.verbose_name}"
        return field.verbose_name
    except Exception:
        return field_name.replace("__", " - ").replace("_", " ").title()


@register.filter
def total_sum_excluding_aggregate(pivot_table, _unused=None):
    """Return the grand total record count across all rows (the precomputed
    'total' key), formatted for display. This is always a plain count,
    unrelated to whichever aggregate columns the report also shows."""
    total = 0
    for _row, values in pivot_table.items():
        value = values.get("total", 0)
        if isinstance(value, (int, float, Decimal)):
            total += float(value)
    return _format_number_with_commas(total)


@register.filter
def sum_aggregate(items, aggregate_column_name):
    """
    Compute aggregate for a list of items based on aggregate_column.function.
    """
    if not items or not aggregate_column_name:
        return "-"
    # Assuming items is a list of objects with an 'aggregate' field
    # and aggregate_column is passed from the context with 'function'
    aggregate_column = items[0].get("aggregate_column", {}) if items else {}
    agg_func = (
        aggregate_column.get("function", "sum")
        if isinstance(aggregate_column, dict)
        else "sum"
    )

    values = [item.aggregate for item in items if item.aggregate is not None]
    if not values:
        return "-"

    funcs = {
        "sum": sum,
        "max": max,
        "min": min,
        "count": len,
    }

    return funcs.get(agg_func, lambda _: "-")(values)


@register.filter
def sum_level2_aggregate(level2_groups, aggregate_column_name):
    """
    Compute aggregate for level 2 groups.
    """
    if not level2_groups or not aggregate_column_name:
        return "-"
    aggregate_column = (
        level2_groups[0].get("aggregate_column", {}) if level2_groups else {}
    )
    agg_func = (
        aggregate_column.get("function", "sum")
        if isinstance(aggregate_column, dict)
        else "sum"
    )

    values = []
    for group in level2_groups:
        for item in group.level3_items:
            if item.aggregate is not None:
                values.append(item.aggregate)

    if not values:
        return "-"

    return {
        "sum": sum,
        "max": max,
        "min": min,
        "count": len,
    }.get(
        agg_func, lambda _: "-"
    )(values)


@register.filter
def sum_level1_aggregate(level1_groups, aggregate_column_name):
    """
    Compute aggregate for level 1 groups.
    """
    if not level1_groups or not aggregate_column_name:
        return "-"
    aggregate_column = (
        level1_groups[0].get("aggregate_column", {}) if level1_groups else {}
    )
    agg_func = (
        aggregate_column.get("function", "sum")
        if isinstance(aggregate_column, dict)
        else "sum"
    )

    values = []
    for group in level1_groups:
        for level2_group in group.level2_groups:
            for item in level2_group.level3_items:
                if item.aggregate is not None:
                    values.append(item.aggregate)

    if not values:
        return "-"

    return {"sum": sum, "max": max, "min": min, "count": len}.get(
        agg_func, lambda _: "-"
    )(values)


@register.filter
def aggregate_names(aggregate_columns):
    """Return a list of aggregate column names from the aggregate_columns definition."""
    return [agg["name"] for agg in aggregate_columns]


@register.filter
def is_choice_or_foreign(report, field_name):
    """Return True when the given field on the report's model is a choice field or a foreign key."""
    return report.is_choice_or_foreign_key_field(field_name)


@register.filter
def csv_contains(csv_value, item):
    """Return True when `item` is one of the comma-separated values in `csv_value`."""
    return str(item) in [v.strip() for v in str(csv_value or "").split(",")]


@register.filter
def get_field_choices(report, field_name):
    """Return choices or related object options for the report's given field."""
    return report.get_field_choices(field_name)


@register.filter
def get_display_text(composite_key):
    """Extract display text from composite key format 'Display||ID'"""
    if isinstance(composite_key, dict):
        return composite_key.get("_display", composite_key)
    if "||" in str(composite_key):
        return str(composite_key).split("||")[0]
    return str(composite_key)


@register.filter
def is_aggregatable(field_name, model_class):
    """
    Check if a field can be aggregated (is numeric).
    Usage: {% if field.name|is_aggregatable:report.model_class %}
    """
    try:
        field = model_class._meta.get_field(field_name)

        # Check if field is numeric and not a primary key
        if (
            isinstance(
                field,
                (
                    IntegerField,
                    FloatField,
                    DecimalField,
                    PositiveIntegerField,
                    PositiveSmallIntegerField,
                    BigIntegerField,
                    SmallIntegerField,
                ),
            )
            and not field.primary_key
        ):
            return True

        return False
    except Exception:
        return False


@register.filter
def filter_operators(report, field_name):
    """Operators offered for a report filter field (same as the list filter)."""
    return get_report_filter_operators(report.model_class, field_name)


@register.filter
def filter_field_type(report, field_name):
    """List-filter field type key ("text", "number", "date", ...) for a report field."""
    return get_report_filter_field_type(report.model_class, field_name)


@register.filter
def csv_part(csv_value, index):
    """Return the `index`-th comma-separated part of a value (for "between")."""
    parts = str(csv_value or "").split(",", 1)
    index = int(index)
    return parts[index].strip() if index < len(parts) else ""


@register.filter
def is_no_value_operator(operator):
    """True for operators that need no value input (is empty, today, ...)."""
    return operator in NO_VALUE_OPERATORS


@register.filter
def filter_summary(filter_value, report):
    """Pill text for an applied filter, e.g. "Activity Owner - Role Equals CEO, Sales Manager".

    Returns "" for a filter that has no effect yet (no value and a value-needing operator).
    """
    operator = filter_value.get("operator", "exact")
    value = filter_value.get("value", "")
    if not value and operator not in NO_VALUE_OPERATORS:
        return ""
    field = filter_value.get("original_field")
    label = get_field_verbose_name(field, report.model_class)
    op_label = dict(get_report_filter_operators(report.model_class, field)).get(
        operator, operator
    )
    if operator in NO_VALUE_OPERATORS:
        return f"{label} {op_label}"
    if operator == "between":
        start, _sep, end = str(value).partition(",")
        return f"{label} {op_label} {start.strip()} - {end.strip()}"
    if report.is_choice_or_foreign_key_field(field):
        names = {
            str(c["value"]): str(c["display"]) for c in report.get_field_choices(field)
        }
        value = ", ".join(
            names.get(v.strip(), v.strip()) for v in str(value).split(",") if v.strip()
        )
    return f"{label} {op_label} {value}"


@register.filter
def has_applied_filters(report):
    """True when at least one filter row has an effect (shows as a pill)."""
    return any(
        filter_summary(fv, report)
        for fv in report.filters_dict.values()
        if isinstance(fv, dict)
    )


@register.filter
def has_pending_filters(report):
    """True when a filter row was added but still has no value (still being edited)."""
    return any(
        isinstance(fv, dict) and not filter_summary(fv, report)
        for fv in report.filters_dict.values()
    )


@register.filter
def applied_filter_count(report):
    """Number of filter rows that currently have an effect."""
    return sum(
        1
        for fv in report.filters_dict.values()
        if isinstance(fv, dict) and filter_summary(fv, report)
    )


@register.filter
def grouping_count(report):
    """Number of row groups plus column groups."""
    return len(report.row_groups_list) + len(report.column_groups_list)
