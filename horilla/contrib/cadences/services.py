"""
Cadence enrollment lifecycle and runtime item creation.

Every run of a cadence for a record is a ``CadenceEnrollment``. All runtime items
(activities and mails) created for a run carry ``cadence_runtime.enrollment_id``,
so runs never see, advance or cancel each other's items, even when the same record
is enrolled in several cadences or enrolled again in the same one.

Items created before enrollments existed have no ``enrollment_id``. They are adopted
lazily by ``adopt_legacy_enrollment`` the first time their record and cadence are
touched, so no data migration is needed.
"""

# Standard library imports
import logging
from datetime import timedelta

# Third-party imports
from dateutil.relativedelta import relativedelta

# Third-party imports (Django)
from django.db import IntegrityError

from horilla.contrib.activity.models import Activity
from horilla.contrib.automations.methods import resolve_mail_recipients
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.mail.models import (
    HorillaMail,
    HorillaMailConfiguration,
    HorillaMailTemplate,
)
from horilla.contrib.mail.services import HorillaMailManager
from horilla.contrib.utils.middlewares import _thread_local

# First party imports (Horilla)
from horilla.db import transaction
from horilla.db.models import Max, Q
from horilla.utils import timezone
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .followup_types import (
    BUILTIN_KEYS,
    CHANNEL_SENT_STATUS,
    TEMPLATE_MAIL,
    TEMPLATE_NOTIFICATION,
    get_channel_template_kind,
    get_followup_channel,
    is_builtin_followup_type,
)
from .models import Cadence, CadenceEnrollment, CadenceScheduledFollowUp

logger = logging.getLogger(__name__)

# Activity statuses that finish a follow-up; everything else is still open.
CLOSED_ACTIVITY_STATUSES = ("completed", "cancelled")
# Mail statuses that mean "not sent yet".
OPEN_MAIL_STATUSES = ("scheduled",)
FAILED_MAIL_STATUSES = ("failed", "bounced")
# Delays up to this long are queued for their exact time. Longer ones are left to the
# periodic task, because Redis redelivers waiting tasks after its visibility timeout.
EXACT_TIMING_MAX_DELAY = timedelta(hours=1)


class EnrollmentError(Exception):
    """Raised when a record cannot be enrolled or un-enrolled; message is user facing."""


# ---------------------------------------------------------------------------
# Runtime item lookup
# ---------------------------------------------------------------------------


def _content_type_for(instance):
    return HorillaContentType.objects.get_for_model(instance.__class__)


def _runtime_of(item):
    info = item.additional_info or {}
    runtime = info.get("cadence_runtime") if isinstance(info, dict) else None
    return runtime if isinstance(runtime, dict) else {}


def enrollment_activities(enrollment):
    """Activities created by this enrollment."""
    return Activity.all_objects.filter(
        content_type_id=enrollment.content_type_id,
        object_id=enrollment.object_id,
        additional_info__cadence_runtime__enrollment_id=enrollment.pk,
    )


def enrollment_mails(enrollment):
    """Mails created by this enrollment."""
    return HorillaMail.objects.filter(
        content_type_id=enrollment.content_type_id,
        object_id=enrollment.object_id,
        additional_info__cadence_runtime__enrollment_id=enrollment.pk,
    )


def enrollment_channel_runs(enrollment):
    """
    Delivery channel follow-ups this enrollment ran (sent or failed).

    A channel follow-up leaves no activity or mail, so its run is the
    ``CadenceScheduledFollowUp`` row; pending rows are still waiting.
    """
    return (
        CadenceScheduledFollowUp.all_objects.filter(enrollment=enrollment)
        .exclude(status="pending")
        .exclude(followup__followup_type__in=BUILTIN_KEYS)
    )


def existing_followup_ids(enrollment):
    """Follow-up ids already created in this enrollment (used to avoid duplicates)."""
    ids = set()
    for item in enrollment_activities(enrollment).only("additional_info"):
        followup_id = _runtime_of(item).get("followup_id")
        if followup_id:
            ids.add(followup_id)
    for item in enrollment_mails(enrollment).only("additional_info"):
        followup_id = _runtime_of(item).get("followup_id")
        if followup_id:
            ids.add(followup_id)
    ids.update(
        CadenceScheduledFollowUp.all_objects.filter(enrollment=enrollment).values_list(
            "followup_id", flat=True
        )
    )
    return ids


