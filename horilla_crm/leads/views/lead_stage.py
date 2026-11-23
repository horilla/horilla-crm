"""Lead Stage Views"""

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
from horilla.utils.functional import cached_property
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView, View
from horilla.web import HxTriggerResponse, JsonResponse, ScriptResponse

# Local imports
from horilla_crm.leads.filters import LeadStatusFilter
from horilla_crm.leads.forms import LeadStatusForm
from horilla_crm.leads.models import LeadStatus


class LeadsStageView(LoginRequiredMixin, HorillaView):
    """
    TemplateView for company information settings page.
    """

    template_name = "settings/settings_list_shell.html"
    view_id = "leads-status-view"
    nav_url = reverse_lazy("leads:lead_stage_nav_view")
    list_url = reverse_lazy("leads:lead_stage_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("leads.view_leadstatus"), name="dispatch")
class LeadStageNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar for LeadStage"""

    nav_description = _("Define the stages a lead moves through in your pipeline.")
    search_url = reverse_lazy("leads:lead_stage_list_view")
    main_url = reverse_lazy("leads:lead_stage_view")
    filterset_class = LeadStatusFilter
    model_name = "LeadStatus"
    model_app_label = "leads"
    nav_width = False
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False

    @cached_property
    def new_button(self):
        """New button configuration"""
        if self.request.user.has_perm("leads.add_leadstatus"):
            return {
                "url": f"""{reverse_lazy("leads:create_lead_stage")}?new=true""",
                "attrs": {"id": "lead-stage-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.view_leadstatus"), name="dispatch"
)
class LeadStageListView(LoginRequiredMixin, HorillaListView):
    """
    Lead List view
    """

    model = LeadStatus
    view_id = "lead-stage-list"
    filterset_class = LeadStatusFilter
    search_url = reverse_lazy("leads:lead_stage_list_view")
    main_url = reverse_lazy("leads:lead_stage_view")
    save_to_list_option = False
    bulk_select_option = False
    enable_sorting = False

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.order_by("order")
        return queryset

    @cached_property
    def col_attrs(self):
        """Define column attributes for the list view"""
        return [
            {
                "order": {
                    "is_draggable": "true",
                    "sort_url": reverse_lazy("leads:update_lead_stage_order"),
                    "permission": "leads.change_leadstatus",
                }
            }
        ]

    def no_record_add_button(self):
        """Button to show when no records exist"""
        if self.request.user.has_perm("leads.add_leadstatus"):
            return {
                "url": f"""{reverse_lazy("leads:create_lead_stage")}?new=true""",
                "attrs": 'id="lead-stage-create"',
            }
        return None

    columns = ["order", "name", ("is_final", "is_final_col"), "probability"]
    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "leads.change_leadstatus",
            "attrs": """
                        hx-get="{get_edit_url}?new=true"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "leads.delete_leadstatus",
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
    permission_required_or_denied("leads.change_leadstatus"), name="dispatch"
)
class ChangeFinalStage(LoginRequiredMixin, View):
    """
    View to change the default currency for a company and update conversion rates.
    """

    def post(self, request, *_args, **kwargs):
        """Handle changing the final lead stage."""
        stage_id = kwargs.get("pk")
        try:
            company = get_active_company(request)
            new_final_stage = LeadStatus.objects.get(id=stage_id, company=company)
            with transaction.atomic():
                new_final_stage.is_final = True
                new_final_stage.save()
            messages.success(request, _("Final Stage  changed successfully."))
            return HxTriggerResponse()

        except Exception as e:
            messages.error(request, e)
            return ScriptResponse(reload=True)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.add_leadstatus"), name="dispatch"
)
class CreateLeadStage(LoginRequiredMixin, HorillaSingleFormView):
    """View to create or edit a LeadStatus instance."""

    model = LeadStatus
    modal_height = False
    form_class = LeadStatusForm

    def get_initial(self):
        """Provide default stage order when creating a new lead stage."""
        initial = super().get_initial()
        if not self.kwargs.get("pk"):  # Only set initial order for new stages
            company = get_active_company()
            if company:
                initial["order"] = LeadStatus.get_next_order_for_company(company)
        return initial

    @cached_property
    def form_url(self):
        """URL to load the form"""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("leads:edit_lead_stage", kwargs={"pk": pk})
        return reverse_lazy("leads:create_lead_stage")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.change_leadstatus"), name="dispatch"
)
class ToggleOrderFieldView(LoginRequiredMixin, TemplateView):
    """
    HTMX endpoint to toggle the visibility of the order field based on is_final checkbox
    """

    template_name = "partials/order_field.html"

    def get_context_data(self, **kwargs):
        """Return template state for order-field visibility and default value."""
        context = super().get_context_data(**kwargs)
        is_final = self.request.POST.get("is_final") or self.request.GET.get("is_final")
        current_order_value = self.request.POST.get(
            "order", ""
        ) or self.request.GET.get("order", "")

        context["show_order_field"] = is_final != "on"

        if context["show_order_field"] and not current_order_value:
            company = get_active_company()
            if company:
                current_order_value = LeadStatus.get_next_order_for_company(company)

        context["order_value"] = current_order_value
        return context

    def post(self, request, *args, **kwargs):
        """Handle POST requests to toggle order field visibility."""
        return self.get(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.delete_leadstatus", modal=True),
    name="dispatch",
)
class LeadStatusDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View to handle deletion of a LeadStatus instance."""

    model = LeadStatus

    def get_post_delete_response(self):
        return HxTriggerResponse()


@method_decorator(
    permission_required_or_denied("leads.change_leadstatus"), name="dispatch"
)
class UpdateLeadStageOrderView(LoginRequiredMixin, View):
    """
    Handles AJAX requests for updating lead stage order via drag-and-drop
    """

    def post(self, request, *_args, **_kwargs):
        """Handle updating lead stage order via drag-and-drop."""
        try:
            ids = request.POST.getlist("ids[]") or request.POST.getlist("ids")
            if not ids:
                return JsonResponse(
                    {"status": "error", "message": "No IDs provided"}, status=400
                )

            with transaction.atomic():
                # Get all statuses at once for efficiency
                statuses = {str(s.id): s for s in LeadStatus.objects.filter(id__in=ids)}

                # Validate all IDs exist
                if len(statuses) != len(ids):
                    missing_ids = set(ids) - set(statuses.keys())
                    return JsonResponse(
                        {"status": "error", "message": f"Invalid IDs: {missing_ids}"},
                        status=400,
                    )

                # Update orders while maintaining final stage constraints
                for order, status_id in enumerate(ids, start=1):
                    status = statuses[status_id]
                    if not status.is_final:  # Only update order for non-final stages
                        if status.order != order:
                            status.order = order
                            status.save(update_fields=["order"])

                # Ensure final stages are always last
                self._ensure_final_stages_last(company=statuses[ids[0]].company)

            return JsonResponse({"status": "success"})

        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    def _ensure_final_stages_last(self, company):
        """
        Ensures all final stages are ordered after non-final stages
        """
        non_final = list(
            LeadStatus.objects.filter(company=company, is_final=False).order_by(
                "order", "id"
            )
        )

        final = list(
            LeadStatus.objects.filter(company=company, is_final=True).order_by(
                "order", "id"
            )
        )

        with transaction.atomic():
            for order, status in enumerate(non_final + final, start=1):
                if status.order != order:
                    LeadStatus.objects.filter(id=status.id).update(order=order)
