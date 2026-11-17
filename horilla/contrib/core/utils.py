"""Utility functions for Horilla Core app."""

# Standard library imports
import json
import logging
from decimal import Decimal

# Third-party imports
import requests
from dateutil.parser import parse

# First party imports (Horilla)
from horilla.apps import apps
from horilla.contrib.utils.middlewares import _thread_local, get_current_request
from horilla.db import models, transaction
from horilla.db.models import QuerySet
from horilla.utils.choices import TABLE_FALLBACK_FIELD_TYPES

from .models import FieldPermission, HorillaContentType, MultipleCurrency, RecycleBin

# Local imports
from .services.exchange_providers import fetch_rates

logger = logging.getLogger(__name__)


def sanitize_export_value(value):
    """
    Sanitize cell values to prevent formula injection in CSV/XLSX exports.
    Prefixes formula-triggering characters (=, +, -, @, tab, CR) with a single quote.
    """
    if not isinstance(value, str):
        return value
    if value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def fetch_exchange_rate_from_api(base_currency, target_currency):
    """
    Fetch exchange rate from Frankfurter (free, no API key required).
    Falls back to the free Currency API (CC0) if Frankfurter fails.

    Args:
        base_currency: The base currency code (e.g., 'USD')
        target_currency: The target currency code (e.g., 'INR')

    Returns:
        Decimal: The exchange rate, or None if fetch fails
    """
    rates, _source = fetch_exchange_rates_bulk_with_source(
        base_currency, [target_currency]
    )
    return rates.get(target_currency)


def fetch_exchange_rate_with_source(base_currency, target_currency, preferred="auto"):
    """
    Same as fetch_exchange_rate but returns (rate, source_name).
    """
    rates, source = fetch_exchange_rates_bulk_with_source(
        base_currency, [target_currency], preferred
    )
    return rates.get(target_currency), source


def fetch_exchange_rates_bulk(base_currency, target_currencies, preferred="auto"):
    """
    Fetch exchange rates for multiple target currencies in a single API call.
    Returns a dict of currency code -> Decimal rate.
    """
    return fetch_exchange_rates_bulk_with_source(
        base_currency, target_currencies, preferred
    )[0]


def fetch_exchange_rates_bulk_with_source(
    base_currency, target_currencies, preferred="auto"
):
    """
    Fetch exchange rates for several currencies using the chosen provider.

    ``preferred`` is "auto" (the providers marked in_auto, in priority order)
    or the key of one registered provider. Providers are pluggable: see
    ``services/exchange_providers.py``.

    Returns (rates dict of code -> Decimal, provider label or None).
    """
    return fetch_rates(base_currency, target_currencies, preferred)


