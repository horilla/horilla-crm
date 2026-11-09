"""
Workflow execution engine: condition evaluation and action executors.
"""

# Standard library imports
import logging
import sys
import threading

# Third-party imports (Django)
from django.db.models import Q
from django.template import engines

from horilla.auth.models import User
from horilla.contrib.automations.tasks import MockRequest as _WorkflowMockRequest
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.mail.models import (
    HorillaMail,
    HorillaMailConfiguration,
    HorillaMailTemplate,
)
from horilla.contrib.mail.services import HorillaMailManager
from horilla.contrib.notifications.methods import create_notification
from horilla.contrib.utils.middlewares import _thread_local
from horilla.db import connection, transaction

# First party imports (Horilla)
from horilla.utils import timezone

# Local imports
from .action_types import (
    TEMPLATE_MAIL,
    TEMPLATE_NOTIFICATION,
    get_action_channel,
    get_channel_template_kind,
)
from .models import ScheduledWorkflowExecution, WorkflowRule

logger = logging.getLogger(__name__)


def is_running_migrations():
    """Return True when Django migrations are running (tables may not exist yet)."""
    if "migrate" in sys.argv:
        return True
    try:
        db_table_names = connection.introspection.table_names()
        if "auditlog_logentry" not in db_table_names:
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------

# Sentinel meaning "this helper does not handle this operator/type combination,
# fall through to the next comparison stage" (distinct from a real True/False result).
_UNHANDLED = object()


def _compare_date_between(raw, value, parse):
    """Evaluate the date/datetime 'between' operator."""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if len(parts) < 2:
        return False
    s, e = parse(parts[0]), parse(parts[1])
    return s is not None and e is not None and raw is not None and s <= raw <= e


def _compare_date_operator(op, raw, value, parse):
    """Evaluate isnull/isnotnull/exact/gt/lt/between for date/datetime fields."""
    handlers = {
        "isnull": lambda: raw is None,
        "isnotnull": lambda: raw is not None,
        "exact": lambda: (
            raw is not None and raw == parse(value)
            if parse(value)
            else str(raw) == value
        ),
        "gt": lambda: (
            raw is not None and raw > parse(value) if parse(value) else False
        ),
        "lt": lambda: (
            raw is not None and raw < parse(value) if parse(value) else False
        ),
        "between": lambda: _compare_date_between(raw, value, parse),
    }
    return handlers.get(op, lambda: _UNHANDLED)()


def _compare_numeric_exact(op, field_value, value):
    """Evaluate the numeric exact/ne shortcut; falls through on bad input."""
    try:
        fn = float(field_value) if field_value else None
        vn = float(value) if value else None
        return fn == vn if op == "exact" else fn != vn
    except (ValueError, TypeError):
        return _UNHANDLED


def _compare_string_relational(op, field_value, value):
    """Evaluate the gt/gte/lt/lte string-as-numeric operators."""
    try:
        fv, v = float(field_value), float(value)
    except (ValueError, TypeError):
        return False
    return {"gt": fv > v, "gte": fv >= v, "lt": fv < v, "lte": fv <= v}[op]


def _compare_string_between(field_value, value):
    """Evaluate the string 'between' operator (numeric range on the raw strings)."""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if len(parts) < 2:
        return False
    try:
        return float(parts[0]) <= float(field_value) <= float(parts[1])
    except (ValueError, TypeError):
        return False


def _compare_string_operator(op, field_value, value):
    """Evaluate the string/generic operators (exact, ne, icontains, gt, between, ...)."""
    handlers = {
        "exact": lambda: field_value == value,
        "ne": lambda: field_value != value,
        "icontains": lambda: value.lower() in field_value.lower(),
        "not_contains": lambda: value.lower() not in field_value.lower(),
        "istartswith": lambda: field_value.lower().startswith(value.lower()),
        "iendswith": lambda: field_value.lower().endswith(value.lower()),
        "gt": lambda: _compare_string_relational(op, field_value, value),
        "gte": lambda: _compare_string_relational(op, field_value, value),
        "lt": lambda: _compare_string_relational(op, field_value, value),
        "lte": lambda: _compare_string_relational(op, field_value, value),
        "isnull": lambda: not field_value or field_value.strip() == "",
        "isnotnull": lambda: bool(field_value and field_value.strip()),
        "between": lambda: _compare_string_between(field_value, value),
    }
    return handlers.get(op, lambda: False)()