def _legacy_items(cadence, instance, content_type):
    """Runtime activities/mails of this cadence+record that have no enrollment yet."""
    activities = [
        item
        for item in Activity.all_objects.filter(
            content_type=content_type,
            object_id=instance.pk,
            additional_info__cadence_runtime__cadence_id=cadence.pk,
        )
        if not _runtime_of(item).get("enrollment_id")
    ]
    mails = [
        item
        for item in HorillaMail.objects.filter(
            content_type=content_type,
            object_id=instance.pk,
            additional_info__cadence_runtime__cadence_id=cadence.pk,
        )
        if not _runtime_of(item).get("enrollment_id")
    ]
    return activities, mails


# ---------------------------------------------------------------------------
# Runtime item creation
# ---------------------------------------------------------------------------


def _runtime_info(cadence, followup, enrollment):
    return {
        "cadence_runtime": {
            "cadence_id": cadence.pk,
            "enrollment_id": enrollment.pk,
            "run_number": enrollment.run_number,
            "followup_id": followup.pk,
            "followup_number": followup.followup_number,
            "branch_from_id": followup.branch_from_id,
        }
    }


def _resolve_outgoing_mail_sender(company):
    sender = None
    if company:
        sender = (
            HorillaMailConfiguration.all_objects.filter(
                company=company, mail_channel="outgoing", is_primary=True
            ).first()
            or HorillaMailConfiguration.all_objects.filter(
                company=company, mail_channel="outgoing"
            ).first()
        )
    if not sender:
        sender = HorillaMailConfiguration.all_objects.filter(
            mail_channel="outgoing", is_primary=True
        ).first()
    return sender


def _create_email_draft_for_followup(
    instance, cadence, followup, enrollment, content_type
):
    if not followup.email_template_id:
        return None
    template = followup.email_template
    actor = getattr(instance, "updated_by", None) or getattr(
        instance, "created_by", None
    )
    company = getattr(instance, "company", None)
    sender = _resolve_outgoing_mail_sender(company)
    if not sender:
        logger.warning(
            "Cadence email follow-up skipped (no outgoing server): cadence=%s followup=%s record=%s:%s",
            cadence.pk,
            followup.pk,
            instance.__class__.__name__,
            instance.pk,
        )
        return None
    recipients = resolve_mail_recipients(followup.to or "", instance, actor)
    draft = HorillaMail.objects.create(
        sender=sender,
        to=",".join(recipients),
        subject=template.subject or "",
        body=template.body or "",
        content_type=content_type,
        object_id=instance.pk,
        mail_status="draft",
        company=company,
        created_by=actor if getattr(actor, "pk", None) else None,
        updated_by=actor if getattr(actor, "pk", None) else None,
        additional_info=_runtime_info(cadence, followup, enrollment),
    )
    # Send cadence emails immediately; status is updated to sent/failed by mail service.
    try:
        template_context = {
            "instance": instance,
            "user": actor,
            "active_company": company,
            "request": getattr(_thread_local, "request", None),
        }
        HorillaMailManager.send_mail(draft, context=template_context)
        draft.refresh_from_db()
    except Exception:
        logger.exception(
            "Cadence email follow-up send failed: cadence=%s followup=%s record=%s:%s",
            cadence.pk,
            followup.pk,
            instance.__class__.__name__,
            instance.pk,
        )
    return draft


class ChannelFollowUpMessage:
    """
    What a delivery channel's ``send()`` reads for one cadence follow-up.

    Channels are written for Automations and read the message settings from
    the ``HorillaAutomation`` they get as ``automation``: ``title``, ``pk``,
    ``company``, ``mail_template``, ``notification_template``,
    ``mail_server``, ``mail_to``, ``created_by``, ``updated_by``. A cadence
    follow-up passes this object instead, built from its ``channel_config``.
    ``cadence``, ``followup`` and ``enrollment`` are the cadence objects.
    """

    def __init__(self, enrollment, followup, channel, template=None, company=None):
        cadence = enrollment.cadence
        kind = get_channel_template_kind(channel)
        self.cadence = cadence
        self.followup = followup
        self.enrollment = enrollment
        self.pk = followup.pk
        self.title = cadence.name
        self.company = company
        self.mail_template = template if kind == TEMPLATE_MAIL else None
        self.notification_template = template if kind == TEMPLATE_NOTIFICATION else None
        # No mail server is chosen on a follow-up: the mail channel picks the
        # company's outgoing server.
        self.mail_server = None
        self.mail_to = (followup.channel_config or {}).get("to", "") or ""
        self.created_by = cadence.created_by
        self.updated_by = cadence.updated_by
        self.additional_info = {}

    def __str__(self):
        return str(self.title)


