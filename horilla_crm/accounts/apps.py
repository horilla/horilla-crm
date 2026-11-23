"""App configuration for the Accounts module."""

# First party imports (Horilla)
from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class AccountsConfig(AppLauncher):
    """Accounts App Configuration"""

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_crm.accounts"
    verbose_name = _("Accounts")

    url_prefix = "crm/accounts/"
    url_module = "horilla_crm.accounts.urls"
    url_namespace = "accounts"

    auto_import_modules = [
        "registration",
        "signals",
        "menu",
        "dashboard",
        "tour",
    ]

    demo_data = {
        "files": [
            (10, "load_data/account.json"),
        ],
        "order": 5,
        "options": [100, 250, 500, 1000],
        "default": 250,
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
                "pattern": "crm/accounts/",
                "view_or_include": "horilla_crm.accounts.api.urls",
                "name": "horilla_crm_accounts_api",
                "namespace": "horilla_crm_accounts",
            }
        ]
