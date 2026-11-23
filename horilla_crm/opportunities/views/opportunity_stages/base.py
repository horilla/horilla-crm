"""Base views for opportunity stage management: list, create, delete, and toggle."""

# Standard library imports
import logging
from functools import cached_property

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla.contrib.utils.middlewares import get_active_company
from horilla.db import transaction
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView, View
from horilla.web import HxTriggerResponse, ScriptResponse

# Local imports
from horilla_crm.opportunities.filters import OpportunityStageFilter
from horilla_crm.opportunities.forms import OpportunityStageForm
from horilla_crm.opportunities.models import OpportunityStage

logger = logging.getLogger(__name__)


class OpportunityStageView(LoginRequiredMixin, HorillaView):
    """
    TemplateView for company information settings page.
    """

    template_name = "settings/settings_list_shell.html"
    view_id = "opportunity-stage-view"
    nav_url = reverse_lazy("opportunities:opportunity_stage_nav_view")
    list_url = reverse_lazy("opportunities:opportunity_stage_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required("opportunities.view_opportunitystage"), name="dispatch"
)
class OpportunityStageNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar view for opportunity stages."""

    nav_description = _(
        "Define the stages an opportunity moves through before it closes."
    )
    search_url = reverse_lazy("opportunities:opportunity_stage_list_view")
    main_url = reverse_lazy("opportunities:opportunity_stage_view")
    filterset_class = OpportunityStageFilter
    model_name = "OpportunityStage"
    model_app_label = "opportunities"
    nav_width = False
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False

    @cached_property
    def new_button(self):
        """Return new button configuration if user has create permission."""
        if self.request.user.has_perm("opportunities:create_opportunitystage"):
            return {
                "url": f"""{reverse_lazy("opportunities:create_opportunity_stage")}?new=true""",
                "attrs": {"id": "opportunity-stage-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("opportunities.view_opportunitystage"),
    name="dispatch",
)
class OpportunityStageListView(LoginRequiredMixin, HorillaListView):
    """
    opportunity List view
    """

    model = OpportunityStage
    view_id = "opportunity-stage-list"
    filterset_class = OpportunityStageFilter
    search_url = reverse_lazy("opportunities:opportunity_stage_list_view")
    main_url = reverse_lazy("opportunities:opportunity_stage_view")
    save_to_list_option = False
    bulk_select_option = False
    enable_sorting = False

    def get_queryset(self):
        """Return queryset ordered by stage order."""
        queryset = super().get_queryset()
        queryset = queryset.order_by("order")
        return queryset

    @cached_property
    def col_attrs(self):
        """Return column attributes for draggable order column."""
        return [
            {
                "order": {
                    "is_draggable": "true",
                    "sort_url": reverse_lazy(
                        "opportunities:update_opportunity_stage_order"
                    ),
                    "permission": "opportunities.change_opportunitystage",
                }
            }
        ]

    def no_record_add_button(self):
        """Return add button configuration when no records exist."""
        if self.request.user.has_perm("opportunities:create_opportunitystage"):
            return {
                "url": f"""{reverse_lazy("opportunities:create_opportunity_stage")}?new=true""",
                "attrs": 'id="opportunity-stage-create"',
            }
        return None

    columns = [
        "order",
        "name",
        ("is_final", "is_final_col"),
        "probability",
        "stage_type",
    ]

    actions = [
        {
            "action": _("Edit"),
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "opportunities:change_opportunitystage",
            "attrs": """
                    hx-get="{get_edit_url}?new=true"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    onclick="openModal()"
                    """,
        },
        {
            "action": _("Delete"),
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "opportunities:delete_opportunitystage",
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
@method_decorator(
    permission_required_or_denied("opportunities.change_opportunitystage"),
    name="dispatch",
)
class ChangeFinalStage(LoginRequiredMixin, View):
    """
    View to change the final stage for a company.
    """

    def post(self, request, *args, **kwargs):
        """Handle POST request to change final stage."""
        stage_id = kwargs.get("pk")

        try:
            new_final_stage = OpportunityStage.objects.get(id=stage_id)

            with transaction.atomic():
                company = new_final_stage.company
                all_stages = list(
                    OpportunityStage.objects.filter(company=company)
                    .select_for_update()
                    .order_by("order")
                )

                temp_order_start = 10000
                for idx, stage in enumerate(all_stages):
                    OpportunityStage.objects.filter(pk=stage.pk).update(
                        order=temp_order_start + idx
                    )

                OpportunityStage.objects.filter(company=company, is_final=True).exclude(
                    pk=new_final_stage.pk
                ).update(is_final=False)

                new_final_stage.is_final = True
                new_final_stage.save()

            messages.success(request, _("Final stage changed successfully."))
            return HxTriggerResponse()

        except OpportunityStage.DoesNotExist:
            messages.error(request, _("Stage not found."))
            return ScriptResponse(reload=True)
        except Exception as e:
            messages.error(request, f"Error changing final stage: {str(e)}")
            return ScriptResponse(reload=True)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("opportunities.add_opportunitystage"), name="dispatch"
)
class CreateOpportunityStage(LoginRequiredMixin, HorillaSingleFormView):
    """View for creating and editing opportunity stages."""

    model = OpportunityStage
    modal_height = False
    form_class = OpportunityStageForm

    def get_initial(self):
        """Set initial order for new opportunity stages."""
        initial = super().get_initial()
        if not self.kwargs.get("pk"):  # Only set initial order for new stages
            company = get_active_company()
            if company:
                initial["order"] = OpportunityStage.get_next_order_for_company(company)
        return initial

    @cached_property
    def form_url(self):
        """Return form URL based on whether editing or creating."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "opportunities:edit_opportunity_stage", kwargs={"pk": pk}
            )
        return reverse_lazy("opportunities:create_opportunity_stage")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("opportunities.change_opportunitystage"),
    name="dispatch",
)
class OpportynityToggleOrderFieldView(LoginRequiredMixin, TemplateView):
    """
    HTMX endpoint to toggle the visibility of the order field based on is_final checkbox
    """

    template_name = "partials/order_field.html"

    def get_context_data(self, **kwargs):
        """Get context data for order field toggle."""
        context = super().get_context_data(**kwargs)
        is_final = self.request.POST.get("is_final") or self.request.GET.get("is_final")
        current_order_value = self.request.POST.get(
            "order", ""
        ) or self.request.GET.get("order", "")

        context["show_order_field"] = is_final != "on"

        if context["show_order_field"] and not current_order_value:
            company = get_active_company()
            if company:
                current_order_value = OpportunityStage.get_next_order_for_company(
                    company
                )

        context["order_value"] = current_order_value
        return context

    def post(self, request, *args, **kwargs):
        """Handle POST request for order field toggle."""
        return self.get(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("opportunities.delete_opportunitystage", modal=True),
    name="dispatch",
)
class OpportunityStatusDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View for deleting opportunity stages."""

    model = OpportunityStage

    def get_post_delete_response(self):
        """Return response after successful deletion."""
        return HxTriggerResponse()
