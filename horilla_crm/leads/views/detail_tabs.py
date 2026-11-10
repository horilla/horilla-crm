"""Views for the detail tabs of the Lead model."""

# Standard library imports
from urllib.parse import urlencode

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.activity.views import HorillaActivitySectionView
from horilla.contrib.generics.views import (
    HorillaDetailSectionView,
    HorillaDetailTabView,
    HorillaHistorySectionView,
    HorillaNotesAttachementSectionView,
    HorillaRelatedListSectionView,
)
from horilla.urls import reverse_lazy
from horilla.utils.decorators import method_decorator, permission_required_or_denied
from horilla.utils.functional import cached_property

# Local imports
from horilla_crm.leads.assignment.owner_lock import owner_locked
from horilla_crm.leads.assignment.pool import OWNER_FIELD
from horilla_crm.leads.models import Lead


@method_decorator(
    permission_required_or_denied(["leads.view_lead", "leads.view_own_lead"]),
    name="dispatch",
)
class LeadsDetailTab(LoginRequiredMixin, HorillaDetailSectionView):
    """Lead Detail Tab View"""

    model = Lead

    @property
    def non_editable_fields(self):
        """
        The owner cannot be edited here when the lead's assignment rule does not
        let this user change it (see ``assignment.owner_lock``). Edit Details
        shows it as plain text, and a posted owner is not applied.
        """
        if not hasattr(self, "_owner_is_locked"):
            lead = getattr(self, "object", None)
            if not isinstance(lead, Lead):
                pk = getattr(self, "kwargs", {}).get("pk")
                lead = Lead.objects.filter(pk=pk).first() if pk else None
            user = getattr(getattr(self, "request", None), "user", None)
            self._owner_is_locked = owner_locked(lead, user)
        return [OWNER_FIELD] if self._owner_is_locked else []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.excluded_fields.append("lead_status")
        self.excluded_fields.append("is_convert")
        self.excluded_fields.append("message_id")
        self.excluded_fields.extend(
            [
                "converted_contact",
                "converted_opportunity",
                "converted_at",
            ]
        )


@method_decorator(
    permission_required_or_denied(["leads.view_lead", "leads.view_own_lead"]),
    name="dispatch",
)
class LeadsNotesAndAttachments(LoginRequiredMixin, HorillaNotesAttachementSectionView):
    """Notes and Attachments Tab View"""

    model = Lead


@method_decorator(
    permission_required_or_denied(["leads.view_lead", "leads.view_own_lead"]),
    name="dispatch",
)
class LeadsDetailViewTabView(LoginRequiredMixin, HorillaDetailTabView):
    """Lead Detail Tab View"""

    def _prepare_detail_tabs(self):
        self.object_id = self.request.GET.get("object_id")
        self.model = Lead
        if self.object_id:
            obj = Lead.objects.get(pk=self.object_id)
            if obj.is_convert:
                self.tab_class = "h-[calc(_100vh_-_370px_)] overflow-hidden"
                self.urls = {
                    "details": "leads:leads_details_tab",
                    "activity": "leads:lead_activity_detail_view",
                    "notes_attachments": "leads:leads_notes_attachments",
                    "history": "leads:leads_history_tab_view",
                }
            else:
                self.urls = {
                    "details": "leads:leads_details_tab",
                    "activity": "leads:lead_activity_detail_view",
                    "related_lists": "leads:lead_related_lists",
                    "notes_attachments": "leads:leads_notes_attachments",
                    "history": "leads:leads_history_tab_view",
                }
        super()._prepare_detail_tabs()


@method_decorator(
    permission_required_or_denied(["leads.view_lead", "leads.view_own_lead"]),
    name="dispatch",
)
class LeadsActivityTabView(LoginRequiredMixin, HorillaActivitySectionView):
    """
    Activity Tab View
    """

    model = Lead


@method_decorator(
    permission_required_or_denied(["leads.view_lead", "leads.view_own_lead"]),
    name="dispatch",
)
@method_decorator(
    permission_required_or_denied(["leads.view_lead", "leads.view_own_lead"]),
    name="dispatch",
)
class LeadsHistoryTabView(LoginRequiredMixin, HorillaHistorySectionView):
    """
    History Tab View
    """

    model = Lead


@method_decorator(
    permission_required_or_denied(["leads.view_lead", "leads.view_own_lead"]),
    name="dispatch",
)
class LeadRelatedLists(LoginRequiredMixin, HorillaRelatedListSectionView):
    """Related Lists Tab View"""

    model = Lead

    @cached_property
    def related_list_config(self):
        """Related list config for lead"""

        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        pk = self.request.GET.get("object_id")
        referrer_url = "leads_detail"
        col_attrs = [
            {
                "campaign_name": {
                    "style": "cursor:pointer",
                    "class": "hover:text-primary-600",
                    "hx-get": (
                        f"{{get_detail_view_url}}?referrer_app={self.model._meta.app_label}"
                        f"&referrer_model={self.model._meta.model_name}"
                        f"&referrer_id={pk}&referrer_url={referrer_url}&{query_string}"
                    ),
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

        config = {
            "title": Lead._meta.get_field("lead_campaign_members")
            .related_model._meta.get_field("campaign")
            .related_model._meta.verbose_name_plural,
            "columns": [
                (
                    Lead._meta.get_field("lead_campaign_members")
                    .related_model._meta.get_field("campaign")
                    .related_model._meta.get_field("campaign_name")
                    .verbose_name,
                    "campaign_name",
                ),
                (
                    Lead._meta.get_field("lead_campaign_members")
                    .related_model._meta.get_field("campaign")
                    .related_model._meta.get_field("status")
                    .verbose_name,
                    "get_status_display",
                ),
                (
                    Lead._meta.get_field("lead_campaign_members")
                    .related_model._meta.get_field("campaign")
                    .related_model._meta.get_field("start_date")
                    .verbose_name,
                    "start_date",
                ),
                (
                    Lead._meta.get_field("lead_campaign_members")
                    .related_model._meta.get_field("member_status")
                    .verbose_name,
                    "members__get_member_status_display",
                ),
            ],
            "col_attrs": col_attrs,
            "can_add": self._can_add_to_related(),
            "add_url": reverse_lazy("campaigns:add_to_campaign"),
            "actions": [
                {
                    "action": "edit",
                    "src": "/assets/icons/edit.svg",
                    "img_class": "w-4 h-4",
                    "permission": "campaigns.change_campaignmember",
                    "own_permission": "campaigns.change_own_campaignmember",
                    "owner_field": "created_by",
                    "intermediate_model": "CampaignMember",
                    "intermediate_field": "campaign",
                    "parent_field": "lead",
                    "attrs": """
                                        hx-get="{get_specific_member_edit_url}"
                                        hx-target="#modalBox"
                                        hx-swap="innerHTML"
                                        onclick="event.stopPropagation();openModal()"
                                        hx-indicator="#modalBox"
                                        """,
                },
            ],
        }

        return {
            "custom_related_lists": {
                "campaigns": {
                    "app_label": "campaigns",
                    "model_name": "Campaign",
                    "intermediate_model": "CampaignMember",
                    "intermediate_field": "members",
                    "related_field": "lead",
                    "config": config,
                },
            },
        }

    excluded_related_lists = ["lead_campaign_members", "bookings"]