def evaluate_workflow_condition(condition, instance):
    """
    Evaluate a single WorkflowCondition against a model instance.

    Returns True if the condition is satisfied, False otherwise.
    """
    try:
        from horilla.contrib.generics.forms.condition_fields import (
            evaluate_extension_condition,
        )

        # Fields contributed by other apps (e.g. custom fields) aren't columns.
        handled, extension_result = evaluate_extension_condition(
            condition.field,
            instance,
            condition.operator,
            condition.value,
            _compare_string_operator,
        )
        if handled:
            return extension_result

        field_value = getattr(instance, condition.field, None)

        try:
            field = instance._meta.get_field(condition.field)
        except Exception:
            field = None

        is_numeric = False
        is_date = False
        is_datetime = False

        if field and hasattr(field, "get_internal_type"):
            ftype = field.get_internal_type()
            is_numeric = ftype in (
                "IntegerField",
                "BigIntegerField",
                "SmallIntegerField",
                "PositiveIntegerField",
                "PositiveSmallIntegerField",
                "DecimalField",
                "FloatField",
            )
            is_date = ftype == "DateField"
            is_datetime = ftype == "DateTimeField"

        # FK → use pk as string. All Django fields have related_model attr; check it is not None.
        if field and getattr(field, "related_model", None) is not None:
            field_value = (
                str(field_value.pk)
                if field_value and hasattr(field_value, "pk")
                else ""
            )
        else:
            field_value = "" if field_value is None else str(field_value)

        value = condition.value or ""
        op = condition.operator
        result = _UNHANDLED

        # Date / datetime comparisons
        if is_date or is_datetime:
            from django.utils.dateparse import parse_date, parse_datetime

            raw = getattr(instance, condition.field, None)
            parse = parse_date if is_date else parse_datetime
            result = _compare_date_operator(op, raw, value, parse)

        # Numeric equality shortcuts
        if result is _UNHANDLED and is_numeric and op in ("exact", "ne"):
            result = _compare_numeric_exact(op, field_value, value)

        # String operators
        if result is _UNHANDLED:
            result = _compare_string_operator(op, field_value, value)

        return result

    except Exception as exc:
        logger.error("Error evaluating workflow condition %s: %s", condition, exc)
        return False


def evaluate_workflow_conditions(rule, instance):
    """
    Evaluate all conditions for a WorkflowRule against an instance.

    Returns True if the overall result passes (AND/OR chain), or if there are no conditions.
    """
    conditions = rule.conditions.all().order_by("order", "created_at")

    if not conditions.exists():
        return True

    result = None
    previous_logical_op = None

    for condition in conditions:
        cond_result = evaluate_workflow_condition(condition, instance)

        if result is None:
            result = cond_result
        elif previous_logical_op == "or":
            result = result or cond_result
        else:
            result = result and cond_result

        previous_logical_op = condition.logical_operator

    return bool(result)


# ---------------------------------------------------------------------------
# Recipient helpers
# ---------------------------------------------------------------------------


def _resolve_email_recipients(to_value, also_send_to, instance, user):
    """
    Resolve email recipient addresses.

    Each comma-separated spec can be:
      - "self"                    → the triggering user's email
      - "instance.field.subfield" → dotted path on the instance (e.g. instance.assigned_to.email)
      - an integer PK             → looked up in User table
      - a raw email address       → used directly
    """
    recipients = []

    def _add(spec):
        spec = (spec or "").strip()
        if not spec:
            return
        if spec == "self":
            if user and user.email:
                recipients.append(user.email)
            return
        # Dotted path traversal: instance.field.subfield
        if spec.startswith("instance."):
            field_path = spec[len("instance.") :]
            value = instance
            for attr in field_path.split("."):
                value = getattr(value, attr, None)
                if value is None:
                    break
            if value and isinstance(value, str) and "@" in value:
                recipients.append(value)
            elif value and hasattr(value, "email") and value.email:
                recipients.append(value.email)
            return
        # Integer PK → User lookup
        try:
            pk = int(spec)
            u = User.objects.filter(pk=pk).first()
            if u and u.email:
                recipients.append(u.email)
            return
        except (ValueError, TypeError):
            pass
        # Raw email address
        if "@" in spec:
            recipients.append(spec)

    for s in (to_value or "").split(","):
        _add(s)
    for s in (also_send_to or "").split(","):
        _add(s)

    # De-duplicate preserving order
    seen = set()
    result = []
    for r in recipients:
        if r not in seen:
            seen.add(r)
            result.append(r)
    return result


