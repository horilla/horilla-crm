"""
Methods for executing automations
"""

# Standard library imports
import logging

# Third-party imports (Django)
from django.utils.dateparse import parse_date, parse_datetime

from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.mail.delivery import MailChannel
from horilla.contrib.notifications.delivery import NotificationChannel
from horilla.contrib.utils.middlewares import _thread_local

# First party imports (Horilla)
from horilla.registry.delivery import get_delivery_channel

# Local imports
from .models import HorillaAutomation, split_delivery_channels

logger = logging.getLogger(__name__)


def _compare_date_comparison_op(op, raw_value, value, is_date_field):
    """Handle exact/gt/lt for date/datetime fields."""
    comp_value = parse_date(value) if is_date_field else parse_datetime(value)
    if comp_value is None:
        return str(raw_value) == value if op == "exact" else False
    if op == "exact":
        return raw_value is not None and raw_value == comp_value
    if op == "gt":
        return raw_value is not None and raw_value > comp_value
    return raw_value is not None and raw_value < comp_value


def _compare_date_between_op(raw_value, value, is_date_field):
    """Handle the "between" operator for date/datetime fields."""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if len(parts) >= 2:
        start_val = parse_date(parts[0]) if is_date_field else parse_datetime(parts[0])
        end_val = parse_date(parts[1]) if is_date_field else parse_datetime(parts[1])
        if start_val is not None and end_val is not None and raw_value is not None:
            return start_val <= raw_value <= end_val
    return False


def _compare_date_operator(op, field_value, raw_value, value, is_date_field):
    """
    Handle the date/datetime "Filter-style operators" block: isnull, isnotnull,
    exact, gt, lt, between. Returns None if op is not one of these (fall through).
    """
    if op == "isnull":
        return field_value in (None, "") or (raw_value is None)
    if op == "isnotnull":
        return raw_value is not None
    if op in ("exact", "gt", "lt"):
        return _compare_date_comparison_op(op, raw_value, value, is_date_field)
    if op == "between":
        return _compare_date_between_op(raw_value, value, is_date_field)
    return None


def _compare_numeric_none_aware(
    field_num, value_num, if_both_none, if_either_none, cmp
):
    if field_num is None and value_num is None:
        return if_both_none
    if field_num is None or value_num is None:
        return if_either_none
    return cmp(field_num, value_num)


def _compare_numeric_exact(op, field_value, value):
    """
    Handle the numeric exact/ne shortcut block. Returns None to signal
    fall-through to string comparison (matching the original try/except
    ValueError/TypeError fallback behavior).
    """
    try:
        # Convert both to float for comparison (handles Decimal, Float, Integer)
        field_num = float(field_value) if field_value else None
        value_num = float(value) if value else None

        # Preserved as-is: the guard is `op in ["exact", "ne"]` but this checks "equals"
        if op == "equals":
            return _compare_numeric_none_aware(
                field_num, value_num, True, False, lambda a, b: a == b
            )
        if op == "ne":
            return _compare_numeric_none_aware(
                field_num, value_num, False, True, lambda a, b: a != b
            )
    except (ValueError, TypeError):
        # If conversion fails, fall back to string comparison
        pass
    return None


def _compare_text_operator(op, field_value, value):
    if op == "exact":
        return field_value == value
    if op == "ne":
        return field_value != value
    if op == "icontains":
        return value.lower() in field_value.lower()
    if op == "not_contains":
        return value.lower() not in field_value.lower()
    if op == "istartswith":
        return field_value.lower().startswith(value.lower())
    return field_value.lower().endswith(value.lower())


def _compare_numeric_generic(op, field_value, value):
    try:
        if op == "gt":
            return float(field_value) > float(value)
        if op == "gte":
            return float(field_value) >= float(value)
        if op == "lt":
            return float(field_value) < float(value)
        return float(field_value) <= float(value)
    except (ValueError, TypeError):
        return False


