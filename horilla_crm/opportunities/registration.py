"""
Feature registration for Opportunities app.
"""

from django.db.models.functions import Cast, Now, TruncMonth

from horilla.contrib.cadences.registration import register_cadence_tab

# Third-party imports (Django)
from horilla.contrib.reports.utils import (
    register_report_related_fields,
    register_virtual_field,
)

# First party imports (Horilla)
from horilla.db.models import DateTimeField, DurationField, ExpressionWrapper, F
from horilla.registry.feature import register_model_for_feature
from horilla.utils.translation import gettext_lazy as _

register_model_for_feature(
    app_label="opportunities",
    model_name="OpportunityStage",
    features=["import_data", "export_data"],
)

register_model_for_feature(
    app_label="opportunities",
    model_name="Opportunity",
    all=True,
    features=[
        "approval_models",
        "reviews_models",
        "scoring",
        "workflow_models",
        "field_requirements",
        "custom_fields_models",
        "form_layouts",
        "activity_related_models",
        "custom_calendar_models",
        "mobile",
        "cadences_models",
    ],
    options={
        "global_search": {
            "search_fields": [
                "name",
                "email",
                "description",
                "next_step",
                "opportunity_type",
                "order_number",
                "account__name",
                "owner__first_name",
                "owner__last_name",
            ],
            "columns": [
                "name",
                ("Account", "account"),
                "email",
                ("Owner", "owner"),
                "opportunity_type",
            ],
        }
    },
)

register_model_for_feature(
    app_label="opportunities",
    model_name="OpportunityTeam",
    features=["report_choices"],
)

register_model_for_feature(
    app_label="opportunities",
    model_name="OpportunitySplit",
    features=["report_choices"],
)

register_cadence_tab(
    app_label="opportunities",
    model_name="Opportunity",
    url_prefix="opportunity-cadences-tab/<int:pk>/",
    url_name="opportunity_cadences_tab",
)

register_virtual_field(
    app_label="opportunities",
    model_name="Opportunity",
    field_name="days_open",
    verbose_name=_("Days Open"),
    annotation=ExpressionWrapper(Now() - F("created_at"), output_field=DurationField()),
)

register_virtual_field(
    app_label="opportunities",
    model_name="Opportunity",
    field_name="close_month",
    verbose_name=_("Close Month"),
    annotation=TruncMonth("close_date"),
)

register_virtual_field(
    app_label="opportunities",
    model_name="Opportunity",
    field_name="days_to_close",
    verbose_name=_("Days to Close"),
    annotation=ExpressionWrapper(
        Cast("close_date", output_field=DateTimeField()) - F("created_at"),
        output_field=DurationField(),
    ),
)

# The Win/Loss Analysis report filters on the stage type
register_report_related_fields(
    "opportunities", "opportunity", {"stage": ["stage_type"]}
)
