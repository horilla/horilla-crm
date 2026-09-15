"""
Feature registration for Leads app.
"""

# First-party / Horilla apps
from calls.registration import register_callable_model
from horilla.contrib.cadences.registration import register_cadence_tab

# First party imports (Horilla)
from horilla.registry.feature import register_model_for_feature

register_model_for_feature(
    app_label="leads",
    model_name="LeadStatus",
    features=["import_data", "export_data", "global_search"],
)

register_model_for_feature(
    app_label="leads",
    model_name="Lead",
    all=True,
    features=[
        "duplicate_models",
        "approval_models",
        "reviews_models",
        "workflow_models",
        "scoring",
        "field_requirements",
        "form_layouts",
    ],
)

register_cadence_tab(
    app_label="leads",
    model_name="Lead",
    url_prefix="lead-cadences-tab/<int:pk>/",
    url_name="lead_cadences_tab",
)

register_callable_model("leads", "Lead", "contact_number")