def _compare_generic_operator(op, field_value, value):
    """
    Handle the final string/numeric fallback block: exact, ne, icontains,
    not_contains, istartswith, iendswith, gt, gte, lt, lte, isnull, isnotnull.
    """
    if op in ("exact", "ne", "icontains", "not_contains", "istartswith", "iendswith"):
        return _compare_text_operator(op, field_value, value)
    if op in ("gt", "gte", "lt", "lte"):
        return _compare_numeric_generic(op, field_value, value)
    if op == "isnull":
        return not field_value or field_value.strip() == ""
    if op == "isnotnull":
        return bool(field_value and field_value.strip())
    return False


def evaluate_condition(condition, instance):
    """
    Evaluate a single condition against an instance.

    Args:
        condition: AutomationCondition instance
        instance: Model instance to evaluate against

    Returns:
        bool: True if condition is met, False otherwise
    """
    try:
        # Fields contributed by other apps (e.g. custom fields) aren't model
        # columns; the app that owns the field resolves the value.
        from horilla.contrib.generics.forms.condition_fields import (
            evaluate_extension_condition,
        )

        handled, extension_result = evaluate_extension_condition(
            condition.field,
            instance,
            condition.operator,
            condition.value,
            _compare_generic_operator,
        )
        if handled:
            return extension_result

        # Get the field value from the instance
        field_value = getattr(instance, condition.field, None)

        # Get the field object to determine its type
        field = instance._meta.get_field(condition.field)

        # Check if field is numeric / date / datetime
        is_numeric_field = False
        is_date_field = False
        is_datetime_field = False
        field_type = None
        if hasattr(field, "get_internal_type"):
            field_type = field.get_internal_type()
            numeric_types = [
                "IntegerField",
                "BigIntegerField",
                "SmallIntegerField",
                "PositiveIntegerField",
                "PositiveSmallIntegerField",
                "DecimalField",
                "FloatField",
            ]
            is_numeric_field = field_type in numeric_types
            is_date_field = field_type == "DateField"
            is_datetime_field = field_type == "DateTimeField"

        # Handle ForeignKey fields - get the ID
        if hasattr(field, "related_model"):
            # It's a ForeignKey
            if field_value:
                field_value = (
                    str(field_value.pk)
                    if hasattr(field_value, "pk")
                    else str(field_value)
                )
            else:
                field_value = ""
        else:
            # Convert field_value to string for comparison (unless we'll use date/datetime comparison)
            if field_value is None:
                field_value = ""
            else:
                field_value = str(field_value)

        value = condition.value or ""
        op = condition.operator
        result = None

        # Filter-style operators for date/datetime: exact, gt, lt, between, isnull, isnotnull
        if is_date_field or is_datetime_field:
            raw_value = getattr(instance, condition.field, None)
            if op in ("isnull", "isnotnull", "exact", "gt", "lt", "between"):
                result = _compare_date_operator(
                    op, field_value, raw_value, value, is_date_field
                )

        # For numeric fields with equals/not_equals, do numeric comparison
        if result is None and is_numeric_field and op in ["exact", "ne"]:
            result = _compare_numeric_exact(op, field_value, value)

        # Perform comparison based on operator (string comparison for non-numeric or fallback)
        if result is None:
            result = _compare_generic_operator(op, field_value, value)

        return result

    except Exception as e:
        logger.error("Error evaluating condition %s: %s", condition, str(e))
        return False


def evaluate_automation_conditions(automation, instance):
    """
    Evaluate all conditions for an automation against an instance.

    Args:
        automation: HorillaAutomation instance
        instance: Model instance to evaluate against

    Returns:
        bool: True if all conditions are met, False otherwise
    """
    conditions = automation.conditions.all().order_by("order", "created_at")

    if not conditions.exists():
        # No conditions means always execute
        return True

    result = None
    previous_logical_op = None

    for condition in conditions:
        condition_result = evaluate_condition(condition, instance)

        if result is None:
            # First condition
            result = condition_result
        else:
            # Apply logical operator
            if previous_logical_op == "or":
                result = result or condition_result
            else:  # default to "and"
                result = result and condition_result

        previous_logical_op = condition.logical_operator

    return result if result is not None else True


