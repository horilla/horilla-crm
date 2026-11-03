"""
Celery tasks for the cadences app.

process_due_cadence_followups — periodic task, queues follow-ups whose delay is over.
run_cadence_scheduled_followup — worker task, creates one delayed follow-up.
"""

# Standard library imports
import logging

# Third-party imports (Django)
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def process_due_cadence_followups():
    """
    Periodic task: queue a worker task for every pending cadence follow-up whose
    "Do This" delay has passed. Runs every minute via Celery Beat.
    """
    from . import services

    due_ids = services.due_scheduled_followup_ids()
    logger.info("Cadence scheduler: %s follow-ups due", len(due_ids))
    for scheduled_id in due_ids:
        run_cadence_scheduled_followup.delay(scheduled_id)
    return f"Queued {len(due_ids)} cadence follow-ups"


@shared_task
def run_cadence_scheduled_followup(scheduled_id):
    """Worker task: create the task / call / email of one delayed follow-up."""
    from . import services

    scheduled = services.run_scheduled_followup(scheduled_id)
    if scheduled is not None:
        logger.info(
            "Cadence follow-up %s finished with status %s",
            scheduled_id,
            scheduled.status,
        )