def restore_recycle_bin_records(request, recycle_objs):
    """
    Restore one or more RecycleBin records to their original models using the exact logic from RecycleRestoreView.

    Args:
        request: The Django request object for messaging.
        recycle_objs: A single RecycleBin object, a QuerySet, or a list of RecycleBin objects.

    Returns:
        tuple: (restored_count, failed_records)
            - restored_count: Number of successfully restored records.
            - failed_records: List of strings describing failed restorations.
    """
    from multiselectfield.db.fields import MultiSelectField  # Add this import

    restored_count = 0
    failed_records = []

    if not isinstance(recycle_objs, (QuerySet, list, tuple)):
        recycle_objs = [recycle_objs]

    for recycle_obj in recycle_objs:
        try:
            with transaction.atomic():
                app_label, model_name = recycle_obj.model_name.split(".")
                ModelClass = apps.get_model(app_label, model_name)

                if ModelClass.objects.filter(pk=recycle_obj.record_id).exists():
                    failed_records.append(
                        f"{recycle_obj.record_name()}: Record with ID {recycle_obj.record_id} already exists in {model_name}"
                    )
                    continue

                data = json.loads(recycle_obj.data)
                processed_data = {}

                for field in ModelClass._meta.fields:
                    field_name = field.name

                    if field.auto_created or field.primary_key:
                        continue

                    if field_name in data:
                        field_value = data[field_name]

                        # Handle MultiSelectField BEFORE checking for empty values
                        if isinstance(field, MultiSelectField):
                            # MultiSelectField stores as comma-separated string
                            if field_value in ["[]", "", "null", None, []]:
                                # Empty multiselect should be empty string
                                processed_data[field_name] = ""
                            elif isinstance(field_value, list):
                                # If it's already a list, join with commas
                                processed_data[field_name] = ",".join(
                                    str(v) for v in field_value
                                )
                            elif (
                                isinstance(field_value, str)
                                and field_value.startswith("[")
                                and field_value.endswith("]")
                            ):
                                # Handle string representation of list like "['monday','tuesday']"
                                try:
                                    parsed_list = json.loads(
                                        field_value.replace("'", '"')
                                    )
                                    processed_data[field_name] = (
                                        ",".join(str(v) for v in parsed_list)
                                        if parsed_list
                                        else ""
                                    )
                                except Exception:
                                    # If parsing fails, treat as comma-separated string
                                    processed_data[field_name] = field_value
                            else:
                                # Already a comma-separated string
                                processed_data[field_name] = str(field_value)
                            continue

                        if (
                            field_value == ""
                            or field_value == "null"
                            or field_value is None
                        ):
                            if field.null:
                                processed_data[field_name] = None
                            elif field.blank:
                                processed_data[field_name] = ""
                            else:
                                if (
                                    hasattr(field, "default")
                                    and field.default != models.NOT_PROVIDED
                                ):
                                    processed_data[field_name] = field.default
                                else:
                                    if hasattr(field, "get_internal_type"):
                                        field_type = field.get_internal_type()
                                        if field_type in TABLE_FALLBACK_FIELD_TYPES:
                                            processed_data[field_name] = ""
                                        else:
                                            continue
                            continue

                        if hasattr(field, "get_internal_type"):
                            field_type = field.get_internal_type()

                            try:
                                if field_type == "DateTimeField":
                                    if isinstance(field_value, str):
                                        field_value = parse(field_value)
                                elif field_type == "DateField":
                                    if isinstance(field_value, str):
                                        field_value = parse(field_value).date()
                                elif field_type == "BooleanField":
                                    field_value = (
                                        bool(field_value)
                                        if field_value not in ["", "null", None]
                                        else False
                                    )
                                elif field_type in [
                                    "IntegerField",
                                    "BigIntegerField",
                                    "SmallIntegerField",
                                    "PositiveIntegerField",
                                ]:
                                    if str(field_value).strip() != "":
                                        field_value = int(field_value)
                                    else:
                                        if field.null:
                                            field_value = None
                                        else:
                                            field_value = 0
                                elif field_type in ["FloatField", "DecimalField"]:
                                    if str(field_value).strip() != "":
                                        field_value = float(field_value)
                                    else:
                                        if field.null:
                                            field_value = None
                                        else:
                                            field_value = 0.0
                                elif field_type == "ForeignKey":
                                    if field_value and str(field_value).strip() not in [
                                        "",
                                        "null",
                                        "None",
                                    ]:
                                        try:
                                            related_model = field.related_model
                                            related_obj = related_model.objects.get(
                                                pk=int(field_value)
                                            )
                                            field_value = related_obj
                                        except (
                                            related_model.DoesNotExist,
                                            ValueError,
                                            TypeError,
                                        ) as e:
                                            logger.warning(
                                                "ForeignKey error for field %s in %s: %s",
                                                field_name,
                                                recycle_obj.record_name(),
                                                e,
                                            )
                                            if field.null:
                                                field_value = None
                                            else:
                                                # Assign the first available related object
                                                default_obj = (
                                                    related_model.objects.first()
                                                )
                                                if default_obj:
                                                    field_value = default_obj
                                                    logger.info(
                                                        "Assigned default %s ID %s to %s for field %s",
                                                        related_model.__name__,
                                                        default_obj.pk,
                                                        recycle_obj.record_name(),
                                                        field_name,
                                                    )
                                                else:
                                                    failed_records.append(
                                                        f"{recycle_obj.record_name()}: No available {related_model.__name__} for required field {field_name}"
                                                    )
                                                    raise ValueError(
                                                        f"No available {related_model.__name__} for required field {field_name}"
                                                    ) from e
                                    else:
                                        field_value = None
                                elif (
                                    field_type in TABLE_FALLBACK_FIELD_TYPES[:2]
                                ):  # [CharField, TextField]
                                    if field_value == "null":
                                        field_value = None if field.null else ""
                                    else:
                                        field_value = str(field_value)
                                elif field_type == "EmailField":
                                    if field_value in ["", "null", None]:
                                        field_value = None if field.null else ""
                                    else:
                                        field_value = str(field_value)

                            except (ValueError, TypeError) as e:
                                logger.warning(
                                    "Error processing field %s in %s: %s",
                                    field_name,
                                    recycle_obj.record_name(),
                                    e,
                                )

                                if field.null:
                                    field_value = None
                                else:
                                    continue

                        processed_data[field_name] = field_value

                restored_instance = ModelClass(**processed_data)
                restored_instance.save()
                recycle_obj.delete()
                restored_count += 1
        except Exception as e:
            failed_records.append(f"{recycle_obj.record_name()}: {str(e)}")
            logger.error("Failed to restore %s: %s", recycle_obj.record_name(), e)

    return restored_count, failed_records


