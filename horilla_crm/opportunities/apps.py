"""App configuration for the opportunities module."""

# First party imports (Horilla)
from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class OpportunitiesConfig(AppLauncher):
    """Opportunities App Configuration"""

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_crm.opportunities"
    verbose_name = _("Opportunities")

    url_prefix = "crm/opportunities/"
    url_module = "horilla_crm.opportunities.urls"
    url_namespace = "opportunities"

    auto_import_modules = [
        "registration",
        "signals",
        "menu",
        "dashboard",
        "onboarding",
    ]

    demo_data = [
        {
            "files": [
                (8, "load_data/opportunity_stage.json"),
                (9, "load_data/opportunity.json"),
            ],
            "order": 3,
        },
        {
            "files": [
                (21, "load_data/workflow_rule.json"),
                (24, "load_data/approval_rule.json"),
                (25, "load_data/review_process.json"),
                (27, "load_data/big_deal_alert.json"),
            ],
            "order": 7,
            "configurable": False,
        },
    ]

    report_files = [
        "report_data/reports.json",
    ]

    def get_api_paths(self):
        """
        Return API path configurations for this app.

        Returns:
            list: List of dictionaries containing path configuration
        """
        return [
            {
                "pattern": "crm/opportunities/",
                "view_or_include": "horilla_crm.opportunities.api.urls",
                "name": "horilla_crm_opportunities_api",
                "namespace": "horilla_crm_opportunities",
            }
        ]