class _PreSaveSnapshotProxy:
    """
    Thin wrapper around a model instance that reports pre-save values for
    whichever fields have a "_old_<field>" attribute stashed on the instance
    falling back to the  instance's current value for any field without a snapshot.
    """

    def __init__(self, instance):
        self._instance = instance

    def __getattr__(self, name):
        old_name = f"_old_{name}"
        if hasattr(self._instance, old_name):
            return getattr(self._instance, old_name)
        return getattr(self._instance, name)

    @property
    def _meta(self):
        return self._instance._meta

    @property
    def pk(self):
        return self._instance.pk


def _conditions_already_met_before_save(automation, instance):
    """
    Return whether ``automation``'s conditions were already satisfied by
    ``instance`` BEFORE this save, using any "_old_<field>" snapshot
    attributes available on the instance. If no snapshot is available for a
    condition's field, this conservatively returns False (i.e. treat it as
    not previously met, so the automation still fires) rather than guessing.
    """
    conditions = automation.conditions.all()
    if not conditions.exists():
        return False

    has_snapshot = any(
        hasattr(instance, f"_old_{condition.field}") for condition in conditions
    )
    if not has_snapshot:
        return False

    return evaluate_automation_conditions(automation, _PreSaveSnapshotProxy(instance))


def resolve_mail_recipients(mail_to, instance, user):
    """
    Email addresses for the mail_to field, as the mail channel resolves them.

    Kept for callers outside Automations (e.g. Cadences); the logic lives in
    ``MailChannel.resolve_recipients``.
    """
    return MailChannel().resolve_recipients(mail_to, instance, user)


def resolve_notification_users(mail_to, instance, user):
    """
    Users for the mail_to field, as the notification channel resolves them.

    The logic lives in ``NotificationChannel.resolve_recipients``.
    """
    return NotificationChannel().resolve_recipients(mail_to, instance, user)


