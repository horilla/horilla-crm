"""
Views for Campaigns
"""

# Standard library imports
import logging
from functools import cached_property
from urllib.parse import urlencode

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.activity.views import HorillaActivitySectionView
from horilla.contrib.core.utils import field_readonly_hidden_if
from horilla.contrib.generics.mixins import RecentlyViewedMixin
from horilla.contrib.generics.views import (
    HorillaChartView,
    HorillaDetailSectionView,
    HorillaDetailTabView,
    HorillaDetailView,
    HorillaGroupByView,
    HorillaHistorySectionView,
    HorillaKanbanView,
    HorillaListView,
    HorillaNavView,
    HorillaNotesAttachementSectionView,
    HorillaRelatedListSectionView,
    HorillaSplitView,
    HorillaView,
)
from horilla.contrib.generics.views.card import HorillaCardView
from horilla.contrib.generics.views.timeline import HorillaTimelineView
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.html import escapejs
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View

# Local imports
from horilla_crm.campaigns.filters import CampaignFilter
from horilla_crm.campaigns.models import Campaign, CampaignMember

logger = logging.getLogger(__name__)


class CampaignView(LoginRequiredMixin, HorillaView):
    """
    Render the campaign page
    """

    nav_url = reverse_lazy("campaigns:campaign_nav_view")
    list_url = reverse_lazy("campaigns:campaign_list_view")
    kanban_url = reverse_lazy("campaigns:campaign_kanban_view")
    group_by_url = reverse_lazy("campaigns:campaign_group_by")
    card_url = reverse_lazy("campaigns:campaign_card_view")
    split_view_url = reverse_lazy("campaigns:campaign_split_view")
    chart_url = reverse_lazy("campaigns:campaign_chart_view")
    timeline_url = reverse_lazy("campaigns:campaign_timeline")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required(["campaigns.view_campaign", "campaigns.view_own_campaign"]),
    name="dispatch",
)
class CampaignNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar View for Campaign page
    """

    search_url = reverse_lazy("campaigns:campaign_list_view")
    main_url = reverse_lazy("campaigns:campaign_view")
    kanban_url = reverse_lazy("campaigns:campaign_kanban_view")
    group_by_url = reverse_lazy("campaigns:campaign_group_by")
    card_url = reverse_lazy("campaigns:campaign_card_view")
    model_str = "campaigns.Campaign"
    model_name = "Campaign"
    model_app_label = "campaigns"
    filterset_class = CampaignFilter
    exclude_kanban_fields = "company"
    enable_actions = True
    enable_quick_filters = True
    split_view_url = reverse_lazy("campaigns:campaign_split_view")
    chart_url = reverse_lazy("campaigns:campaign_chart_view")
    timeline_url = reverse_lazy("campaigns:campaign_timeline")

    @cached_property
    def new_button(self):
        """
        Function to return new button configuration
        """
        if self.request.user.has_perm(
            "campaigns:add_campaign"
        ) or self.request.user.has_perm("campaigns.add_own_campaign"):
            return {
                "url": f"""{reverse_lazy("campaigns:campaign_single_create")}?new=true""",
                "attrs": {"id": "campaign-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["campaigns.view_campaign", "campaigns.view_own_campaign"]
    ),
    name="dispatch",
)
class CampaignListView(LoginRequiredMixin, HorillaListView):
    """
    Campaign List view
    """

    model = Campaign
    paginate_by = 20
    view_id = "campaign-list"
    filterset_class = CampaignFilter
    search_url = reverse_lazy("campaigns:campaign_list_view")
    main_url = reverse_lazy("campaigns:campaign_view")
    enable_quick_filters = True

    columns = [
        "campaign_name",
        "campaign_type",
        "campaign_owner",
        "status",
        "expected_revenue",
        "budget_cost",
    ]

    @cached_property
    def col_attrs(self):
        """
        Function to return attributes for columns in the list view
        """
        query_params = self.request.GET.dict()
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        return [
            {
                "campaign_name": {
                    "hx-get": f"{{get_detail_view_url}}?{query_string}",
                    "hx-target": "#mainContent",
                    "hx-swap": "outerHTML",
                    "hx-push-url": "true",
                    "hx-select": "#mainContent",
                    "permission": "campaigns.view_campaign",
                    "own_permission": "campaigns.view_own_campaign",
                    "owner_field": "campaign_owner",
                }
            }
        ]

    bulk_update_fields = [
        "campaign_type",
        "campaign_owner",
        "status",
        "expected_revenue",
        "budget_cost",
    ]

    campaingn_permissions = {
        "permission": "campaigns.change_campaign",
        "own_permission": "campaigns.change_own_campaign",
        "owner_field": "campaign_owner",
    }
    actions = [
        {
            **campaingn_permissions,
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "attrs": """
                        hx-get="{get_edit_campaign_url}?new=true"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        },
        {
            **campaingn_permissions,
            "action": "Change Owner",
            "src": "assets/icons/a2.svg",
            "img_class": "w-4 h-4",
            "hidden_if": field_readonly_hidden_if(Campaign, "campaign_owner"),
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
            "permission": "campaigns.add_campaign",
            "own_permission": "campaigns.add_own_campaign",
            "owner_field": "campaign_owner",
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
            "permission": "campaigns.delete_campaign",
            "own_permission": "campaigns.delete_own_campaign",
            "owner_field": "campaign_owner",
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

    def no_record_add_button(self):
        """
        Function to return no record add button configuration
        """
        if self.request.user.has_perm(
            "campaigns.add_campaign"
        ) or self.request.user.has_perm("campaigns.add_own_campaign"):
            return {
                "url": f"""{reverse_lazy("campaigns:campaign_single_create")}?new=true""",
                "attrs": 'id="campaign-create"',
            }
        return None


@method_decorator(
    permission_required_or_denied(
        ["campaigns.view_campaign", "campaigns.view_own_campaign"]
    ),
    name="dispatch",
)
class CampaignKanbanView(LoginRequiredMixin, HorillaKanbanView):
    """
    Kanban view for campaign
    """

    model = Campaign
    view_id = "campaign-kanban"
    filterset_class = CampaignFilter
    search_url = reverse_lazy("campaigns:campaign_list_view")
    main_url = reverse_lazy("campaigns:campaign_view")
    group_by_field = "status"

    actions = CampaignListView.actions

    columns = [
        "campaign_name",
        "campaign_owner",
        "campaign_type",
        "expected_revenue",
        "budget_cost",
    ]

    @cached_property
    def kanban_attrs(self):
        """
        Function to return attributes for kanban cards
        """

        # Build query params
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")

        query_string = urlencode(query_params)

        return {
            "hx-get": f"{{get_detail_view_url}}?{query_string}",
            "hx-target": "#mainContent",
            "hx-swap": "outerHTML",
            "hx-push-url": "true",
            "hx-select": "#mainContent",
            "permission": "campaigns.view_campaign",
            "own_permission": "campaigns.view_own_campaign",
            "owner_field": "campaign_owner",
        }


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["campaigns.view_campaign", "campaigns.view_own_campaign"]
    ),
    name="dispatch",
)
class CampaignCardView(LoginRequiredMixin, HorillaCardView):
    """
    Card view for campaign
    """

    model = Campaign
    view_id = "campaign-card"
    filterset_class = CampaignFilter
    search_url = reverse_lazy("campaigns:campaign_list_view")
    main_url = reverse_lazy("campaigns:campaign_view")

    columns = [
        "campaign_name",
        "campaign_owner",
        "campaign_type",
        "status",
        "expected_revenue",
    ]

    actions = CampaignListView.actions

    col_attrs = CampaignListView.col_attrs

    no_record_add_button = CampaignListView.no_record_add_button


