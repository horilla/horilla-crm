"""
Feature registration for Leads app.
"""

# First-party / Horilla apps
from calls.registration import register_callable_model
from horilla.contrib.cadences.registration import register_cadence_tab
from horilla.contrib.mail.actions import register_incoming_mail_action
from horilla.contrib.mail.fetch_hooks import register_incoming_mail_fetch_hook

# First party imports (Horilla)
from horilla.registry.feature import register_model_for_feature
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import EmailToLeadConfig, Lead
from .utils import create_lead_from_email, lead_warning_for_mail

register_model_for_feature(
    app_label="leads",
    model_name="LeadStatus",
    features=["import_data", "export_data"],
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
                "title",
                "first_name",
                "last_name",
                "email",
                "contact_number",
                "lead_company",
                "industry",
                "city",
                "lead_owner__first_name",
                "lead_owner__last_name",
            ],
            "columns": [
                "title",
                "first_name",
                "last_name",
                "email",
                "contact_number",
                "lead_company",
            ],
        }
    },
)

register_cadence_tab(
    app_label="leads",
    model_name="Lead",
    url_prefix="lead-cadences-tab/<int:pk>/",
    url_name="lead_cadences_tab",
)

register_callable_model("leads", "Lead", "contact_number")


def _add_as_lead(incoming_mail, request):
    """Inbox action handler: create a Lead from an incoming email."""
    return create_lead_from_email(incoming_mail, request)


register_incoming_mail_action(
    key="lead",
    label=_("Add as Lead"),
    handler=_add_as_lead,
    icon="assets/icons/add_as_lead.svg",
    permission="leads.add_lead",
    warning_check=lead_warning_for_mail,
)


class _ConfigRequest:
    """
    Minimal request-like shim so create_lead_from_email/create_contact_from_email
    (whose shared contract takes a request for request.user/request.active_company)
    can also be driven from the generic mail fetch task (mail/tasks.py's
    fetch_emails_to_incoming_mail),
    which has no real request - only the EmailToLeadConfig's own owner/company.
    """

    def __init__(self, config):
        self.user = config.owner
        self.active_company = config.company


def _get_email_to_lead_config(mail_config):
    """Fetch-hook: look up the EmailToLeadConfig for this mailbox, if any."""
    return EmailToLeadConfig.objects.filter(mail=mail_config).first()


def _get_allowed_senders(config):
    """Fetch-hook: allowed-sender filter list from an EmailToLeadConfig."""
    return config.get_accepted_emails()


def _matches_filters(config, subject, body):
    """Fetch-hook: keyword filter from an EmailToLeadConfig."""
    return config.matches_keywords(subject, body)


def _create_record(config, incoming_mail):
    """
    Fetch-hook: create either a Lead or a Contact from a freshly persisted
    IncomingMail row, based on config.create_as, and mark the IncomingMail
    row as converted on success. leads already depends on contacts for the
    "create_as=contact" case (both are CRM apps), so this imports
    create_contact_from_email directly rather than splitting the hook further.
    """
    config_request = _ConfigRequest(config)
    if config.create_as == "contact":
        # Local import: keeps the contacts dependency scoped to this one
        # branch, and avoids a hard import-time dependency from leads on
        # contacts for installations where only leads is enabled.
        from horilla_crm.contacts.utils import create_contact_from_email

        create_contact_from_email(incoming_mail, config_request)
        incoming_mail.mark_action_converted("contact")
    else:
        create_lead_from_email(
            incoming_mail,
            config_request,
            apply_assignment_rule=config.apply_assignment_rule,
        )
        incoming_mail.mark_action_converted("lead")


def _is_duplicate_message(message_ids):
    """
    Fetch-hook: True if any of the given Message-IDs already has a Lead
    created from it. Lead.message_id exists only so a Lead created from an
    old email doesn't get reprocessed even if the originating IncomingMail
    row was somehow deleted - see fetch_hooks.py's docstring.
    """
    return Lead.objects.filter(message_id__in=message_ids).exists()


register_incoming_mail_fetch_hook(
    get_config=_get_email_to_lead_config,
    get_allowed_senders=_get_allowed_senders,
    matches_filters=_matches_filters,
    create_record=_create_record,
    is_duplicate_message=_is_duplicate_message,
)
