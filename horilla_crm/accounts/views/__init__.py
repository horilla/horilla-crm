"""Aggregate and re-export account-related views for convenience imports."""

# Local imports
from horilla_crm.accounts.views.core import (
    AccountView,
    AccountsNavbar,
    AccountListView,
    AccountGroupByView,
    AccountsKanbanView,
    AccountCardView,
    AccountSplitView,
    AccountChartView,
    AccountTimelineView,
)
from horilla_crm.accounts.views.detail import (
    AccountDetailView,
    AccountDetailViewTabs,
    AccountDetailsTab,
    AccountActivityTab,
    AccountHistoryTab,
    AccountRelatedListsTab,
    AccountHierarchyView,
    AccountsNotesAndAttachments,
)
from horilla_crm.accounts.views.actions import (
    AccountFormView,
    AccountsSingleFormView,
    AccountChangeOwnerForm,
    AddRelatedContactFormView,
    AddChildAccountFormView,
    AccountPartnerFormView,
    ChildAccountDeleteView,
    PartnerAccountDeleteView,
    AccountDeleteView,
)

__all__ = [
    # core
    "AccountView",
    "AccountsNavbar",
    "AccountListView",
    "AccountGroupByView",
    "AccountsKanbanView",
    "AccountCardView",
    "AccountSplitView",
    "AccountChartView",
    "AccountTimelineView",
    # detail
    "AccountDetailView",
    "AccountDetailViewTabs",
    "AccountDetailsTab",
    "AccountActivityTab",
    "AccountHistoryTab",
    "AccountRelatedListsTab",
    "AccountHierarchyView",
    "AccountsNotesAndAttachments",
    # account_form
    "AccountFormView",
    "AccountsSingleFormView",
    "AccountChangeOwnerForm",
    "AddRelatedContactFormView",
    "AddChildAccountFormView",
    "AccountPartnerFormView",
    "ChildAccountDeleteView",
    "PartnerAccountDeleteView",
    "AccountDeleteView",
]
