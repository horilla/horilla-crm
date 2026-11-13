"""
Accounts Detail Views Module

Django views for viewing a single account in Horilla CRM.
Handles the account detail page, its tabs, hierarchy and notes/attachments.
"""

# Standard library imports
from functools import cached_property
from urllib.parse import urlencode

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.activity.views import HorillaActivitySectionView
from horilla.contrib.generics.mixins import RecentlyViewedMixin
from horilla.contrib.generics.views import (
    HorillaDetailSectionView,
    HorillaDetailTabView,
    HorillaDetailView,
    HorillaHistorySectionView,
    HorillaNotesAttachementSectionView,
    HorillaRelatedListSectionView,
)
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.html import escapejs
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View

# Local imports
from horilla_crm.accounts.models import Account, PartnerAccountRelationship
from horilla_crm.accounts.views.core import AccountListView
from horilla_crm.contacts.models import ContactAccountRelationship


@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountDetailView(RecentlyViewedMixin, LoginRequiredMixin, HorillaDetailView):
    """
    Detail view for account
    """

    model = Account
    breadcrumbs = [
        ("People", "accounts:accounts_view"),
        ("Accounts", "accounts:accounts_view"),
    ]
    body = [
        "name",
        "account_owner",
        "account_source",
        "industry",
        "annual_revenue",
        "account_type",
    ]
    tab_url = reverse_lazy("accounts:account_detail_view_tabs")

    actions = AccountListView.actions


@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountDetailViewTabs(LoginRequiredMixin, HorillaDetailTabView):
    """
    Tab Views for account detail view
    """

    def _prepare_detail_tabs(self):
        self.object_id = self.request.GET.get("object_id")
        self.model = Account
        super()._prepare_detail_tabs()

    urls = {
        "details": "accounts:account_details_tab_view",
        "activity": "accounts:account_activity_tab_view",
        "related_lists": "accounts:account_related_list_tab_view",
        "notes_attachments": "accounts:account_notes_attachements",
        "history": "accounts:account_history_tab_view",
    }


@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountDetailsTab(LoginRequiredMixin, HorillaDetailSectionView):
    """
    Details Tab view of account detail view
    """

    model = Account


@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountActivityTab(LoginRequiredMixin, HorillaActivitySectionView):
    """
    account detain view activity tab
    """

    model = Account


@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountHistoryTab(LoginRequiredMixin, HorillaHistorySectionView):
    """
    History tab foe account detail view
    """

    model = Account


