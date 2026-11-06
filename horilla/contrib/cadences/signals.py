"""
Signals for the cadences app
"""

import logging

# Standard library imports
import sys
from datetime import timedelta

# Third-party imports (Django)
from django.dispatch import receiver

from horilla.contrib.activity.models import Activity
from horilla.contrib.automations.methods import evaluate_condition
from horilla.contrib.core.models import HorillaContentType
from horilla.db import transaction
from horilla.db.models.signals import post_save, pre_save

# First party imports (Horilla)
from horilla.utils import timezone

# Local imports
from . import services
from .models import Cadence, CadenceEnrollment, CadenceFollowUp

logger = logging.getLogger(__name__)


def _is_migrate_command():
    return "migrate" in sys.argv


def _is_cadence_supported_instance(instance):
    from horilla.registry.feature import FEATURE_REGISTRY

    return instance.__class__ in FEATURE_REGISTRY["cadence_models"]


def _evaluate_cadence_conditions(cadence, instance):
    conditions = getattr(cadence, "_prefetched_objects_cache", {}).get("conditions")
    if conditions is None:
        conditions = cadence.conditions.all()
    conditions = sorted(
        conditions, key=lambda condition: (condition.order, condition.id)
    )
    if not conditions:
        return True
    result = None
    for idx, condition in enumerate(conditions):
        current = evaluate_condition(condition, instance)
        if idx == 0 or condition.logical_operator == "and":
            result = current if result is None else (result and current)
        elif condition.logical_operator == "or":
            result = current if result is None else (result or current)
        else:
            result = current if result is None else (result and current)
    return bool(result)


def _dedupe_runtime_activities_for_instance(instance):
    """
    Keep only one runtime activity per (enrollment, follow-up) for a record.
    Older buggy runs may have inserted duplicates; we keep the earliest one.
    Items from before enrollments existed have no enrollment id and are keyed by cadence.
    """
    content_type = HorillaContentType.objects.get_for_model(instance.__class__)
    qs = Activity.all_objects.filter(
        content_type=content_type, object_id=instance.pk
    ).order_by("created_at", "id")
    seen = set()
    duplicate_ids = []
    for activity in qs.only("id", "additional_info"):
        info = activity.additional_info or {}
        runtime = info.get("cadence_runtime") if isinstance(info, dict) else None
        if not runtime:
            continue
        cadence_id = runtime.get("cadence_id")
        followup_id = runtime.get("followup_id")
        if not cadence_id or not followup_id:
            continue
        key = (runtime.get("enrollment_id") or ("legacy", cadence_id), followup_id)
        if key in seen:
            duplicate_ids.append(activity.id)
        else:
            seen.add(key)
    if duplicate_ids:
        Activity.all_objects.filter(id__in=duplicate_ids).delete()


def _activity_status_key(activity):
    if activity.activity_type == "task":
        return activity.status
    if activity.activity_type == "log_call":
        return activity.status
    return None


def _run_automatic_enrollment(cadence, instance):
    """Start (or top up) the automatic enrollment of ``instance`` in ``cadence``."""
    enrollment, _created = services.get_or_create_auto_enrollment(cadence, instance)
    if not enrollment or enrollment.status != "active":
        return
    services.create_first_followups(enrollment, instance)
    services.refresh_status(enrollment, allow_fail=False)


def _trigger_initial_followups(instance):
    if not instance.pk:
        return []
    content_type = HorillaContentType.objects.get_for_model(instance.__class__)
    cadences = list(
        Cadence.objects.filter(module=content_type, is_active=True)
        .prefetch_related("conditions", "followups")
        .order_by("-created_at")
    )
    for cadence in cadences:
        if not _evaluate_cadence_conditions(cadence, instance):
            continue
        _run_automatic_enrollment(cadence, instance)
    return cadences


def ensure_initial_followups_for_instance(instance):
    """Public helper: create missing FU1 runtime activities for one record."""
    if not instance or not getattr(instance, "pk", None):
        return []
    if not _is_cadence_supported_instance(instance):
        return []
    _dedupe_runtime_activities_for_instance(instance)
    return _trigger_initial_followups(instance)


def _trigger_initial_followups_for_cadence(cadence):
    model = cadence.module.model_class() if cadence.module_id else None
    if not model:
        return
    try:
        records = model.objects.all()
    except Exception:
        return
    for instance in records.iterator():
        try:
            if not _evaluate_cadence_conditions(cadence, instance):
                continue
            _run_automatic_enrollment(cadence, instance)
        except Exception:
            logger.exception(
                "Cadence backfill failed for record %s:%s in cadence %s",
                instance.__class__.__name__,
                getattr(instance, "pk", None),
                cadence.pk,
            )
    # Follow-ups added later also reach records that were enrolled manually.
    manual = CadenceEnrollment.all_objects.filter(
        cadence=cadence, source="manual", status="active"
    )
    for enrollment in manual:
        try:
            instance = enrollment.related_object
            if instance is not None:
                services.create_first_followups(enrollment, instance)
        except Exception:
            logger.exception(
                "Cadence backfill failed for enrollment %s in cadence %s",
                enrollment.pk,
                cadence.pk,
            )


