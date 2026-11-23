"""App configuration for the Campaign module."""

# First party imports (Horilla)
from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class CampaignsConfig(AppLauncher):
    """Campaigns App Configuration"""

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_crm.campaigns"
    verbose_name = _("Campaigns")

    url_prefix = "crm/campaigns/"
    url_module = "horilla_crm.campaigns.urls"
    url_namespace = "campaigns"

    auto_import_modules = [
        "registration",
        "signals",
        "menu",
        "dashboard",
        "tour",
    ]

    # The file alternates between the two demo companies, so any even count is split
    # evenly between them (20 gives 10 and 10). Company 2 has 50 campaigns, so 100 is the
    # largest count that is still even.
    demo_data = {
        "files": [
            (6, "load_data/campaign.json"),
        ],
        "order": 4,
        "options": [10, 20, 50, 100],
        "default": 20,
    }

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
                "pattern": "crm/campaigns/",
                "view_or_include": "horilla_crm.campaigns.api.urls",
                "name": "horilla_crm_campaigns_api",
                "namespace": "horilla_crm_campaigns",
            }
        ]
