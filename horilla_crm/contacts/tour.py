"""
Tours of the Contacts app: the list page, and a single contact.

Picked up through ``"tour"`` in this app's ``auto_import_modules``, like ``menu.py``.
The list and detail steps come from ``horilla.contrib.tour.presets`` (shared by every
CRM app) with Contacts wording on top. A step whose element is missing (no permission,
a field hidden by the form layout, an empty list) is skipped.
"""

# First party imports (Horilla)
from horilla.contrib.tour.presets import detail_page_steps, list_page_steps
from horilla.contrib.tour.registry import Tour
from horilla.utils.translation import gettext_lazy as _

CONTACT_VIEW_PERMS = ["contacts.view_contact", "contacts.view_own_contact"]
CONTACT_LIST_URL = "contacts:contacts_view"
CREATE_BUTTON = "contact-create"
FIRST_CONTACT = "#data-container-contact-list tr:first-child td[hx-get]"


class ContactsListTour(Tour):
    """The Contacts list page."""

    key = "contacts_list"
    title = _("Working with the Contacts List")
    description = _(
        "Find the people you deal with, switch layouts, select rows and "
        "add a new contact."
    )
    group = _("Contacts")
    icon = "/assets/icons/contact.svg"
    order = 310
    match = (CONTACT_LIST_URL,)
    ready = "#navBar h3"
    permission = CONTACT_VIEW_PERMS
    auto_start = True
    steps = list_page_steps(
        view_id="contact-list",
        create_id=CREATE_BUTTON,
        record_plural=_("contacts"),
        intro=_("A contact is a person you deal with, usually at an account."),
        create_body=_("Add a new contact here. A short form opens."),
    )


class ContactsDetailTour(Tour):
    """A single contact."""

    key = "contacts_detail"
    title = _("Inside a Contact")
    description = _(
        "The summary and tabs of a contact: activity, related records, "
        "notes and history."
    )
    group = _("Contacts")
    icon = "/assets/icons/contact.svg"
    order = 312
    match = ("contacts:contact_detail_view",)
    open_with = {"from": CONTACT_LIST_URL, "click": FIRST_CONTACT}
    # Not the header card: that is hidden while the tabs are expanded.
    ready = "#detailViewport"
    permission = CONTACT_VIEW_PERMS
    auto_start = True
    steps = detail_page_steps(
        intro=_("One contact in full: the person and everything linked to them."),
        related_lists=[
            (
                "child_contacts",
                _("Child Contacts"),
                _("Contacts grouped under this one."),
            ),
            (
                "campaigns",
                _("Related Campaigns"),
                _("Campaigns this person is part of."),
            ),
            (
                "opportunities",
                _("Related Opportunities"),
                _("Deals this person takes part in."),
            ),
            (
                "account_relationships",
                _("Related Accounts"),
                _("The companies this person belongs to."),
            ),
        ],
    )