def _resolve_notification_users(to_value, also_notify_to, instance, user):
    """
    Resolve User objects for notification delivery.
    Same resolution logic as _resolve_email_recipients but returns User instances.
    """
    users = []

    def _add(spec):
        spec = (spec or "").strip()
        if not spec:
            return
        if spec == "self":
            if user:
                users.append(user)
            return
        # Dotted path traversal: instance.field.subfield
        if spec.startswith("instance."):
            field_path = spec[len("instance.") :]
            value = instance
            for attr in field_path.split("."):
                value = getattr(value, attr, None)
                if value is None:
                    break
            if value and isinstance(value, User):
                users.append(value)
            elif value and hasattr(value, "email"):
                u = User.objects.filter(email=value.email).first()
                if u:
                    users.append(u)
            return
        try:
            pk = int(spec)
            u = User.objects.filter(pk=pk).first()
            if u:
                users.append(u)
            return
        except (ValueError, TypeError):
            pass
        if "@" in spec:
            u = User.objects.filter(email=spec).first()
            if u:
                users.append(u)

    for s in (to_value or "").split(","):
        _add(s)
    for s in (also_notify_to or "").split(","):
        _add(s)

    seen_pks = set()
    result = []
    for u in users:
        if u.pk not in seen_pks:
            seen_pks.add(u.pk)
            result.append(u)
    return result


# ---------------------------------------------------------------------------
# Action executors
# ---------------------------------------------------------------------------


def _execute_update_field(action, instance, user):
    """Update a field on the record to the configured value."""
    config = action.action_config or {}
    field_name = config.get("field", "").strip()
    new_value = config.get("value", "")

    if not field_name:
        logger.warning("update_field action %s has no field configured", action.pk)
        return

    try:
        field = instance._meta.get_field(field_name)
    except Exception:
        logger.warning(
            "update_field action %s: field '%s' not found on %s",
            action.pk,
            field_name,
            instance.__class__.__name__,
        )
        return

    try:
        # Coerce value for numeric/boolean fields
        ftype = field.get_internal_type() if hasattr(field, "get_internal_type") else ""
        if ftype in (
            "IntegerField",
            "BigIntegerField",
            "SmallIntegerField",
            "PositiveIntegerField",
            "PositiveSmallIntegerField",
        ):
            new_value = int(new_value)
        elif ftype in ("FloatField", "DecimalField"):
            from decimal import Decimal

            new_value = (
                Decimal(str(new_value)) if ftype == "DecimalField" else float(new_value)
            )
        elif ftype == "BooleanField":
            new_value = str(new_value).lower() in ("true", "1", "yes")
        elif hasattr(field, "related_model") and field.related_model:
            # FK — store by PK
            related_model = field.related_model
            new_value = related_model.objects.filter(pk=int(new_value)).first()

        setattr(instance, field_name, new_value)
        # Use update_fields to avoid triggering unrelated signals recursively
        instance.save(update_fields=[field_name])
        logger.info(
            "Workflow update_field: set %s.%s = %r (instance pk=%s)",
            instance.__class__.__name__,
            field_name,
            new_value,
            instance.pk,
        )
    except Exception as exc:
        logger.error(
            "Error in update_field action %s: %s", action.pk, exc, exc_info=True
        )


