"""
Feature registration for Horilla Reports app.
"""

# First party imports (Horilla)
from horilla.registry.feature import register_feature, register_model_for_feature

register_feature("report_choices", "report_models")

register_model_for_feature(
    app_label="reports",
    model_name="ReportFolder",
    features=["import_data", "export_data", "global_search"],
    options={
        "global_search": {
            "search_fields": [
                "name",
                "parent__name",
                "report_folder_owner__first_name",
                "report_folder_owner__last_name",
            ],
            "columns": [
                "name",
                ("Parent Folder", "parent"),
                ("Owner", "report_folder_owner"),
            ],
        }
    },
)

register_model_for_feature(
    app_label="reports",
    model_name="Report",
    features=["import_data", "export_data", "global_search"],
    options={
        "global_search": {
            "search_fields": ["name", ("Module", "module__model"), "folder__name"],
            "columns": ["name", "module", "folder", ("Chart Type", "chart_type")],
        }
    },
)
