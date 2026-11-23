"""Opportunity related lists, contact role forms and select closed stage views."""

# Standard library imports
from urllib.parse import urlencode

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaRelatedListSectionView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
)
from horilla.contrib.generics.views.details import (
    check_record_change_access,
    check_record_delete_access,
)
from horilla.contrib.utils.middlewares import get_active_company
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.functional import cached_property  # type: ignore
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import HxTriggerResponse, ScriptResponse

# Local imports
from horilla_crm.contacts.models import ContactAccountRelationship
from horilla_crm.opportunities.models import (
    Opportunity,
    OpportunityContactRole,
    OpportunitySettings,
    OpportunityStage,
)
from horilla_crm.opportunities.views.opportunity_split.manage import can_manage_splits


@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityRelatedLists(LoginRequiredMixin, HorillaRelatedListSectionView):
    """Related lists section view for opportunities."""

    model = Opportunity

    def _get_related_parent(self):
        """Return the opportunity whose related lists are rendered, or None."""
        obj = getattr(self, "object", None)
        if obj is None:
            try:
                obj = self.get_object()
            except Exception:
                return None
        return obj

    @cached_property
    def related_list_config(self):
        """Return related list configuration for opportunities."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        pk = self.request.GET.get("object_id")
        referrer_url = "opportunity_detail_view"
        contact_col_attrs = [
            {
                "first_name": {
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
        ]
        config = {
            "custom_related_lists": {
                "contact": {
                    "app_label": "contacts",
                    "model_name": "Contact",
                    "intermediate_model": "OpportunityContactRole",
                    "intermediate_field": "contact",
                    "related_field": "opportunity",
                    "config": {
                        "title": _("Contact Roles"),
                        "columns": [
                            (
                                self.model._meta.get_field("contact_roles")
                                .related_model._meta.get_field("contact")
                                .related_model._meta.get_field("first_name")
                                .verbose_name,
                                "first_name",
                            ),
                            (
                                self.model._meta.get_field("contact_roles")
                                .related_model._meta.get_field("contact")
                                .related_model._meta.get_field("last_name")
                                .verbose_name,
                                "last_name",
                            ),
                            (
                                self.model._meta.get_field("contact_roles")
                                .related_model._meta.get_field("role")
                                .verbose_name,
                                "opportunity_roles__role",
                            ),
                            (
                                self.model._meta.get_field("contact_roles")
                                .related_model._meta.get_field("is_primary")
                                .verbose_name,
                                "opportunity_roles__is_primary",
                            ),
                        ],
                        "can_add": self._can_add_to_related(),
                        "add_url": reverse_lazy(
                            "opportunities:add_opportunity_contact_role"
                        ),
                        "actions": [
                            {
                                "action": "edit",
                                "src": "/assets/icons/edit.svg",
                                "img_class": "w-4 h-4",
                                "permission": "opportunities.change_opportunitycontactrole",
                                "own_permission": "opportunities.change_own_opportunitycontactrole",
                                "owner_field": "created_by",
                                "intermediate_model": "OpportunityContactRole",
                                "intermediate_field": "contact",
                                "parent_field": "opportunity",
                                "attrs": """
                                    hx-get="{get_opportunity_contact_role_edit_url}"
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
                                "permission": "opportunities.delete_opportunitycontactrole",
                                "intermediate_model": "OpportunityContactRole",
                                "intermediate_field": "contact",
                                "parent_field": "opportunity",
                                "attrs": """
                                        hx-post="{get_opportunity_contact_role_delete_url}"
                                        hx-target="#deleteModeBox"
                                        hx-swap="innerHTML"
                                        hx-trigger="click"
                                        hx-vals='{{"check_dependencies": "true"}}'
                                        onclick="openDeleteModeModal()"
                                        """,
                            },
                        ],
                        "col_attrs": contact_col_attrs,
                    },
                },
            },
        }
        add_perm = self._can_add_to_related()
        if OpportunitySettings.is_team_selling_enabled():
            custom_buttons = []
            if add_perm:
                custom_buttons.extend(
                    [
                        {
                            "label": _("Add Team"),
                            "url": reverse_lazy("opportunities:add_default_team"),
                            "attrs": """
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            onclick="openModal()"
                            hx-indicator="#modalBox"
                        """,
                            "icon": "fa-solid fa-users",
                            "class": "outline outline-1 outline-offset-[-1px] outline-primary-600 rounded-md hover:bg-primary-300 transition duration-300 text-primary-600 bg-white cursor-pointer text-sm px-4 py-1",
                        },
                        {
                            "label": _("Add Members"),
                            "url": reverse_lazy("opportunities:add_opportunity_member"),
                            "attrs": """
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            onclick="openModal()"
                            hx-indicator="#modalBox"
                        """,
                            "icon": "fa-solid fa-user-plus",
                            "class": "bg-primary-600 rounded-md hover:bg-primary-800 transition duration-300 text-white text-sm px-4 py-1 cursor-pointer",
                        },
                    ]
                )
            config["opportunity_team_members"] = {
                "title": "Opportunity Team",
                "columns": [
                    (
                        self.model._meta.get_field("opportunity_team_members")
                        .related_model._meta.get_field("user")
                        .verbose_name,
                        "user",
                    ),
                    (
                        self.model._meta.get_field("opportunity_team_members")
                        .related_model._meta.get_field("team_role")
                        .verbose_name,
                        "team_role",
                    ),
                ],
                "can_add": False,
                "custom_buttons": custom_buttons,
                "actions": [
                    {
                        "action": "Edit",
                        "src": "/assets/icons/edit.svg",
                        "img_class": "w-4 h-4",
                        "permission": "opportunities.change_opportunityteammember",
                        "attrs": """
                                    hx-get="{get_edit_url}"
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
                        "permission": "opportunities.delete_opportunityteammember",
                        "attrs": """
                                    hx-post="{get_delete_url}"
                                    hx-target="#deleteModeBox"
                                    hx-swap="innerHTML"
                                    hx-trigger="click"
                                    hx-vals='{{"check_dependencies": "true"}}'
                                    onclick="openDeleteModeModal()"
                                    """,
                    },
                ],
            }
            if OpportunitySettings.is_split_enabled():
                splits_custom_buttons = []
                if can_manage_splits(self.request.user, self._get_related_parent()):
                    splits_custom_buttons.append(
                        {
                            "label": _("Manage Opportunity Splits"),
                            "url": reverse_lazy(
                                "opportunities:manage_opportunity_splits"
                            ),
                            "attrs": """
                            hx-target="#contentModalBox"
                            hx-swap="innerHTML"
                            onclick="openContentModal()"
                        """,
                            "class": "bg-primary-600 rounded-md hover:bg-primary-800 transition duration-300 text-white text-sm px-4 py-1 cursor-pointer",
                        }
                    )
                config["splits"] = {
                    "title": _("Opportunity Splits"),
                    "columns": [
                        (
                            self.model._meta.get_field("splits")
                            .related_model._meta.get_field("user")
                            .verbose_name,
                            "user",
                        ),
                        (
                            self.model._meta.get_field("splits")
                            .related_model._meta.get_field("split_type")
                            .verbose_name,
                            "split_type",
                        ),
                        (
                            self.model._meta.get_field("splits")
                            .related_model._meta.get_field("split_percentage")
                            .verbose_name,
                            "split_percentage",
                        ),
                        (
                            self.model._meta.get_field("splits")
                            .related_model._meta.get_field("split_amount")
                            .verbose_name,
                            "split_amount",
                        ),
                    ],
                    "can_add": False,
                    "custom_buttons": splits_custom_buttons,
                }
                if self.request.user.has_perm("opportunities.delete_opportunitysplit"):
                    config["splits"]["action_method"] = "actions"

        return config

    def get_excluded_related_lists(self):
        """
        Dynamically determine which related lists to exclude based on settings
        """
        excluded = ["contact_roles", "converted_from_leads"]

        # If Team Selling is DISABLED, exclude opportunity_team_members from showing
        if not OpportunitySettings.is_team_selling_enabled():
            excluded.append("opportunity_team_members")
        if not OpportunitySettings.is_split_enabled():
            excluded.append("splits")

        return excluded

    @property
    def excluded_related_lists(self):
        """Property wrapper for excluded_related_lists."""
        return self.get_excluded_related_lists()

    @excluded_related_lists.setter
    def excluded_related_lists(self, value):
        """Setter to allow parent view to set the value (but we ignore it)"""
        # We ignore the setter since we calculate dynamically


@method_decorator(htmx_required, name="dispatch")
class OpportunityContactRoleFormview(LoginRequiredMixin, HorillaSingleFormView):
    """Form view for creating and editing opportunity contact roles."""

    model = OpportunityContactRole
    fields = ["is_primary", "role", "contact", "opportunity"]
    full_width_fields = ["is_primary", "role", "contact"]
    modal_height = False
    form_title = _("Add Contact Role")
    hidden_fields = ["opportunity"]
    save_and_new = False

    def form_valid(self, form):
        """Handle form validation and create contact-account relationship."""
        super().form_valid(form)
        opportunity_contact_role = form.instance
        contact = opportunity_contact_role.contact
        opportunity = opportunity_contact_role.opportunity
        role = opportunity_contact_role.role

        # Automatically create related ContactAccountRelationship
        if opportunity.account:
            ContactAccountRelationship.objects.get_or_create(
                contact=contact,
                account=opportunity.account,
                defaults={"role": role},
                company=get_active_company(self.request),
            )

        return ScriptResponse(
            extra="htmx.trigger('#tab-contact-btn', 'click');",
            close=True,
        )

    def get_initial(self):
        """Get initial form data with opportunity ID if provided."""
        initial = super().get_initial()
        obj_id = self.request.GET.get("id")
        if obj_id:
            initial["opportunity"] = obj_id
        return initial

    @cached_property
    def form_url(self):
        """Return form URL for create or update view."""
        if self.kwargs.get("pk"):
            return reverse_lazy(
                "opportunities:edit_opportunity_contact_role",
                kwargs={"pk": self.kwargs.get("pk")},
            )
        return reverse_lazy("opportunities:add_opportunity_contact_role")

    def _get_opportunity(self):
        pk = self.kwargs.get("pk")
        opportunity_id = self.request.GET.get("id")
        if pk:
            role = get_object_or_404(OpportunityContactRole, pk=pk)
            return role.opportunity
        if opportunity_id:
            return get_object_or_404(Opportunity, pk=opportunity_id)
        return None

    def has_permission(self):
        user = self.request.user
        if user.is_superuser:
            return True
        opportunity = self._get_opportunity()
        if opportunity:
            return check_record_change_access(user, opportunity)
        return False

    def get_form(self, form_class=None):
        """Allow unrestricted contact and opportunity fields on the form."""
        form = super().get_form(form_class)
        unrestricted = {"contact", "opportunity"}
        for field_name in unrestricted:
            if field_name in form.fields:
                form._unrestricted_fields = getattr(
                    form, "_unrestricted_fields", set()
                ) | {field_name}
        return form

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
class OpportunityContactRoleDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete view for Opportunity Contact Role
    """

    model = OpportunityContactRole

    def dispatch(self, request, *args, **kwargs):
        """Require delete access on the related opportunity before proceeding."""
        role = get_object_or_404(OpportunityContactRole, pk=self.kwargs.get("pk"))
        if not check_record_delete_access(request.user, role.opportunity):
            return render(request, "403.html", {"modal": True})
        return super().dispatch(request, *args, **kwargs)

    def get_post_delete_response(self):
        return HxTriggerResponse(id="tab-contact-btn")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["opportunities.change_opportunity", "opportunities.change_own_opportunity"]
    ),
    name="dispatch",
)
class SelectClosedStageView(LoginRequiredMixin, View):
    """View to select between Closed Won and Closed Lost stages."""

    def get(self, request, *args, **kwargs):
        """Render the closed stage selection modal."""
        opportunity = get_object_or_404(Opportunity, pk=kwargs.get("pk"))

        # Get closed won and closed lost stages for the company
        company = opportunity.company if hasattr(opportunity, "company") else None
        closed_won_stage = None
        closed_lost_stage = None
        current_stage = (
            opportunity.stage
            if hasattr(opportunity, "stage") and opportunity.stage
            else None
        )
        current_stage_id = current_stage.id if current_stage else None

        if company:
            closed_won_stage = OpportunityStage.objects.filter(
                company=company, stage_type="won"
            ).first()
            closed_lost_stage = OpportunityStage.objects.filter(
                company=company, stage_type="lost"
            ).first()

        context = {
            "opportunity": opportunity,
            "closed_won_stage": closed_won_stage,
            "closed_lost_stage": closed_lost_stage,
            "current_stage": current_stage,
            "current_stage_id": current_stage_id,
        }

        return render(
            request,
            "opportunities/select_closed_stage.html",
            context,
        )

    def post(self, request, *args, **kwargs):
        """Handle the selection of closed won or closed lost."""
        opportunity = get_object_or_404(Opportunity, pk=kwargs.get("pk"))
        stage_id = request.POST.get("stage_id")

        if not stage_id:
            messages.error(request, _("Please select a stage"))
            return ScriptResponse(msgs=True, reload=True, status=400)

        try:
            stage = OpportunityStage.objects.get(pk=stage_id)
            # Verify it's a closed stage
            if stage.stage_type not in ["won", "lost"]:
                messages.error(request, _("Invalid stage selected"))
                return ScriptResponse(msgs=True, reload=True, status=400)

            # Update the opportunity stage
            opportunity.stage = stage
            opportunity.save()

            return ScriptResponse(reload=True, close=True)
        except OpportunityStage.DoesNotExist:
            messages.error(request, _("Stage not found"))
            return ScriptResponse(msgs=True, reload=True, status=404)
