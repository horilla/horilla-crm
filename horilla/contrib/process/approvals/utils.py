"""Utility helpers for approval matching, jobs, and edit guards."""

# Standard library imports
import json
import threading
from decimal import Decimal

# Third-party imports (Django)
from django.db import close_old_connections
from django.utils.dateparse import parse_date, parse_datetime

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.process.integration import (
    run_pre_approval_sync_hooks,
    should_suppress_approval,
)
from horilla.contrib.utils.middlewares import _thread_local
from horilla.core.exceptions import ValidationError
from horilla.db import models as db_models
from horilla.db import transaction
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import ApprovalInstance, ApprovalProcessRule


def safe_content_object(instance):
    """Return instance.content_object safely, or None if the model class is unresolvable."""
    ct = getattr(instance, "content_type", None)
    if ct and ct.model_class() is None:
        return None
    try:
        return instance.content_object
    except Exception:
        return None


def _compare_date_operator(operator, raw_value, value, parser):
    if operator == "isnull":
        return raw_value is None
    if operator == "isnotnull":
        return raw_value is not None
    parsed = parser(value)
    if parsed is None or raw_value is None:
        return str(raw_value) == str(value) if operator == "exact" else False
    if operator == "exact":
        return raw_value == parsed
    if operator == "gt":
        return raw_value > parsed
    return raw_value < parsed


def _compare_numeric_operator(operator, left, right):
    try:
        left_dec = Decimal(left)
        right_dec = Decimal(right)
    except Exception:
        return False
    if operator == "gt":
        return left_dec > right_dec
    if operator == "gte":
        return left_dec >= right_dec
    if operator == "lt":
        return left_dec < right_dec
    return left_dec <= right_dec


def _compare_text_operator(operator, left, right):
    if operator == "exact":
        return left == right
    if operator == "ne":
        return left != right
    if operator == "icontains":
        return right.lower() in left.lower()
    if operator == "not_contains":
        return right.lower() not in left.lower()
    if operator == "istartswith":
        return left.lower().startswith(right.lower())
    return left.lower().endswith(right.lower())


def _compare_string_operator(operator, left, right):
    if operator in (
        "exact",
        "ne",
        "icontains",
        "not_contains",
        "istartswith",
        "iendswith",
    ):
        return _compare_text_operator(operator, left, right)
    if operator in ("gt", "gte", "lt", "lte"):
        return _compare_numeric_operator(operator, left, right)
    if operator == "isnull":
        return not left.strip()
    if operator == "isnotnull":
        return bool(left.strip())
    return False


def evaluate_condition(instance, condition):
    """Evaluate a single ApprovalCondition against the given model instance."""
    field_name = getattr(condition, "field", "")
    operator = (getattr(condition, "operator", "") or "").strip()
    value = getattr(condition, "value", "")
    from horilla.contrib.generics.forms.condition_fields import (
        evaluate_extension_condition,
    )
    from horilla.contrib.generics.related_fields import resolve_instance_path

    # Fields contributed by other apps (e.g. custom fields) aren't columns.
    handled, extension_result = evaluate_extension_condition(
        field_name, instance, operator, value, _compare_string_operator
    )
    if handled:
        return extension_result
    # "owner__department" reads the field off the related record.
    instance, field_name = resolve_instance_path(instance, field_name)
    try:
        field = instance._meta.get_field(field_name)
        raw_value = getattr(instance, field_name, None)
    except Exception:
        return False

    if isinstance(field, db_models.ForeignKey):
        raw_value = getattr(instance, f"{field_name}_id", raw_value)

    field_type = getattr(field, "get_internal_type", lambda: "")()
    is_date = field_type == "DateField"
    is_datetime = field_type == "DateTimeField"

    if is_date or is_datetime:
        if operator in ("isnull", "isnotnull", "exact", "gt", "lt"):
            parser = parse_date if is_date else parse_datetime
            return _compare_date_operator(operator, raw_value, value, parser)

    left = "" if raw_value is None else str(raw_value)
    right = "" if value is None else str(value)
    return _compare_string_operator(operator, left, right)