def _channel_followup_template(followup, channel, company):
    """
    ``(template, ok)`` for a channel follow-up: ``ok`` is false when the
    channel needs a template and the one in ``channel_config`` is missing or
    belongs to another company.
    """
    from horilla.contrib.notifications.models import NotificationTemplate

    kind = get_channel_template_kind(channel)
    if kind is None:
        return None, True
    model = (
        NotificationTemplate if kind == TEMPLATE_NOTIFICATION else HorillaMailTemplate
    )
    templates = model.all_objects.all()
    if company is not None:
        templates = templates.filter(Q(company=company) | Q(company__isnull=True))
    try:
        template_id = int((followup.channel_config or {}).get("template_id"))
    except (ValueError, TypeError):
        return None, False
    template = templates.filter(pk=template_id).first()
    return template, template is not None


def _deliver_channel_followup(instance, enrollment, followup, channel):
    """
    Hand a channel follow-up's message to ``channel``.

    Returns ``None`` when it was sent, else why it was not (logged).
    """
    cadence = enrollment.cadence
    actor = (
        getattr(instance, "updated_by", None)
        or getattr(instance, "created_by", None)
        or cadence.updated_by
        or cadence.created_by
    )
    company = getattr(instance, "company", None) or cadence.company
    template, ok = _channel_followup_template(followup, channel, company)
    if not ok:
        error = str(_("The follow-up's template was not found."))
    else:
        to = (followup.channel_config or {}).get("to", "") or ""
        recipients = channel.resolve_recipients(to, instance, actor)
        if not recipients:
            error = str(_("No recipient could be resolved."))
        else:
            message = ChannelFollowUpMessage(
                enrollment, followup, channel, template, company
            )
            context = {
                "instance": instance,
                "user": actor,
                "self": actor,
                "active_company": company,
                "request": getattr(_thread_local, "request", None),
            }
            try:
                channel.send(message, instance, recipients, context, actor)
                return None
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.exception(
                    "Cadence %s follow-up send failed: cadence=%s followup=%s record=%s:%s",
                    channel.key,
                    cadence.pk,
                    followup.pk,
                    instance.__class__.__name__,
                    instance.pk,
                )
                return str(exc)
    logger.warning(
        "Cadence %s follow-up not sent (%s): cadence=%s followup=%s record=%s:%s",
        channel.key,
        error,
        cadence.pk,
        followup.pk,
        instance.__class__.__name__,
        instance.pk,
    )
    return error


def _record_channel_run(enrollment, followup, error, trigger_time):
    """
    Record the run of a channel follow-up and return its row.

    A channel leaves no activity or mail behind, so the run is recorded as a
    ``CadenceScheduledFollowUp`` (``completed``, or ``failed`` with ``error``),
    which is what keeps the follow-up from running again in this enrollment
    and what ``refresh_status`` reads. A follow-up that waited for its delay
    already has that row: only the reason is written on it here, and
    ``run_scheduled_followup`` sets its status.
    """
    now = trigger_time or timezone.now()
    run, created = CadenceScheduledFollowUp.all_objects.get_or_create(
        enrollment=enrollment,
        followup=followup,
        defaults={
            "scheduled_at": now,
            "status": "failed" if error else "completed",
            "executed_at": now,
            "error_message": error or "",
            "company": enrollment.company,
        },
    )
    if not created and error:
        run.error_message = error
        run.save(update_fields=["error_message", "updated_at"])
    return run


def _send_channel_followup(instance, enrollment, followup, channel, trigger_time):
    """
    Send a channel follow-up and record the run.

    Returns the row when the message was sent, else ``None``.
    """
    error = _deliver_channel_followup(instance, enrollment, followup, channel)
    run = _record_channel_run(enrollment, followup, error, trigger_time)
    return None if error else run


def create_followup_item(instance, enrollment, followup, trigger_time=None):
    """
    Create the task / call / email for ``followup`` inside ``enrollment``, or
    send its message when it is a delivery channel follow-up.

    A new task or call already has a status (for example a call starts as
    Scheduled), and creating it is not a status change, so the signal never sees
    it. The follow-ups waiting for that status are therefore started here. A
    sent channel message is final, so the follow-ups waiting for it to be sent
    start here too.
    """
    item = _build_followup_item(instance, enrollment, followup, trigger_time)
    if isinstance(item, Activity):
        create_next_followups(enrollment, instance, followup, item.status)
    elif isinstance(item, CadenceScheduledFollowUp):
        create_next_followups(enrollment, instance, followup, CHANNEL_SENT_STATUS)
    return item


