"""
Tours of the Accounts app: the list page, and a single account.

Picked up through ``"tour"`` in this app's ``auto_import_modules``, like ``menu.py``.
The list and detail steps come from ``horilla.contrib.tour.presets`` (shared by every
CRM app) with Accounts wording on top. A step whose element is missing (no permission,
a field hidden by the form layout, an empty list) is skipped.
"""

# First party imports (Horilla)
from horilla.contrib.tour.presets import detail_page_steps, list_page_steps
from horilla.contrib.tour.registry import Tour
from horilla.utils.translation import gettext_lazy as _

ACCOUNT_VIEW_PERMS = ["accounts.view_account", "accounts.view_own_account"]
ACCOUNT_LIST_URL = "accounts:accounts_view"
CREATE_BUTTON = "account-create"
FIRST_ACCOUNT = "#data-container-accounts-list tr:first-child td[hx-get]"


class AccountsListTour(Tour):
    """The Accounts list page."""

    key = "accounts_list"
    title = _("Working with the Accounts List")
    description = _(
        "Find the companies you work with, switch layouts, select rows and "
        "add a new account."
    )
    group = _("Accounts")
    icon = "/assets/icons/account.svg"
    order = 300
    match = (ACCOUNT_LIST_URL,)
    ready = "#navBar h3"
    permission = ACCOUNT_VIEW_PERMS
    auto_start = True
    steps = list_page_steps(
        view_id="accounts-list",
        create_id=CREATE_BUTTON,
        record_plural=_("accounts"),
        intro=_("An account is a company you do business with."),
        create_body=_("Add a new account here. A short form opens."),
    )


class AccountsDetailTour(Tour):
    """A single account."""

    key = "accounts_detail"
    title = _("Inside an Account")
    description = _(
        "The summary and tabs of an account: activity, contacts, deals, "
        "notes and history."
    )
    group = _("Accounts")
    icon = "/assets/icons/account.svg"
    order = 302
    match = ("accounts:account_detail_view",)
    open_with = {"from": ACCOUNT_LIST_URL, "click": FIRST_ACCOUNT}
    # Not the header card: that is hidden while the tabs are expanded.
    ready = "#detailViewport"
    permission = ACCOUNT_VIEW_PERMS
    auto_start = True
    steps = detail_page_steps(
        intro=_("One account in full: the company, its contacts and deals."),
        related_lists=[
            (
                "child_accounts",
                _("Child Accounts"),
                _("Branches or subsidiaries of this company."),
            ),
            (
                "opportunity_account",
                _("Opportunities"),
                _("Deals with this company."),
            ),
            (
                "contact_relationships",
                _("Related Contacts"),
                _("People who work at this company."),
            ),
            (
                "partner",
                _("Partner"),
                _("Other companies that work with this one, and their role."),
            ),
        ],
    )
