"""Celery beat schedule for the cadences app."""

from datetime import timedelta

HORILLA_BEAT_SCHEDULE = {
    "process-due-cadence-followups-every-minute": {
        "task": "horilla.contrib.cadences.tasks.process_due_cadence_followups",
        "schedule": timedelta(minutes=1),
    },
}