def _build_followup_item(instance, enrollment, followup, trigger_time=None):
    if not is_builtin_followup_type(followup.followup_type):
        channel = get_followup_channel(followup.followup_type)
        if channel is None:
            # The channel's app is gone: nothing can be sent for this step.
            # Record it as failed, so the step is not tried again on every
            # save; ``None`` keeps the next follow-ups from starting.
            logger.error(
                "Cadence follow-up %s: type %r is not a built-in or a registered "
                "delivery channel",
                followup.pk,
                followup.followup_type,
            )
            error = str(
                _(
                    "The follow-up type %(followup_type)s is not a built-in "
                    "or a registered delivery channel."
                )
            ) % {"followup_type": followup.followup_type}
            _record_channel_run(enrollment, followup, error, trigger_time)
            return None
        return _send_channel_followup(
            instance, enrollment, followup, channel, trigger_time
        )
    cadence = enrollment.cadence
    content_type = _content_type_for(instance)
    now = trigger_time or timezone.now()
    if followup.followup_type == "email":
        return _create_email_draft_for_followup(
            instance, cadence, followup, enrollment, content_type
        )
    runtime = _runtime_info(cadence, followup, enrollment)
    if followup.followup_type == "task":
        due_dt = now + timedelta(days=(followup.due_after_days or 0))
        subject_text = followup.subject or f"{cadence.name} - Task"
        activity = Activity.objects.create(
            activity_type="task",
            subject=subject_text,
            title=subject_text,
            status=followup.task_status or "not_started",
            task_priority=followup.task_priority or "medium",
            due_datetime=due_dt,
            start_datetime=now,
            owner=followup.task_owner,
            company=getattr(instance, "company", None),
            content_type=content_type,
            object_id=instance.pk,
            additional_info=runtime,
        )
        if followup.task_owner:
            activity.assigned_to.add(followup.task_owner)
        return activity
    start_dt = now + timedelta(days=(followup.call_start_after_days or 0))
    call_text = followup.purpose or f"{cadence.name} - Call"
    return Activity.objects.create(
        activity_type="log_call",
        subject=call_text,
        title=call_text,
        status=followup.call_status or "scheduled",
        call_type=followup.call_type or "outbound",
        call_purpose=followup.purpose,
        start_datetime=start_dt,
        due_datetime=start_dt,
        owner=followup.call_owner,
        company=getattr(instance, "company", None),
        content_type=content_type,
        object_id=instance.pk,
        additional_info=runtime,
    )


def followup_delay(followup):
    """Wait configured in "Do This" as a timedelta, or ``None`` for no wait."""
    value = followup.do_this_value or 0
    if followup.do_this_unit == "minute":
        return timedelta(minutes=value)
    if followup.do_this_unit == "hour":
        return timedelta(hours=value)
    if followup.do_this_unit == "day":
        return timedelta(days=value)
    if followup.do_this_unit == "month":
        return relativedelta(months=value)
    return None


def start_followup(instance, enrollment, followup, trigger_time=None):
    """
    Create the item for ``followup`` now, or schedule it when it has a delay.

    Returns the created item, or the pending ``CadenceScheduledFollowUp`` when the
    follow-up has to wait; ``None`` when nothing could be created.
    """
    delay = followup_delay(followup)
    if delay is None:
        return create_followup_item(instance, enrollment, followup, trigger_time)
    scheduled, created = CadenceScheduledFollowUp.all_objects.get_or_create(
        enrollment=enrollment,
        followup=followup,
        defaults={
            "scheduled_at": (trigger_time or timezone.now()) + delay,
            "company": enrollment.company,
        },
    )
    if created and isinstance(delay, timedelta) and delay <= EXACT_TIMING_MAX_DELAY:
        _queue_at_scheduled_time(scheduled)
    return scheduled