def _execute_email(action, instance, user):
    """Send an email using the configured mail template and recipient list."""
    config = action.action_config or {}
    template_id = config.get("template_id")
    to = config.get("to", "")
    also_send_to = config.get("also_send_to", "")

    if not template_id:
        logger.warning("email action %s has no template_id configured", action.pk)
        return

    try:
        template = HorillaMailTemplate.objects.filter(pk=int(template_id)).first()
    except (ValueError, TypeError):
        template = None

    if not template:
        logger.warning(
            "email action %s: mail template %s not found", action.pk, template_id
        )
        return

    recipients = _resolve_email_recipients(to, also_send_to, instance, user)
    if not recipients:
        logger.warning("email action %s: no valid recipients resolved", action.pk)
        return

    # Resolve actor and company
    actor = (
        user
        or getattr(instance, "updated_by", None)
        or getattr(instance, "created_by", None)
    )
    request = getattr(_thread_local, "request", None)
    company = getattr(request, "active_company", None) if request else None
    if not company and hasattr(instance, "company"):
        company = instance.company

    # Find outgoing mail server
    sender = None
    if company:
        sender = (
            HorillaMailConfiguration.objects.filter(
                company=company, mail_channel="outgoing", is_primary=True
            ).first()
            or HorillaMailConfiguration.objects.filter(
                company=company, mail_channel="outgoing"
            ).first()
        )
    if not sender:
        sender = HorillaMailConfiguration.objects.filter(
            mail_channel="outgoing", is_primary=True
        ).first()

    content_type = HorillaContentType.objects.get_for_model(instance)

    try:
        mail = HorillaMail.objects.create(
            sender=sender,
            to=",".join(recipients),
            subject=template.subject or "",
            body=template.body or "",
            content_type=content_type,
            object_id=instance.pk,
            mail_status="draft",
            created_by=actor,
            updated_by=actor,
            company=company,
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )
    except Exception as exc:
        logger.error(
            "email action %s: failed to create HorillaMail: %s",
            action.pk,
            exc,
            exc_info=True,
        )
        return

    context = {
        "instance": instance,
        "user": user,
        "self": user,
    }
    if request:
        context["request"] = request
        context["active_company"] = company

    # Capture request metadata from the current thread before spawning
    _captured_request = getattr(_thread_local, "request", None)
    _request_info = {}
    if _captured_request:
        _request_info = {
            "meta": getattr(_captured_request, "META", {}),
            "host": (
                _captured_request.get_host()
                if hasattr(_captured_request, "get_host")
                else ""
            ),
            "scheme": getattr(_captured_request, "scheme", "https"),
        }

    def _send():
        try:
            if sender:
                setattr(_thread_local, "from_mail_id", sender.pk)

            setattr(
                _thread_local,
                "request",
                _WorkflowMockRequest(actor, company, _request_info),
            )
            HorillaMailManager.send_mail(mail, context=context)
            logger.info(
                "Workflow email sent: action=%s instance=%s recipients=%s",
                action.pk,
                instance.pk,
                recipients,
            )
        except Exception as exc:
            logger.error(
                "Workflow email action %s failed in thread: %s",
                action.pk,
                exc,
                exc_info=True,
            )
            try:
                mail.refresh_from_db()
                mail.mail_status = "failed"
                mail.mail_status_message = str(exc)
                mail.save(update_fields=["mail_status", "mail_status_message"])
            except Exception:
                pass
        finally:
            for attr in ("from_mail_id", "request"):
                try:
                    delattr(_thread_local, attr)
                except AttributeError:
                    pass

    threading.Thread(target=_send, daemon=True).start()


#: The record field each task due basis of the action form counts from.
TASK_DUE_BASIS_FIELDS = {
    "record_submission_date": "created_at",
    "record_update_date": "updated_at",
}


