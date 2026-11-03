"""
Feature registration for Horilla Activity app, Such as import, export,
global search, and other pluggable capabilities.
"""

# First party imports (Horilla)
from horilla.registry.feature import register_feature, register_model_for_feature

# Selective: a model joins by listing "activity_related_models" in its own
# registration (only records whose detail page lists activities should).
register_feature("activity_related", "activity_related_models", auto_register_all=False)

register_model_for_feature(
    app_label="activity",
    model_name="Activity",
    features=[
        "global_search",
        "automation",
        "mail_template",
        "export_data",
        "notification_template",
        "report_choices",
        "dashboard_component",
    ],
)
