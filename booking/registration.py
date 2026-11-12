"""
Feature registration for the horilla_booking app.
"""

# First party imports (Horilla)
from horilla.registry.feature import register_model_for_feature

register_model_for_feature(
    app_label="booking",
    model_name="Booking",
    features=["export_data", "global_search"],
    options={
        "global_search": {
            "search_fields": [
                "booker_name",
                "booker_email",
                "status",
                "booking_page__title",
            ],
            "columns": [
                ("Name", "booker_name"),
                ("Email", "booker_email"),
                ("Booking Page", "booking_page"),
                ("Start", "start_datetime"),
                "status",
            ],
        }
    },
)