def _execute_assign_task(action, instance, user):
    """Create an Activity task and assign it to the record owner (or triggering user)."""
    from datetime import timedelta

    from horilla.contrib.activity.models import Activity

    config = action.action_config or {}
    title = (config.get("title") or "").strip()
    description = (config.get("description") or "").strip() or None
    status = (config.get("status") or "not_started").strip()
    priority = (config.get("priority") or "").strip() or None

    # Compute due date
    due_datetime = None
    try:
        due_in_days = int(config.get("due_in_days") or 1)
        due_basis = (config.get("due_basis") or "rule_trigger_date").strip()
        if due_basis == "rule_trigger_date":
            base_date = timezone.now()
        else:
            field_name = TASK_DUE_BASIS_FIELDS.get(due_basis, due_basis)
            base_date = getattr(instance, field_name, None)
            if base_date is None:
                base_date = timezone.now()
            # If it's a plain date (not datetime), convert to datetime
            import datetime as _dt

            if isinstance(base_date, _dt.date) and not isinstance(
                base_date, _dt.datetime
            ):
                from django.utils.timezone import make_aware

                base_date = make_aware(_dt.datetime.combine(base_date, _dt.time.min))
        due_datetime = base_date + timedelta(days=due_in_days)
    except Exception:
        due_datetime = None

    # Resolve owner: try common owner FK names (OWNER_FIELDS-style) on the instance.
    owner = user
    for attr in ("owner", "assigned_to", "created_by", "lead_owner"):
        candidate = getattr(instance, attr, None)
        if candidate and isinstance(candidate, User):
            owner = candidate
            break

    try:
        content_type = HorillaContentType.objects.get_for_model(instance)
        company = getattr(instance, "company", None)
        task = Activity.objects.create(
            subject=title or f"Task for {instance}",
            description=description,
            activity_type="task",
            content_type=content_type,
            object_id=instance.pk,
            status=status,
            task_priority=priority,
            due_datetime=due_datetime,
            owner=owner,
            company=company,
            created_by=user or owner,
            updated_by=user or owner,
        )
        task.assigned_to.add(owner)
        logger.info(
            "Workflow assign_task: created task pk=%s for %s pk=%s assigned to user pk=%s",
            task.pk,
            instance.__class__.__name__,
            instance.pk,
            owner.pk if owner else None,
        )
    except Exception as exc:
        logger.error(
            "Error in assign_task action %s: %s", action.pk, exc, exc_info=True
        )


def _execute_notification(action, instance, user):
    """Send an in-app notification using the configured template and recipient list."""
    from horilla.contrib.notifications.models import NotificationTemplate

    config = action.action_config or {}
    template_id = config.get("template_id")
    to = config.get("to", "")
    also_notify_to = config.get("also_notify_to", "")
    custom_message = config.get("custom_message", "").strip()

    # Resolve message text
    message = ""
    if custom_message:
        message = custom_message
    elif template_id:
        try:
            tmpl = NotificationTemplate.objects.filter(pk=int(template_id)).first()
            if tmpl and tmpl.message:
                # Render Django template tags inside the message
                django_engine = engines["django"]
                request = getattr(_thread_local, "request", None)
                ctx = {"instance": instance, "user": user, "self": user}
                if request:
                    ctx["request"] = request
                raw = "{% load horilla_tags %}\n" + tmpl.message
                try:
                    message = django_engine.from_string(raw).render(ctx)
                except Exception:
                    message = tmpl.message
        except (ValueError, TypeError):
            pass

    if not message:
        message = f"Workflow rule triggered for {instance}"

    message = message[:500]

    users_to_notify = _resolve_notification_users(to, also_notify_to, instance, user)
    if not users_to_notify:
        logger.warning("notification action %s: no users resolved", action.pk)
        return

    # Resolve a URL for the notification (use the instance's detail URL if available)
    instance_url = None
    for attr in dir(instance):
        if attr.startswith("get_detail_"):
            try:
                url = getattr(instance, attr)()
                if url and str(url).strip() and str(url) != "#":
                    instance_url = str(url).strip()
                    break
            except Exception:
                pass

    try:
        with transaction.atomic():
            for notify_user in users_to_notify:
                create_notification(
                    user=notify_user,
                    message=message,
                    sender=user,
                    url=instance_url,
                    instance=instance,
                    read=False,
                )
        logger.info(
            "Workflow notification sent: action=%s instance=%s users=%s",
            action.pk,
            instance.pk,
            [u.pk for u in users_to_notify],
        )
    except Exception as exc:
        logger.error(
            "Workflow notification action %s failed: %s", action.pk, exc, exc_info=True
        )