def _queue_at_scheduled_time(scheduled):
    """
    Ask Celery to run ``scheduled`` exactly when it is due.

    The periodic task still picks it up if this fails or is lost, so this only
    removes the wait for the next beat tick.
    """
    from .tasks import run_cadence_scheduled_followup

    def queue():
        try:
            run_cadence_scheduled_followup.apply_async(
                args=[scheduled.pk], eta=scheduled.scheduled_at
            )
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Could not queue cadence follow-up %s; the periodic task will run it",
                scheduled.pk,
                exc_info=True,
            )

    transaction.on_commit(queue)


def run_scheduled_followup(scheduled_id):
    """Create the item of one due scheduled follow-up and record the outcome."""
    with transaction.atomic():
        scheduled = (
            CadenceScheduledFollowUp.all_objects.select_for_update()
            .select_related("enrollment__cadence", "followup")
            .filter(pk=scheduled_id, status="pending")
            .first()
        )
        if scheduled is None:
            return None
        enrollment = scheduled.enrollment
        instance = enrollment.related_object if enrollment.status == "active" else None
        if instance is None:
            scheduled.status = "cancelled"
            scheduled.executed_at = timezone.now()
            scheduled.save(update_fields=["status", "executed_at", "updated_at"])
            return scheduled
        try:
            with transaction.atomic():
                item = create_followup_item(
                    instance,
                    enrollment,
                    scheduled.followup,
                    trigger_time=timezone.now(),
                )
            scheduled.status = "completed" if item else "failed"
            if not item:
                # A channel follow-up writes why it failed on this row.
                scheduled.refresh_from_db(fields=["error_message"])
                if not scheduled.error_message:
                    scheduled.error_message = str(_("Nothing could be created."))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.exception(
                "Cadence delayed follow-up failed: enrollment=%s followup=%s",
                enrollment.pk,
                scheduled.followup_id,
            )
            scheduled.status = "failed"
            scheduled.error_message = str(exc)
        scheduled.executed_at = timezone.now()
        scheduled.save(
            update_fields=["status", "error_message", "executed_at", "updated_at"]
        )
    refresh_status(enrollment)
    return scheduled


def due_scheduled_followup_ids(now=None):
    """Ids of pending scheduled follow-ups whose wait is over."""
    return list(
        CadenceScheduledFollowUp.all_objects.filter(
            status="pending", scheduled_at__lte=now or timezone.now()
        ).values_list("pk", flat=True)
    )


def create_first_followups(enrollment, instance):
    """Create the stage-1 follow-ups that this enrollment does not have yet."""
    created = []
    existing = existing_followup_ids(enrollment)
    first_followups = enrollment.cadence.followups.filter(followup_number=1).order_by(
        "order", "id"
    )
    for followup in first_followups:
        if followup.pk in existing:
            continue
        item = start_followup(instance, enrollment, followup)
        if item:
            existing.add(followup.pk)
            created.append(item)
    return created


def create_next_followups(enrollment, instance, source_followup, status_key):
    """
    Create the follow-ups that hang off ``source_followup`` for ``status_key``.

    Only children of that exact follow-up (same cadence) are considered, and only
    inside ``enrollment``.
    """
    existing = existing_followup_ids(enrollment)
    next_followups = enrollment.cadence.followups.filter(
        branch_from_id=source_followup.pk,
        followup_number=source_followup.followup_number + 1,
        previous_status=status_key,
    ).order_by("followup_number", "order", "id")
    created = []
    for followup in next_followups:
        if followup.pk in existing:
            continue
        item = start_followup(
            instance, enrollment, followup, trigger_time=timezone.now()
        )
        if item:
            existing.add(followup.pk)
            created.append(item)
    return created


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def refresh_status(enrollment, allow_fail=True):
    """
    Mark an active enrollment ``completed`` once every follow-up it created is done,
    or ``failed`` when nothing could be created at all.

    Automatic enrollments pass ``allow_fail=False``: with nothing created yet (for
    example no outgoing mail server) they stay ongoing and are retried on the next save.
    """
    if enrollment.status != "active":
        return enrollment
    # A follow-up still waiting for its delay keeps the run going.
    if CadenceScheduledFollowUp.all_objects.filter(
        enrollment=enrollment, status="pending"
    ).exists():
        return enrollment
    activity_statuses = list(
        enrollment_activities(enrollment).values_list("status", flat=True)
    )
    mail_statuses = list(
        enrollment_mails(enrollment).values_list("mail_status", flat=True)
    )
    channel_statuses = list(
        enrollment_channel_runs(enrollment).values_list("status", flat=True)
    )
    if not activity_statuses and not mail_statuses and not channel_statuses:
        if allow_fail:
            _finish(enrollment, "failed")
        return enrollment
    if any(status not in CLOSED_ACTIVITY_STATUSES for status in activity_statuses):
        return enrollment
    if any(status in OPEN_MAIL_STATUSES for status in mail_statuses):
        return enrollment
    if (
        not activity_statuses
        and all(status in FAILED_MAIL_STATUSES for status in mail_statuses)
        and all(status == "failed" for status in channel_statuses)
    ):
        _finish(enrollment, "failed")
        return enrollment
    _finish(enrollment, "completed")
    return enrollment


