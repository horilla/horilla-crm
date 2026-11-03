"""
Core contact views for the CRM system.
Includes the main contact page, navbar, and the list, group-by, split, kanban,
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
from horilla_crm.contacts.filters import ContactFilter
from horilla_crm.contacts.models import Contact

logger = logging.getLogger(__name__)


class ContactView(LoginRequiredMixin, HorillaView):
    """
    Render the contact page
    """

    nav_url = reverse_lazy("contacts:contacts_navbar")
    list_url = reverse_lazy("contacts:contact_list_view")
    kanban_url = reverse_lazy("contacts:contact_kanban_view")
    group_by_url = reverse_lazy("contacts:contact_group_by_view")
    card_url = reverse_lazy("contacts:contact_card_view")
    split_view_url = reverse_lazy("contacts:contact_split_view")
    chart_url = reverse_lazy("contacts:contact_chart_view")
    timeline_url = reverse_lazy("contacts:contacts_timeline")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required(["contacts.view_contact", "contacts.view_own_contact"]),
    name="dispatch",
)
class ContactNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar View for Contact page
    """

    search_url = reverse_lazy("contacts:contact_list_view")
    main_url = reverse_lazy("contacts:contacts_view")
    kanban_url = reverse_lazy("contacts:contact_kanban_view")
    group_by_url = reverse_lazy("contacts:contact_group_by_view")
    card_url = reverse_lazy("contacts:contact_card_view")
    model_str = "contacts.Contact"
    model_name = "Contact"
    model_app_label = "contacts"
    filterset_class = ContactFilter
    exclude_kanban_fields = "company"
    enable_actions = True
    enable_quick_filters = True
    split_view_url = reverse_lazy("contacts:contact_split_view")
    chart_url = reverse_lazy("contacts:contact_chart_view")
    timeline_url = reverse_lazy("contacts:contacts_timeline")

    @cached_property
    def new_button(self):
        """Create a new contact button"""
        if self.request.user.has_perm(
            "contacts.add_contact"
        ) or self.request.user.has_perm("contacts.add_own_contact"):
            return {
                "url": f"""{reverse_lazy("contacts:contact_single_create_form")}?new=true""",
                "attrs": {"id": "contact-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["contacts.view_contact", "contacts.view_own_contact"]
    ),
    name="dispatch",
)
class ContactListView(LoginRequiredMixin, HorillaListView):
    """
    Contact List View
    """

    model = Contact
    paginate_by = 20
    view_id = "contact-list"
    filterset_class = ContactFilter
    search_url = reverse_lazy("contacts:contact_list_view")
    main_url = reverse_lazy("contacts:contacts_view")
    enable_quick_filters = True
    max_visible_actions = 5

    def no_record_add_button(self):
        """Button to add a new contact if no records exist"""
        if self.request.user.has_perm(
            "contacts.add_contact"
        ) or self.request.user.has_perm("contacts.add_own_contact"):
            return {
                "url": f"""{reverse_lazy("contacts:contact_single_create_form")}?new=true""",
                "attrs": 'id="contact-create"',
            }
        return None

    bulk_update_fields = [
        "title",
        "contact_source",
        "languages",
        "address_city",
        "address_state",
        "address_zip",
        "address_country",
        "is_primary",
    ]

    header_attrs = [
        {"email": {"style": "width: 250px;"}, "title": {"style": "width: 250px;"}},
    ]

    columns = [
        "first_name",
        "last_name",
        "title",
        "email",
        "contact_number",
        "contact_source",
    ]

    contact_permissions = {
        "permission": "contacts.change_contact",
        "own_permission": "contacts.change_own_contact",
        "owner_field": "contact_owner",
    }
    actions = [
        {
            **contact_permissions,
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
            **contact_permissions,
            "action": _("Change Owner"),
            "src": "assets/icons/a2.svg",
            "img_class": "w-4 h-4",
            "hidden_if": field_readonly_hidden_if(Contact, "contact_owner"),
            "attrs": """
                        hx-get="{get_change_owner_url}"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        },
        {
            **contact_permissions,
            "action": _("Link Leads"),
            "src": "assets/icons/link-record.svg",
            "img_class": "w-4 h-4",
            "attrs": """
                        hx-get="{get_link_leads_url}"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        },
        {
            "action": _("Duplicate"),
            "src": "assets/icons/duplicate.svg",
            "img_class": "w-4 h-4",
            "permission": "contacts.add_contact",
            "own_permission": "contacts.add_own_contact",
            "owner_field": "contact_owner",
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
            "permission": "contacts.delete_contact",
            "own_permission": "contacts.delete_own_contact",
            "owner_field": "contact_owner",
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

    @cached_property
    def col_attrs(self):
        """Attributes for columns in the contact list"""
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
            "permission": "contacts.view_contact",
            "own_permission": "contacts.view_own_contact",
            "owner_field": "contact_owner",
        }
        return [
            {
                "first_name": {
                    **attrs,
                }
            }
        ]


@method_decorator(
    permission_required_or_denied(
        ["contacts.view_contact", "contacts.view_own_contact"]
    ),
    name="dispatch",
)
class ContactGroupByView(LoginRequiredMixin, HorillaGroupByView):
    """
    Contact Group By view
    """

    model = Contact
    view_id = "contacts-group-by"
    filterset_class = ContactFilter
    search_url = reverse_lazy("contacts:contact_list_view")
    main_url = reverse_lazy("contacts:contacts_view")
    enable_quick_filters = True
    group_by_field = "contact_source"

    columns = [
        "first_name",
        "last_name",
        "title",
        "email",
        "contact_number",
        "contact_source",
    ]
    actions = ContactListView.actions
    bulk_update_fields = ContactListView.bulk_update_fields

    def no_record_add_button(self):
        """Button to add a new contact if no records exist"""
        if self.request.user.has_perm(
            "contacts.add_contact"
        ) or self.request.user.has_perm("contacts.add_own_contact"):
            return {
                "url": f"""{reverse_lazy("contacts:contact_single_create_form")}?new=true""",
                "attrs": 'id="contact-create"',
            }
        return None

    @cached_property
    def col_attrs(self):
        """Attributes for columns in the contact group-by view"""
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
            "permission": "contacts.view_contact",
            "own_permission": "contacts.view_own_contact",
            "owner_field": "contact_owner",
        }
        return [
            {
                "first_name": {
                    **attrs,
                }
            }
        ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["contacts.view_contact", "contacts.view_own_contact"]
    ),
    name="dispatch",
)
class ContactSplitView(LoginRequiredMixin, HorillaSplitView):
    """
    Contact Split view: left = tile list, right = simple details on click.
    """

    model = Contact
    view_id = "contact-split"
    filterset_class = ContactFilter
    search_url = reverse_lazy("contacts:contact_list_view")
    main_url = reverse_lazy("contacts:contacts_view")
    enable_quick_filters = True
    split_view_permission = "contacts.view_contact"
    split_view_own_permission = "contacts.view_own_contact"
    split_view_owner_field = "contact_owner"

    columns = ["first_name", "email"]

    no_record_add_button = ContactListView.no_record_add_button
    actions = ContactListView.actions


