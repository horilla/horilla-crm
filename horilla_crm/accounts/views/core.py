"""
Accounts Core Views Module

Django views for listing accounts in Horilla CRM.
Handles the main account page, navbar and the list, group-by, split, kanban,
card, chart and timeline views.
"""

# Standard library imports
import logging
from functools import cached_property
from urllib.parse import urlencode

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.utils import field_readonly_hidden_if
from horilla.contrib.generics.views import (
    HorillaChartView,
    HorillaGroupByView,
    HorillaKanbanView,
    HorillaListView,
    HorillaNavView,
    HorillaSplitView,
    HorillaView,
)
from horilla.contrib.generics.views.card import HorillaCardView
from horilla.contrib.generics.views.timeline import HorillaTimelineView
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _

# Local imports
from horilla_crm.accounts.filters import AccountFilter
from horilla_crm.accounts.models import Account

logger = logging.getLogger(__name__)


class AccountView(LoginRequiredMixin, HorillaView):
    """
    Render the accounts page
    """

    nav_url = reverse_lazy("accounts:accounts_nav_view")
    list_url = reverse_lazy("accounts:accounts_list_view")
    kanban_url = reverse_lazy("accounts:accounts_kanban_view")
    group_by_url = reverse_lazy("accounts:accounts_group_by_view")
    card_url = reverse_lazy("accounts:accounts_card_view")
    split_view_url = reverse_lazy("accounts:accounts_split_view")
    chart_url = reverse_lazy("accounts:accounts_chart_view")
    timeline_url = reverse_lazy("accounts:accounts_timeline")


@method_decorator(
    [
        htmx_required,
        permission_required(["accounts.view_account", "accounts.view_own_account"]),
    ],
    name="dispatch",
)
class AccountsNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar View for accounts page
    """

    search_url = reverse_lazy("accounts:accounts_list_view")
    main_url = reverse_lazy("accounts:accounts_view")
    kanban_url = reverse_lazy("accounts:accounts_kanban_view")
    group_by_url = reverse_lazy("accounts:accounts_group_by_view")
    card_url = reverse_lazy("accounts:accounts_card_view")
    model_name = "Account"
    model_app_label = "accounts"
    filterset_class = AccountFilter
    exclude_kanban_fields = "company"
    enable_actions = True
    enable_quick_filters = True
    split_view_url = reverse_lazy("accounts:accounts_split_view")
    chart_url = reverse_lazy("accounts:accounts_chart_view")
    timeline_url = reverse_lazy("accounts:accounts_timeline")

    @cached_property
    def new_button(self):
        """Return the 'New Account' button if the user has add permission."""
        if self.request.user.has_perm(
            "accounts.add_account"
        ) or self.request.user.has_perm("accounts.add_own_account"):
            return {
                "url": f"""{reverse_lazy("accounts:account_single_create_form_view")}?new=true""",
                "attrs": {"id": "account-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountListView(LoginRequiredMixin, HorillaListView):
    """
    account List view
    """

    model = Account
    view_id = "accounts-list"
    filterset_class = AccountFilter
    search_url = reverse_lazy("accounts:accounts_list_view")
    main_url = reverse_lazy("accounts:accounts_view")
    enable_quick_filters = True

    def no_record_add_button(self):
        """Return the 'New Account' button if the user has add permission."""
        if self.request.user.has_perm(
            "accounts.add_account"
        ) or self.request.user.has_perm("accounts.add_own_account"):
            return {
                "url": f"""{reverse_lazy("accounts:account_single_create_form_view")}?new=true""",
                "attrs": 'id="account-create"',
            }
        return None

    columns = [
        "name",
        "account_number",
        "account_owner",
        "account_type",
        "account_source",
        "annual_revenue",
    ]

    @cached_property
    def col_attrs(self):
        """Return column attributes for HTMX interactions if the user can view accounts."""
        query_params = self.request.GET.dict()
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {
            "hx-get": f"{{get_detail_url}}?{query_string}",
            "hx-target": "#mainContent",
            "hx-swap": "outerHTML",
            "hx-push-url": "true",
            "hx-select": "#mainContent",
            "permission": "accounts.view_account",
            "own_permission": "accounts.view_own_account",
            "owner_field": "account_owner",
        }
        return [
            {
                "name": {
                    **attrs,
                }
            }
        ]

    bulk_update_fields = ["account_type", "account_owner", "account_source", "industry"]

    acc_permissions = {
        "permission": "accounts.change_account",
        "own_permission": "accounts.change_own_account",
        "owner_field": "account_owner",
    }
    actions = [
        {
            **acc_permissions,
            "action": _("Edit"),
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "attrs": """
                            hx-get="{get_edit_url}?new=true"
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            onclick="openModal()"
                            """,
        },
        {
            **acc_permissions,
            "action": _("Change Owner"),
            "src": "assets/icons/a2.svg",
            "img_class": "w-4 h-4",
            "hidden_if": field_readonly_hidden_if(Account, "account_owner"),
            "attrs": """
                        hx-get="{get_change_owner_url}"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        },
        {
            "action": _("Duplicate"),
            "src": "assets/icons/duplicate.svg",
            "img_class": "w-4 h-4",
            "permission": "accounts.add_account",
            "own_permission": "accounts.add_own_account",
            "owner_field": "account_owner",
            "attrs": """
                            hx-get="{get_duplicate_url}?duplicate=true"
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            onclick="openModal()"
                            """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "accounts.delete_account",
            "own_permission": "accounts.delete_own_account",
            "owner_field": "account_owner",
            "attrs": """
                        hx-post="{get_delete_url}"
                        hx-target="#deleteModeBox"
                        hx-swap="innerHTML"
                        hx-trigger="click"
                        hx-vals='{{"check_dependencies": "true"}}'
                        onclick="openDeleteModeModal()"
                    """,
        },
    ]


