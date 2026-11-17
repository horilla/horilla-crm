"""
Celery beat schedules for the Horilla Core app.

Defines periodic tasks used by the core system,
such as processing scheduled exports.
"""

# Standard library imports
from datetime import timedelta

HORILLA_BEAT_SCHEDULE = {
    "process-scheduled-exports": {
        "task": "horilla.contrib.core.tasks.process_scheduled_exports",
        "schedule": timedelta(seconds=10),
    },
    "refresh-exchange-rates": {
        "task": "horilla.contrib.core.tasks.refresh_exchange_rates",
        "schedule": timedelta(hours=1),
    },
}