@method_decorator(
    permission_required_or_denied(
        ["contacts.view_contact", "contacts.view_own_contact"]
    ),
    name="dispatch",
)
class ContactKanbanView(LoginRequiredMixin, HorillaKanbanView):
    """
    Kanban view for Contact
    """

    model = Contact
    view_id = "contact-kanban"
    filterset_class = ContactFilter
    search_url = reverse_lazy("contacts:contact_list_view")
    main_url = reverse_lazy("contacts:contacts_view")
    group_by_field = "contact_source"
    actions = ContactListView.actions

    columns = ["first_name", "title", "email", "contact_number", "birth_date"]

    @cached_property
    def kanban_attrs(self):
        """Attributes for columns in the contact kanban"""
        query_params = self.request.GET.dict()
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        if self.request.user.has_perm(
            "contacts.view_contact"
        ) or self.request.user.has_perm("contacts.view_own_contact"):
            return f"""
                    hx-get="{{get_detail_url}}?{query_string}"
                    hx-target="#mainContent"
                    hx-swap="outerHTML"
                    hx-push-url="true"
                    hx-select="#mainContent"
                    style ="cursor:pointer",
                    """
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["contacts.view_contact", "contacts.view_own_contact"]
    ),
    name="dispatch",
)
class ContactCardView(LoginRequiredMixin, HorillaCardView):
    """
    Card view for Contact
    """

    model = Contact
    view_id = "contact-card"
    filterset_class = ContactFilter
    search_url = reverse_lazy("contacts:contact_list_view")
    main_url = reverse_lazy("contacts:contacts_view")

    columns = ["first_name", "title", "email", "contact_number", "birth_date"]

    actions = ContactListView.actions

    col_attrs = ContactListView.col_attrs

    no_record_add_button = ContactListView.no_record_add_button


@method_decorator(
    permission_required_or_denied(
        ["contacts.view_contact", "contacts.view_own_contact"]
    ),
    name="dispatch",
)
class ContactTimelineView(LoginRequiredMixin, HorillaTimelineView):
    """Timeline from created_at to updated_at; rows by contact_source."""

    model = Contact
    view_id = "contacts-timeline"
    filterset_class = ContactFilter
    search_url = reverse_lazy("contacts:contact_list_view")
    main_url = reverse_lazy("contacts:contacts_view")
    enable_quick_filters = True
    timeline_start_field = "created_at"
    timeline_end_field = "updated_at"
    timeline_group_by_field = "contact_source"
    timeline_title_field = "first_name"
    columns = ["first_name", "last_name", "title", "email", "contact_source"]
    actions = ContactListView.actions
    col_attrs = ContactListView.col_attrs


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["contacts.view_contact", "contacts.view_own_contact"]
    ),
    name="dispatch",
)
class ContactChartView(LoginRequiredMixin, HorillaChartView):
    """Contact chart view: counts by group-by field using same filters as list/kanban."""

    model = Contact
    view_id = "contacts-chart"
    filterset_class = ContactFilter
    search_url = reverse_lazy("contacts:contact_list_view")
    main_url = reverse_lazy("contacts:contacts_view")
    group_by_field = "contact_source"
    exclude_chart_fields = "company"
    chart_numeric_metrics = {"contact_score": ["avg", "min", "max"]}
