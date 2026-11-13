"""Template tags for action permissions and filtering (including intermediate models)."""

# Standard library imports
import logging

# First party imports (Horilla)
from horilla.apps import apps

# Local imports
from ._registry import register

logger = logging.getLogger(__name__)


def get_app_labels_from_context(related_obj, request, action=None):
    """
    Dynamically discover app labels from context.

    Args:
        related_obj: The related model instance
        request: The request object
        action: Optional action dict that may contain intermediate_app_label

    Returns:
        list: Ordered list of app labels to try (most likely first)
    """

    app_labels = []
    seen = set()

    if action and action.get("intermediate_app_label"):
        app_label = action.get("intermediate_app_label")
        if app_label not in seen:
            app_labels.append(app_label)
            seen.add(app_label)

    if related_obj and hasattr(related_obj, "_meta"):
        app_label = related_obj._meta.app_label
        if app_label not in seen:
            app_labels.append(app_label)
            seen.add(app_label)

    if request and hasattr(request, "resolver_match") and request.resolver_match:
        view_func = request.resolver_match.func
        if hasattr(view_func, "view_class"):
            view_class = view_func.view_class
            if hasattr(view_class, "model") and view_class.model:
                app_label = view_class.model._meta.app_label
                if app_label not in seen:
                    app_labels.append(app_label)
                    seen.add(app_label)

    if request and hasattr(request, "resolver_match") and request.resolver_match:
        url_name = request.resolver_match.url_name
        if url_name:
            if ":" in url_name:
                app_name = url_name.split(":")[0]
                if app_name not in seen:
                    app_labels.append(app_name)
                    seen.add(app_name)
            elif "_" in url_name:
                app_name = url_name.split("_")[0]
                if app_name not in seen:
                    app_labels.append(app_name)
                    seen.add(app_name)

        namespace = getattr(request.resolver_match, "namespace", None)
        if namespace and namespace not in seen:
            app_labels.append(namespace)
            seen.add(namespace)

    for app_config in apps.get_app_configs():
        if app_config.label not in seen:
            app_labels.append(app_config.label)
            seen.add(app_config.label)

    return app_labels


def get_intermediate_instance(action, related_obj, request):
    """
    Get the intermediate model instance based on action config.

    Args:
        action: Action dictionary with intermediate_model config
        related_obj: The related model instance (e.g., Department)
        request: The request object to get parent object ID

    Returns:
        The intermediate model instance or None
    """

    intermediate_model_name = action.get("intermediate_model")
    if not intermediate_model_name:
        return None

    try:
        parent_id = None
        if hasattr(request, "resolver_match") and request.resolver_match:
            parent_id = request.resolver_match.kwargs.get("pk")
        if not parent_id:
            parent_id = request.GET.get("object_id")

        if not parent_id:
            return None

        app_labels_to_try = get_app_labels_from_context(related_obj, request, action)

        intermediate_model = None
        for app_label in app_labels_to_try:
            try:
                intermediate_model = apps.get_model(app_label, intermediate_model_name)
                logger.debug(
                    "Found intermediate model '%s' in app '%s'",
                    intermediate_model_name,
                    app_label,
                )
                break
            except LookupError:
                continue

        if not intermediate_model:
            logger.warning(
                "Could not find intermediate model '%s' in any of these apps: %s",
                intermediate_model_name,
                app_labels_to_try[:5],
            )
            return None

        intermediate_field_name = action.get("intermediate_field")
        parent_field_name = action.get("parent_field")

        if not intermediate_field_name or not parent_field_name:
            logger.error(
                "Action missing 'intermediate_field' or 'parent_field' configuration"
            )
            return None

        filter_kwargs = {
            intermediate_field_name: related_obj,
            f"{parent_field_name}_id": parent_id,
        }

        intermediate_obj = intermediate_model.objects.filter(**filter_kwargs).first()

        if not intermediate_obj:
            logger.debug(
                "No %s found with filters: %s", intermediate_model_name, filter_kwargs
            )

        return intermediate_obj

    except Exception as e:
        logger.error("Error getting intermediate instance: %s", e, exc_info=True)
        return None