def _finish(enrollment, status):
    enrollment.status = status
    enrollment.ended_at = timezone.now()
    enrollment.save(update_fields=["status", "ended_at", "updated_at"])


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------


def latest_enrollment(cadence, instance):
    """Most recent enrollment (any status) of this record in this cadence."""
    return (
        CadenceEnrollment.all_objects.filter(
            cadence=cadence,
            content_type=_content_type_for(instance),
            object_id=instance.pk,
        )
        .order_by("-run_number", "-id")
        .first()
    )


def adopt_legacy_enrollment(cadence, instance):
    """
    Create the enrollment for items made before enrollments existed.

    Returns the new enrollment, or ``None`` when the record already has an
    enrollment in this cadence or has no legacy items. Only JSON of the legacy
    items is touched (``enrollment_id`` is added); nothing is deleted or moved.
    """
    content_type = _content_type_for(instance)
    if CadenceEnrollment.all_objects.filter(
        cadence=cadence, content_type=content_type, object_id=instance.pk
    ).exists():
        return None
    activities, mails = _legacy_items(cadence, instance, content_type)
    items = activities + mails
    if not items:
        return None
    started = min(item.created_at for item in items)
    with transaction.atomic():
        enrollment = CadenceEnrollment.all_objects.create(
            cadence=cadence,
            content_type=content_type,
            object_id=instance.pk,
            source="auto",
            status="active",
            run_number=1,
            started_at=started,
            company=getattr(instance, "company", None),
        )
        for model, rows in (
            (Activity.all_objects, activities),
            (HorillaMail.objects, mails),
        ):
            for item in rows:
                info = dict(item.additional_info or {})
                runtime = dict(info.get("cadence_runtime") or {})
                runtime["enrollment_id"] = enrollment.pk
                runtime["run_number"] = 1
                info["cadence_runtime"] = runtime
                model.filter(pk=item.pk).update(additional_info=info)
    refresh_status(enrollment)
    return enrollment


def get_or_create_auto_enrollment(cadence, instance):
    """
    Enrollment used by condition based (automatic) execution.

    A new automatic enrollment is created only when the record has never been
    enrolled in this cadence, so a record that was un-enrolled or already
    completed is never silently started again by a later save. Returns
    ``(enrollment, created)``; ``enrollment`` is ``None`` if there is nothing to run.
    """
    content_type = _content_type_for(instance)
    existing = latest_enrollment(cadence, instance)
    if existing:
        return existing, False
    adopted = adopt_legacy_enrollment(cadence, instance)
    if adopted:
        return adopted, True
    if not cadence.followups.filter(followup_number=1).exists():
        return None, False
    try:
        with transaction.atomic():
            enrollment = CadenceEnrollment.all_objects.create(
                cadence=cadence,
                content_type=content_type,
                object_id=instance.pk,
                source="auto",
                status="active",
                run_number=1,
                started_at=timezone.now(),
                company=getattr(instance, "company", None),
            )
    except IntegrityError:
        return latest_enrollment(cadence, instance), False
    return enrollment, True


def eligible_cadences(instance):
    """
    Cadences ``instance`` can be enrolled in now: active, of the active company, of the
    record's module, with a first follow-up, and not already running for this record
    (enrolled by hand or added automatically). Cadences it finished or was un-enrolled
    from stay listed so they can be enrolled again.
    """
    content_type = _content_type_for(instance)
    running = CadenceEnrollment.all_objects.filter(
        content_type=content_type, object_id=instance.pk, status="active"
    ).values("cadence_id")
    return (
        Cadence.objects.filter(
            module=content_type,
            is_active=True,
            followups__followup_number=1,
        )
        .exclude(pk__in=running)
        .distinct()
        .order_by("name")
    )