def delete_recycle_bin_records(request, recycle_objs):
    """
    Delete one or more RecycleBin records.

    Args:
        request: The Django request object for messaging.
        recycle_objs: A single RecycleBin object, a QuerySet, or a list of RecycleBin objects.

    Returns:
        tuple: (deleted_count, failed_records)
            - deleted_count: Number of successfully deleted records.
            - failed_records: List of strings describing failed deletions.
    """
    deleted_count = 0
    failed_records = []

    # Convert input to iterable
    if not isinstance(recycle_objs, (QuerySet, list, tuple)):
        recycle_objs = [recycle_objs]

    for recycle_obj in recycle_objs:
        try:
            with transaction.atomic():
                if not RecycleBin.objects.filter(pk=recycle_obj.pk).exists():
                    failed_records.append(
                        f"{recycle_obj.record_name()}: Record with ID {recycle_obj.pk} does not exist"
                    )
                    continue

                recycle_obj.delete()
                deleted_count += 1
        except Exception as e:
            failed_records.append(f"{recycle_obj.record_name()}: {str(e)}")
            logger.error("Failed to delete %s: %s", recycle_obj.record_name(), e)

    return deleted_count, failed_records


def _get_cached_currency(cache_attr, key, loader):
    """Memoize a MultipleCurrency lookup on the current request for its
    lifetime, so formatting many rows (e.g. a group-by table) doesn't repeat
    the same company/user currency query per cell. Falls back to `loader()`
    with no caching when there's no request in scope (e.g. shell/tests).
    """
    request = get_current_request()
    if request is None:
        return loader()
    cache = getattr(request, cache_attr, None)
    if cache is None:
        cache = {}
        setattr(request, cache_attr, cache)
    if key not in cache:
        cache[key] = loader()
    return cache[key]


def get_currency_display_value(obj, field_name, user):
    """
    Generic helper to format currency fields with user's preferred currency

    Args:
        obj: The model instance
        field_name: Name of the field to display
        user: Current user

    Returns:
        Formatted currency string like "USD 100.00" or "EUR 85.00 (USD 100.00)"
    """
    value = getattr(obj, field_name, None)

    if value is None or value == "":
        return ""

    company = getattr(obj, "company", None)
    if not company and hasattr(user, "company"):
        company = user.company

    if not company:
        return str(value)

    # Get currencies (memoized per request - the same company/user pair is
    # looked up once per cell otherwise, e.g. once per row in a list/table).
    default_currency = _get_cached_currency(
        "_horilla_default_currency_cache",
        company.pk,
        lambda: MultipleCurrency.get_default_currency(company),
    )
    user_currency = _get_cached_currency(
        "_horilla_user_currency_cache",
        getattr(user, "pk", None),
        lambda: MultipleCurrency.get_user_currency(user),
    )

    if not default_currency:
        return str(value)

    # If user currency is same as default or not set, just show default
    if not user_currency or user_currency.pk == default_currency.pk:
        return default_currency.display_with_symbol(value, user=user)

    converted_amount = user_currency.convert_from_default(value)
    user_display = user_currency.display_with_symbol(converted_amount, user=user)
    default_display = default_currency.display_with_symbol(value, user=user)

    return f"{default_display} ({user_display})"


