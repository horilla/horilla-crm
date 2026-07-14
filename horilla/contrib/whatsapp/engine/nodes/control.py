"""
Control-flow node handlers: condition, wait.
"""

# Standard library imports
import logging
from datetime import datetime, timedelta

# Third-party imports (Django)
from django.utils import timezone

# Local imports
from ..base import NodeHandler, NodeResult
from ..interpolation import _resolve as resolve_token_path
from ..interpolation import interpolate
from ..registry import register_node

logger = logging.getLogger(__name__)

_TOKEN_NAMESPACES = ("variables.", "record.", "conversation.")


def _get_field_value(session, field_path):
    """
    Resolve a condition rule's `field` against the session. A path
    prefixed with a known token namespace (`variables.`, `record.`,
    `conversation.`) resolves the same way `{{...}}` value tokens do
    elsewhere in this flow (see interpolation.py); a bare, unprefixed path
    (e.g. `is_convert`) is treated as a `record.` field for backward
    compatibility with rules written before namespaces were supported here.
    """
    if field_path.startswith(_TOKEN_NAMESPACES):
        value = resolve_token_path(field_path, session)
        return value if value != "" else None

    record = session.related_to
    if record is None:
        return None
    value = record
    try:
        for part in field_path.split("."):
            value = getattr(value, part)
        return value
    except AttributeError:
        return None


def _eval_rule(rule, session):
    """Evaluate a single condition rule dict against the session; return bool."""
    rule_type = rule.get("type")

    if rule_type == "record_exists":
        return session.related_to is not None
    if rule_type == "record_not_exists":
        return session.related_to is None
    if rule_type == "variable_exists":
        return rule.get("variable") in (session.variables or {})
    if rule_type == "button_selected":
        return (session.variables or {}).get("_last_reply_id") == interpolate(
            rule.get("value", ""), session
        )
    if rule_type == "list_selected":
        return (session.variables or {}).get("_last_reply_id") == interpolate(
            rule.get("value", ""), session
        )

    field_value = _get_field_value(session, rule.get("field", ""))
    compare_value = interpolate(rule.get("value", ""), session)

    if rule_type == "field_equals":
        return str(field_value).casefold() == str(compare_value).casefold()
    if rule_type == "field_not_equals":
        return str(field_value).casefold() != str(compare_value).casefold()
    if rule_type == "field_contains":
        return str(compare_value).casefold() in str(field_value or "").casefold()
    if rule_type in ("field_gt", "field_lt", "date_before", "date_after"):
        try:
            if rule_type in ("date_before", "date_after"):
                left = _as_datetime(field_value)
                right = _as_datetime(compare_value)
            else:
                left = float(field_value)
                right = float(compare_value)
        except (TypeError, ValueError):
            return False
        if rule_type in ("field_gt",):
            return left > right
        if rule_type == "field_lt":
            return left < right
        if rule_type == "date_before":
            return left < right
        if rule_type == "date_after":
            return left > right

    logger.warning("Unknown condition rule type: %s", rule_type)
    return False


def _as_datetime(value):
    """Best-effort coercion of a value to a datetime for date comparisons."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


@register_node("condition")
class ConditionNode(NodeHandler):
    """
    Evaluates branches (each a list of AND-ed rules) top-to-bottom; the
    first branch whose rules all pass selects the outgoing edge via its
    `handle`. Falls back to `default_handle` if nothing matches.
    """

    def execute(self, session, node):
        config = node.config
        for branch in config.get("branches", []):
            rules = branch.get("rules", [])
            if rules and all(_eval_rule(rule, session) for rule in rules):
                return NodeResult(status="advance", source_handle=branch["handle"])

        default_handle = config.get("default_handle")
        if default_handle:
            return NodeResult(status="advance", source_handle=default_handle)

        return NodeResult(
            status="failed",
            error="No condition branch matched and no default_handle set.",
        )


@register_node("wait")
class WaitNode(NodeHandler):
    """
    Pauses the flow for a fixed duration, backed by a WhatsAppScheduledResume
    row that a Celery beat task resolves later (see celery_schedules.py).
    """

    def execute(self, session, node):
        from ...models import WhatsAppScheduledResume

        duration_seconds = node.config.get("duration_seconds", 0)
        resume_at = timezone.now() + timedelta(seconds=duration_seconds)
        WhatsAppScheduledResume.objects.create(
            session=session,
            resume_at=resume_at,
            company=session.conversation.company,
        )
        return NodeResult(status="wait")

    def resume(self, session, node, reply_text, reply_id, flow_answers=None):
        """Called by the Celery resume task once `resume_at` has passed."""
        return NodeResult(status="advance")
