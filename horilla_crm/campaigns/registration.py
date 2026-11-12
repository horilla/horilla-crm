"""
Feature registration for Campaigns app.
"""

# Third-party imports (Django)

# First party imports (Horilla)
from horilla.contrib.cadences.registration import register_cadence_tab
from horilla.contrib.reports.utils import register_virtual_field
from horilla.db.models import Case, ExpressionWrapper, F, FloatField, Value, When
from horilla.registry.feature import register_model_for_feature
from horilla.utils.translation import gettext_lazy as _

register_model_for_feature(
    app_label="campaigns",
    model_name="Campaign",
    all=True,
    features=[
        "workflow_models",
        "field_requirements",
        "custom_fields_models",
        "form_layouts",
        "activity_related_models",
        "custom_calendar_models",
        "cadences_models",
    ],
    options={
        "global_search": {
            "search_fields": [
                "campaign_name",
                "status",
                "campaign_type",
                "description",
                "campaign_owner__first_name",
                "campaign_owner__last_name",
            ],
            "columns": [
                "campaign_name",
                "status",
                "campaign_type",
                ("Owner", "campaign_owner"),
            ],
        }
    },
)

register_cadence_tab(
    app_label="campaigns",
    model_name="Campaign",
    url_prefix="campaign-cadences-tab/<int:pk>/",
    url_name="campaign_cadences_tab",
)

register_virtual_field(
    app_label="campaigns",
    model_name="Campaign",
    field_name="roi_percentage",
    verbose_name=_("ROI %"),
    annotation=Case(
        When(
            actual_cost__gt=0,
            then=ExpressionWrapper(
                (F("value_won_opportunities") - F("actual_cost"))
                * 100.0
                / F("actual_cost"),
                output_field=FloatField(),
            ),
        ),
        default=Value(0.0),
        output_field=FloatField(),
    ),
)