class ChannelActionMessage:
    """
    What a delivery channel's ``send()`` reads for one workflow action.

    Channels are written for Automations and read the message settings from
    the ``HorillaAutomation`` they get as ``automation``: ``title``, ``pk``,
    ``company``, ``mail_template``, ``notification_template``,
    ``mail_server``, ``mail_to``, ``created_by``, ``updated_by``. A workflow
    action passes this object instead, built from its ``action_config``.
    ``action`` and ``rule`` are the workflow action and its rule.
    """

    def __init__(self, action, channel, template=None):
        config = action.action_config or {}
        rule = getattr(action, "rule", None)
        kind = get_channel_template_kind(channel)
        self.action = action
        self.rule = rule
        self.pk = action.pk
        self.title = getattr(rule, "name", None) or str(action)
        self.company = getattr(action, "company", None) or getattr(
            rule, "company", None
        )
        self.mail_template = template if kind == TEMPLATE_MAIL else None
        self.notification_template = template if kind == TEMPLATE_NOTIFICATION else None
        # No mail server is chosen on a workflow action: the mail channel
        # picks the company's outgoing server.
        self.mail_server = None
        self.mail_to = config.get("to", "") or ""
        self.created_by = getattr(rule, "created_by", None)
        self.updated_by = getattr(rule, "updated_by", None)
        self.additional_info = {}

    def __str__(self):
        return str(self.title)


def _get_channel_template(action, channel, company):
    """
    The template ``action_config["template_id"]`` points to for ``channel``,
    or ``None``. Returns ``(template, ok)``: ``ok`` is false when the channel
    needs a template and it is missing. Only a template of ``company`` (or of
    no company) is used, as the action form lists.
    """
    from horilla.contrib.notifications.models import NotificationTemplate

    kind = get_channel_template_kind(channel)
    if kind is None:
        return None, True
    template_id = (action.action_config or {}).get("template_id")
    model = (
        NotificationTemplate if kind == TEMPLATE_NOTIFICATION else HorillaMailTemplate
    )
    templates = model.all_objects.all()
    if company is not None:
        templates = templates.filter(Q(company=company) | Q(company__isnull=True))
    try:
        template = templates.filter(pk=int(template_id)).first()
    except (ValueError, TypeError):
        template = None
    return template, template is not None


def _also_send_to_users(also_send_to):
    """The users of a comma-separated list of user PKs (``also_send_to``)."""
    ids = []
    for part in str(also_send_to or "").split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    if not ids:
        return []
    users = User.objects.in_bulk(ids)
    return [users[pk] for pk in dict.fromkeys(ids) if pk in users]


def _execute_channel(action, channel, instance, user):
    """
    Send through a registered delivery channel (``action_type`` is its key).

    ``action_config`` is ``{"template_id", "to", "also_send_to"}``: the
    channel resolves ``to`` for its own address kind (emails, users, phone
    numbers), adds the users of ``also_send_to`` (user PKs), and sends the
    template as it does for an automation.
    """
    config = action.action_config or {}

    rule = getattr(action, "rule", None)
    company = getattr(action, "company", None) or getattr(rule, "company", None)
    template, ok = _get_channel_template(action, channel, company)
    if not ok:
        logger.warning(
            "%s action %s: template %s not found",
            channel.key,
            action.pk,
            config.get("template_id"),
        )
        return

    recipients = channel.resolve_recipients(config.get("to", "") or "", instance, user)
    recipients = channel.add_also_sent_to(
        recipients, _also_send_to_users(config.get("also_send_to"))
    )
    if not recipients:
        logger.warning("%s action %s: no recipients resolved", channel.key, action.pk)
        return

    message = ChannelActionMessage(action, channel, template)

    # The same context Automations renders templates with.
    request = getattr(_thread_local, "request", None)
    actor = (
        user
        or getattr(instance, "updated_by", None)
        or getattr(instance, "created_by", None)
        or message.updated_by
        or message.created_by
    )
    active_company = getattr(request, "active_company", None) or (
        getattr(actor, "company", None) if actor else None
    )
    context = {
        "instance": instance,
        "user": actor,
        "self": user,
        "active_company": active_company,
    }
    if request:
        context["request"] = request

    channel.send(message, instance, recipients, context, user)
    logger.info(
        "Workflow %s sent: action=%s instance=%s recipients=%s",
        channel.key,
        action.pk,
        instance.pk,
        len(recipients),
    )