@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountGroupByView(LoginRequiredMixin, HorillaGroupByView):
    """
    Account Group By view
    """

    model = Account
    view_id = "accounts-group-by"
    filterset_class = AccountFilter
    search_url = reverse_lazy("accounts:accounts_list_view")
    main_url = reverse_lazy("accounts:accounts_view")
    enable_quick_filters = True
    group_by_field = "account_type"

    columns = [
        "name",
        "account_number",
        "account_owner",
        "account_type",
        "account_source",
        "annual_revenue",
    ]
    actions = AccountListView.actions
    bulk_update_fields = AccountListView.bulk_update_fields

    def no_record_add_button(self):
        """Return the 'New Account' button if the user has add permission."""
        if self.request.user.has_perm(
            "accounts.add_account"
        ) or self.request.user.has_perm("accounts.add_own_account"):
            return {
                "url": f"""{reverse_lazy("accounts:account_single_create_form_view")}?new=true""",
                "attrs": 'id="account-create"',
            }
        return None

    @cached_property
    def col_attrs(self):
        """Return column attributes for HTMX interactions if the user can view accounts."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {
            "hx-get": f"{{get_detail_url}}?{query_string}",
            "hx-target": "#mainContent",
            "hx-swap": "outerHTML",
            "hx-push-url": "true",
            "hx-select": "#mainContent",
            "permission": "accounts.view_account",
            "own_permission": "accounts.view_own_account",
            "owner_field": "account_owner",
        }
        return [
            {
                "name": {
                    **attrs,
                }
            }
        ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountSplitView(LoginRequiredMixin, HorillaSplitView):
    """
    Account Split view: left = tile list, right = simple details on click.
    """

    model = Account
    view_id = "accounts-split"
    filterset_class = AccountFilter
    search_url = reverse_lazy("accounts:accounts_list_view")
    main_url = reverse_lazy("accounts:accounts_view")
    enable_quick_filters = True
    split_view_permission = "accounts.view_account"
    split_view_own_permission = "accounts.view_own_account"
    split_view_owner_field = "account_owner"

    columns = ["name", "annual_revenue"]

    no_record_add_button = AccountListView.no_record_add_button
    actions = AccountListView.actions


@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountsKanbanView(LoginRequiredMixin, HorillaKanbanView):
    """
    Kanban view for account
    """

    model = Account
    view_id = "account-kanban"
    filterset_class = AccountFilter
    search_url = reverse_lazy("accounts:accounts_list_view")
    main_url = reverse_lazy("accounts:accounts_view")
    group_by_field = "account_type"

    columns = [
        "name",
        "account_number",
        "account_owner",
        "account_type",
        "account_source",
        "annual_revenue",
    ]

    actions = AccountListView.actions

    def no_record_add_button(self):
        """Return the 'New Account' button if the user has add permission."""
        if self.request.user.has_perm("accounts.add_account"):
            return {
                "url": f"""{reverse_lazy("accounts:account_single_create_form_view")}?new=true""",
                "attrs": 'id="account-create"',
            }
        return None

    @cached_property
    def kanban_attrs(self):
        """Return kanban card attributes for HTMX interactions if the user can view accounts."""

        # Build query params
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")

        query_string = urlencode(query_params)

        return {
            "hx-get": f"{{get_detail_url}}?{query_string}",
            "hx-target": "#mainContent",
            "hx-swap": "outerHTML",
            "hx-push-url": "true",
            "hx-select": "#mainContent",
            "permission": "accounts.view_account",
            "own_permission": "accounts.view_own_account",
            "owner_field": "account_owner",
        }


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountCardView(LoginRequiredMixin, HorillaCardView):
    """
    Card view for account
    """

    model = Account
    view_id = "account-card"
    filterset_class = AccountFilter
    search_url = reverse_lazy("accounts:accounts_list_view")
    main_url = reverse_lazy("accounts:accounts_view")

    columns = [
        "name",
        "account_number",
        "account_owner",
        "account_type",
        "annual_revenue",
    ]

    actions = AccountListView.actions

    col_attrs = AccountListView.col_attrs

    no_record_add_button = AccountListView.no_record_add_button


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountChartView(LoginRequiredMixin, HorillaChartView):
    """Account chart view: counts by group-by field using same filters as list/kanban."""

    model = Account
    view_id = "accounts-chart"
    filterset_class = AccountFilter
    search_url = reverse_lazy("accounts:accounts_list_view")
    main_url = reverse_lazy("accounts:accounts_view")
    group_by_field = "account_type"
    exclude_chart_fields = "company"
    chart_numeric_metrics = {
        "number_of_employees": ["avg", "min", "max"],
        "account_score": ["avg", "min", "max"],
    }


@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountTimelineView(LoginRequiredMixin, HorillaTimelineView):
    """Timeline from created_at to updated_at; rows by account_type."""

    model = Account
    view_id = "accounts-timeline"
    filterset_class = AccountFilter
    search_url = reverse_lazy("accounts:accounts_list_view")
    main_url = reverse_lazy("accounts:accounts_view")
    enable_quick_filters = True
    timeline_start_field = "created_at"
    timeline_end_field = "updated_at"
    timeline_group_by_field = "account_type"
    timeline_title_field = "name"
    columns = [
        "name",
        "account_number",
        "account_owner",
        "account_type",
    ]
    actions = AccountListView.actions
    col_attrs = AccountListView.col_attrs
