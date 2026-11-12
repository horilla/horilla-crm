"""Queryset utilities shared across Horilla contrib apps."""

# Standard library imports
import logging
from functools import reduce
from operator import or_

# Third-party imports (Django)
from django.contrib.auth import get_user_model

from horilla.contrib.generics.forms.condition_fields import get_extension_condition_q
from horilla.contrib.generics.related_fields import resolve_field_path
from horilla.db.models import ForeignKey, ManyToManyField, Q

logger = logging.getLogger(__name__)

__all__ = [
    "apply_conditions",
    "get_queryset_for_module",
    "get_viewable_queryset",
    "filter_viewable_queryset",
    "get_granted_access_filter",
    "user_has_granted_access",
]


def get_granted_access_filter(model, user, action):
    """
    Return a Q object matching records that grant ``user`` access to ``action``
    via the model's optional ``granted_access_filter(user, action)`` classmethod
    (e.g. team/shared-access grants that live outside OWNER_FIELDS, such as
    Opportunity's OpportunityTeamMember), or None if the model doesn't opt in.

    Models opt in by defining a classmethod
    ``granted_access_filter(cls, user, action)`` returning a Q object usable in
    ``queryset.filter(...)``, where ``action`` is one of "view", "change", "delete".
    """
    getter = getattr(model, "granted_access_filter", None)
    if getter is None:
        return None
    try:
        return getter(user, action)
    except Exception:
        logger.exception(
            "Error building granted access filter for %r action=%s", model, action
        )
        return None


def user_has_granted_access(obj, user, action):
    """
    Return True if ``obj`` grants ``user`` access to ``action`` via the
    optional per-instance ``has_granted_access(user, action)`` hook.
    """
    checker = getattr(obj, "has_granted_access", None)
    if checker is None:
        return False
    try:
        return bool(checker(user, action))
    except Exception:
        logger.exception("Error resolving granted access for %r action=%s", obj, action)
        return False


def get_queryset_for_module(user, model):
    """
    Returns queryset for a given model based on user permissions.
    Uses model.OWNER_FIELDS if available.
    """
    app_label = model._meta.app_label
    model_name = model._meta.model_name

    if user.has_perm(f"{app_label}.view_{model_name}"):
        return model.objects.all()

    if user.has_perm(f"{app_label}.view_own_{model_name}"):
        owner_fields = getattr(model, "OWNER_FIELDS", [])
        if not owner_fields:
            return model.objects.none()

        q_filter = Q()
        for field in owner_fields:
            q_filter |= Q(**{field: user})
        return model.objects.filter(q_filter)

    return model.objects.none()


def get_viewable_queryset(user, model):
    """
    Return the records of ``model`` that ``user`` may view, by the same rule as
    the list view's owner filtration: ``view_<model>`` sees every record,
    ``view_own_<model>`` sees records owned by the user or a subordinate role
    (``OWNER_FIELDS``) plus records granted through ``granted_access_filter``,
    and anyone else sees nothing.
    """
    from horilla.contrib.core.utils import get_allowed_user_ids

    app_label = model._meta.app_label
    model_name = model._meta.model_name

    if user.has_perm(f"{app_label}.view_{model_name}"):
        return model.objects.all()
    if not user.has_perm(f"{app_label}.view_own_{model_name}"):
        return model.objects.none()

    query = None
    owner_fields = getattr(model, "OWNER_FIELDS", None)
    if owner_fields:
        allowed_user_ids = list(get_allowed_user_ids(user))
        query = reduce(
            or_,
            (Q(**{f"{field}__in": allowed_user_ids}) for field in owner_fields),
            Q(),
        )
    granted_query = get_granted_access_filter(model, user, "view")
    if granted_query is not None:
        query = granted_query if query is None else query | granted_query
    if query is None:
        return model.objects.none()

    # Deduplicate by primary key in a subquery rather than .distinct() on the
    # outer queryset: report code calls .values(*fields) on the result, and an
    # outer DISTINCT would merge different records with equal column values.
    return model.objects.filter(pk__in=model.objects.filter(query).values("pk"))


def _owner_queries(model, field_names, user, allowed_ids):
    """
    Q objects matching records whose owner fields hold one of ``allowed_ids``.

    A relation counts as an owner field only if it points to a user (or employee);
    a plain field is matched by value. Names that are not fields are skipped.
    """
    queries = []
    for field_name in field_names:
        try:
            field = model._meta.get_field(field_name)
            if field.is_relation:
                related_model = field.related_model
                if isinstance(field, (ForeignKey, ManyToManyField)) and (
                    related_model._meta.model_name.lower() in ["user", "employee"]
                    or related_model == user.__class__
                    or related_model._meta.label_lower == "auth.user"
                ):
                    queries.append(Q(**{f"{field_name}__in": allowed_ids}))
            else:
                queries.append(Q(**{f"{field_name}__in": allowed_ids}))
        except Exception:  # pylint: disable=broad-exception-caught
            # Not a field of this model: skip it
            continue
    return queries


