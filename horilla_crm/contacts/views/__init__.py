"""Aggregate and re-export contact-related views for convenience imports."""

# Local imports
from horilla_crm.contacts.views.core import (
    ContactGroupByView,
    ContactKanbanView,
    ContactListView,
    ContactNavbar,
    ContactView,
    ContactCardView,
    ContactSplitView,
    ContactChartView,
    ContactTimelineView,
)
from horilla_crm.contacts.views.detail import (
    ContactActivityTab,
    ContactDetailTab,
    ContactDetailView,
    ContactDetailViewTabs,
    ContactHierarchyView,
    ContactHistorytab,
    ContactRelatedListsTab,
    ContactsNotesAndAttachments,
)
from horilla_crm.contacts.views.actions import (
    AddChildContactFormView,
    AddRelatedAccountsFormView,
    ChildContactDeleteView,
    ContactChangeOwnerFormView,
    ContactDeleteView,
    ContactFormView,
    ContactsSingleFormView,
    RelatedContactDeleteView,
    RelatedContactFormView,
    RelatedContactSingleFormView,
)

__all__ = [
    # core
    "ContactView",
    "ContactNavbar",
    "ContactListView",
    "ContactGroupByView",
    "ContactKanbanView",
    "ContactCardView",
    "ContactSplitView",
    "ContactChartView",
    "ContactTimelineView",
    # detail
    "ContactDetailView",
    "ContactDetailViewTabs",
    "ContactDetailTab",
    "ContactActivityTab",
    "ContactsNotesAndAttachments",
    "ContactHistorytab",
    "ContactRelatedListsTab",
    "ContactHierarchyView",
    # actions
    "ContactFormView",
    "ContactsSingleFormView",
    "RelatedContactFormView",
    "RelatedContactSingleFormView",
    "ContactChangeOwnerFormView",
    "AddRelatedAccountsFormView",
    "AddChildContactFormView",
    "ChildContactDeleteView",
    "ContactDeleteView",
    "RelatedContactDeleteView",
]