def execute_automation(automation, instance, user=None, trigger_type="on_create"):
    """
    Execute an automation for a given instance.

    Args:
        automation: HorillaAutomation instance
        instance: Model instance that triggered the automation
        user: User who triggered the automation (optional)
        trigger_type: Type of trigger ('on_create', 'on_update', 'on_delete')
    """
    try:
        # Check if automation trigger matches
        # Handle 'on_create_or_update' option - it should trigger for both create and update
        if automation.trigger == "on_create_or_update":
            if trigger_type not in ["on_create", "on_update"]:
                return
        elif automation.trigger != trigger_type:
            return

        # Evaluate conditions (skip for delete operations if instance is minimal)
        # For delete operations, instance might be a minimal representation
        skip_conditions = (
            trigger_type == "on_delete"
            and hasattr(instance, "__class__")
            and instance.__class__.__name__ == "DeletedInstance"
        )

        if not skip_conditions:
            if not evaluate_automation_conditions(automation, instance):
                logger.info(
                    "Automation %s conditions not met for instance %s",
                    automation.title,
                    instance,
                )
                return

            # Edge-trigger opt-in: an automation can set
            # additional_info["edge_trigger_only"] = True to only fire when a
            # condition newly becomes true on this save, instead of on every
            # subsequent edit to a record that already qualified (e.g. CRM's
            # "Big Deal Alert" wants this; most automations don't and leave
            # the flag unset). This only applies to "on_update", and only
            # when the model exposes a pre-save snapshot via the
            # "_old_<field>" attribute convention (see
            # horilla_crm/opportunities/signals.py for an example); any
            # automation not opting in is completely unaffected.
            if (
                trigger_type == "on_update"
                and automation.additional_info
                and automation.additional_info.get("edge_trigger_only")
                and _conditions_already_met_before_save(automation, instance)
            ):
                logger.info(
                    "Automation %s already matched before this save for "
                    "instance %s - skipping re-alert",
                    automation.title,
                    instance,
                )
                return

        # Get user from thread local if not provided
        if not user:
            request = getattr(_thread_local, "request", None)
            if request:
                user = getattr(request, "user", None)

        # Prepare context for template rendering
        request = getattr(_thread_local, "request", None)

        # Resolve an actor to format date/time fields with (e.g. due_datetime)
        # in a real timezone instead of raw UTC. Scheduled automations run with
        # no request/user, so fall back to the instance's own
        # owner/updated_by/created_by, same as MailChannel.send does.
        # Template filters like `user_datetime_format` read the acting
        # user/company from `_thread_local.request`, not from this context
        # dict, so channels that render templates outside of a real request
        # (e.g. NotificationChannel.send) must install a stand-in request
        # built from this same actor/company before rendering.
        actor = (
            user
            or getattr(instance, "updated_by", None)
            or getattr(instance, "created_by", None)
            or getattr(automation, "updated_by", None)
            or getattr(automation, "created_by", None)
        )
        active_company = getattr(request, "active_company", None) or (
            getattr(actor, "company", None) if actor else None
        )

        context = {
            "instance": instance,
            "user": actor,
            "self": user,  # 'self' refers to the user who triggered
            "active_company": active_company,
        }

        if request:
            context["request"] = request

        # One send per selected channel, in stored order. A row still holding
        # the old "both" sends through mail, then notification.
        for key in split_delivery_channels(automation.delivery_channel):
            channel = get_delivery_channel(key)
            if channel is None:
                # The app that registered the channel is gone: skip this key
                # only, the other selected channels still send. This runs
                # from a signal, so it must not fail the save.
                logger.error(
                    "Automation %s delivery channel %s is not registered",
                    automation.title,
                    key,
                )
                continue
            recipients = channel.resolve_recipients(automation.mail_to, instance, user)
            recipients = channel.add_also_sent_to(
                recipients, automation.also_sent_to.all()
            )
            if not recipients:
                logger.warning(
                    "Automation %s channel %s has no recipients",
                    automation.title,
                    key,
                )
                continue
            try:
                channel.send(automation, instance, recipients, context, user)
            except Exception as e:
                logger.error(
                    "Automation %s channel %s failed to send: %s",
                    automation.title,
                    key,
                    str(e),
                    exc_info=True,
                )

    except Exception as e:
        logger.error(
            "Error executing automation %s: %s", automation.title, str(e), exc_info=True
        )


def trigger_automations(instance, trigger_type="on_create", user=None):
    """
    Trigger all applicable automations for an instance.

    Args:
        instance: Model instance that triggered the automation
        trigger_type: Type of trigger ('on_create', 'on_update', 'on_delete')
        user: User who triggered the automation (optional)
    """
    try:
        content_type = HorillaContentType.objects.get_for_model(instance)

        # Get company from instance if it has one
        company = None
        if hasattr(instance, "company"):
            company = instance.company

        # If no company on instance, try to get from thread local request
        if not company:
            request = getattr(_thread_local, "request", None)
            if request:
                company = getattr(request, "active_company", None)

        # Build query filter
        # For 'on_create' or 'on_update', also include 'on_create_or_update' automations
        if trigger_type in ["on_create", "on_update"]:
            filter_kwargs = {
                "model": content_type,
                "trigger__in": [trigger_type, "on_create_or_update"],
                "is_active": True,  # Only active automations
            }
        else:
            filter_kwargs = {
                "model": content_type,
                "trigger": trigger_type,
                "is_active": True,  # Only active automations
            }

        # Filter by company if available
        if company:
            filter_kwargs["company"] = company

        automations = HorillaAutomation.objects.filter(**filter_kwargs)

        for automation in automations:
            try:
                execute_automation(automation, instance, user, trigger_type)
            except Exception as e:
                logger.error(
                    "Error executing automation %s: %s",
                    automation.title,
                    str(e),
                    exc_info=True,
                )
                continue

    except Exception as e:
        logger.error("Error triggering automations: %s", str(e), exc_info=True)