def _resolve_enrollment_for_activity(activity, runtime, cadence, instance):
    """Enrollment the activity belongs to; items from before enrollments are adopted."""
    enrollment_id = runtime.get("enrollment_id")
    if enrollment_id:
        return CadenceEnrollment.all_objects.filter(
            pk=enrollment_id, cadence_id=cadence.pk
        ).first()
    # Item created before enrollments existed: same rule as before (conditions must
    # match), then it joins the automatic enrollment created for it.
    if not _evaluate_cadence_conditions(cadence, instance):
        return None
    enrollment = services.adopt_legacy_enrollment(cadence, instance)
    if enrollment:
        return enrollment
    fresh = Activity.all_objects.filter(pk=activity.pk).first()
    fresh_id = (
        ((fresh.additional_info or {}).get("cadence_runtime") or {}).get(
            "enrollment_id"
        )
        if fresh
        else None
    )
    if not fresh_id:
        return None
    return CadenceEnrollment.all_objects.filter(
        pk=fresh_id, cadence_id=cadence.pk
    ).first()


def _trigger_next_followups_from_activity(activity):
    info = activity.additional_info or {}
    runtime = info.get("cadence_runtime") if isinstance(info, dict) else None
    if not runtime:
        return
    cadence_id = runtime.get("cadence_id")
    source_followup_id = runtime.get("followup_id")
    if not cadence_id or not source_followup_id:
        return
    model = activity.content_type.model_class() if activity.content_type_id else None
    if not model:
        return
    instance = model.objects.filter(pk=activity.object_id).first()
    if not instance:
        return
    cadence = Cadence.objects.filter(pk=cadence_id, is_active=True).first()
    if not cadence:
        return
    enrollment = _resolve_enrollment_for_activity(activity, runtime, cadence, instance)
    # Un-enrolled / completed runs never advance, which also keeps the "cancelled"
    # status set while un-enrolling from triggering follow-ups.
    if not enrollment or enrollment.status != "active":
        return
    # Automatic enrollments follow the cadence conditions; manual ones ignore them.
    if enrollment.source == "auto" and not _evaluate_cadence_conditions(
        cadence, instance
    ):
        return
    status_key = _activity_status_key(activity)
    source_followup = CadenceFollowUp.objects.filter(
        pk=source_followup_id, cadence_id=cadence.pk
    ).first()
    if status_key and source_followup:
        services.create_next_followups(
            enrollment, instance, source_followup, status_key
        )
    services.refresh_status(enrollment)


def _runtime_activity_owners(followup, activities):
    """
    ``{activity pk: owner id}`` for the pending activities of ``followup``,
    with the same rule as when they were created. Activities left out keep
    their owner. The records are read once per module, not once per activity.
    The owner note in each activity's runtime info is refreshed in place.

    A record that is gone keeps its activity's owner as it is.
    """
    fixed_id, from_record = services.followup_owner_setting(followup)
    if not from_record:
        for activity in activities:
            services.note_owner_source(_runtime_of(activity), "fixed", False)
        if not fixed_id:
            return {}
        return {activity.pk: fixed_id for activity in activities}

    object_ids = {}
    for activity in activities:
        object_ids.setdefault(activity.content_type_id, set()).add(activity.object_id)
    records = {}
    for content_type_id, ids in object_ids.items():
        model = HorillaContentType.objects.get_for_id(content_type_id).model_class()
        if model is None:
            continue
        for pk, record in model._base_manager.in_bulk(ids).items():
            records[(content_type_id, pk)] = record

    owners = {}
    for activity in activities:
        record = records.get((activity.content_type_id, activity.object_id))
        if record is None:
            continue
        owner_id, source = services.resolve_followup_owner(followup, record)
        services.note_owner_source(_runtime_of(activity), source, True)
        if owner_id:
            owners[activity.pk] = owner_id
    return owners


def _runtime_of(activity):
    """The ``cadence_runtime`` dict of ``activity`` (edited in place)."""
    if not isinstance(activity.additional_info, dict):
        activity.additional_info = {}
    runtime = activity.additional_info.get("cadence_runtime")
    if not isinstance(runtime, dict):
        runtime = activity.additional_info["cadence_runtime"] = {}
    return runtime