def get_user_field_permission(user, model, field_name):
    """
    Get field permission for a user (checks both user and role permissions)
    Returns: 'readonly', 'readwrite', or 'hidden'
    Default: 'readwrite' if no permission is set

    Priority:
    1. User-specific permission (highest)
    2. Role permission (if user has a role)
    3. Default: 'readwrite' (lowest)

    List/detail renderers call this once per row/action for the same
    (user, model, field_name), so the result is cached on the current
    request (mirrors get_custom_field_definitions's request-cache
    pattern) to avoid repeated FieldPermission queries within a request.
    """
    if user.is_superuser:
        return "readwrite"

    request = get_current_request()
    cache_key = (model, field_name, user.pk) if request is not None else None
    if cache_key is not None:
        cache = getattr(request, "_field_permission_cache", None)
        if cache is None:
            cache = {}
            request._field_permission_cache = cache
        if cache_key in cache:
            return cache[cache_key]

    content_type = HorillaContentType.objects.get_for_model(model)

    user_perm = FieldPermission.objects.filter(
        user=user, content_type=content_type, field_name=field_name
    ).first()

    if user_perm:
        result = user_perm.permission_type
    else:
        result = None
        if hasattr(user, "role") and user.role:
            role_perm = FieldPermission.objects.filter(
                role=user.role, content_type=content_type, field_name=field_name
            ).first()

            if role_perm:
                result = role_perm.permission_type

        if result is None:
            model_defaults = getattr(model, "default_field_permissions", {})
            result = model_defaults.get(field_name, "readwrite")

    if cache_key is not None:
        cache[cache_key] = result

    return result


def field_readonly_hidden_if(model, field_name):
    """
    Build a `hidden_if` callable for an action dict that hides the action
    when `field_name` on `model` is readonly for the current user, per the
    FieldPermission system. Use for actions (e.g. "Change Owner") whose
    modal form edits a field that may be locked independently of the
    action's own model permission (permission/own_permission/owner_field).
    """

    def _hidden_if(_obj):
        request = get_current_request()
        if not request or not request.user.is_authenticated:
            return False
        return get_user_field_permission(request.user, model, field_name) == "readonly"

    return _hidden_if


def get_field_permissions_for_model(user, model):
    """
    Get all field permissions for a model for a specific user
    Returns a dictionary: {field_name: permission_type}

    This is optimized to reduce database queries by fetching
    all permissions at once instead of one by one.

    List/filter/column builders call ``filter_hidden_fields`` (and thus this
    helper) several times for the same (user, model) in a single request, so
    the result is cached on the current request (same pattern as
    ``get_user_field_permission``) to avoid repeating the user+role
    FieldPermission queries.
    """

    if not user.is_authenticated:
        permissions_dict = {}
        model_defaults = getattr(model, "default_field_permissions", {})
        for field_name, default_value in model_defaults.items():
            permissions_dict[field_name] = default_value
        return permissions_dict

    if user.is_superuser:
        return {}

    request = get_current_request()
    cache_key = (model, user.pk) if request is not None else None
    if cache_key is not None:
        cache = getattr(request, "_field_permissions_for_model_cache", None)
        if cache is None:
            cache = {}
            request._field_permissions_for_model_cache = cache
        if cache_key in cache:
            return cache[cache_key]

    content_type = HorillaContentType.objects.get_for_model(model)
    permissions_dict = {}

    user_perms = FieldPermission.objects.filter(user=user, content_type=content_type)
    for perm in user_perms:
        permissions_dict[perm.field_name] = perm.permission_type

    if hasattr(user, "role") and user.role:
        role_perms = FieldPermission.objects.filter(
            role=user.role, content_type=content_type
        )
        for perm in role_perms:
            if perm.field_name not in permissions_dict:
                permissions_dict[perm.field_name] = perm.permission_type

    model_defaults = getattr(model, "default_field_permissions", {})
    for field_name, default_value in model_defaults.items():
        if field_name not in permissions_dict:
            permissions_dict[field_name] = default_value

    if cache_key is not None:
        cache[cache_key] = permissions_dict

    return permissions_dict


def filter_hidden_fields(user, model, fields_list):
    """
    Filter out fields that should be hidden from a list of field names

    Args:
        user: The user to check permissions for
        model: The Django model class
        fields_list: List of field names to filter

    Returns:
        List of field names that are not hidden
    """
    if user.is_superuser:
        return fields_list

    field_permissions = get_field_permissions_for_model(user, model)

    visible_fields = []
    for field_name in fields_list:
        # Check the field itself first
        permission = field_permissions.get(field_name, "readwrite")

        # If it's a display method (get_*_display), always check the base field permission
        # Display methods should inherit the base field's permission
        if field_name.startswith("get_") and field_name.endswith("_display"):
            base_field = field_name.replace("get_", "").replace("_display", "")
            base_permission = field_permissions.get(base_field, "readwrite")
            # Use base field permission (it takes precedence for display methods)
            permission = base_permission

        if permission != "hidden":
            visible_fields.append(field_name)

    return visible_fields


