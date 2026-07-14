"""Celery beat schedules for the whatsapp app."""

# Third-party imports (other)
from celery.schedules import crontab

WHATSAPP_BEAT_SCHEDULE = {
    "process-whatsapp-bot-rule-scheduled-resumes": {
        "task": "horilla.contrib.whatsapp.tasks.process_whatsapp_bot_rule_scheduled_resumes",
        "schedule": crontab(minute="*"),  # Every minute
    },
}
