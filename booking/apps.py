"""
App configuration for the booking app.
"""

from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class BookingConfig(AppLauncher):
    """
    Configuration class for the booking app in Horilla.
    """

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "booking"
    verbose_name = _("Booking")

    url_prefix = "booking/"
    url_module = "booking.urls"
    url_namespace = "booking"

    auto_import_modules = [
        "registration",
        "signals",
        "menu",
    ]

    demo_data = {
        "files": [
            (35, "load_data/booking_page.json"),
            (36, "load_data/booking.json"),
        ],
        "order": 8,
        "configurable": False,
    }

    celery_schedule_module = "celery_schedules"
    celery_schedule_variable = "HORILLA_BEAT_SCHEDULE"
