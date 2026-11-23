"""Views for opportunity stage ordering and stage-load modal."""

# Standard library imports
import logging

# Third-party imports (Django)
from django.conf import settings

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.models import Company
from horilla.contrib.utils.middlewares import get_active_company
from horilla.db import models, transaction
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.views.generic import View
from horilla.web import HttpNotFound, JsonResponse

# Local imports
from horilla_crm.opportunities.models import (
    DEFAULT_OPPORTUNITY_INIT_STAGES,
    OpportunityStage,
)

logger = logging.getLogger(__name__)


@method_decorator(
    permission_required_or_denied("opportunities.change_opportunitystage"),
    name="dispatch",
)
class UpdateOpportunityStageOrderView(LoginRequiredMixin, View):
    """
    Handles AJAX requests for updating opportunity stage order via drag-and-drop
    """

    def post(self, request, *args, **kwargs):
        """Handle POST request to update opportunity stage order."""
        try:
            ids = request.POST.getlist("ids[]") or request.POST.getlist("ids")
            if not ids:
                return JsonResponse(
                    {"status": "error", "message": "No IDs provided"}, status=400
                )

            with transaction.atomic():
                statuses = {
                    str(s.id): s for s in OpportunityStage.objects.filter(id__in=ids)
                }
                if len(statuses) != len(ids):
                    missing_ids = set(ids) - set(statuses.keys())
                    return JsonResponse(
                        {"status": "error", "message": f"Invalid IDs: {missing_ids}"},
                        status=400,
                    )

                company = statuses[ids[0]].company

                all_stages = OpportunityStage.objects.filter(company=company)
                max_existing_order = (
                    all_stages.aggregate(max_order=models.Max("order"))["max_order"]
                    or 0
                )

                temp_order_start = max_existing_order + 1000

                for i, id in enumerate(ids):
                    status = statuses[id]
                    if not status.is_final:
                        temp_order = temp_order_start + i
                        OpportunityStage.objects.filter(id=status.id).update(
                            order=temp_order
                        )

                for order, id in enumerate(ids, start=1):
                    status = statuses[id]
                    if not status.is_final:
                        OpportunityStage.objects.filter(id=status.id).update(
                            order=order
                        )

                self._ensure_final_stages_last(company=company)

            return JsonResponse({"status": "success"})

        except Exception as e:
            logger.error("Error updating opportunity stage order: %s", e)
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    def _ensure_final_stages_last(self, company):
        """
        Ensures all final stages are ordered after non-final stages
        """
        non_final = list(
            OpportunityStage.objects.filter(company=company, is_final=False).order_by(
                "order", "id"
            )
        )

        final = list(
            OpportunityStage.objects.filter(company=company, is_final=True).order_by(
                "order", "id"
            )
        )

        all_stages = non_final + final

        max_existing_order = (
            OpportunityStage.objects.filter(company=company).aggregate(
                max_order=models.Max("order")
            )["max_order"]
            or 0
        )
        temp_order_start = max_existing_order + 2000

        with transaction.atomic():
            for i, status in enumerate(all_stages):
                temp_order = temp_order_start + i
                OpportunityStage.objects.filter(id=status.id).update(order=temp_order)

            for order, status in enumerate(all_stages, start=1):
                OpportunityStage.objects.filter(id=status.id).update(order=order)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("opportunities.view_opportunitystage"),
    name="dispatch",
)
class LoadOpportunityStagesView(LoginRequiredMixin, View):
    """View to load opportunity stages modal for a company."""

    def get(self, request, company_id):
        """Load and display opportunity stages modal for a company."""
        initialization = request.GET.get("initialization") == "true"
        if initialization:
            init_company_id = request.session.get("company_id")
            if request.session.get("db_password") != settings.DB_INIT_PASSWORD or (
                str(init_company_id) != str(company_id)
            ):
                raise HttpNotFound("Company not found.")
        else:
            active_company = get_active_company(request)
            is_active_company = active_company and str(active_company.id) == str(
                company_id
            )
            newly_created_company_id = request.session.get("newly_created_company_id")
            is_newly_created = str(newly_created_company_id) == str(company_id)
            if not (is_active_company or is_newly_created):
                raise HttpNotFound("Company not found.")
        try:
            company = get_object_or_404(Company, id=company_id)
        except Exception as e:
            raise HttpNotFound(e) from e
        default_stages = DEFAULT_OPPORTUNITY_INIT_STAGES

        all_stages = (
            OpportunityStage.all_objects.filter(company_id=company_id)
            .values(
                "name",
                "order",
                "probability",
                "is_final",
                "company__name",
                "company_id",
            )
            .order_by("company_id", "order")
        )

        raw_company_stages = {}
        for stage in all_stages:
            company_id = stage["company_id"]
            if company_id not in raw_company_stages:
                raw_company_stages[company_id] = {
                    "company_name": stage["company__name"],
                    "stages": [],
                }
            raw_company_stages[company_id]["stages"].append(
                {
                    "name": stage["name"],
                    "order": stage["order"],
                    "probability": stage["probability"],
                    "is_final": stage["is_final"],
                }
            )

        # Create signature for stage comparison
        def create_stage_signature(stages):
            """Create a hashable signature for a set of stages."""
            return tuple(
                (s["name"], s["order"], s["probability"], s["is_final"])
                for s in sorted(stages, key=lambda x: x["order"])
            )

        # Group companies by their stage signatures
        signature_groups = {}
        default_signature = create_stage_signature(default_stages)

        for _comp_id, comp_data in raw_company_stages.items():
            signature = create_stage_signature(comp_data["stages"])

            if signature == default_signature:
                continue

            if signature not in signature_groups:
                signature_groups[signature] = []
            signature_groups[signature].append(comp_data)

        company_stages = {}

        group_counter = 1
        for signature, companies in signature_groups.items():
            representative = companies[0]

            if len(companies) > 1:
                _company_names = [comp["company_name"] for comp in companies]
                representative["company_name"] = (
                    f"{representative['company_name']} (+{len(companies) - 1} others)"
                )

            company_stages[f"group_{group_counter}"] = representative
            group_counter += 1

        # Build context dictionary
        context = {
            "default_stages": default_stages,
            "company_stages": company_stages,
            "company": company,
            "initialization": initialization,
            "hx_target": (
                "initialize-opportunity-stages" if initialization else "stage-messages"
            ),
            "hx_swap": "outerHTML" if initialization else "innerHTML",
            "hx_push_url": (
                reverse_lazy("core:home_view") if initialization else "false"
            ),
        }

        # Only add hx_select when initialization is True
        if initialization:
            context["hx_select"] = "#sec1"

        return render(
            request,
            "opportunity_stage/opportunity_stages_modal.html",
            context,
        )