def is_field_editable(user, model, field_name):
    """
    Check if a field is editable (not readonly or hidden) for a user

    Returns:
        True if field has 'readwrite' permission
        False if field has 'readonly' or 'hidden' permission
    """
    permission = get_user_field_permission(user, model, field_name)
    return permission == "readwrite"


def get_editable_fields(user, model, fields_list):
    """
    Get list of fields that are editable by the user

    Args:
        user: The user to check permissions for
        model: The Django model class
        fields_list: List of field names to check

    Returns:
        List of field names that have 'readwrite' permission
    """
    if user.is_superuser:
        return fields_list

    field_permissions = get_field_permissions_for_model(user, model)

    return [
        field_name
        for field_name in fields_list
        if field_permissions.get(field_name, "readwrite") == "readwrite"
    ]


def get_allowed_user_ids(user):
    """
    Return the set of user PKs that `user` is considered an owner for.

    Includes the user themselves plus all users in subordinate roles
    (resolved recursively via the role hierarchy). This is the single
    canonical implementation used by list views, detail views, forms,
    and filterset mixins when enforcing view_own / change_own access.

    Loads the whole role tree for the user's company in one query and
    walks it in memory, instead of issuing a `subroles` + user query per
    role in the hierarchy.

    List views call this once per owner_field action per row (e.g. Edit,
    Change Owner, Duplicate, Delete on the same page), so the result is
    cached on the current request per user, following the same
    request-cache pattern as get_custom_field_definitions, to avoid
    re-walking the role tree and re-querying users on every row.
    """
    request = get_current_request()
    cache = None
    if request is not None:
        cache = getattr(request, "_allowed_user_ids_cache", None)
        if cache is None:
            cache = {}
            request._allowed_user_ids_cache = cache
        if user.pk in cache:
            return cache[user.pk]

    from horilla.auth.models import User

    allowed = {user.pk}
    role = getattr(user, "role", None)
    if role is None:
        if cache is not None:
            cache[user.pk] = allowed
        return allowed

    from .models import Role

    children_by_parent = {}
    for role_id, parent_id in Role.objects.filter(
        company_id=role.company_id
    ).values_list("id", "parent_role_id"):
        children_by_parent.setdefault(parent_id, []).append(role_id)

    subordinate_role_ids = []
    stack = list(children_by_parent.get(role.pk, []))
    while stack:
        role_id = stack.pop()
        subordinate_role_ids.append(role_id)
        stack.extend(children_by_parent.get(role_id, []))

    if subordinate_role_ids:
        allowed.update(
            User.objects.filter(role_id__in=subordinate_role_ids).values_list(
                "pk", flat=True
            )
        )

    if cache is not None:
        cache[user.pk] = allowed

    return allowed


def is_owner(model_class, pk):
    """
    Generic method to check if the current user is the owner of a model instance.
    Uses thread local to get the current user from the request.

    Args:
        model_class: The Django model class (e.g., HorillaUser)
        pk: Primary key of the instance to check

    Returns:
        bool: True if user is an owner, False otherwise
    """
    request = getattr(_thread_local, "request", None)
    user = request.user

    if not user or not user.is_authenticated:
        return False

    # Check if model has OWNER_FIELDS defined
    if not hasattr(model_class, "OWNER_FIELDS") or not model_class.OWNER_FIELDS:
        return False

    try:
        instance = model_class.objects.get(pk=pk)
    except Exception:
        return False

    for field_name in model_class.OWNER_FIELDS:
        try:
            field_value = getattr(instance, field_name, None)

            if field_value is None:
                continue

            # Handle ForeignKey (single user)
            if hasattr(field_value, "pk"):
                if field_value.pk == user.pk:
                    return True

            # Handle ManyToManyField (multiple users)
            elif hasattr(field_value, "filter"):
                if field_value.filter(pk=user.pk).exists():
                    return True

            # Handle direct ID comparison
            elif field_value == user.pk:
                return True

        except (AttributeError, TypeError):
            continue

    return False