def has_action_permission(action, context):
    """
    Check if user has permission to perform an action on an object.
    Supports both direct object permissions and intermediate model permissions.

    Args:
        action: Action dict with permission config
        context: Dict with 'user', 'object', and optionally 'intermediate_object'

    Returns:
        bool: True if user has permission
    """
    user = context.get("user")
    obj = context.get("object")

    perm = action.get("permission")
    own_perm = action.get("own_permission")
    owner_field = action.get("owner_field")
    owner_method = action.get("owner_method")

    perms = action.get("permissions", [])
    perm_logic = action.get("permission_logic", "OR")

    if not perm and not own_perm and not owner_field or user.is_superuser:
        return True

    intermediate_config = action.get("intermediate_model")

    target_obj = obj
    if intermediate_config:
        intermediate_obj = context.get("intermediate_object")
        if intermediate_obj:
            target_obj = intermediate_obj

    if own_perm and not owner_field and not owner_method:
        raise ValueError(
            f"Action '{action.get('action')}' must define BOTH "
            "'own_permission' and ('owner_field' OR 'owner_method')."
        )

    if owner_field and owner_method:
        raise ValueError(
            f"Action '{action.get('action')}' cannot define BOTH "
            "'owner_field' AND 'owner_method'. Use only one."
        )

    if perm and user.has_perm(perm):
        return True

    if perms:
        perm_checks = [user.has_perm(p) for p in perms]

        if perm_logic.upper() == "OR":
            if any(perm_checks):
                return True
        elif perm_logic.upper() == "AND":
            if all(perm_checks):
                return True
        else:
            raise ValueError(
                f"Invalid permission_logic '{perm_logic}'. Must be 'OR' or 'AND'."
            )

    if own_perm and target_obj:
        if owner_method:
            if hasattr(target_obj, owner_method):
                method = getattr(target_obj, owner_method)
                if callable(method):
                    # owner_method grants (e.g. per-record team access levels)
                    # are an explicit, granular permission in their own right,
                    # not just an ownership marker -- unlike owner_field, they
                    # don't additionally require the role-level own_permission.
                    if method(user):
                        return True
            else:
                raise ValueError(
                    f"Object {target_obj.__class__.__name__} does not have method '{owner_method}'"
                )

        elif owner_field:
            from horilla.contrib.core.utils import get_allowed_user_ids

            allowed_ids = get_allowed_user_ids(user)
            owner_fields = (
                owner_field if isinstance(owner_field, list) else [owner_field]
            )

            for field in owner_fields:
                owner = getattr(target_obj, field, None)
                if owner is not None:
                    if hasattr(owner, "all"):
                        if any(m.pk in allowed_ids for m in owner.all()):
                            if user.has_perm(own_perm):
                                return True
                    elif hasattr(owner, "pk"):
                        if owner.pk in allowed_ids and user.has_perm(own_perm):
                            return True
                    elif owner in allowed_ids and user.has_perm(own_perm):
                        return True

    return False


@register.simple_tag(takes_context=True)
def filter_actions_by_permission(context, actions, data):
    """
    Return only the actions the user is authorized to perform on ``data``,
    excluding any whose `hidden_if(data)` callable returns True.
    Actions without any permission config are always shown as enabled.

    Menu-style renderers (dropdown/kebab lists in detail_view.html,
    card_view_cards.html, kanban_items.html) render straight off this
    result without going through render_action_button, so hidden_if must
    be honored here too — not just in render_action_button — or a hidden
    action would still appear in those menus.
    """
    request = context.get("request")
    user = request.user if request else None

    if not user:
        return []

    result = []

    for action in actions:
        hidden_if = action.get("hidden_if")
        if callable(hidden_if) and hidden_if(data):
            continue

        action_context = {
            "user": user,
            "object": data,
        }

        intermediate_model_name = action.get("intermediate_model")
        if intermediate_model_name:
            intermediate_obj = get_intermediate_instance(action, data, request)
            if intermediate_obj:
                action_context["intermediate_object"] = intermediate_obj

        if has_action_permission(action, action_context):
            result.append(action)

    return result