@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountRelatedListsTab(LoginRequiredMixin, HorillaRelatedListSectionView):
    """
    Related list tab view
    """

    model = Account

    @cached_property
    def related_list_config(self):
        """
        Return configuration for related lists (child accounts, contacts, partners)
        with columns, actions, and add URLs.
        """
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        pk = self.request.GET.get("object_id")
        referrer_url = "account_detail_view"
        opportunity_model = self.model._meta.get_field(
            "opportunity_account"
        ).related_model
        contact_custom_buttons = []
        if self._can_add_to_related():
            contact_custom_buttons.append(
                {
                    "label": _("Add Relationship"),
                    "url": reverse_lazy("accounts:create_account_contact_relation"),
                    "attrs": """
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            onclick="openModal()"
                            hx-indicator="#modalBox"
                        """,
                    "icon": "fa-solid fa-users",
                    "class": "outline outline-1 outline-offset-[-1px] outline-primary-600 rounded-md hover:bg-primary-300 transition duration-300 text-primary-600 bg-white cursor-pointer text-sm px-4 py-1",
                }
            )

        if self._can_add_to_related():
            contact_custom_buttons.append(
                {
                    "label": _("New Contact"),
                    "url": reverse_lazy(
                        "contacts:related_account_contact_single_create_form"
                    ),
                    "attrs": """
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            onclick="openModal()"
                            hx-indicator="#modalBox"
                        """,
                    "icon": "fa-solid fa-user-plus",
                    "class": "bg-primary-600 rounded-md hover:bg-primary-800 transition duration-300 text-white text-sm px-4 py-1 cursor-pointer",
                }
            )

        return {
            "custom_related_lists": {
                "contact_relationships": {
                    "app_label": "contacts",
                    "model_name": "Contact",
                    "intermediate_model": "ContactAccountRelationship",
                    "intermediate_field": "contact",
                    "related_field": "account",
                    "config": {
                        "title": _("Related Contacts"),
                        "columns": [
                            (
                                ContactAccountRelationship._meta.get_field("contact")
                                .related_model._meta.get_field("first_name")
                                .verbose_name,
                                "first_name",
                            ),
                            (
                                ContactAccountRelationship._meta.get_field("contact")
                                .related_model._meta.get_field("last_name")
                                .verbose_name,
                                "last_name",
                            ),
                            (
                                ContactAccountRelationship._meta.get_field(
                                    "role"
                                ).verbose_name,
                                "account_relationships__role",
                            ),
                        ],
                        "custom_buttons": contact_custom_buttons,
                        "col_attrs": [
                            {
                                "title": {
                                    "permission": "contacts.view_contact",
                                    "own_permission": "contacts.view_own_contact",
                                    "owner_field": "contact_owner",
                                    "hx-get": f"{{get_detail_url}}?referrer_app={self.model._meta.app_label}&referrer_model={self.model._meta.model_name}&referrer_id={pk}&referrer_url={referrer_url}&{query_string}",
                                    "hx-target": "#mainContent",
                                    "hx-swap": "outerHTML",
                                    "hx-push-url": "true",
                                    "hx-select": "#mainContent",
                                }
                            }
                        ],
                        "actions": [
                            (
                                {
                                    "permission": "contacts.change_contactaccountrelationship",
                                    "own_permission": "contacts.change_own_contactaccountrelationship",
                                    "owner_field": "created_by",
                                    "intermediate_model": "ContactAccountRelationship",
                                    "intermediate_field": "contact",
                                    "parent_field": "account",
                                    "action": _("Edit"),
                                    "src": "assets/icons/edit.svg",
                                    "img_class": "w-4 h-4",
                                    "attrs": """
                                            hx-get="{get_edit_account_contact_relation_url}?new=true"
                                            hx-target="#modalBox"
                                            hx-swap="innerHTML"
                                            onclick="openModal()"
                                            """,
                                }
                            ),
                            (
                                {
                                    "permission": "contacts.delete_contactaccountrelationship",
                                    "action": "Delete",
                                    "src": "assets/icons/a4.svg",
                                    "img_class": "w-4 h-4",
                                    "attrs": """
                                                hx-post="{get_delete_related_contact_url}"
                                                hx-target="#deleteModeBox"
                                                hx-swap="innerHTML"
                                                hx-trigger="click"
                                                hx-vals='{{"check_dependencies": "true"}}'
                                                onclick="openDeleteModeModal()"
                                            """,
                                }
                            ),
                        ],
                    },
                },
                "partner": {
                    "app_label": "accounts",
                    "model_name": "Account",
                    "intermediate_model": "PartnerAccountRelationship",
                    "intermediate_field": "partner",
                    "related_field": "account",
                    "config": {
                        "title": _("Partner"),
                        "can_add": self._can_add_to_related(),
                        "add_url": reverse_lazy("accounts:account_partner_create_form"),
                        "columns": [
                            (
                                PartnerAccountRelationship._meta.get_field("partner")
                                .related_model._meta.get_field("name")
                                .verbose_name,
                                "name",
                            ),
                            (
                                PartnerAccountRelationship._meta.get_field("partner")
                                .related_model._meta.get_field("annual_revenue")
                                .verbose_name,
                                "annual_revenue",
                            ),
                            (
                                PartnerAccountRelationship._meta.get_field(
                                    "role"
                                ).verbose_name,
                                "partner__role",
                            ),
                        ],
                        "col_attrs": [
                            {
                                "name": {
                                    "hx-get": f"{{get_detail_url}}?referrer_app={self.model._meta.app_label}&referrer_model={self.model._meta.model_name}&referrer_id={pk}&referrer_url={referrer_url}&{query_string}",
                                    "hx-target": "#mainContent",
                                    "hx-swap": "outerHTML",
                                    "hx-push-url": "true",
                                    "hx-select": "#mainContent",
                                    "permission": "accounts.view_account",
                                    "own_permission": "accounts.view_own_account",
                                    "owner_field": "account_owner",
                                }
                            }
                        ],
                        "actions": [
                            (
                                {
                                    "action": _("Edit"),
                                    "src": "assets/icons/edit.svg",
                                    "img_class": "w-4 h-4",
                                    "permission": "accounts.change_partneraccountrelationship",
                                    "own_permission": "accounts.change_own_partneraccountrelationship",
                                    "owner_field": "created_by",
                                    "intermediate_model": "PartnerAccountRelationship",
                                    "intermediate_field": "partner",
                                    "parent_field": "account",
                                    "attrs": """
                                            hx-get="{get_account_partner_url}?new=true"
                                            hx-target="#modalBox"
                                            hx-swap="innerHTML"
                                            onclick="openModal()"
                                            """,
                                }
                            ),
                            (
                                {
                                    "action": "Delete",
                                    "src": "assets/icons/a4.svg",
                                    "img_class": "w-4 h-4",
                                    "permission": "accounts.delete_partneraccountrelationship",
                                    "attrs": """
                                            hx-post="{get_account_partner_delete_url}"
                                            hx-target="#deleteModeBox"
                                            hx-swap="innerHTML"
                                            hx-trigger="click"
                                            hx-vals='{{"check_dependencies": "true"}}'
                                            onclick="openDeleteModeModal()"
                                            """,
                                }
                            ),
                        ],
                    },
                },
            },
            "child_accounts": {
                "title": _("Child Accounts"),
                "can_add": self._can_add_to_related(),
                "add_url": reverse_lazy("accounts:create_child_accounts"),
                "columns": [
                    (Account._meta.get_field("name").verbose_name, "name"),
                    (
                        Account._meta.get_field("account_type").verbose_name,
                        "get_account_type_display",
                    ),
                    (
                        Account._meta.get_field("annual_revenue").verbose_name,
                        "annual_revenue",
                    ),
                ],
                "col_attrs": [
                    {
                        "name": {
                            "hx-get": f"{{get_detail_url}}?referrer_app={self.model._meta.app_label}&referrer_model={self.model._meta.model_name}&referrer_id={pk}&referrer_url={referrer_url}&{query_string}",
                            "hx-target": "#mainContent",
                            "hx-swap": "outerHTML",
                            "hx-push-url": "true",
                            "hx-select": "#mainContent",
                            "permission": "accounts.view_account",
                            "own_permission": "accounts.view_own_account",
                            "owner_field": "account_owner",
                        }
                    }
                ],
                "actions": [
                    (
                        {
                            "action": "delete",
                            "src": "/assets/icons/a4.svg",
                            "img_class": "w-4 h-4",
                            "permission": "accounts.delete_account",
                            "attrs": f"""
                                    hx-delete="{{get_child_account_url}}"
                                    hx-on:click="hxConfirm(this,'{escapejs(_("Are you sure you want to remove this child account relationship?"))}')"
                                    hx-target="#deleteModeBox"
                                    hx-swap="innerHTML"
                                    hx-trigger="confirmed"
                                    """,
                        }
                    ),
                ],
                "custom_buttons": [
                    {
                        "label": _("View Hierarchy"),
                        "url": reverse_lazy("accounts:account_hierarchy"),
                        "attrs": """
                                        hx-target="#modalBox"
                                        hx-swap="innerHTML"
                                        onclick="openModal()"
                                        hx-indicator="#modalBox"
                                    """,
                        "icon": "fa-solid fa-sitemap",
                        "class": "outline outline-1 outline-offset-[-1px] outline-primary-600 rounded-md hover:bg-primary-300 transition duration-300 text-primary-600 bg-white text-sm px-4 py-1",
                    },
                ],
            },
            "opportunity_account": {
                "title": _("Opportunities"),
                "can_add": self._can_add_to_related(),
                "add_url": reverse_lazy("opportunities:opportunity_single_create"),
                "columns": [
                    (
                        opportunity_model._meta.get_field("name").verbose_name,
                        "name",
                    ),
                    (
                        opportunity_model._meta.get_field("amount").verbose_name,
                        "amount",
                    ),
                    (
                        opportunity_model._meta.get_field("stage").verbose_name,
                        "stage__name",
                    ),
                    (
                        opportunity_model._meta.get_field("close_date").verbose_name,
                        "close_date",
                    ),
                ],
                "col_attrs": [
                    {
                        "name": {
                            "hx-get": f"{{get_detail_url}}?referrer_app={self.model._meta.app_label}&referrer_model={self.model._meta.model_name}&referrer_id={pk}&referrer_url={referrer_url}&{query_string}",
                            "hx-target": "#mainContent",
                            "hx-swap": "outerHTML",
                            "hx-push-url": "true",
                            "hx-select": "#mainContent",
                            "style": "cursor:pointer",
                            "class": "hover:text-primary-600",
                        }
                    }
                ],
                "actions": [
                    (
                        {
                            "action": _("Edit"),
                            "src": "assets/icons/edit.svg",
                            "img_class": "w-4 h-4",
                            "permission": "opportunities.change_opportunity",
                            "own_permission": "opportunities.change_own_opportunity",
                            "owner_field": "owner",
                            "attrs": """
                                hx-get="{get_edit_url}?new=true"
                                hx-target="#modalBox"
                                hx-swap="innerHTML"
                                onclick="openModal()"
                                """,
                        }
                    ),
                    (
                        {
                            "action": "Delete",
                            "src": "assets/icons/a4.svg",
                            "img_class": "w-4 h-4",
                            "permission": "opportunities.delete_opportunity",
                            "attrs": """
                                    hx-post="{get_delete_url}"
                                    hx-target="#deleteModeBox"
                                    hx-swap="innerHTML"
                                    hx-trigger="click"
                                    hx-vals='{{"check_dependencies": "true"}}'
                                    onclick="openDeleteModeModal()"
                                """,
                        }
                    ),
                ],
            },
        }

    excluded_related_lists = ["contact_relationships", "partner_account", "partner"]