def get_ineligible_reason(cadence, instance):
    """Return why ``instance`` cannot be enrolled in ``cadence`` now, else ``None``."""
    content_type = _content_type_for(instance)
    if not cadence.is_active:
        return _("This cadence is not active.")
    if cadence.module_id != content_type.pk:
        return _("This cadence belongs to a different module.")
    if not cadence.followups.filter(followup_number=1).exists():
        return _("No follow-ups are configured in this cadence.")
    latest = latest_enrollment(cadence, instance)
    if latest is None:
        adopt_legacy_enrollment(cadence, instance)
        latest = latest_enrollment(cadence, instance)
    if latest is not None and latest.status == "active":
        return _("This record is already enrolled in this cadence.")
    return None


def enroll(cadence, instance, user):
    """
    Enroll ``instance`` in ``cadence`` manually and start from the first follow-up.

    Always a fresh run: earlier enrollments (and their activities) stay untouched.
    Cadence conditions are not checked for manual enrollment.
    """
    reason = get_ineligible_reason(cadence, instance)
    if reason:
        raise EnrollmentError(reason)
    content_type = _content_type_for(instance)
    with transaction.atomic():
        last_run = CadenceEnrollment.all_objects.filter(
            cadence=cadence, content_type=content_type, object_id=instance.pk
        ).aggregate(last=Max("run_number"))["last"]
        try:
            with transaction.atomic():
                enrollment = CadenceEnrollment.all_objects.create(
                    cadence=cadence,
                    content_type=content_type,
                    object_id=instance.pk,
                    source="manual",
                    status="active",
                    run_number=(last_run or 0) + 1,
                    started_at=timezone.now(),
                    company=getattr(instance, "company", None),
                    created_by=user if getattr(user, "pk", None) else None,
                )
        except IntegrityError as exc:
            raise EnrollmentError(
                _("This record is already enrolled in this cadence.")
            ) from exc
        create_first_followups(enrollment, instance)
        refresh_status(enrollment)
    return enrollment


def unenroll(enrollment, user):
    """
    Un-enroll a manual, running enrollment.

    The enrollment is closed first (so cancelling activities cannot advance the
    cadence), then its still-open activities are cancelled. Completed activities are
    kept as history.
    """
    if enrollment.source != "manual":
        raise EnrollmentError(
            _("Records enrolled automatically cannot be un-enrolled.")
        )
    if enrollment.status != "active":
        raise EnrollmentError(_("Only a running enrollment can be un-enrolled."))
    with transaction.atomic():
        enrollment.status = "unenrolled"
        enrollment.ended_at = timezone.now()
        enrollment.unenrolled_by = user if getattr(user, "pk", None) else None
        enrollment.save(
            update_fields=["status", "ended_at", "unenrolled_by", "updated_at"]
        )
        CadenceScheduledFollowUp.all_objects.filter(
            enrollment=enrollment, status="pending"
        ).update(status="cancelled", executed_at=timezone.now())
        open_activities = enrollment_activities(enrollment).exclude(
            status__in=CLOSED_ACTIVITY_STATUSES
        )
        for activity in open_activities:
            activity.status = "cancelled"
            activity.save(update_fields=["status", "updated_at"])
    return enrollment


# ---------------------------------------------------------------------------
# Helpers for the record tab
# ---------------------------------------------------------------------------


def latest_followup_summary(enrollment):
    """
    Return ``(type_label, status_label)`` of the most advanced item of this enrollment,
    or ``None`` when it has no items yet.
    """
    items = []
    for activity in enrollment_activities(enrollment).only(
        "activity_type", "status", "additional_info", "id"
    ):
        items.append(
            (
                _runtime_of(activity).get("followup_number", 0),
                activity.pk,
                activity.activity_type,
                activity.get_status_display(),
            )
        )
    for mail in enrollment_mails(enrollment).only(
        "mail_status", "additional_info", "id"
    ):
        items.append(
            (
                _runtime_of(mail).get("followup_number", 0),
                mail.pk,
                "email",
                mail.get_mail_status_display(),
            )
        )
    for run in enrollment_channel_runs(enrollment).select_related("followup"):
        items.append(
            (
                run.followup.followup_number,
                run.pk,
                run.followup.followup_type,
                (
                    _("Sent")
                    if run.status == CHANNEL_SENT_STATUS
                    else run.get_status_display()
                ),
            )
        )
    if not items:
        return None
    _stage, _pk, kind, status = max(items, key=lambda row: (row[0], row[1]))
    return kind, status