@method_decorator(
    permission_required_or_denied(
        ["campaigns.view_campaign", "campaigns.view_own_campaign"]
    ),
    name="dispatch",
)
class CampaignGroupByView(LoginRequiredMixin, HorillaGroupByView):
    """
    Campaign Group By view
    """

    model = Campaign
    view_id = "campaign-group-by"
    filterset_class = CampaignFilter
    search_url = reverse_lazy("campaigns:campaign_list_view")
    main_url = reverse_lazy("campaigns:campaign_view")
    enable_quick_filters = True
    group_by_field = "status"

    columns = [
        "campaign_name",
        "campaign_type",
        "campaign_owner",
        "status",
        "expected_revenue",
        "budget_cost",
    ]
    actions = CampaignListView.actions
    bulk_update_fields = CampaignListView.bulk_update_fields

    @cached_property
    def col_attrs(self):
        """
        Function to return attributes for columns in the group by view
        """
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        return [
            {
                "campaign_name": {
                    "hx-get": f"{{get_detail_view_url}}?{query_string}",
                    "hx-target": "#mainContent",
                    "hx-swap": "outerHTML",
                    "hx-push-url": "true",
                    "hx-select": "#mainContent",
                    "permission": "campaigns.view_campaign",
                    "own_permission": "campaigns.view_own_campaign",
                    "owner_field": "campaign_owner",
                }
            }
        ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["campaigns.view_campaign", "campaigns.view_own_campaign"]
    ),
    name="dispatch",
)
class CampaignSplitView(LoginRequiredMixin, HorillaSplitView):
    """
    Campaign Split view: left = tile list, right = simple details on click.
    """

    model = Campaign
    view_id = "campaign-split"
    filterset_class = CampaignFilter
    search_url = reverse_lazy("campaigns:campaign_list_view")
    main_url = reverse_lazy("campaigns:campaign_view")
    enable_quick_filters = True
    split_view_permission = "campaigns.view_campaign"
    split_view_own_permission = "campaigns.view_own_campaign"
    split_view_owner_field = "campaign_owner"

    columns = [
        "campaign_name",
        "campaign_type",
        "campaign_owner",
        "status",
        "expected_revenue",
        "budget_cost",
    ]

    no_record_add_button = CampaignListView.no_record_add_button
    actions = CampaignListView.actions


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["campaigns.view_campaign", "campaigns.view_own_campaign"]
    ),
    name="dispatch",
)
class CampaignChartView(LoginRequiredMixin, HorillaChartView):
    """Campaign chart view: counts by group-by field using same filters as list/kanban."""

    model = Campaign
    view_id = "campaign-chart"
    filterset_class = CampaignFilter
    search_url = reverse_lazy("campaigns:campaign_list_view")
    main_url = reverse_lazy("campaigns:campaign_view")
    group_by_field = "status"
    exclude_chart_fields = "company"
    chart_numeric_metrics = {"expected_response": ["avg", "min", "max"]}