def filter_viewable_queryset(user, model, base_queryset):
    """
    Narrow ``base_queryset`` to the records of ``model`` that ``user`` may view.

    ``view_<model>`` sees everything. ``view_own_<model>`` sees records owned by the
    user or the users under them: by ``OWNER_FIELDS`` (plus ``granted_access_filter``),
    or, for a model without them, by the common owner fields (``created_by``,
    ``user``, ``owner``, ``employee_id``). For the user model itself, "owned" means
    the user's own record and the users under them. Anyone else sees nothing.

    Used where records are listed outside a list view (global search, the Select2
    endpoint and the User Picker), so all three apply the same rule.
    """
    from horilla.contrib.core.utils import get_allowed_user_ids

    app_label = model._meta.app_label
    model_name = model._meta.model_name

    if user.has_perm(f"{app_label}.view_{model_name}"):
        return base_queryset

    if not user.has_perm(f"{app_label}.view_own_{model_name}"):
        return base_queryset.none()

    allowed_ids = get_allowed_user_ids(user)

    # A user record is owned by that user, not by whoever created it, so with
    # view_own a user sees themselves and the users under them (the same set
    # get_allowed_user_ids gives every other owner check).
    if issubclass(model, get_user_model()):
        return base_queryset.filter(pk__in=allowed_ids)

    owner_fields = getattr(model, "OWNER_FIELDS", None)
    if owner_fields:
        queries = _owner_queries(model, owner_fields, user, allowed_ids)
        granted_query = get_granted_access_filter(model, user, "view")
        if granted_query is not None:
            queries.append(granted_query)
        if queries:
            return base_queryset.filter(reduce(or_, queries)).distinct()
        # No valid ownership fields
        return base_queryset.none()

    # No OWNER_FIELDS: fall back to common ownership field names
    queries = _owner_queries(
        model, ["created_by", "user", "owner", "employee_id"], user, allowed_ids
    )
    if queries:
        return base_queryset.filter(reduce(or_, queries)).distinct()
    return base_queryset.none()


def apply_conditions(queryset, conditions):
    """Apply filter conditions to a queryset with proper type handling."""

    for condition in conditions:
        field = condition.field
        operator = condition.operator
        value = condition.value

        if not value and operator not in [
            "is_null",
            "is_not_null",
            "isnull",
            "isnotnull",
        ]:
            continue

        # Fields contributed by other apps (e.g. custom fields) aren't columns.
        extension_q = get_extension_condition_q(queryset.model, field, operator, value)
        if extension_q is not None:
            queryset = queryset.filter(extension_q)
            continue

        try:
            model = queryset.model
            # "owner__department" resolves to the field on the related model.
            field_obj = resolve_field_path(model, field) or model._meta.get_field(field)

            converted_value = value
            if hasattr(field_obj, "get_internal_type"):
                field_type = field_obj.get_internal_type()

                if field_type in [
                    "IntegerField",
                    "BigIntegerField",
                    "SmallIntegerField",
                    "PositiveIntegerField",
                    "PositiveSmallIntegerField",
                    "DecimalField",
                    "FloatField",
                ]:
                    try:
                        if field_type in ["DecimalField", "FloatField"]:
                            converted_value = float(value)
                        else:
                            converted_value = int(value)
                    except (ValueError, TypeError):
                        logger.warning(
                            "Could not convert value '%s' to numeric for field '%s'",
                            value,
                            field,
                        )
                        continue

                elif field_type == "BooleanField":
                    if str(value).lower() in ["true", "1", "yes"]:
                        converted_value = True
                    elif str(value).lower() in ["false", "0", "no"]:
                        converted_value = False
                    else:
                        logger.warning(
                            "Invalid boolean value '%s' for field '%s'",
                            value,
                            field,
                        )
                        continue

                elif field_type == "ForeignKey":
                    try:
                        converted_value = int(value)
                    except (ValueError, TypeError):
                        logger.warning(
                            "Could not convert FK value '%s' to int for field '%s'",
                            value,
                            field,
                        )
                        continue

            if operator in ["equals", "exact"]:
                queryset = queryset.filter(**{field: converted_value})

            elif operator in ["not_equals", "ne"]:
                queryset = queryset.exclude(**{field: converted_value})

            elif operator == "greater_than":
                queryset = queryset.filter(**{f"{field}__gt": converted_value})

            elif operator == "less_than":
                queryset = queryset.filter(**{f"{field}__lt": converted_value})

            elif operator in ["greater_equal", "gte"]:
                queryset = queryset.filter(**{f"{field}__gte": converted_value})

            elif operator in ["less_equal", "lte"]:
                queryset = queryset.filter(**{f"{field}__lte": converted_value})

            elif operator == "gt":
                queryset = queryset.filter(**{f"{field}__gt": converted_value})

            elif operator == "lt":
                queryset = queryset.filter(**{f"{field}__lt": converted_value})

            elif operator in ["contains", "icontains"]:
                queryset = queryset.filter(**{f"{field}__icontains": value})

            elif operator == "not_contains":
                queryset = queryset.exclude(**{f"{field}__icontains": value})

            elif operator in ["starts_with", "istartswith"]:
                queryset = queryset.filter(**{f"{field}__istartswith": value})

            elif operator in ["ends_with", "iendswith"]:
                queryset = queryset.filter(**{f"{field}__iendswith": value})

            elif operator in ["is_null", "isnull"]:
                queryset = queryset.filter(**{f"{field}__isnull": True})

            elif operator in ["is_not_null", "isnotnull"]:
                queryset = queryset.filter(**{f"{field}__isnull": False})

            elif operator == "in":
                values = [v.strip() for v in str(value).split(",")]
                queryset = queryset.filter(**{f"{field}__in": values})

            elif operator == "not_in":
                values = [v.strip() for v in str(value).split(",")]
                queryset = queryset.exclude(**{f"{field}__in": values})

        except Exception as e:
            logger.error(
                "Error applying condition %s %s %s: %s", field, operator, value, e
            )
            continue

    return queryset