def _sync_runtime_activities_for_followup(followup):
    """
    Keep existing cadence runtime activities in sync when follow-up config changes.
    Focus on pending activities so completed history is not rewritten.
    """
    activities = list(
        Activity.all_objects.filter(
            additional_info__cadence_runtime__followup_id=followup.pk
        ).exclude(status="completed")
    )
    owners = _runtime_activity_owners(followup, activities)
    now = timezone.now()
    for activity in activities:
        owner_id = owners.get(activity.pk)
        start_base = activity.start_datetime or activity.created_at or now
        if followup.followup_type == "task" and activity.activity_type == "task":
            subject_text = followup.subject or activity.subject
            activity.subject = subject_text
            activity.title = subject_text
            activity.task_priority = followup.task_priority or activity.task_priority
            if owner_id:
                activity.owner_id = owner_id
            activity.due_datetime = start_base + timedelta(
                days=(followup.due_after_days or 0)
            )
            activity.save(
                update_fields=[
                    "subject",
                    "title",
                    "task_priority",
                    "owner",
                    "due_datetime",
                    "additional_info",
                    "updated_at",
                    "updated_by",
                ]
            )
            if owner_id:
                activity.assigned_to.set([owner_id])
        elif followup.followup_type == "call" and activity.activity_type == "log_call":
            call_text = followup.purpose or activity.subject
            activity.subject = call_text
            activity.title = call_text
            activity.call_purpose = followup.purpose
            if owner_id:
                activity.owner_id = owner_id
            shifted = start_base + timedelta(days=(followup.call_start_after_days or 0))
            activity.start_datetime = shifted
            activity.due_datetime = shifted
            activity.save(
                update_fields=[
                    "subject",
                    "title",
                    "call_purpose",
                    "owner",
                    "start_datetime",
                    "due_datetime",
                    "additional_info",
                    "updated_at",
                    "updated_by",
                ]
            )


@receiver(post_save)
def cadence_apply_on_record_save(sender, instance, **kwargs):
    """On save of any record, trigger cadence FU1 creation if conditions are met and not already created."""
    if _is_migrate_command():
        return
    if sender in {Cadence, Activity}:
        return
    if not _is_cadence_supported_instance(instance):
        return
    try:
        _trigger_initial_followups(instance)
    except Exception:
        logger.exception(
            "Cadence initial trigger failed for %s:%s", sender, instance.pk
        )


@receiver(pre_save, sender=Activity)
def cache_previous_activity_status(sender, instance, **kwargs):
    """Cache the previous status of the activity before saving, so we can detect status changes in post_save."""
    if not instance.pk:
        instance._cadence_previous_status = None
        return
    prev = (
        Activity.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
    )
    instance._cadence_previous_status = prev


@receiver(post_save, sender=Activity)
def cadence_progress_on_activity_status(sender, instance, created, **kwargs):
    """When an activity is saved, if it has cadence runtime info and its status changed, trigger next follow-ups."""
    if _is_migrate_command():
        return
    # Only advance cadence on status changes after creation.
    if created:
        return
    prev_status = getattr(instance, "_cadence_previous_status", None)
    if prev_status == instance.status:
        return
    try:
        _trigger_next_followups_from_activity(instance)
    except Exception:
        logger.exception("Cadence progression failed for activity %s", instance.pk)


@receiver(post_save, sender=Cadence)
def cadence_backfill_existing_records(sender, instance, **kwargs):
    """When cadence is saved/updated, create FU1 runtime activities for matching existing records."""
    if _is_migrate_command() or not instance.is_active:
        return
    transaction.on_commit(lambda: _trigger_initial_followups_for_cadence(instance))


@receiver(post_save, sender=CadenceFollowUp)
def cadence_fu1_backfill_on_followup_save(sender, instance, **kwargs):
    """When FU1 is saved, backfill initial runtime activities for matching existing records."""
    if _is_migrate_command():
        return
    if instance.followup_number != 1 or not instance.cadence_id:
        return
    cadence = instance.cadence
    if not cadence.is_active:
        return
    transaction.on_commit(lambda: _trigger_initial_followups_for_cadence(cadence))
    transaction.on_commit(lambda: _sync_runtime_activities_for_followup(instance))


@receiver(post_save, sender=CadenceFollowUp)
def cadence_runtime_sync_on_followup_update(sender, instance, **kwargs):
    """Sync existing runtime activities whenever a follow-up is updated."""
    if _is_migrate_command():
        return
    try:
        _sync_runtime_activities_for_followup(instance)
    except Exception:
        logger.exception("Cadence runtime sync failed for followup %s", instance.pk)
