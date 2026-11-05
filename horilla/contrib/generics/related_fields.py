"""
Related fields offered through a relation, shared by every field picker.

Report fields, the list filter panel and condition builders (automations,
approvals, ...) all list, next to a relation such as ``owner``, the useful
fields of the related model as ``owner__department``. The fields worth
showing for a model are registered once here, from the owning app's
``registration.py``, and reach every picker.
"""

# Standard library imports
from django.core.exceptions import FieldDoesNotExist

RELATED_FIELD_SEPARATOR = "__"

# "app_label.model_name": [field names] shown when reached through a relation.
_RELATED_DEFAULT_FIELDS = {}


def register_default_related_fields(app_label, model_name, fields):
    """Fields of app_label.model_name listed behind any relation to it
    (e.g. the user's department/role/company behind owner, created by, ...)."""
    _RELATED_DEFAULT_FIELDS[f"{app_label}.{model_name.lower()}"] = list(fields)


def get_default_related_fields(related_model):
    """Registered default field names of ``related_model`` (empty if none)."""
    key = f"{related_model._meta.app_label}.{related_model._meta.model_name}"
    return list(_RELATED_DEFAULT_FIELDS.get(key, []))


def iter_related_fields(model, exclude=()):
    """Yield ``(path, relation, related_field)`` for each registered related
    field behind a forward FK/one-to-one of ``model``; ``path`` is
    ``relation__field``. Relations named in ``exclude`` are skipped."""
    for relation in model._meta.fields:
        if relation.name in exclude or not relation.is_relation:
            continue
        if not (relation.many_to_one or relation.one_to_one):
            continue
        related_model = relation.related_model
        if related_model is None:
            continue
        for name in get_default_related_fields(related_model):
            try:
                related_field = related_model._meta.get_field(name)
            except FieldDoesNotExist:
                continue
            if not hasattr(related_field, "verbose_name"):
                continue
            yield (
                f"{relation.name}{RELATED_FIELD_SEPARATOR}{name}",
                relation,
                related_field,
            )


def resolve_field_path(model, path):
    """Return the model field a ``a__b`` path ends at, or ``None``.

    A plain field name behaves like ``model._meta.get_field``.
    """
    parts = path.split(RELATED_FIELD_SEPARATOR)
    current = model
    field = None
    for index, part in enumerate(parts):
        if current is None:
            return None
        try:
            field = current._meta.get_field(part)
        except (FieldDoesNotExist, AttributeError):
            return None
        if index < len(parts) - 1:
            current = getattr(field, "related_model", None)
    return field


def resolve_instance_path(instance, path):
    """Return ``(target, leaf)`` for a ``a__b`` path on a record.

    ``target`` is the record owning the last field; when a relation on the way
    is empty it is a blank unsaved instance, so the field reads as empty. A
    plain field name returns ``(instance, path)`` unchanged.
    """
    if RELATED_FIELD_SEPARATOR not in path:
        return instance, path
    *parents, leaf = path.split(RELATED_FIELD_SEPARATOR)
    target = instance
    for part in parents:
        related = getattr(target, part, None)
        if related is None:
            try:
                related = target._meta.get_field(part).related_model()
            except (FieldDoesNotExist, AttributeError, TypeError):
                return instance, path
        target = related
    return target, leaf
