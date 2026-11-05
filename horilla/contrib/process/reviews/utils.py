"""Utility helpers for matching review conditions and syncing jobs."""

# Standard library imports
from decimal import Decimal

# Third-party imports (Django)
from django.utils.dateparse import parse_date, parse_datetime

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.utils.middlewares import get_current_request
from horilla.db import models as db_models
from horilla.urls import reverse_lazy
from horilla.utils import timezone
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import ReviewCondition, ReviewJob, ReviewProcess, ReviewRuleCondition


def _send_pending_review_notification(job, record):
    """Send a notification to the assigned approver for a newly created review job."""
    try:
        from horilla.contrib.notifications.methods import create_notification
    except Exception:
        return
    try:
        assignee = job.assigned_to
        if not getattr(assignee, "pk", None):
            return
        record_label = str(record) if record else "-"
        process_label = str(job.reviews)
        redirect_url = reverse_lazy("reviews:review_job_view")
        create_notification(
            user=assignee,
            message=_(
                "You have a pending review request for %(record)s in %(process)s."
            )
            % {"record": record_label, "process": process_label},
            sender=None,
            instance=record,
            url=redirect_url,
        )
    except Exception:
        pass


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
        result = _compare_text_operator(operator, left, right)
    elif operator in ("gt", "gte", "lt", "lte"):
        result = _compare_numeric_operator(operator, left, right)
    elif operator == "isnull":
        result = not left.strip()
    elif operator == "isnotnull":
        result = bool(left.strip())
    else:
        result = False
    return result


def evaluate_condition(instance, condition):
    """Evaluate a single condition against a record instance."""
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

    if (is_date or is_datetime) and operator in (
        "isnull",
        "isnotnull",
        "exact",
        "gt",
        "lt",
    ):
        result = _compare_date_operator(
            operator, raw_value, value, parse_date if is_date else parse_datetime
        )
    else:
        left = "" if raw_value is None else str(raw_value)
        right = "" if value is None else str(value)
        result = _compare_string_operator(operator, left, right)
    return result


def evaluate_conditions(instance, conditions):
    """Evaluate a list of conditions against a record instance, respecting logical operators."""
    conditions = list(conditions)
    if not conditions:
        return True
    result = None
    for cond in conditions:
        current = evaluate_condition(instance, cond)
        if result is None:
            result = current
            continue
        result = (
            (result or current)
            if getattr(cond, "logical_operator", "and") == "or"
            else (result and current)
        )
    return bool(result)


def _get_approvers(rule):
    if not rule:
        return []
    if rule.approver_type == "role":
        return list(User.objects.filter(role__in=rule.approver_roles.all()).distinct())
    return list(rule.approver_users.all())


def _get_snapshot(record, review_fields):
    snapshot = {}
    for field_name in review_fields or []:
        value = getattr(record, field_name, None)
        snapshot[field_name] = None if value is None else str(value)
    return snapshot


def sync_approval_for_record_if_available(record):
    """
    Trigger approval resync if approvals app is installed.

    Uses created=None to run an explicit reconciliation pass (both create/edit
    trigger types), while approval-side logic suppresses instances when review
    is still pending.
    """
    if not record:
        return
    try:
        from horilla.contrib.process.approvals.utils import (
            sync_approval_instances_for_record,
        )
    except Exception:
        return
    try:
        sync_approval_instances_for_record(record, created=None)
    except Exception:
        # Review flow should stay resilient even if approval sync fails.
        pass


def record_has_pending_review_jobs(record):
    """Return True when the record has any active pending review jobs."""
    if not record:
        return False
    content_type = HorillaContentType.objects.get_for_model(record.__class__)
    return ReviewJob.all_objects.filter(
        content_type=content_type,
        object_id=record.pk,
        status=ReviewJob.STATUS_PENDING,
        is_active=True,
    ).exists()


def _review_field_attname(model, field_name):
    """Return the concrete column attribute for a reviewed field, or None."""
    try:
        field = model._meta.get_field(field_name)
    except Exception:
        return None
    if not getattr(field, "concrete", False) or field.many_to_many:
        return None
    return field.attname


def _get_condition_field_names(process):
    """Fields used in the process entry criteria and rule criteria."""
    names = set(
        ReviewCondition.objects.filter(reviews=process).values_list("field", flat=True)
    )
    names.update(
        ReviewRuleCondition.objects.filter(review_rule__reviews=process).values_list(
            "field", flat=True
        )
    )
    return names


