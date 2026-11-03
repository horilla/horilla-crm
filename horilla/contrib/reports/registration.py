"""
Feature registration for Horilla Reports app.
"""

# First party imports (Horilla)
from horilla.contrib.reports.utils import register_report_default_related_fields
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

# Related fields shown for any relation to a user (owner, created by, ...)
register_report_default_related_fields(
    "core",
    "horillauser",
    [
        "department",
        "role",
        "company",
    ],
)
