"""Utility functions for the contacts module."""

# Local imports
from horilla.contrib.utils.middlewares import get_active_company

from .models import Contact


def find_duplicate_contact(email, company):
    """Return an existing Contact with the same email within the company, if any."""
    return Contact.objects.filter(email__iexact=email, company=company).first()


def contact_already_exists_for_mail(incoming_mail, request):
    """
    Inbox action predicate: True if incoming_mail's sender already has a
    Contact, even if this particular message was never itself converted
    (e.g. a second email from someone already added as a Contact).
    """
    company = get_active_company(request)
    return find_duplicate_contact(incoming_mail.sender_email, company) is not None


def create_contact_from_email(incoming_mail, request, owner=None):
    """
    Create (or reuse) a Contact from a fetched IncomingMail row.

    Splits `incoming_mail.sender_name` into first/last name (fallback: the
    whole string as first_name, empty last_name). Runs email-based dedup
    (`find_duplicate_contact`) first; if a match exists within the company,
    returns the existing Contact unchanged. Mirrors Django's `get_or_create`
    return convention: (contact, created).
    """
    owner = owner or request.user
    company = get_active_company(request)

    existing_contact = find_duplicate_contact(incoming_mail.sender_email, company)
    if existing_contact:
        return existing_contact, False

    sender_name = (incoming_mail.sender_name or "").strip()
    if sender_name and " " in sender_name:
        first_name, last_name = sender_name.split(" ", 1)
    else:
        first_name, last_name = sender_name, ""

    contact = Contact.objects.create(
        contact_owner=owner,
        first_name=first_name,
        last_name=last_name,
        email=incoming_mail.sender_email,
        company=company,
        contact_source="email",
        message_id=incoming_mail.message_id,
    )
    return contact, True