@method_decorator(
    permission_required_or_denied(
        ["campaigns.view_campaign", "campaigns.view_own_campaign"]
    ),
    name="dispatch",
)
class CampaignTimelineView(LoginRequiredMixin, HorillaTimelineView):
    """Timeline from created_at to updated_at; rows by status. Use Timeline settings to use start/end date."""

    model = Campaign
    view_id = "campaign-timeline"
    filterset_class = CampaignFilter
    search_url = reverse_lazy("campaigns:campaign_list_view")
    main_url = reverse_lazy("campaigns:campaign_view")
    enable_quick_filters = True
    timeline_start_field = "created_at"
    timeline_end_field = "updated_at"
    timeline_group_by_field = "status"
    timeline_title_field = "campaign_name"
    columns = [
        "campaign_name",
        "campaign_type",
        "campaign_owner",
        "status",
        "start_date",
        "end_date",
    ]
    actions = CampaignListView.actions
    col_attrs = CampaignListView.col_attrs


@method_decorator(
    permission_required_or_denied(
        ["campaigns.view_campaign", "campaigns.view_own_campaign"]
    ),
    name="dispatch",
)
class CampaignDetailView(RecentlyViewedMixin, LoginRequiredMixin, HorillaDetailView):
    """
    Detail view for campaign
    """

    model = Campaign
    pipeline_field = "status"
    breadcrumbs = [
        ("Sales", "leads:leads_view"),
        ("Campaigns", "campaigns:campaign_view"),
    ]
    body = [
        "campaign_name",
        "campaign_owner",
        "start_date",
        "end_date",
        "campaign_type",
        "expected_revenue",
        "expected_response",
    ]

    tab_url = reverse_lazy("campaigns:campaign_detail_view_tabs")

    actions = CampaignListView.actions


