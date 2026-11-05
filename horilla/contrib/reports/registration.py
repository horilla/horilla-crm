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
)

register_model_for_feature(
    app_label="reports",
    model_name="Report",
    features=["import_data", "export_data", "global_search"],
)