@register.simple_tag(takes_context=True)
def resolve_row_actions(context, actions, data, queryset):
    """
    Return every action not explicitly hidden for ``data``, decorated so
    render_action_button shows it disabled when the user isn't authorized
    for this particular row.

    An action is dropped entirely (not even shown disabled) only when no
    object in ``queryset`` grants it to the current user -- e.g. a Delete
    icon nobody in the current page can ever use. Otherwise, if at least
    one row in the queryset allows it, the action is shown on every row,
    disabled on rows lacking permission, so the action column stays
    visually consistent instead of icons shifting per row.
    """
    request = context.get("request")
    user = request.user if request else None

    if not user or not actions:
        return []

    result = []
    for action in actions:
        hidden_if = action.get("hidden_if")
        if callable(hidden_if) and hidden_if(data):
            continue

        action_context = {"user": user, "object": data}
        intermediate_model_name = action.get("intermediate_model")
        if intermediate_model_name:
            intermediate_obj = get_intermediate_instance(action, data, request)
            if intermediate_obj:
                action_context["intermediate_object"] = intermediate_obj

        if has_action_permission(action, action_context):
            result.append(action)
            continue

        if not _any_row_allows(action, user, queryset, request):
            continue

        disabled_action = dict(action)
        disabled_action["disabled_if"] = lambda obj: True
        result.append(disabled_action)

    return result


def _any_row_allows(action, user, queryset, request):
    """True if at least one object in ``queryset`` grants ``action`` to ``user``.

    Called once per row for any action the row itself doesn't pass (see
    resolve_row_actions), but the answer only depends on (action, queryset,
    user) -- the same triple for every row in one render -- so it's cached
    on the request to avoid rescanning the whole page queryset per row.
    """
    if user.is_superuser or not (
        action.get("permission")
        or action.get("own_permission")
        or action.get("owner_field")
        or action.get("owner_method")
    ):
        return True

    if action.get("permission") and user.has_perm(action["permission"]):
        return True

    if queryset is None:
        return False

    cache = None
    cache_key = None
    if request is not None:
        cache = getattr(request, "_any_row_allows_cache", None)
        if cache is None:
            cache = {}
            request._any_row_allows_cache = cache
        cache_key = (id(action), id(queryset), user.pk)
        if cache_key in cache:
            return cache[cache_key]

    result = False
    for obj in queryset:
        action_context = {"user": user, "object": obj}
        intermediate_model_name = action.get("intermediate_model")
        if intermediate_model_name:
            intermediate_obj = get_intermediate_instance(action, obj, request)
            if intermediate_obj:
                action_context["intermediate_object"] = intermediate_obj
        if has_action_permission(action, action_context):
            result = True
            break

    if cache_key is not None:
        cache[cache_key] = result

    return result


def _action_shown_on_any_row(action, user, queryset, request):
    """True if ``action`` would render on at least one row of ``queryset``.

    Mirrors what the row cells do: a row hides the action when ``hidden_if``
    is true for it, and otherwise shows it when the user is authorized for
    that row (see ``_any_row_allows`` for the page-wide, cached check).
    """
    hidden_if = action.get("hidden_if")
    if callable(hidden_if) and queryset is not None:
        if all(hidden_if(obj) for obj in queryset):
            return False
    return _any_row_allows(action, user, queryset, request)


@register.simple_tag(takes_context=True)
def has_any_actions_for_queryset(context, actions, queryset):
    """
    Decide whether the Actions column header should be shown: True only when
    at least one row in ``queryset`` would actually render one of ``actions``
    for the current user.

    Holding a permission is not enough on its own. A user with only an
    ``own_permission`` (e.g. ``delete_own``) sees no action on records they
    don't own, so every row cell would be empty; the header must be hidden in
    that case too, otherwise an empty "Actions" column is left behind.

    Args:
        context: template context with request
        actions: list of action dicts
        queryset: the page's objects, checked per row for ownership,
            ``owner_method`` and ``hidden_if``

    Returns:
        bool: True if at least one action is shown on at least one row
    """
    request = context.get("request")
    user = request.user if request else None

    if not user or not actions:
        return False

    return any(
        _action_shown_on_any_row(action, user, queryset, request) for action in actions
    )


@register.simple_tag(takes_context=True)
def col_attr_has_permission(context, col_attrs_for_field, data):
    """
    Return True if the user has permission to use this col_attr link on ``data``.

    Unlike filter_actions_by_permission (which always returns a non-empty list),
    this tag returns a plain boolean so the template can decide whether to render
    the HTMX link attrs or leave the cell as plain text.
    """
    request = context.get("request")
    user = request.user if request else None
    if not user:
        return False
    if not isinstance(col_attrs_for_field, dict):
        return True
    action_context = {"user": user, "object": data}
    return has_action_permission(col_attrs_for_field, action_context)
