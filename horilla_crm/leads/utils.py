"""Utility functions for leads module."""

# Standard library imports
import html
import re

# Third-party imports (Django)
from django.utils.html import format_html

from horilla.contrib.utils.middlewares import get_active_company

# First party imports (Horilla)
from horilla.utils.translation import gettext as _

# Local imports
from .assignment.pool import VIA_FORM, build_assignment_info
from .models import Lead, LeadStatus


def _html_to_text(value):
    """Convert an HTML email body to plain text, keeping line breaks."""
    if not value:
        return ""
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", value)
    value = re.sub(r"(?i)<br\s*/?>|</(div|p|li|tr|h[1-6])>", "\n", value)
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value)
    return re.sub(r"\n\s*\n+", "\n", value).strip()


def lead_warning_for_mail(incoming_mail, request):
    """
    Inbox action warning: if this sender already has a Contact, say so (with
    a link) without blocking "Add as Lead" - mirrors how Salesforce/HubSpot/
    Zoho warn rather than block when creating a Lead for someone already a
    Contact, since a genuinely new inquiry from an existing customer is a
    normal, allowed case.
    """
    from horilla_crm.contacts.utils import find_duplicate_contact

    company = get_active_company(request)
    contact = find_duplicate_contact(incoming_mail.sender_email, company)
    if not contact:
        return None
    # format_html escapes each interpolated value (sender email, contact
    # name/URL) individually, so a maliciously-named Contact can't inject
    # markup into this warning - only the literal template text is trusted.
    return format_html(
        '{} {} <a href="{}" class="underline" target="_blank">{}</a>.',
        incoming_mail.sender_email,
        _("already has a contact:"),
        contact.get_detail_url(),
        str(contact),
    )


def build_lead_from_email(incoming_mail, owner=None, company=None):
    """Return an unsaved Lead holding what the email says (name, subject, body)."""
    return Lead(
        first_name=(incoming_mail.sender_name or "").strip()[:100],
        title=incoming_mail.subject,
        email=incoming_mail.sender_email,
        requirements=_html_to_text(incoming_mail.body),
        lead_owner=owner,
        lead_status=LeadStatus.objects.first(),
        company=company,
        lead_source="email",
        message_id=incoming_mail.message_id,
    )


def create_lead_from_email(
    incoming_mail,
    request,
    owner=None,
    apply_assignment_rule=True,
    assignment_decision=None,
):
    """
    Create a Lead from a fetched IncomingMail row.

    Thin wrapper around the existing Lead.objects.create(...) shape used by
    the email-to-lead Celery task (leads/tasks.py), extracted here so both
    the automatic pipeline and the interactive "Add as Lead" inbox action
    share the same creation logic.

    assignment_decision is the (condition, owner) the inbox form already
    settled with a rule; the lead then keeps that owner instead of running the
    rules again.
    """
    owner = owner or request.user
    company = get_active_company(request)

    lead = build_lead_from_email(incoming_mail, owner, company)
    if not apply_assignment_rule:
        # Keep the configured owner; read by handle_lead_assignment on post_save.
        lead._skip_assignment_rule = True
    elif assignment_decision is not None:
        condition, decided_owner = assignment_decision
        lead._assignment_condition_id = condition.pk
        lead.additional_info = build_assignment_info(
            lead.additional_info, condition, decided_owner, VIA_FORM
        )
    lead.save()
    return lead