@method_decorator(
    permission_required_or_denied(
        ["campaigns.view_campaign", "campaigns.view_own_campaign"]
    ),
    name="dispatch",
)
class CampaignDetailsTab(LoginRequiredMixin, HorillaDetailSectionView):
    """
    Details Tab view of campaign detail view
    """

    model = Campaign
    non_editable_fields = [
        "leads_in_campaign",
        "converted_leads_in_campaign",
        "contacts_in_campaign",
        "opportunities_in_campaign",
        "won_opportunities_in_campaign",
        "value_opportunities",
        "value_won_opportunities",
        "responses_in_campaign",
    ]
    excluded_fields = [
        "id",
        "created_at",
        "additional_info",
        "updated_at",
        "history",
        "is_active",
        "created_by",
        "updated_by",
    ]


@method_decorator(
    permission_required_or_denied(
        ["campaigns.view_campaign", "campaigns.view_own_campaign"]
    ),
    name="dispatch",
)
class CampaignDetailViewTabs(LoginRequiredMixin, HorillaDetailTabView):
    """
    Tab Views for Campaign detail view
    """

    def _prepare_detail_tabs(self):
        self.object_id = self.request.GET.get("object_id")
        self.model = Campaign
        super()._prepare_detail_tabs()

    urls = {
        "details": "campaigns:campaign_details_tab_view",
        "activity": "campaigns:campaign_activity_tab_view",
        "related_lists": "campaigns:campaign_related_list_tab_view",
        "notes_attachments": "campaigns:campaign_notes_attachments",
        "history": "campaigns:campaign_history_tab_view",
    }


@method_decorator(
    permission_required_or_denied(
        ["campaigns.view_campaign", "campaigns.view_own_campaign"]
    ),
    name="dispatch",
)
class CampaignNotesAndAttachments(
    LoginRequiredMixin, HorillaNotesAttachementSectionView
):
    """Notes and Attachments Tab View"""

    model = Campaign


@method_decorator(
    permission_required_or_denied(
        ["campaigns.view_campaign", "campaigns.view_own_campaign"]
    ),
    name="dispatch",
)
class CampaignActivityTab(LoginRequiredMixin, HorillaActivitySectionView):
    """
    Campaign detain view activity tab
    """

    model = Campaign


@method_decorator(
    permission_required_or_denied(
        ["campaigns.view_campaign", "campaigns.view_own_campaign"]
    ),
    name="dispatch",
)
class CampaignHistoryTab(LoginRequiredMixin, HorillaHistorySectionView):
    """
    History tab foe campaign detail view
    """

    model = Campaign


