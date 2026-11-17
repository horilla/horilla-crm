"""Views for custom opportunity stage creation and database initialization."""

# Standard library imports
import logging

# Third-party imports (Django)
from django.conf import settings
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.auth.models import User
from horilla.contrib.core.models import Company
from horilla.contrib.core.progress import ProgressStepsMixin
from horilla.db import transaction
from horilla.shortcuts import get_object_or_404, redirect, render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.html import format_html
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import HttpNotFound, HttpResponse

# Local imports
from horilla_crm.opportunities.models import OpportunityStage
from horilla_crm.opportunities.signals import opp_stage_created

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("opportunities.add_opportunitystage"), name="dispatch"
)
class CustomOppStagesFormView(LoginRequiredMixin, View):
    """View to display custom opportunity stages form."""

    def get(self, request, company_id):
        """Display custom opportunity stages form for a company."""
        initialization = request.GET.get("initialization") == "True"
        if initialization:
            init_company_id = request.session.get("company_id")
            if request.session.get("db_password") != settings.DB_INIT_PASSWORD or (
                str(init_company_id) != str(company_id)
            ):
                raise HttpNotFound("Company not found.")
        else:
            active_company = getattr(request, "active_company", None) or getattr(
                request.user, "company", None
            )
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
        all_stages_from_db = (
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

        default_stages = [
            {
                "name": _("Prospecting"),
                "order": 1,
                "probability": 10,
                "is_final": False,
            },
            {
                "name": _("Qualification"),
                "order": 2,
                "probability": 20,
                "is_final": False,
            },
            {
                "name": _("Needs Analysis"),
                "order": 3,
                "probability": 30,
                "is_final": False,
            },
            {
                "name": _("Value Proposition"),
                "order": 4,
                "probability": 50,
                "is_final": False,
            },
            {
                "name": _("Id. Decision Makers"),
                "order": 5,
                "probability": 60,
                "is_final": False,
            },
            {
                "name": _("Perception Analysis"),
                "order": 6,
                "probability": 70,
                "is_final": False,
            },
            {
                "name": _("Proposal/Price Quote"),
                "order": 7,
                "probability": 80,
                "is_final": False,
            },
            {
                "name": _("Negotiation/Review"),
                "order": 8,
                "probability": 90,
                "is_final": False,
            },
            {"name": _("Closed Lost"), "order": 9, "probability": 0, "is_final": False},
            {
                "name": _("Closed Won"),
                "order": 10,
                "probability": 100,
                "is_final": True,
            },
        ]

        unique_stages = {}

        for stage in default_stages:
            unique_stages[stage["name"]] = stage

        for stage in all_stages_from_db:
            stage_name = stage["name"]
            if stage_name not in unique_stages:
                unique_stages[stage_name] = {
                    "name": stage["name"],
                    "order": stage["order"],
                    "probability": stage["probability"],
                    "is_final": stage["is_final"],
                }

        combined_stages = []
        for i, (_name, stage) in enumerate(unique_stages.items(), 1):
            stage_copy = stage.copy()
            stage_copy["order"] = i
            combined_stages.append(stage_copy)

        # Build context dictionary
        context = {
            "company": company,
            "company_stages": {company_id: combined_stages},
            "default_stages": combined_stages,
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
            "opportunity_stage/custom_stages_form_opp.html",
            context,
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("opportunities.add_opportunitystage"), name="dispatch"
)
class SaveCustomOppStagesView(LoginRequiredMixin, View):
    """View to save custom opportunity stages for a company."""

    def get_signal_kwargs(self, company, request, initialization, stages=None):
        """
        Extension point: Override this method to pass additional data to signal.
        Clients can add custom data without modifying source code.
        """
        return {
            "company": company,
            "request": request,
            "view": self,
            "initialization": initialization,
            "stages": stages or [],
        }

    def _error_response(self, request, message):
        """Return HTMX response that shows error in form (single-form-view style, oob into #custom-stages-error)."""
        return render(
            request,
            "partials/custom_stages_error.html",
            {"error_message": message},
            status=200,
        )

    def _success_response(self, request):
        """Return HTMX response that clears any previous error in the form."""
        return render(
            request,
            "partials/custom_stages_error.html",
            {"error_message": None},
            status=200,
        )

    def post(self, request, company_id):
        """Handle POST request to save custom opportunity stages."""
        initialization = request.GET.get("initialization") == "True"
        if initialization:
            init_company_id = request.session.get("company_id")
            if request.session.get("db_password") != settings.DB_INIT_PASSWORD or (
                str(init_company_id) != str(company_id)
            ):
                raise HttpNotFound("Company not found.")
        else:
            active_company = getattr(request, "active_company", None) or getattr(
                request.user, "company", None
            )
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
        stage_names = request.POST.getlist("stage_name_custom[]")
        stage_orders = request.POST.getlist("stage_order_custom[]")
        stage_probabilities = request.POST.getlist("stage_probability_custom[]")
        stage_is_finals = request.POST.getlist("stage_is_final_custom[]")
        initialization = request.GET.get("initialization") == "True"

        # Validate that all lists have the same length
        n = len(stage_names)
        if len(stage_orders) != n or len(stage_probabilities) != n:
            return self._error_response(
                request,
                "Invalid form data: order or probability missing for one or more stages.",
            )

        try:
            # Validate all stages before making any DB changes
            parsed_stages = []
            seen_names = set()
            for i, stage_name in enumerate(stage_names):
                is_final = str(i) in stage_is_finals
                name = stage_name.strip()
                if not name:
                    return self._error_response(
                        request, f"Stage name cannot be empty for stage {i + 1}."
                    )
                if name in seen_names:
                    return self._error_response(
                        request, f'Duplicate stage name "{name}" in submission.'
                    )
                seen_names.add(name)
                try:
                    order = int(stage_orders[i])
                except (ValueError, TypeError):
                    return self._error_response(
                        request,
                        f'Invalid order for stage {i + 1} ("{name}"). Use a whole number.',
                    )
                try:
                    probability = float(stage_probabilities[i])
                except (ValueError, TypeError):
                    return self._error_response(
                        request,
                        f'Invalid probability for stage "{name}". Use a number between 0 and 100.',
                    )
                if probability < 0 or probability > 100:
                    return self._error_response(
                        request,
                        f"Probability must be between 0 and 100 for stage: {name}",
                    )
                if probability == 100.0:
                    stage_type = "won"
                elif probability == 0.0:
                    stage_type = "lost"
                else:
                    stage_type = "open"
                parsed_stages.append(
                    {
                        "name": name,
                        "order": order,
                        "probability": probability,
                        "is_final": is_final,
                        "stage_type": stage_type,
                    }
                )

            with transaction.atomic():
                submitted_names = {s["name"] for s in parsed_stages}

                # Delete only stages with no opportunities attached
                for stage in OpportunityStage.all_objects.filter(company=company):
                    if (
                        stage.name not in submitted_names
                        and not stage.opportunity_set.exists()
                    ):
                        stage.delete()

                for stage_data in parsed_stages:
                    OpportunityStage.all_objects.update_or_create(
                        company=company,
                        name=stage_data["name"],
                        defaults={
                            "order": stage_data["order"],
                            "probability": stage_data["probability"],
                            "is_final": stage_data["is_final"],
                            "stage_type": stage_data["stage_type"],
                        },
                    )
            messages.success(
                request,
                f"Successfully created {company} and associated Opportunity Stages.",
            )
            stages = list(
                OpportunityStage.all_objects.filter(company=company).order_by("order")
            )
            signal_kwargs = self.get_signal_kwargs(
                company=company,
                request=request,
                initialization=initialization,
                stages=stages,
            )

            responses = opp_stage_created.send(sender=self.__class__, **signal_kwargs)

            for _receiver, response in responses:
                if isinstance(response, HttpResponse):
                    return response

            if initialization:
                request.session.pop("db_password", None)
                request.session.pop("company_id", None)
                response = HttpResponse()
                response["HX-Redirect"] = "/"
                return response

            request.session.pop("newly_created_company_id", None)
            branches_view_url = reverse_lazy("core:branches_view")
            response_html = format_html(
                "<span "
                'hx-trigger="load" '
                'hx-get="{}" '
                'hx-select="#branches-view" '
                'hx-target="#branches-view" '
                'hx-swap="outerHTML" '
                'hx-on::after-request="closeContentModal()">'
                "</span>"
                '<div id="custom-stages-error" hx-swap-oob="true"></div>',
                branches_view_url,
            )
            return HttpResponse(response_html)

        except Exception:
            return self._error_response(
                request,
                "An error occurred while saving stages. Please try again.",
            )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("opportunities.add_opportunitystage"), name="dispatch"
)
class CreateOppStageGroupView(LoginRequiredMixin, View):
    """View to create opportunity stage group for a company."""

    def get_signal_kwargs(self, company, request, initialization):
        """
        Extension point: Override this method to pass additional data to signal.
        Clients can add custom data without modifying source code.
        """
        return {
            "company": company,
            "request": request,
            "view": self,
            "initialization": initialization,
        }

    def post(self, request, pk):
        """Handle POST request to create opportunity stage group."""
        initialization = request.GET.get("initialization") == "True"
        if initialization:
            init_company_id = request.session.get("company_id")
            if request.session.get("db_password") != settings.DB_INIT_PASSWORD or (
                str(init_company_id) != str(pk)
            ):
                raise HttpNotFound("Company not found.")
        else:
            active_company = getattr(request, "active_company", None) or getattr(
                request.user, "company", None
            )
            is_active_company = active_company and str(active_company.id) == str(pk)
            newly_created_company_id = request.session.get("newly_created_company_id")
            is_newly_created = str(newly_created_company_id) == str(pk)
            if not (is_active_company or is_newly_created):
                raise HttpNotFound("Company not found.")
        try:
            company = get_object_or_404(Company, pk=pk)
        except Exception as e:
            raise HttpNotFound(e) from e
        stage_names = request.POST.getlist("stage_name")
        stage_orders = request.POST.getlist("stage_order")
        stage_probabilities = request.POST.getlist("stage_probability")
        stage_is_finals = request.POST.getlist("stage_is_final")

        try:
            created_stages = []
            for i, _stage_name in enumerate(stage_names):
                is_final_value = (
                    stage_is_finals[i] if i < len(stage_is_finals) else "false"
                )
                is_final = is_final_value.lower() in ["true", "on", "1", "yes"]

                try:
                    order = int(stage_orders[i])
                    probability = float(stage_probabilities[i])
                except (ValueError, IndexError) as e:
                    response = render(
                        request,
                        "common/message_fragment.html",
                        {
                            "message": f"Invalid numeric value for stage {i + 1}: {str(e)}"
                        },
                    )
                    response.status_code = 400
                    return response

                if probability < 0 or probability > 100:
                    response = render(
                        request,
                        "common/message_fragment.html",
                        {
                            "message": f"Probability must be between 0 and 100 for stage: {stage_names[i]}"
                        },
                    )
                    response.status_code = 400
                    return response

                if OpportunityStage.objects.filter(
                    name=stage_names[i], company=company
                ).exists():
                    response = render(
                        request,
                        "common/message_fragment.html",
                        {
                            "message": f'Stage "{stage_names[i]}" already exists for this company.',
                        },
                    )
                    response.status_code = 400
                    return response

                if probability == 100.0:
                    stage_type = "won"
                elif probability == 0.0:
                    stage_type = "lost"
                else:
                    stage_type = "open"

                stage = OpportunityStage.objects.create(
                    name=stage_names[i],
                    order=order,
                    probability=probability,
                    is_final=is_final,
                    company=company,
                    created_by=(
                        request.user
                        if request.user.is_authenticated
                        else User.objects.first()
                    ),
                    stage_type=stage_type,
                )
                created_stages.append(stage)
            messages.success(
                request,
                f"Successfully created {company} and associated Opportunity Stages.",
            )
            signal_kwargs = self.get_signal_kwargs(
                company=company, request=request, initialization=initialization
            )

            responses = opp_stage_created.send(sender=self.__class__, **signal_kwargs)

            for _receiver, response in responses:
                if isinstance(response, HttpResponse):
                    return response

            if initialization:
                request.session.pop("db_password", None)
                request.session.pop("company_id", None)
                response = HttpResponse()
                response["HX-Redirect"] = "/"
                return response

            request.session.pop("newly_created_company_id", None)
            branches_view_url = reverse_lazy("core:branches_view")
            response_html = format_html(
                "<span "
                'hx-trigger="load" '
                'hx-get="{}" '
                'hx-select="#branches-view" '
                'hx-target="#branches-view" '
                'hx-swap="outerHTML" '
                'hx-on::after-request="closeContentModal()">'
                "</span>",
                branches_view_url,
            )
            return HttpResponse(response_html)

        except Exception as e:
            print(f"Error:{e}")
            response = render(
                request,
                "common/message_fragment.html",
                {"message": f"Error creating stages: {str(e)}"},
            )
            response.status_code = 500
            return response


class InitializeDatabaseOpportunityStages(View, ProgressStepsMixin):
    """View for initializing opportunity stages during database setup."""

    current_step = 6

    def get(self, request, *args, **kwargs):
        """Display opportunity stages initialization page."""
        company_id = request.POST.get("company_id") or request.session.get("company_id")
        if request.session.get("db_password") == settings.DB_INIT_PASSWORD:
            context = {
                "progress_steps": self.get_progress_steps(),
                "current_step": self.current_step,
                "company_id": company_id,
            }
            return render(
                request, "opportunity_stage/oppor_stages_initialize.html", context
            )
        return redirect("/")
