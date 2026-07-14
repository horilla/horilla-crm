"""Celery tasks for the whatsapp app."""

# Standard library imports
import logging

# Third-party imports (other)
from celery import shared_task

# Third-party imports (Django)
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def process_whatsapp_bot_rule_scheduled_resumes():
    """Resume any WhatsAppScheduledResume whose resume_at has passed."""
    from .engine.base import FlowEngine
    from .models import WhatsAppScheduledResume

    due = WhatsAppScheduledResume.objects.filter(
        status="pending", resume_at__lte=timezone.now()
    )
    for scheduled_resume in due:
        resume_whatsapp_bot_rule_session.delay(scheduled_resume.pk)


@shared_task
def resume_whatsapp_bot_rule_session(scheduled_resume_id):
    """Resume the session tied to one WhatsAppScheduledResume row."""
    from .engine.base import FlowEngine
    from .models import WhatsAppScheduledResume

    scheduled_resume = WhatsAppScheduledResume.objects.filter(
        pk=scheduled_resume_id, status="pending"
    ).first()
    if not scheduled_resume:
        return

    try:
        FlowEngine(scheduled_resume.session).resume(reply_text=None, reply_id=None)
        scheduled_resume.status = "resumed"
        scheduled_resume.save(update_fields=["status"])
    except (
        Exception
    ) as exc:  # noqa: BLE001 - record and move on, don't crash the beat task
        logger.exception(
            "Failed to resume bot flow session for scheduled resume %s",
            scheduled_resume_id,
        )
        scheduled_resume.status = "failed"
        scheduled_resume.error_message = str(exc)
        scheduled_resume.save(update_fields=["status", "error_message"])