@method_decorator(
    permission_required_or_denied(
        ["campaigns.view_campaign", "campaigns.view_own_campaign"]
    ),
    name="dispatch",
)
class CampaignRelatedListsTab(LoginRequiredMixin, HorillaRelatedListSectionView):
    """
    Related list tab view
    """

    model = Campaign

    @cached_property
    def related_list_config(self):
        """
        Return configuration for related lists
        """
        user = self.request.user
        pk = self.request.GET.get("object_id")
        referrer_url = "campaign_detail_view"

        member_actions = [
            {
                "action": "edit",
                "src": "/assets/icons/edit.svg",
                "img_class": "w-4 h-4",
                "permission": "campaigns.change_campaignmember",
                "own_permission": "campaigns.change_own_campaignmember",
                "owner_field": "created_by",
                "attrs": """
                        hx-get="{get_edit_campaign_member}"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="event.stopPropagation();openModal()"
                        hx-indicator="#modalBox"
                """,
            },
            {
                "action": "Delete",
                "src": "assets/icons/a4.svg",
                "img_class": "w-4 h-4",
                "permission": "campaigns.delete_campaignmember",
                "attrs": """
                    hx-post="{get_delete_url}"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    hx-trigger="click"
                    hx-vals='{{"check_dependencies": "false"}}'
                    onclick="openModal()"
                """,
            },
        ]

        members_config = {
            "title": "Campaign Members",
            "columns": [
                ("Name", "get_title"),
                (
                    CampaignMember._meta.get_field("member_type").verbose_name,
                    "get_member_type_display",
                ),
                (
                    CampaignMember._meta.get_field("member_status").verbose_name,
                    "get_member_status_display",
                ),
            ],
            "can_add": self._can_add_to_related(),
            "add_url": reverse_lazy("campaigns:add_campaign_members"),
            "actions": member_actions,
        }
        if (
            user.has_perm("leads.view_lead")
            or user.has_perm("contacts.view_contact")
            or user.has_perm("leads.view_own_lead")
            or user.has_perm("contacts.view_own_contact")
        ):
            members_config["col_attrs"] = [
                {
                    "get_title": {
                        "style": "cursor:pointer",
                        "class": "hover:text-primary-600",
                        "hx-get": (
                            f"{{get_detail_view}}?referrer_app={self.model._meta.app_label}"
                            f"&referrer_model={self.model._meta.model_name}"
                            f"&referrer_id={pk}&referrer_url={referrer_url}"
                        ),
                        "hx-target": "#mainContent",
                        "hx-swap": "outerHTML",
                        "hx-push-url": "true",
                        "hx-select": "#mainContent",
                    }
                }
            ]

        child_campaigns_config = {
            "title": "Child Campaigns",
            "columns": [
                (
                    Campaign._meta.get_field("campaign_name").verbose_name,
                    "campaign_name",
                ),
                (Campaign._meta.get_field("start_date").verbose_name, "start_date"),
                (Campaign._meta.get_field("end_date").verbose_name, "end_date"),
            ],
            "actions": [
                {
                    "action": "edit",
                    "src": "/assets/icons/edit.svg",
                    "img_class": "w-4 h-4",
                    "permission": "campaigns.change_campaign",
                    "own_permission": "campaigns.change_own_campaign",
                    "owner_field": "campaign_owner",
                    "attrs": """
                        hx-get="{get_edit_campaign_url}"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="event.stopPropagation();openModal()"
                        hx-indicator="#modalBox"
                    """,
                },
                (
                    {
                        "action": "Delete",
                        "src": "assets/icons/a4.svg",
                        "img_class": "w-4 h-4",
                        "permission": "campaigns.delete_campaign",
                        "attrs": f"""
                        hx-delete="{{get_delete_child_campaign_url}}"
                        hx-on:click="hxConfirm(this,'{escapejs(_("Are you sure you want to remove this child campaign relationship?"))}')"
                        hx-target="#deleteModeBox"
                        hx-swap="innerHTML"
                        hx-trigger="confirmed"
                    """,
                    }
                ),
            ],
            "can_add": self._can_add_to_related(),
            "add_url": reverse_lazy("campaigns:create_child_campaign"),
            "custom_buttons": [
                {
                    "label": _("View Hierarchy"),
                    "url": reverse_lazy("campaigns:campaign_hierarchy"),
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
        }

        child_campaigns_config["col_attrs"] = [
            {
                "campaign_name": {
                    "permission": "campaigns.change_campaign",
                    "own_permission": "campaigns.change_own_campaign",
                    "owner_field": "campaign_owner",
                    "hx-get": (
                        f"{{get_detail_view_url}}?referrer_app={self.model._meta.app_label}"
                        f"&referrer_model={self.model._meta.model_name}"
                        f"&referrer_id={pk}&referrer_url={referrer_url}"
                    ),
                    "hx-target": "#mainContent",
                    "hx-swap": "outerHTML",
                    "hx-push-url": "true",
                    "hx-select": "#mainContent",
                }
            }
        ]

        opportunities_config = {
            "title": "Related Opportunities",
            "columns": [
                (
                    Campaign._meta.get_field("opportunities")
                    .related_model._meta.get_field("name")
                    .verbose_name,
                    "name",
                ),
                (
                    Campaign._meta.get_field("opportunities")
                    .related_model._meta.get_field("amount")
                    .verbose_name,
                    "amount",
                ),
                (
                    Campaign._meta.get_field("opportunities")
                    .related_model._meta.get_field("close_date")
                    .verbose_name,
                    "close_date",
                ),
                (
                    Campaign._meta.get_field("opportunities")
                    .related_model._meta.get_field("expected_revenue")
                    .verbose_name,
                    "expected_revenue",
                ),
            ],
        }

        opportunities_config["col_attrs"] = [
            {
                "name": {
                    "style": "cursor:pointer",
                    "class": "hover:text-primary-600",
                    "hx-get": (
                        f"{{get_detail_url}}?referrer_app={self.model._meta.app_label}"
                        f"&referrer_model={self.model._meta.model_name}"
                        f"&referrer_id={pk}&referrer_url={referrer_url}"
                    ),
                    "hx-target": "#mainContent",
                    "hx-swap": "outerHTML",
                    "hx-push-url": "true",
                    "hx-select": "#mainContent",
                    "permission": "opportunities.view_opportunity",
                    "own_permission": "opportunities.view_own_opportunity",
                    "owner_field": "owner",
                }
            }
        ]

        return {
            "members": members_config,
            "child_campaigns": child_campaigns_config,
            "opportunities": opportunities_config,
        }

    excluded_related_lists = ["contacts"]


def _build_campaign_tree(campaign, visited=None):
    """Build tree of campaign and descendants for <details> hierarchy."""
    if visited is None:
        visited = set()
    if campaign.pk in visited:
        return {"campaign": campaign, "children": []}
    visited.add(campaign.pk)
    return {
        "campaign": campaign,
        "children": [
            _build_campaign_tree(c, visited) for c in campaign.child_campaigns.all()
        ],
    }


def _get_root_campaign(campaign):
    """Traverse up to the topmost ancestor of a campaign, guarded against cycles."""
    visited = {campaign.pk}
    while campaign.parent_campaign is not None:
        if campaign.parent_campaign_id in visited:
            break
        visited.add(campaign.parent_campaign_id)
        campaign = campaign.parent_campaign
    return campaign


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["campaigns.view_campaign", "campaigns.view_own_campaign"]
    ),
    name="dispatch",
)
class CampaignHierarchyView(LoginRequiredMixin, View):
    """Modal view showing campaign hierarchy with expand/collapse (no JS)."""

    def get(self, request, *args, **kwargs):
        """
        Get method for campaign hierarchy
        """
        campaign_id = request.GET.get("id")
        if not campaign_id:
            return render(request, "403.html", {"modal": True})
        campaign = get_object_or_404(Campaign, pk=campaign_id)
        root_campaign = _get_root_campaign(campaign)
        root = _build_campaign_tree(root_campaign)
        return render(
            request,
            "campaigns/campaign_hierarchy_modal.html",
            {"root": root, "active_campaign_id": campaign.pk},
        )