#: The built-in action types and the function that runs each.
BUILTIN_EXECUTORS = {
    "update_field": _execute_update_field,
    "assign_task": _execute_assign_task,
    "email": _execute_email,
    "notification": _execute_notification,
}


def execute_action(action, instance, user):
    """
    Run one ``WorkflowAction`` or ``WorkflowTimeTriggerAction``.

    A built-in runs its executor; any other ``action_type`` is a delivery
    channel key and is sent through the registered channel. Returns False
    when ``action_type`` is neither (the channel's app is gone): the action is
    logged and skipped.
    """
    executor = BUILTIN_EXECUTORS.get(action.action_type)
    if executor is not None:
        executor(action, instance, user)
        return True
    channel = get_action_channel(action.action_type)
    if channel is None:
        logger.error(
            "Workflow action %s: action type %r is not a built-in or a "
            "registered delivery channel",
            action.pk,
            action.action_type,
        )
        return False
    _execute_channel(action, channel, instance, user)
    return True


# ---------------------------------------------------------------------------
# Rule execution
# ---------------------------------------------------------------------------


def execute_workflow_rule(rule, instance, user, trigger_type, met_before=None):
    """
    Execute all actions for a single WorkflowRule in order.

    trigger_type is "on_create" or "on_update". ``met_before`` maps rule pks
    to whether the record met the rule's criteria before this save (see
    ``criteria_met_before_save``); an update does not run a rule with
    ``only_when_criteria_become_true`` whose criteria were already met, and
    an update that takes the record out of such a rule's criteria skips the
    rule's pending time triggers for it.
    """
    # Check trigger flags
    if trigger_type == "on_create" and not rule.trigger_on_create:
        return
    if trigger_type == "on_update" and not rule.trigger_on_edit:
        return

    # Evaluate entry criteria
    if not evaluate_workflow_conditions(rule, instance):
        if (
            trigger_type == "on_update"
            and rule.only_when_criteria_become_true
            and (met_before or {}).get(rule.pk)
        ):
            skip_pending_time_triggers(
                rule,
                instance,
                "The record stopped meeting the workflow rule's criteria.",
            )
        logger.debug(
            "Workflow rule '%s' conditions not met for %s pk=%s",
            rule.name,
            instance.__class__.__name__,
            instance.pk,
        )
        return

    if (
        trigger_type == "on_update"
        and rule.only_when_criteria_become_true
        and (met_before or {}).get(rule.pk)
    ):
        logger.debug(
            "Workflow rule '%s' criteria already met before this edit of %s pk=%s",
            rule.name,
            instance.__class__.__name__,
            instance.pk,
        )
        return

    logger.info(
        "Workflow rule '%s' matched for %s pk=%s (trigger=%s)",
        rule.name,
        instance.__class__.__name__,
        instance.pk,
        trigger_type,
    )

    actions = rule.actions.filter(is_active=True).order_by("order", "created_at")
    for action in actions:
        try:
            execute_action(action, instance, user)
        except Exception as exc:
            logger.error(
                "Error executing workflow action %s (%s): %s",
                action.pk,
                action.action_type,
                exc,
                exc_info=True,
            )

    _schedule_time_triggers(rule, instance)


def time_trigger_skip_reason(time_trigger, instance):
    """
    Return why a due time trigger must not run on ``instance``, or "".

    A time trigger fires some time after its rule matched, so the rule and
    the time trigger must still be active and the record must still meet
    the rule's criteria when it is due.
    """
    rule = time_trigger.rule
    if not rule.is_active:
        return "The workflow rule is inactive."
    if not time_trigger.is_active:
        return "The time trigger is inactive."
    if not evaluate_workflow_conditions(rule, instance):
        return "The record no longer meets the workflow rule's criteria."
    return ""


