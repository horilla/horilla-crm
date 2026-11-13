"""Opportunity list, navbar, kanban, group-by and delete views."""

# Standard library imports
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
    HorillaSingleDeleteView,
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
from horilla.utils.functional import cached_property  # type: ignore
from horilla.utils.translation import gettext_lazy as _
from horilla.web import HxTriggerResponse

# Local imports
from horilla_crm.opportunities.filters import OpportunityFilter
from horilla_crm.opportunities.models import Opportunity


class OpportunityView(LoginRequiredMixin, HorillaView):
    """Render the opportunities page."""

    nav_url = reverse_lazy("opportunities:opportunities_nav")
    list_url = reverse_lazy("opportunities:opportunities_list")
    kanban_url = reverse_lazy("opportunities:opportunities_kanban")
    group_by_url = reverse_lazy("opportunities:opportunities_group_by")
    card_url = reverse_lazy("opportunities:opportunities_card")
    split_view_url = reverse_lazy("opportunities:opportunities_split_view")
    chart_url = reverse_lazy("opportunities:opportunities_chart")
    timeline_url = reverse_lazy("opportunities:opportunities_timeline")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityNavbar(LoginRequiredMixin, HorillaNavView):
    """Navigation bar view for opportunities."""

    search_url = reverse_lazy("opportunities:opportunities_list")
    main_url = reverse_lazy("opportunities:opportunities_view")
    filterset_class = OpportunityFilter
    kanban_url = reverse_lazy("opportunities:opportunities_kanban")
    group_by_url = reverse_lazy("opportunities:opportunities_group_by")
    card_url = reverse_lazy("opportunities:opportunities_card")
    split_view_url = reverse_lazy("opportunities:opportunities_split_view")
    chart_url = reverse_lazy("opportunities:opportunities_chart")
    timeline_url = reverse_lazy("opportunities:opportunities_timeline")
    model_name = "Opportunity"
    model_app_label = "opportunities"
    exclude_kanban_fields = "owner"
    enable_actions = True
    enable_quick_filters = True

    @cached_property
    def new_button(self):
        """Return new button configuration for opportunities."""
        if self.request.user.has_perm(
            "opportunities.add_opportunity"
        ) or self.request.user.has_perm("opportunities.add_own_opportunity"):
            return {
                "url": f"""{reverse_lazy("opportunities:opportunity_single_create")}?new=true""",
                "attrs": {"id": "opportunity-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityListView(LoginRequiredMixin, HorillaListView):
    """
    Opportunity List view
    """

    model = Opportunity
    view_id = "opportunity-container"
    filterset_class = OpportunityFilter
    search_url = reverse_lazy("opportunities:opportunities_list")
    main_url = reverse_lazy("opportunities:opportunities_view")
    enable_quick_filters = True
    bulk_update_fields = ["owner", "opportunity_type", "lead_source"]
    max_visible_actions = 5
    header_attrs = [
        {"email": {"style": "width: 300px;"}, "title": {"style": "width: 200px;"}},
    ]

    @cached_property
    def col_attrs(self):
        """Return column attributes for opportunity list view."""
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
            "permission": "opportunities.view_opportunity",
            "own_permission": "opportunities.view_own_opportunity",
            "owner_method": "is_view_granted",
        }
        return [
            {
                "name": {
                    **attrs,
                }
            }
        ]

    def no_record_add_button(self):
        """Return add button configuration when no records exist."""
        if self.request.user.has_perm(
            "opportunities.add_opportunity"
        ) or self.request.user.has_perm("opportunities.add_own_opportunity"):
            return {
                "url": f"""{reverse_lazy("opportunities:opportunity_single_create")}?new=true""",
                "attrs": 'id="opportunity-create"',
            }
        return None

    columns = [
        "name",
        "amount",
        "close_date",
        "stage",
        "opportunity_type",
        "primary_campaign_source",
    ]

    opp_permissions = {
        "permission": "opportunities.change_opportunity",
        "own_permission": "opportunities.change_own_opportunity",
        "owner_method": "is_change_granted",
    }

    actions = [
        {
            **opp_permissions,
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
            **opp_permissions,
            "action": _("Change Owner"),
            "src": "assets/icons/a2.svg",
            "img_class": "w-4 h-4",
            "hidden_if": field_readonly_hidden_if(Opportunity, "owner"),
            "attrs": """
                    hx-get="{get_change_owner_url}?new=true"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    onclick="openModal()"
                    """,
        },
        {
            **opp_permissions,
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
            "permission": "opportunities.add_opportunity",
            "own_permission": "opportunities.add_own_opportunity",
            "owner_method": "is_change_granted",
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
            "permission": "opportunities.delete_opportunity",
            "own_permission": "opportunities.delete_own_opportunity",
            "owner_method": "is_delete_granted",
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


@method_decorator(htmx_required, name="dispatch")
class OpportunityDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View for deleting opportunities."""

    model = Opportunity

    def get_post_delete_response(self):
        """Return response after deleting opportunity."""
        return HxTriggerResponse()


@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityKanbanView(LoginRequiredMixin, HorillaKanbanView):
    """
    Lead Kanban view
    """

    model = Opportunity
    view_id = "opportunity-kanban"
    filterset_class = OpportunityFilter
    search_url = reverse_lazy("opportunities:opportunities_list")
    main_url = reverse_lazy("opportunities:opportunities_view")
    group_by_field = "stage"

    actions = OpportunityListView.actions

    @cached_property
    def kanban_attrs(self):
        """
        Returns attributes for kanban cards (as a dict).
        """
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
            "permission": "opportunities.view_opportunity",
            "own_permission": "opportunities.view_own_opportunity",
            "owner_method": "is_view_granted",
        }

    columns = [
        "name",
        "amount",
        "owner",
        "close_date",
        "expected_revenue",
    ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityCardView(LoginRequiredMixin, HorillaCardView):
    """
    Opportunity Card view
    """

    model = Opportunity
    view_id = "opportunity-card"
    filterset_class = OpportunityFilter
    search_url = reverse_lazy("opportunities:opportunities_list")
    main_url = reverse_lazy("opportunities:opportunities_view")

    columns = [
        "name",
        "owner",
        "close_date",
        "expected_revenue",
        "stage",
    ]

    actions = OpportunityListView.actions

    col_attrs = OpportunityListView.col_attrs

    no_record_add_button = OpportunityListView.no_record_add_button


@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityGroupByView(LoginRequiredMixin, HorillaGroupByView):
    """
    Opportunity Group By view
    """

    model = Opportunity
    view_id = "opportunity-group-by"
    filterset_class = OpportunityFilter
    search_url = reverse_lazy("opportunities:opportunities_list")
    main_url = reverse_lazy("opportunities:opportunities_view")
    enable_quick_filters = True
    group_by_field = "stage"

    columns = [
        "name",
        "amount",
        "close_date",
        "stage",
        "opportunity_type",
        "primary_campaign_source",
    ]
    actions = OpportunityListView.actions
    bulk_update_fields = OpportunityListView.bulk_update_fields

    @cached_property
    def col_attrs(self):
        """Return column attributes for opportunity group by view."""
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
            "permission": "opportunities.view_opportunity",
            "own_permission": "opportunities.view_own_opportunity",
            "owner_method": "is_view_granted",
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
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunitySplitView(LoginRequiredMixin, HorillaSplitView):
    """
    Opportunity Split view: left = tile list, right = simple details on click.
    """

    model = Opportunity
    view_id = "opportunity-split"
    filterset_class = OpportunityFilter
    search_url = reverse_lazy("opportunities:opportunities_list")
    main_url = reverse_lazy("opportunities:opportunities_view")
    split_view_permission = "opportunities.view_opportunity"
    split_view_own_permission = "opportunities.view_own_opportunity"
    split_view_owner_method = "is_view_granted"

    columns = ["name", "amount"]

    no_record_add_button = OpportunityListView.no_record_add_button


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityChartView(LoginRequiredMixin, HorillaChartView):
    """Opportunity chart view: counts by group-by field using same filters as list/kanban."""

    model = Opportunity
    view_id = "opportunity-chart"
    filterset_class = OpportunityFilter
    search_url = reverse_lazy("opportunities:opportunities_list")
    main_url = reverse_lazy("opportunities:opportunities_view")
    group_by_field = "stage"
    exclude_chart_fields = "owner"
    chart_numeric_metrics = {
        "probability": ["avg", "min", "max"],
        "opportunity_score": ["avg", "min", "max"],
    }


@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityTimelineView(LoginRequiredMixin, HorillaTimelineView):
    """Timeline from created_at to close_date (fallback updated_at); rows by stage."""

    model = Opportunity
    view_id = "opportunity-timeline"
    filterset_class = OpportunityFilter
    search_url = reverse_lazy("opportunities:opportunities_list")
    main_url = reverse_lazy("opportunities:opportunities_view")
    enable_quick_filters = True
    timeline_start_field = "created_at"
    timeline_end_field = "close_date"
    timeline_fallback_end_field = "updated_at"
    timeline_group_by_field = "stage"
    timeline_title_field = "name"
    columns = [
        "name",
        "amount",
        "close_date",
        "stage",
        "opportunity_type",
    ]
    actions = OpportunityListView.actions
    col_attrs = OpportunityListView.col_attrs
