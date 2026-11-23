"""App configuration for the contacts module."""

# First party imports (Horilla)
from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class ContactsConfig(AppLauncher):
    """Contacts App Configuration"""

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_crm.contacts"
    verbose_name = _("Contacts")

    url_prefix = "crm/contacts/"
    url_module = "horilla_crm.contacts.urls"
    url_namespace = "contacts"

    auto_import_modules = [
        "registration",
        "view_extensions",
        "signals",
        "menu",
        "dashboard",
        "tour",
    ]

    demo_data = [
        {
            "files": [
                (11, "load_data/contact.json"),
            ],
            "order": 6,
            "options": [100, 200, 500, 1000],
            "default": 200,
        },
        {
            "files": [
                (26, "load_data/duplicate_control.json"),
            ],
            "order": 7,
            "configurable": False,
        },
    ]

    def get_api_paths(self):
        """
        Return API path configurations for this app.

        Returns:
            list: List of dictionaries containing path configuration
        """
        return [
            {
                "pattern": "crm/contacts/",
                "view_or_include": "horilla_crm.contacts.api.urls",
                "name": "horilla_crm_contacts_api",
                "namespace": "horilla_crm_contacts",
            }
        ]
