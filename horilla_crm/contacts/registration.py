"""
Feature registration for Contacts app.
"""

from calls.registration import register_callable_model
from horilla.contrib.cadences.registration import register_cadence_tab
from horilla.contrib.mail.actions import register_incoming_mail_action

# First party imports (Horilla)
from horilla.registry.feature import register_model_for_feature
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .utils import contact_already_exists_for_mail, create_contact_from_email

register_model_for_feature(
    app_label="contacts",
    model_name="Contact",
    all=True,
    features=[
        "duplicate_models",
        "approval_models",
        "reviews_models",
        "scoring",
        "workflow_models",
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
                "title",
                "first_name",
                "last_name",
                "email",
                "contact_number",
                "secondary_contact_number",
                "address_city",
                "contact_owner__first_name",
                "contact_owner__last_name",
            ],
            "columns": ["title", "first_name", "last_name", "email", "contact_number"],
        }
    },
)

register_cadence_tab(
    app_label="contacts",
    model_name="Contact",
    url_prefix="contact-cadences-tab/<int:pk>/",
    url_name="contact_cadences_tab",
)

register_callable_model("contacts", "Contact", "contact_number")


def _add_as_contact(incoming_mail, request):
    """Inbox action handler: create (or reuse) a Contact from an incoming email."""
    contact, _created = create_contact_from_email(incoming_mail, request)
    return contact


register_incoming_mail_action(
    key="contact",
    label=_("Add as Contact"),
    handler=_add_as_contact,
    icon="assets/icons/add_as_contact.svg",
    permission="contacts.add_contact",
    already_exists_check=contact_already_exists_for_mail,
)