def evaluate_conditions(instance, conditions):
    """Evaluate all ApprovalConditions against the instance, combining with AND/OR logic."""
    conditions = list(conditions)
    if not conditions:
        return True
    result = None
    for cond in conditions:
        current = evaluate_condition(instance, cond)
        if result is None:
            result = current
            continue
        if getattr(cond, "logical_operator", "and") == "or":
            result = result or current
        else:
            result = result and current
    return bool(result)


def _parse_record_modification(rule_config):
    rm = (rule_config or {}).get("record_modification", {})
    if isinstance(rm, dict):
        return rm
    if isinstance(rm, str):
        try:
            parsed = json.loads(rm or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def get_waiting_policy(instance):
    """Return waiting-state edit policy for the instance's current stage."""
    if not instance or not instance.current_step_id:
        return {"scope": "no_fields", "fields": []}
    try:
        process_rule = ApprovalProcessRule.objects.get(
            pk=instance.current_step.approval_process_rule_id
        )
    except ApprovalProcessRule.DoesNotExist:
        return {"scope": "no_fields", "fields": []}
    rm = _parse_record_modification(process_rule.rule_config or {})
    stage_key = f"stage_{instance.current_step.order}"
    by_stage = rm.get("by_stage", {}) if isinstance(rm, dict) else {}
    if isinstance(by_stage, dict) and stage_key in by_stage:
        waiting = (by_stage.get(stage_key, {}) or {}).get("waiting", {}) or {}
        return {
            "scope": waiting.get("scope", "no_fields"),
            "fields": waiting.get("fields", []) or [],
        }
    return {
        "scope": rm.get("waiting_scope", "no_fields"),
        "fields": rm.get("waiting_fields", []) or [],
    }


def get_rejected_policy(instance):
    """Return rejected-state edit policy for the instance's current stage."""
    if not instance:
        return {"scope": "no_fields", "fields": []}

    process_rule = None
    step_order = None

    if instance.current_step_id:
        step_order = instance.current_step.order
        try:
            process_rule = ApprovalProcessRule.objects.get(
                pk=instance.current_step.approval_process_rule_id
            )
        except ApprovalProcessRule.DoesNotExist:
            process_rule = None

    # Rejected instances can lose current_step during lifecycle changes.
    # Fall back to the latest decision's step/rule so rejected policy remains accurate.
    if process_rule is None:
        from .models import ApprovalDecision  # local import to avoid circular import

        latest_decision = (
            ApprovalDecision.objects.filter(instance=instance)
            .select_related("step__approval_process_rule")
            .order_by("-decided_at", "-id")
            .first()
        )
        if latest_decision and latest_decision.step_id:
            process_rule = getattr(latest_decision.step, "approval_process_rule", None)
            step_order = getattr(latest_decision.step, "order", None)

    if process_rule is None:
        return {"scope": "no_fields", "fields": []}

    rm = _parse_record_modification(process_rule.rule_config or {})
    stage_key = f"stage_{step_order}" if step_order else ""
    by_stage = rm.get("by_stage", {}) if isinstance(rm, dict) else {}
    if stage_key and isinstance(by_stage, dict) and stage_key in by_stage:
        rejected = (by_stage.get(stage_key, {}) or {}).get("rejected", {}) or {}
        return {
            "scope": rejected.get("scope", "no_fields"),
            "fields": rejected.get("fields", []) or [],
        }
    if isinstance(by_stage, dict) and by_stage:
        # Stage-wise policy exists but this stage is missing: fail closed.
        return {"scope": "no_fields", "fields": []}
    return {
        "scope": rm.get("rejected_scope", "no_fields"),
        "fields": rm.get("rejected_fields", []) or [],
    }


def _is_user_step(step):
    return bool(step and step.approver_type == "user" and step.approver_user_id)


def _is_role_step(step):
    return bool(
        step
        and step.approver_type == "role"
        and (getattr(step, "role_identifier", None) or "").strip()
    )


def _is_owner_step(step):
    return bool(step and step.approver_type == "owner_manager")


def _is_approver_step(step):
    """Step with a concrete approver: assigned user, Horilla role, or record owner."""
    return _is_user_step(step) or _is_role_step(step) or _is_owner_step(step)


def _record_owner(instance):
    """Return the owner user of an approval instance's record, if any."""
    record = safe_content_object(instance) if instance is not None else None
    return getattr(record, "owner", None)


def user_matches_approver_step(user, step, instance=None):
    """True if this user may act on the given step (user assignee, role member, or record owner)."""
    if not user or not step:
        return False
    if instance is not None and instance.delegated_approver_id:
        return instance.delegated_approver_id == user.id
    if _is_user_step(step):
        return step.approver_user_id == user.id
    if _is_role_step(step):
        rid = (step.role_identifier or "").strip()
        if not rid:
            return False
        role = getattr(user, "role", None)
        if not role or not getattr(role, "role_name", None):
            return False
        return role.role_name.strip().lower() == rid.lower()
    if _is_owner_step(step):
        owner = _record_owner(instance)
        return bool(owner and owner.id == user.id)
    return False


def users_for_approver_step(step, instance=None):
    """Users to notify for this step (one user, all members of a role, or the record owner)."""
    if _is_user_step(step):
        u = getattr(step, "approver_user", None)
        return [u] if u else []
    if _is_role_step(step):
        rid = (step.role_identifier or "").strip()
        if not rid:
            return []
        return list(
            User.objects.filter(
                is_active=True, role__role_name__iexact=rid
            ).select_related("role")
        )
    if _is_owner_step(step):
        owner = _record_owner(instance)
        return [owner] if owner else []
    return []


def get_cycle_started_at(instance):
    """
    Return cycle start datetime for an approval instance.
    When set, only decisions at/after this point belong to current run.
    """
    info = getattr(instance, "additional_info", None) or {}
    raw = info.get("approval_cycle_started_at")
    if not raw:
        return None
    try:
        return parse_datetime(raw) if isinstance(raw, str) else raw
    except Exception:
        return None


def get_who_should_approve_config(process_rule):
    """Return normalized who-should-approve config for a process rule."""
    cfg = (getattr(process_rule, "rule_config", None) or {}).get(
        "who_should_approve", {}
    ) or {}
    overall_method = (cfg.get("overall_method") or "anyone").strip().lower()
    approval_order = (cfg.get("approval_order") or "sequential").strip().lower()
    if overall_method not in {"anyone", "everyone"}:
        overall_method = "anyone"
    if approval_order not in {"sequential", "parallel"}:
        approval_order = "sequential"
    return {"overall_method": overall_method, "approval_order": approval_order}


def get_pending_user_steps(instance):
    """
    Return approver steps currently pending for the approval instance.

    Sequential mode keeps a single active step.
    Parallel mode exposes all pending steps.
    """
    if not instance or instance.status != "pending" or not instance.current_step_id:
        return []
    process_rule = getattr(instance.current_step, "approval_process_rule", None)
    if not process_rule:
        return []

    config = get_who_should_approve_config(process_rule)
    if config["approval_order"] != "parallel":
        return (
            [instance.current_step] if _is_approver_step(instance.current_step) else []
        )

    approver_steps = [
        step
        for step in process_rule.steps.all().order_by("order", "id")
        if _is_approver_step(step)
    ]
    if not approver_steps:
        return []

    from .models import ApprovalDecision  # local import to avoid circular import

    approvals_qs = ApprovalDecision.objects.filter(
        instance=instance,
        decision="approve",
        step_id__in=[s.id for s in approver_steps],
    )
    cycle_started_at = get_cycle_started_at(instance)
    if cycle_started_at:
        approvals_qs = approvals_qs.filter(decided_at__gte=cycle_started_at)
    approved_ids = set(approvals_qs.values_list("step_id", flat=True))
    if config["overall_method"] == "anyone" and approved_ids:
        return []
    return [step for step in approver_steps if step.id not in approved_ids]


def _notify_current_approvers_impl(instance, triggered_by=None):
    """Send configured email/in-app notifications (runs in worker thread when scheduled)."""
    if not instance or instance.status != "pending":
        return
    process_rule = getattr(
        getattr(instance, "current_step", None), "approval_process_rule", None
    )
    if not process_rule:
        return
    notify_cfg = (process_rule.rule_config or {}).get("notify_approver", {}) or {}
    notify_email = bool(notify_cfg.get("email"))
    notify_in_app = bool(notify_cfg.get("notification"))
    if not (notify_email or notify_in_app):
        return

    pending_steps = get_pending_user_steps(instance)
    if not pending_steps and _is_approver_step(instance.current_step):
        pending_steps = [instance.current_step]
    users = []
    seen_ids = set()
    for step in pending_steps:
        for user in users_for_approver_step(step, instance=instance):
            if not user or user.id in seen_ids:
                continue
            seen_ids.add(user.id)
            users.append(user)
    if not users:
        return

    record = getattr(instance, "content_object", None)
    record_label = str(record) if record else str(instance.object_id)
    message = f"Approval request pending for {record_label}"
    notification_url = instance.get_review_url()

    if notify_in_app:
        try:
            from horilla.contrib.notifications.methods import create_notification

            for user in users:
                create_notification(
                    user=user,
                    message=message,
                    sender=triggered_by,
                    url=notification_url,
                    instance=record,
                    read=False,
                )
        except Exception:
            pass

    if notify_email:
        try:
            from horilla.contrib.mail.models import (
                HorillaMail,
                HorillaMailConfiguration,
            )
            from horilla.contrib.mail.services import HorillaMailManager

            sender = (
                HorillaMailConfiguration.objects.filter(
                    is_primary=True, mail_channel="outgoing"
                ).first()
                or HorillaMailConfiguration.objects.filter(
                    mail_channel="outgoing"
                ).first()
            )
            if sender:
                subject = f"Approval Request: {instance.rule.name}"
                body = (
                    "A record is awaiting your approval.\n\n"
                    f"Process: {instance.rule}\n"
                    f"Record: {record_label}\n"
                )
                for user in users:
                    recipient = getattr(user, "email", None)
                    if not recipient:
                        continue
                    mail = HorillaMail.objects.create(
                        sender=sender,
                        to=recipient,
                        subject=subject,
                        body=body,
                        content_type=instance.content_type,
                        object_id=int(instance.object_id),
                        mail_status="draft",
                        company=getattr(instance, "company", None),
                        created_by=triggered_by,
                        updated_by=triggered_by,
                    )
                    HorillaMailManager.send_mail(
                        mail,
                        context={
                            "instance": record,
                            "user": user,
                        },
                    )
        except Exception:
            pass


def notify_current_approvers(instance, triggered_by=None):
    """
    Send approver notifications after the DB transaction commits, in a background thread,
    so SMTP and mail pipeline do not block the HTTP request (saves stay fast).
    """
    if not instance or not getattr(instance, "pk", None):
        return
    inst_pk = instance.pk
    user_pk = getattr(triggered_by, "pk", None)

    def _run():
        close_old_connections()
        try:
            inst = (
                ApprovalInstance.objects.select_related(
                    "current_step__approval_process_rule",
                    "rule",
                    "content_type",
                )
                .filter(pk=inst_pk, status="pending")
                .first()
            )
            if not inst:
                return
            trigger_user = User.objects.filter(pk=user_pk).first() if user_pk else None
            _notify_current_approvers_impl(inst, triggered_by=trigger_user)
        finally:
            close_old_connections()

    def _start():
        threading.Thread(
            target=_run, daemon=True, name="horilla-approval-notify"
        ).start()

    transaction.on_commit(_start)


def get_user_pending_step(instance, user):
    """Return pending step for this user on the given instance, if any."""
    if not getattr(user, "is_authenticated", False):
        return None
    for step in get_pending_user_steps(instance):
        if user_matches_approver_step(user, step, instance=instance):
            return step
    return None


def is_user_pending_approver(instance, user):
    """True when user can currently act on the approval instance."""
    return bool(get_user_pending_step(instance, user))


def get_first_user_step(process_rule):
    """Return first valid approver step (user or role) in a process rule."""
    if not process_rule:
        return None
    for step in process_rule.steps.all().order_by("order", "id"):
        if _is_approver_step(step):
            return step
    return None


def get_next_user_step(current_step, instance=None):
    """Return next valid user approver step after current step."""
    if not current_step:
        return None
    if instance is not None:
        process_rule = getattr(current_step, "approval_process_rule", None)
        cfg = get_who_should_approve_config(process_rule) if process_rule else {}
        # Only parallel mode should resolve from pending-step set.
        # Sequential must move strictly to the next ordered step.
        if cfg.get("approval_order") == "parallel":
            pending_steps = get_pending_user_steps(instance)
            if pending_steps:
                return pending_steps[0]
            return None
    qs = ApprovalProcessRule.objects.filter(
        pk=current_step.approval_process_rule_id
    ).first()
    if not qs:
        return None
    for step in qs.steps.all().order_by("order", "id"):
        if step.order <= current_step.order:
            continue
        if _is_approver_step(step):
            return step
    return None


def sync_approval_instances_for_record(record, *, created=False):
    """Create/update pending approval instances for matching process rules."""
    # Registered hooks (e.g. review process) refresh first so gates apply regardless of signal order.
    run_pre_approval_sync_hooks(record)

    content_type = HorillaContentType.objects.get_for_model(record.__class__)
    object_id = str(record.pk)

    if should_suppress_approval(record):
        ApprovalInstance.objects.filter(
            content_type=content_type,
            object_id=object_id,
            status="pending",
        ).delete()
        return

    from .models import ApprovalRule  # local import to avoid cycle at import time

    processes = ApprovalRule.objects.filter(
        model=content_type, is_active=True
    ).prefetch_related("process_rules__conditions", "process_rules__steps")

    matched_rule_ids = set()
    request = getattr(_thread_local, "request", None)
    request_user = getattr(request, "user", None)
    request_user = (
        request_user if getattr(request_user, "is_authenticated", False) else None
    )
    record_company_id = getattr(record, "company_id", None)

    for process in processes:
        # created=True -> create-triggered save path only
        # created=False -> edit-triggered save path only
        # created=None -> explicit resync path (accept both create/edit triggers)
        if created is True and not process.trigger_on_create:
            continue
        if created is False and not process.trigger_on_edit:
            continue
        if created is None and not (
            process.trigger_on_create or process.trigger_on_edit
        ):
            continue
        process_rules = list(process.process_rules.all().order_by("order", "id"))
        for process_rule in process_rules:
            conds = process_rule.conditions.all().order_by("order", "created_at")
            if not evaluate_conditions(record, conds):
                continue
            first_step = get_first_user_step(process_rule)
            if not first_step:
                continue
            matched_rule_ids.add(process.id)
            pending = ApprovalInstance.objects.filter(
                rule=process,
                content_type=content_type,
                object_id=object_id,
                status="pending",
            ).first()
            if pending:
                update_fields = []
                # Do not reset progression if current step already belongs to this rule.
                same_rule = bool(
                    pending.current_step
                    and pending.current_step.approval_process_rule_id == process_rule.id
                )
                if (not same_rule) and pending.current_step_id != first_step.id:
                    pending.current_step = first_step
                    update_fields.append("current_step")
                    if pending.delegated_approver_id:
                        pending.delegated_approver = None
                        update_fields.append("delegated_approver")
                if record_company_id and pending.company_id != record_company_id:
                    pending.company_id = record_company_id
                    update_fields.append("company")
                if update_fields:
                    pending.save(update_fields=update_fields + ["updated_at"])
                    notify_current_approvers(pending, triggered_by=request_user)
            else:
                created_instance = ApprovalInstance.objects.create(
                    rule=process,
                    content_type=content_type,
                    object_id=object_id,
                    requested_by=request_user,
                    status="pending",
                    current_step=first_step,
                    company_id=record_company_id,
                    created_by=request_user,
                    updated_by=request_user,
                )
                notify_current_approvers(created_instance, triggered_by=request_user)
            break

    ApprovalInstance.objects.filter(
        content_type=content_type,
        object_id=object_id,
        status="pending",
    ).exclude(rule_id__in=matched_rule_ids).delete()


def enforce_pending_edit_policy(instance):
    """Block unauthorized edits on records with pending/rejected approvals."""
    if instance._state.adding:
        return
    if getattr(_thread_local, "skip_approval_edit_guard", False):
        return
    request = getattr(_thread_local, "request", None)
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return

    content_type = HorillaContentType.objects.get_for_model(instance.__class__)
    tracked_instances = list(
        ApprovalInstance.objects.filter(
            content_type=content_type,
            object_id=str(instance.pk),
            status__in=("pending", "rejected"),
        ).select_related("current_step")
    )
    if not tracked_instances:
        return

    db_obj = instance.__class__.objects.filter(pk=instance.pk).first()
    if not db_obj:
        return

    changed_fields = set()
    for field in instance._meta.concrete_fields:
        if not getattr(field, "editable", True):
            continue
        if field.name in {"updated_at", "updated_by"}:
            continue
        new_val = getattr(instance, field.name, None)
        old_val = getattr(db_obj, field.name, None)
        if isinstance(field, db_models.ForeignKey):
            new_val = getattr(instance, f"{field.name}_id", new_val)
            old_val = getattr(db_obj, f"{field.name}_id", old_val)
        if new_val != old_val:
            changed_fields.add(field.name)

    if not changed_fields:
        return

    pending_instances = [i for i in tracked_instances if i.status == "pending"]
    rejected_instances = [i for i in tracked_instances if i.status == "rejected"]

    # Pending: only currently pending approvers can edit.
    user_instances = []
    for approval in pending_instances:
        if is_user_pending_approver(approval, user):
            user_instances.append(approval)
    if pending_instances and not user_instances:
        raise ValidationError(
            _("This record is pending approval and cannot be edited.")
        )

    allow_all = False
    allowed_fields = set()
    if pending_instances:
        for approval in user_instances:
            policy = get_waiting_policy(approval)
            scope = policy.get("scope", "no_fields")
            if scope == "all_fields":
                allow_all = True
                break
            if scope == "specific_fields":
                allowed_fields.update(policy.get("fields", []) or [])
    else:
        # Rejected state: apply rejected-scope record-modification policy.
        for approval in rejected_instances:
            policy = get_rejected_policy(approval)
            scope = policy.get("scope", "all_fields")
            if scope == "all_fields":
                allow_all = True
                break
            if scope == "specific_fields":
                allowed_fields.update(policy.get("fields", []) or [])

    if allow_all:
        return
    if changed_fields - allowed_fields:
        if pending_instances:
            raise ValidationError(
                "Only configured fields are editable while this record is pending approval."
            )
        raise ValidationError(
            "Only configured fields are editable while this record is in rejected state."
        )


def get_bulk_edit_allowed_fields(record, user):
    """Return the field names ``user`` may edit on ``record`` while it has a
    pending or rejected approval, or ``None`` when no approval limits editing.

    Mirrors ``enforce_pending_edit_policy`` so the bulk "Edit Details" form can
    show only the fields the save will actually accept.
    """
    if record is None or getattr(record, "pk", None) is None:
        return None
    if getattr(_thread_local, "skip_approval_edit_guard", False):
        return None
    content_type = HorillaContentType.objects.get_for_model(record.__class__)
    tracked = list(
        ApprovalInstance.objects.filter(
            content_type=content_type,
            object_id=str(record.pk),
            status__in=("pending", "rejected"),
        ).select_related("current_step")
    )
    if not tracked:
        return None

    pending = [i for i in tracked if i.status == "pending"]
    allowed = set()
    if pending:
        approvals = [i for i in pending if is_user_pending_approver(i, user)]
        for approval in approvals:
            policy = get_waiting_policy(approval)
            scope = policy.get("scope", "no_fields")
            if scope == "all_fields":
                return None
            if scope == "specific_fields":
                allowed.update(policy.get("fields", []) or [])
        return allowed

    for approval in tracked:
        policy = get_rejected_policy(approval)
        scope = policy.get("scope", "all_fields")
        if scope == "all_fields":
            return None
        if scope == "specific_fields":
            allowed.update(policy.get("fields", []) or [])
    return allowed