def capture_review_save_context(instance, update_fields=None):
    """
    Remember, before a save, whether it is a create and which reviewed fields
    changed. Called from pre_save so it is in place whichever of the review
    post_save handler or the approval hook reaches
    `refresh_review_jobs_for_record` first.
    """
    skip_edit = instance.__dict__.pop("_review_skip_edit", False)
    instance._review_is_create = bool(instance._state.adding)
    instance._review_changed_fields = set()
    if instance._state.adding or skip_edit or not instance.pk:
        return

    model = instance.__class__
    content_type = HorillaContentType.objects.get_for_model(model)
    processes = ReviewProcess.objects.filter(
        model=content_type, is_active=True, trigger_on_edit=True
    )
    names = set()
    for process in processes:
        names.update(process.review_fields or [])
        names.update(_get_condition_field_names(process))
    if not names:
        return

    saved_names = set(update_fields) if update_fields is not None else None
    attnames = {}
    for name in names:
        attname = _review_field_attname(model, name)
        if attname and (
            saved_names is None or name in saved_names or attname in saved_names
        ):
            attnames[name] = attname
    if not attnames:
        return

    old = (
        model._base_manager.filter(pk=instance.pk)
        .values(*set(attnames.values()))
        .first()
    )
    if old is None:
        return
    instance._review_changed_fields = {
        name
        for name, attname in attnames.items()
        if old[attname] != getattr(instance, attname, None)
    }


def _flag_moved_to_pending_review(record):
    """
    Remember on the current request that this edit moved the record into pending
    review, so the detail view can warn the user (see view_extensions.py).
    """
    request = get_current_request()
    if request is None:
        return
    moved = getattr(request, "_review_moved_records", None)
    if moved is None:
        moved = set()
        request._review_moved_records = moved
    moved.add((record._meta.app_label, record._meta.model_name, str(record.pk)))


def was_moved_to_pending_review(request, app_label, model_name, pk):
    """True if an edit handled by this request moved the record into pending review."""
    moved = getattr(request, "_review_moved_records", None) or set()
    return (app_label, str(model_name).lower(), str(pk)) in moved


def _reset_job_for_edited_fields(job, changed_fields, snapshot, company_id):
    """
    Bring an existing job in line with an edited record.

    Reviewed fields that changed go back to pending for this approver, so the
    old decision on the old value no longer stands. Returns True when an
    existing decision was reset (approver should hear about it).
    """
    info = dict(job.additional_info or {})
    field_reviews = dict(info.get("field_reviews") or {})
    history = list(info.get("review_history") or [])
    job_snapshot = dict(job.review_fields_snapshot or {})
    now = timezone.now().isoformat()
    decision_reset = False

    for field_name in changed_fields:
        job_snapshot[field_name] = snapshot.get(field_name)
        meta = field_reviews.get(field_name) or {}
        if meta.get("status") in (ReviewJob.STATUS_APPROVED, ReviewJob.STATUS_REJECTED):
            history.append({**meta, "field": field_name, "reset_at": now})
            field_reviews[field_name] = {
                "status": ReviewJob.STATUS_PENDING,
                "reset_at": now,
                "reset_reason": "record_edited",
            }
            decision_reset = True

    info["field_reviews"] = field_reviews
    info["review_history"] = history
    job.additional_info = info
    job.review_fields_snapshot = job_snapshot
    update_fields = ["additional_info", "review_fields_snapshot", "updated_at"]

    if job.status == ReviewJob.STATUS_APPROVED:
        job.status = ReviewJob.STATUS_PENDING
        job.reviewed_by = None
        job.reviewed_at = None
        update_fields += ["status", "reviewed_by", "reviewed_at"]
        decision_reset = True
    if company_id and job.company_id != company_id:
        job.company_id = company_id
        update_fields.append("company")
    job.save(update_fields=update_fields)
    return decision_reset


