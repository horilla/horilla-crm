"""Shared field-choice builders for the dashboard component form and its HTMX views."""

# Third-party imports (Django)
from django.utils.encoding import force_str

# First party imports (Horilla)
from horilla.utils.choices import DISPLAYABLE_FIELD_TYPES

NUMERIC_INTERNAL_TYPES = frozenset(
    {
        "IntegerField",
        "BigIntegerField",
        "SmallIntegerField",
        "PositiveIntegerField",
        "PositiveSmallIntegerField",
        "DecimalField",
        "FloatField",
    }
)

# Aggregations offered for every numeric field, as (key, label prefix).
METRIC_AGGREGATIONS = (
    ("sum", "Sum"),
    ("average", "Average"),
    ("min", "Minimum"),
    ("max", "Maximum"),
)


def get_displayable_field_choices(model):
    """
    ``(name, label)`` pairs for fields usable as table columns or chart groupings:
    displayable (or choice) columns plus forward ForeignKeys. Labels are plain
    strings so they are safe for templates and JSON.
    """
    choices = []
    for field in model._meta.get_fields():
        if field.concrete and not field.is_relation:
            field_type = (
                field.get_internal_type() if hasattr(field, "get_internal_type") else ""
            )
            if field_type in DISPLAYABLE_FIELD_TYPES or (
                field_type and getattr(field, "choices", None)
            ):
                choices.append(
                    (field.name, force_str(field.verbose_name or field.name))
                )
        elif hasattr(field, "related_model") and field.many_to_one:
            choices.append((field.name, force_str(field.verbose_name or field.name)))
    return choices


def _aggregation_choices(field_name, field_label):
    """One ``<agg>__<field_name>`` choice per aggregation for a numeric field."""
    return [
        (f"{agg_key}__{field_name}", f"{agg_label} of {field_label}")
        for agg_key, agg_label in METRIC_AGGREGATIONS
    ]


def get_metric_choices(model, extra_fields=()):
    """
    Metric choices: "Count of records" plus Sum/Average/Minimum/Maximum of every
    numeric field on ``model``. ``extra_fields`` are extra ``(name, label)`` pairs
    (e.g. custom fields) that get the same aggregations. Metrics are stored as
    ``<agg>__<field_name>`` so the metric configuration can be parsed unambiguously.
    """
    choices = [("count", "Count of records")]
    if not model:
        return choices

    for field in model._meta.get_fields():
        if not getattr(field, "concrete", False) or getattr(
            field, "is_relation", False
        ):
            continue
        field_type = (
            field.get_internal_type() if hasattr(field, "get_internal_type") else ""
        )
        if field_type not in NUMERIC_INTERNAL_TYPES:
            continue
        label = force_str(getattr(field, "verbose_name", field.name))
        choices.extend(_aggregation_choices(field.name, label))

    for field_name, field_label in extra_fields:
        choices.extend(_aggregation_choices(field_name, force_str(field_label)))
    return choices


def add_current_metric_choice(choices, current_metric):
    """
    Make sure the stored metric stays selectable even if its field is no longer
    offered, labelling it from the stored key. Appends to ``choices`` in place.
    """
    if not current_metric or current_metric in {value for value, _label in choices}:
        return choices

    parts = current_metric.split("__", 1)
    if len(parts) == 2:
        agg_key, field_name = parts
        agg_label = (
            "Average" if agg_key == "average" else agg_key.replace("_", " ").title()
        )
        label = f"{agg_label} of {field_name.replace('_', ' ').title()}"
    else:
        label = current_metric.replace("_", " ").title()
    choices.append((current_metric, label))
    return choices
