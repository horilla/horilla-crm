"""
Feature registration for Accounts app.
"""

# First-party / Horilla apps
from calls.registration import register_callable_model
from horilla.contrib.cadences.registration import register_cadence_tab

# First-party / Horilla apps
from horilla.registry.feature import register_model_for_feature

register_model_for_feature(
    app_label="accounts",
    model_name="Account",
    all=True,
    features=[
        "duplicate_models",
        "approval_models",
        "reviews_models",
        "workflow_models",
        "scoring",
        "activity_related_models",
        "field_requirements",
        "custom_fields_models",
        "form_layouts",
        "custom_calendar_models",
        "mobile",
        "cadences_models",
    ],
    options={
        "global_search": {
            "search_fields": [
                "name",
                "account_number",
                "account_type",
                "site",
                "industry",
                "website",
                "contact_number",
                "billing_city",
                "account_owner__first_name",
                "account_owner__last_name",
            ],
            "columns": [
                "name",
                "account_number",
                "account_type",
                "industry",
                "website",
                "contact_number",
            ],
        }
    },
)

register_cadence_tab(
    app_label="accounts",
    model_name="Account",
    url_prefix="account-cadences-tab/<int:pk>/",
    url_name="account_cadences_tab",
)

register_callable_model("accounts", "Account", "account_number")
