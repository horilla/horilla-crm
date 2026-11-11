"""
Feature registration for Horilla Dashboard app.
"""

# First party imports (Horilla)
from horilla.registry.feature import (
    register_feature,
    register_model_for_feature,
    register_models_for_feature,
)

register_feature("dashboard_component", "dashboard_component_models")

register_model_for_feature(
    app_label="dashboard",
    model_name="DashboardFolder",
    features=["global_search"],
    options={
        "global_search": {
            "search_fields": [
                "name",
                "description",
                "parent_folder__name",
            ],
            "columns": ["name", "description", ("Parent Folder", "parent_folder")],
        }
    },
)

register_model_for_feature(
    app_label="dashboard",
    model_name="Dashboard",
    features=["global_search"],
    options={
        "global_search": {
            "search_fields": [
                "name",
                "description",
                "folder__name",
                "dashboard_owner__first_name",
                "dashboard_owner__last_name",
            ],
            "columns": [
                "name",
                "description",
                ("Folder", "folder"),
                ("Owner", "dashboard_owner"),
            ],
        }
    },
)

# Personal preferences/logs: ignored in the delete dependency dialog.
register_models_for_feature(
    models=[
        ("dashboard", "DefaultHomeLayoutOrder"),
        ("dashboard", "OnboardingState"),
    ],
    features=["delete_dependency"],
)