def _build_account_tree(account, visited=None):
    """Build tree of account and descendants for <details> hierarchy."""
    if visited is None:
        visited = set()
    if account.pk in visited:
        return {"account": account, "children": []}
    visited.add(account.pk)
    return {
        "account": account,
        "children": [
            _build_account_tree(c, visited) for c in account.child_accounts.all()
        ],
    }


def _get_root_account(account):
    """Traverse up to the topmost ancestor of an account, guarded against cycles."""
    visited = {account.pk}
    while account.parent_account is not None:
        if account.parent_account_id in visited:
            break
        visited.add(account.parent_account_id)
        account = account.parent_account
    return account


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountHierarchyView(LoginRequiredMixin, View):
    """Modal view showing account hierarchy with expand/collapse (no JS)."""

    def get(self, request, *args, **kwargs):
        """
        Get method for account hierarchy
        """
        account_id = request.GET.get("id")
        if not account_id:
            return render(request, "403.html", {"modal": True})
        account = get_object_or_404(Account, pk=account_id)
        root_account = _get_root_account(account)
        root = _build_account_tree(root_account)
        return render(
            request,
            "account_hierarchy_modal.html",
            {"root": root, "active_account_id": account.pk},
        )


@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountsNotesAndAttachments(
    LoginRequiredMixin, HorillaNotesAttachementSectionView
):
    """Notes and attachments section for Account objects."""

    model = Account