def skip_pending_time_triggers(rule, instance, reason):
    """
    Mark the pending time-trigger executions of ``rule`` for ``instance``
    skipped with ``reason``, in one query. Returns how many were skipped.
    """
    return ScheduledWorkflowExecution.all_objects.filter(
        time_trigger__rule=rule,
        object_id=instance.pk,
        status=ScheduledWorkflowExecution.STATUS_PENDING,
    ).update(
        status=ScheduledWorkflowExecution.STATUS_SKIPPED,
        error_message=reason,
        executed_at=timezone.now(),
    )


def _schedule_time_triggers(rule, instance):
    """
    For each active time trigger on the rule, calculate the fire datetime and
    create a ScheduledWorkflowExecution row.  Skips if the calculated time
    is in the past (would fire immediately via the next periodic poll instead
    of being silently dropped).
    """
    from datetime import timedelta

    time_triggers = rule.time_trigger_actions.filter(is_active=True)
    if not time_triggers.exists():
        return

    now = timezone.now()

    for tt in time_triggers:
        try:
            if tt.trigger_date_field == "rule_trigger_date":
                base_dt = now
            else:
                base_val = getattr(instance, tt.trigger_date_field, None)
                if base_val is None:
                    continue
                # Convert date → datetime if needed
                if not hasattr(base_val, "hour"):
                    from datetime import datetime

                    base_val = datetime.combine(base_val, datetime.min.time())
                    base_val = timezone.make_aware(base_val)
                base_dt = base_val

            delta = timedelta(**{tt.delay_unit: tt.delay_value})
            fire_at = (
                base_dt + delta if tt.delay_direction == "after" else base_dt - delta
            )

            ScheduledWorkflowExecution.objects.create(
                time_trigger=tt,
                object_id=instance.pk,
                scheduled_at=fire_at,
                company=getattr(instance, "company", None),
            )

            logger.info(
                "Scheduled workflow time trigger pk=%s for %s pk=%s at %s",
                tt.pk,
                instance.__class__.__name__,
                instance.pk,
                fire_at,
            )
        except Exception as exc:
            logger.error(
                "Error scheduling time trigger pk=%s: %s", tt.pk, exc, exc_info=True
            )


def active_workflow_rules(instance):
    """
    The active WorkflowRules for the instance's model and company (the
    instance's company, else the request's active company).
    """
    content_type = HorillaContentType.objects.get_for_model(instance)

    company = getattr(instance, "company", None)
    if not company:
        request = getattr(_thread_local, "request", None)
        if request:
            company = getattr(request, "active_company", None)

    filter_kwargs = {"model": content_type, "is_active": True}
    if company:
        filter_kwargs["company"] = company
    return WorkflowRule.objects.filter(**filter_kwargs)


def criteria_met_before_save(instance):
    """
    For an existing record about to be saved: ``{rule pk: bool}``, whether the
    stored copy meets the criteria of each active rule that runs on edit only
    when its criteria become true. Empty (and no record read) when there is no
    such rule.
    """
    rules = list(
        active_workflow_rules(instance).filter(
            trigger_on_edit=True, only_when_criteria_become_true=True
        )
    )
    if not rules:
        return {}
    stored = instance.__class__._base_manager.filter(pk=instance.pk).first()
    if stored is None:
        return {}
    return {rule.pk: evaluate_workflow_conditions(rule, stored) for rule in rules}


def trigger_workflow_rules(
    instance, trigger_type="on_create", user=None, met_before=None
):
    """
    Find all active WorkflowRules for the given instance's model and execute them.

    Called from the post_save signal handler. ``met_before`` is passed on to
    ``execute_workflow_rule``.
    """
    try:
        rules = active_workflow_rules(instance).prefetch_related(
            "conditions", "actions"
        )

        for rule in rules:
            try:
                execute_workflow_rule(
                    rule, instance, user, trigger_type, met_before=met_before
                )
            except Exception as exc:
                logger.error(
                    "Error executing workflow rule '%s': %s",
                    rule.name,
                    exc,
                    exc_info=True,
                )

    except Exception as exc:
        logger.error("Error in trigger_workflow_rules: %s", exc, exc_info=True)