def refresh_review_jobs_for_record(record):
    """
    Create review jobs for a record that satisfies a review process.

    Runs once per save (the create/edit context captured in pre_save is
    consumed here, so the review signal and the approval hook never both act):
    - On create: for processes with `trigger_on_create`.
    - On edit: for processes with `trigger_on_edit`, and only when one of the
      process's reviewed fields or criteria fields changed. A changed reviewed
      field has its decisions reset to pending; a changed criteria field can
      start (or drop) the review. Edits to other fields do nothing.

    Does not call approval sync; safe to invoke from the approvals app so review
    runs before approval matching regardless of INSTALLED_APPS order or which app
    is enabled.
    """
    if not record:
        return
    is_create = getattr(record, "_review_is_create", None)
    if is_create is None:
        return
    changed_fields = set(getattr(record, "_review_changed_fields", None) or ())
    record._review_is_create = None
    record._review_changed_fields = None
    if not is_create and not changed_fields:
        return

    content_type = HorillaContentType.objects.get_for_model(record.__class__)
    processes = ReviewProcess.objects.filter(model=content_type, is_active=True)
    record_company_id = getattr(record, "company_id", None)

    for process in processes:
        if is_create:
            if not process.trigger_on_create:
                continue
            process_changed = set()
        else:
            if not process.trigger_on_edit:
                continue
            process_changed = changed_fields & set(process.review_fields or [])
            # A criteria field (e.g. Lead Stage) can make the record start or stop
            # matching, so those edits also re-evaluate the process.
            criteria_changed = changed_fields & _get_condition_field_names(process)
            if not process_changed and not criteria_changed:
                continue

        entry_ok = evaluate_conditions(
            record, process.conditions.all().order_by("order", "created_at")
        )
        rules = list(process.rules.all())
        if not rules:
            continue

        snapshot = _get_snapshot(record, process.review_fields)

        for rule in rules:
            rule_ok = evaluate_conditions(
                record, rule.conditions.all().order_by("order", "created_at")
            )
            is_match = entry_ok and rule_ok
            approvers = _get_approvers(rule)
            approver_ids = {u.pk for u in approvers}

            pending_qs = ReviewJob.all_objects.filter(
                reviews=process,
                review_rule=rule,
                content_type=content_type,
                object_id=record.pk,
                status=ReviewJob.STATUS_PENDING,
            )

            if not is_match:
                pending_qs.delete()
                continue

            pending_qs.exclude(assigned_to_id__in=approver_ids).delete()

            new_job_ids = set()
            for user in approvers:
                job, created = ReviewJob.all_objects.get_or_create(
                    reviews=process,
                    review_rule=rule,
                    content_type=content_type,
                    object_id=record.pk,
                    assigned_to=user,
                    defaults={
                        "review_fields_snapshot": snapshot,
                        "company_id": record_company_id,
                    },
                )
                if created:
                    new_job_ids.add(job.pk)
                    _notify_approver_pending_review(job)
                    if not is_create:
                        _flag_moved_to_pending_review(record)

            if not process_changed:
                continue
            existing_jobs = ReviewJob.all_objects.filter(
                reviews=process,
                review_rule=rule,
                content_type=content_type,
                object_id=record.pk,
                is_active=True,
            ).exclude(pk__in=new_job_ids)
            for job in existing_jobs:
                if _reset_job_for_edited_fields(
                    job, process_changed, snapshot, record_company_id
                ):
                    _notify_approver_pending_review(job)
                    _flag_moved_to_pending_review(record)


def _notify_approver_pending_review(job):
    """
    Send a notification to the assigned approver when a new review job is created.
    Only fires when notify_on_submission is enabled on the review process.
    """
    if not job:
        return
    try:
        from horilla.contrib.notifications.methods import create_notification
    except Exception:
        return

    process = job.reviews
    if not getattr(process, "notify_on_submission", False):
        return

    approver = job.assigned_to
    if not getattr(approver, "pk", None):
        return

    record = job.content_object
    redirect_url = reverse_lazy("reviews:review_job_view")
    try:
        create_notification(
            user=approver,
            message=_(
                "You have a pending review request for %(record)s in %(process)s."
            )
            % {
                "record": str(record) if record else "-",
                "process": str(process),
            },
            instance=record,
            url=redirect_url,
        )
    except Exception:
        pass


def sync_jobs_for_record(record):
    """
    Create review jobs for a just-saved record (used by review post_save).

    Approval resync is handled by approvals (which calls
    refresh_review_jobs_for_record before matching rules) and by
    sync_approval_for_record_if_available when review completes in the UI.
    """
    refresh_review_jobs_for_record(record)
