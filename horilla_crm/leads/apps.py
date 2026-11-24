"""Leads app configuration."""

# First party imports (Horilla)
from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class LeadsConfig(AppLauncher):
    """Leads App Configuration"""

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_crm.leads"
    verbose_name = _("Leads")

    url_prefix = "crm/leads/"
    url_module = "horilla_crm.leads.urls"
    url_namespace = "leads"

    auto_import_modules = [
        "registration",
        "view_extensions",
        "signals",
        "menu",
        "dashboard",
        "onboarding",
        "tour",
    ]

    demo_data = [
        {
            "files": [
                (4, "load_data/lead_stage.json"),
                (31, "load_data/leads.json"),
                (22, "load_data/lead_assignment_rule.json"),
                (23, "load_data/lead_capture_form.json"),
            ],
            "order": 2,
            "options": [100, 200, 500, 1000],
            "default": 200,
            "prepare": "horilla_crm.leads.demo.prepare_demo_rows",
        },
        {
            "files": [
                # Shared CRM-wide fixtures
                # horilla_crm/load_data (one file each).
                (17, "../load_data/mail_template.json"),
                (18, "../load_data/notification_template.json"),
                (20, "../load_data/cadence.json"),
                (21, "../load_data/workflow_rule.json"),
                (24, "../load_data/approval_rule.json"),
                (25, "../load_data/review_process.json"),
                (26, "load_data/duplicate_control.json"),
                (30, "../load_data/report.json"),
                # Approval and review jobs reference leads, accounts, contacts
                # and opportunities, so they load after those.
                (33, "../load_data/approval_instance.json"),
                (34, "../load_data/review_job.json"),
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
                "pattern": "crm/leads/",
                "view_or_include": "horilla_crm.leads.api.urls",
                "name": "horilla_crm_leads_api",
                "namespace": "horilla_crm_leads",
            }
        ]
