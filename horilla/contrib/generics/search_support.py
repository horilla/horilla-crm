"""
Helpers shared by global search and the search box of list views.

- ``PRESET_FILTER_LABELS`` / ``apply_preset_filter``: ready-made filters (My Records and
  time periods) that work on any model.
- ``resolve_lookup_label`` / ``build_field_labels``: readable labels for search fields,
  taken from the fields' verbose names.
"""

# Standard library imports
from datetime import timedelta

# Third-party imports (Django)
from django.utils import timezone

# First party imports (Horilla)
from horilla.db.models import Q

PRESET_FILTER_LABELS = {
    "mine": "My Records",
    "today": "Created Today",
    "yesterday": "Created Yesterday",
    "week": "Created This Week",
    "month": "Created This Month",
}


def get_owner_field_names(model):
    """Owner fields of a model (``OWNER_FIELDS``), falling back to ``created_by``."""
    names = list(getattr(model, "OWNER_FIELDS", None) or [])
    if not names and "created_by" in [f.name for f in model._meta.fields]:
        names = ["created_by"]
    return names


def apply_preset_filter(model, queryset, user, key):
    """
    Narrow a queryset with one preset filter (see ``PRESET_FILTER_LABELS``).

    ``mine`` matches the model's owner fields against ``user``; the time periods use
    ``created_at``. A model that cannot satisfy the filter returns nothing. An unknown
    key leaves the queryset unchanged.
    """
    if key not in PRESET_FILTER_LABELS:
        return queryset

    if key == "mine":
        q_owner = Q()
        for name in get_owner_field_names(model):
            q_owner |= Q(**{name: user})
        return queryset.filter(q_owner).distinct() if q_owner else queryset.none()

    if "created_at" not in [f.name for f in model._meta.fields]:
        return queryset.none()

    today = timezone.localdate()
    if key == "yesterday":
        return queryset.filter(created_at__date=today - timedelta(days=1))
    start = {
        "today": today,
        "week": today - timedelta(days=6),
        "month": today.replace(day=1),
    }[key]
    return queryset.filter(created_at__date__gte=start)


# Relative-date operators of the filter rows (see OPERATOR_CHOICES in filters.py)
LIST_QUICK_FILTER_OPERATORS = {
    "today": "today",
    "yesterday": "yesterday",
    "week": "this_week",
    "month": "this_month",
}


def list_quick_filters(model, user, field_names):
    """
    Quick filters of a list's search box, as ordinary filter rows.

    Each item is ``{"key", "label", "field", "operator", "value"}``: the row the filter
    panel would hold, so choosing one just adds a filter and the list's normal filter
    engine, applied-filter tag, counts and saved lists all handle it. ``field_names``
    are the fields the list can filter on; a quick filter whose field is not among them
    is left out. "My Records" uses the model's first owner field.
    """
    rows = []
    owner = next((n for n in get_owner_field_names(model) if n in field_names), None)
    if owner:
        rows.append(
            {
                "key": "mine",
                "label": PRESET_FILTER_LABELS["mine"],
                "field": owner,
                "operator": "exact",
                "value": str(user.pk),
            }
        )
    if "created_at" in field_names:
        for key, operator in LIST_QUICK_FILTER_OPERATORS.items():
            rows.append(
                {
                    "key": key,
                    "label": PRESET_FILTER_LABELS[key],
                    "field": "created_at",
                    "operator": operator,
                    "value": "",
                }
            )
    return rows


def resolve_lookup_label(model, lookup):
    """
    Check that a search lookup (e.g. ``name`` or ``module__model``) exists on a model.

    Returns a readable label, or ``None`` when any part of the path is not a field.
    A path through a relation is labelled "<relation> <field>", without repeating
    a word the field already contains ("Role", not "Role Role").
    """
    current = model
    labels = []
    parts = lookup.split("__")
    for index, part in enumerate(parts):
        try:
            field = current._meta.get_field(part)
        except Exception:  # FieldDoesNotExist, or a non-model on the path
            return None
        labels.append(str(getattr(field, "verbose_name", part)))
        if index < len(parts) - 1:
            if not getattr(field, "is_relation", False) or not field.related_model:
                return None
            current = field.related_model
    if len(labels) == 1:
        return labels[0]
    relation, leaf = labels[-2], labels[-1]
    # The "model" of a content type ("python model class name") reads as the relation:
    # a field named "Module" or "Model", not "Module python model class name".
    if parts[-1] == "model" and {"app_label", "model"} <= {
        f.name for f in current._meta.fields
    }:
        return relation[:1].upper() + relation[1:]
    if relation.lower() in leaf.lower():
        return leaf
    if leaf.lower() in relation.lower():
        return relation
    return f"{relation} {leaf}"


# The search choice that stands for two name fields is their lookups joined by this
# character, e.g. ``first_name+last_name`` or ``host__first_name+host__last_name``.
# It cannot appear in a field lookup, so a key never clashes with a real field.
NAME_KEY_SEPARATOR = "+"


def make_name_key(name_fields):
    """Search choice key for two name fields: ``["first_name", "last_name"]`` -> ``first_name+last_name``."""
    return NAME_KEY_SEPARATOR.join(name_fields)


def split_name_key(key):
    """
    The name fields behind a search choice key, or ``None`` if ``key`` is a single field.

    The reverse of ``make_name_key``.
    """
    if NAME_KEY_SEPARATOR not in key:
        return None
    return key.split(NAME_KEY_SEPARATOR)


def combined_name_label(model, name_fields):
    """
    Label of the choice that searches two name fields together.

    "Name" for the model's own fields; for two fields of one relation (``host__first_name``
    and ``host__last_name``) the relation's label comes first: "Host Name".
    """
    prefixes = {field.rpartition("__")[0] for field in name_fields}
    if len(prefixes) == 1 and "" not in prefixes:
        relation = resolve_lookup_label(model, prefixes.pop())
        if relation:
            return f"{relation[:1].upper()}{relation[1:]} Name"
    return "Name"


def build_field_labels(model, lookups):
    """
    Return ``{lookup: label}`` for the lookups that exist on ``model``.

    Labels are verbose names. Two lookups that would get the same label get the
    relation's name added so they can be told apart ("Folder Name" and
    "Parent Folder Name"). Lookups that are not fields are left out.
    """
    labels = {}
    for lookup in lookups:
        label = resolve_lookup_label(model, lookup)
        if label is not None:
            labels[lookup] = label

    seen = {}
    for lookup, label in labels.items():
        seen.setdefault(label.lower(), []).append(lookup)
    for duplicates in seen.values():
        if len(duplicates) < 2:
            continue
        for lookup in duplicates:
            if "__" not in lookup:
                continue
            relation = lookup.split("__")[-2].replace("_", " ").title()
            if relation.lower() in labels[lookup].lower():
                continue
            words = f"{relation} {labels[lookup]}".split()
            labels[lookup] = " ".join(
                word
                for index, word in enumerate(words)
                if index == 0 or word.lower() != words[index - 1].lower()
            )
    return labels
