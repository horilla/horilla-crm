"""Custom Lead Stage Views"""

# Third-party imports (Django)
from django.conf import settings
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.auth.models import User
from horilla.contrib.core.models import Company
from horilla.contrib.core.progress import BASE_STEPS, ProgressStepsMixin
from horilla.contrib.core.views.initialiaze_database import InitializeRoleView
from horilla.db import transaction
from horilla.shortcuts import get_object_or_404, redirect, render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.views.generic import View
from horilla.web import HttpNotFound, HttpResponse

# Local imports
from horilla_crm.leads.models import DEFAULT_LEAD_INIT_STAGES, LeadStatus
from horilla_crm.leads.signals import lead_stage_created


@method_decorator(htmx_required(), name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.view_leadstatus"), name="dispatch"
)
class LoadLeadStagesView(LoginRequiredMixin, View):
    """View to display the lead stages modal."""

    def get(self, request, company_id):
        """Handle displaying the lead stages modal."""
        initialization = request.GET.get("initialization") == "true"
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
        default_stages = DEFAULT_LEAD_INIT_STAGES

        all_stages = (
            LeadStatus.all_objects.filter(company_id=company_id)
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
            """Create a hashable signature for a set of stages"""
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
                "initialize-lead-stages" if initialization else "stage-messages"
            ),
            "hx_swap": "outerHTML" if initialization else "innerHTML",
            "hx_push_url": (
                reverse_lazy("opportunities:initialiaze_opportunity_stages")
                if initialization
                else "false"
            ),
        }

        # Only add hx_select when initialization is True
        if initialization:
            context["hx_select"] = "#initialize-opportunity-stages"

        return render(
            request,
            "lead_status/lead_stages_modal.html",
            context,
        )


@method_decorator(htmx_required(), name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.add_leadstatus"), name="dispatch"
)
class CustomStagesFormView(LoginRequiredMixin, View):
    """View to display the custom stages form."""

    def get(self, request, company_id):
        """Handle displaying the custom stages form."""
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
            LeadStatus.all_objects.filter(company_id=company_id)
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

        default_stages = DEFAULT_LEAD_INIT_STAGES

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
                "initialize-lead-stages" if initialization else "stage-messages"
            ),
            "hx_swap": "outerHTML" if initialization else "innerHTML",
            "hx_push_url": (
                reverse_lazy("opportunities:initialiaze_opportunity_stages")
                if initialization
                else "false"
            ),
        }

        # Only add hx_select when initialization is True
        if initialization:
            context["hx_select"] = "#initialize-opportunity-stages"

        return render(
            request,
            "lead_status/custom_stages_form.html",
            context,
        )


@method_decorator(htmx_required(), name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.add_leadstatus"), name="dispatch"
)
class SaveCustomStagesView(LoginRequiredMixin, View, ProgressStepsMixin):
    """View to handle saving custom lead stages during company creation."""

    current_step = 6

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
        """Handle saving custom lead stages during company creation."""
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
            for i, name in enumerate(stage_names):
                is_final = str(i) in stage_is_finals
                name = name.strip()
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
                parsed_stages.append(
                    {
                        "name": name,
                        "order": order,
                        "probability": probability,
                        "is_final": is_final,
                    }
                )

            with transaction.atomic():
                submitted_names = {s["name"] for s in parsed_stages}

                # Delete only stages with no leads attached
                for stage in LeadStatus.all_objects.filter(company=company):
                    if stage.name not in submitted_names and not stage.lead.exists():
                        stage.delete()

                for stage_data in parsed_stages:
                    LeadStatus.all_objects.update_or_create(
                        company=company,
                        name=stage_data["name"],
                        defaults={
                            "order": stage_data["order"],
                            "probability": stage_data["probability"],
                            "is_final": stage_data["is_final"],
                        },
                    )

            messages.success(
                request, f"Successfully created {company} and associated Lead Stages."
            )
            stages = list(
                LeadStatus.all_objects.filter(company=company).order_by("order")
            )
            signal_kwargs = self.get_signal_kwargs(
                company=company,
                request=request,
                initialization=initialization,
                stages=stages,
            )

            responses = lead_stage_created.send(sender=self.__class__, **signal_kwargs)

            for _receiver, response in responses:
                if isinstance(response, HttpResponse):
                    return response

            return self._success_response(request)

        except Exception:
            return self._error_response(
                request,
                "An error occurred while saving stages. Please try again.",
            )


@method_decorator(htmx_required(), name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.add_leadstatus"), name="dispatch"
)
class AddStageView(LoginRequiredMixin, View):
    """View to handle adding a new stage to the custom stages form."""

    def get(self, request, company_id):
        """Handle adding a new stage to the custom stages form."""
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

        stage_orders = request.GET.getlist("stage_order_custom[]", [])
        max_order = (
            max([int(order) for order in stage_orders if order], default=0)
            if stage_orders
            else 0
        )
        new_order = max_order + 1
        new_stage = {
            "name": "",
            "order": new_order,
            "probability": 0,
            "is_final": False,
        }
        stage_index = len(stage_orders)
        return render(
            request,
            "lead_status/stage_item.html",
            {
                "stage": new_stage,
                "company": company,
                "stage_index": stage_index,
            },
        )


@method_decorator(htmx_required(), name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.add_leadstatus"), name="dispatch"
)
class RemoveStageView(LoginRequiredMixin, View):
    """View to handle removing a stage from the custom stages form."""

    def post(self, request, company_id):
        """Handle removing a stage from the custom stages form."""
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
        remove_index = request.POST.get("remove_index", "-1")

        try:
            remove_index = int(remove_index)
        except ValueError:
            response = render(
                request,
                "common/message_fragment.html",
                {"message": "Invalid remove index."},
            )
            response.status_code = 400
            return response

        stages = []
        for i, name in enumerate(stage_names):
            if i != remove_index:
                stages.append(
                    {
                        "name": name.strip(),
                        "order": int(stage_orders[i]),
                        "probability": float(stage_probabilities[i]),
                        "is_final": str(i) in stage_is_finals,
                    }
                )
        return render(
            request,
            "lead_status/custom_stages_form.html",
            {
                "company": company,
                "company_stages": {company_id: {"stages": stages}},
                "default_stages": [],
            },
        )


@method_decorator(htmx_required(), name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.add_leadstatus"), name="dispatch"
)
class CreateStageGroupView(LoginRequiredMixin, View, ProgressStepsMixin):
    """View to handle saving custom lead stages during database setup."""

    current_step = 6

    def get_signal_kwargs(self, company, stages, request, initialization):
        """
        Extension point: Override this method to pass additional data to signal.
        Clients can add custom data without modifying source code.
        """
        return {
            "company": company,
            "stages": stages,
            "request": request,
            "view": self,
            "initialization": initialization,
        }

    def post(self, request, pk):
        """Handle saving custom lead stages during database setup."""
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
            for i in range(len(stage_names)):
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
                            "message": f"Probability must be between 0 and 100 for stage: {stage_names[i]}",
                        },
                    )
                    response.status_code = 400
                    return response

                if LeadStatus.objects.filter(
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

                stage = LeadStatus.objects.create(
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
                )
                created_stages.append(stage)
            messages.success(
                request, f"Successfully created {company} and associated Lead Stages."
            )
            signal_kwargs = self.get_signal_kwargs(
                company=company,
                stages=created_stages,
                request=request,
                initialization=initialization,
            )

            responses = lead_stage_created.send(sender=self.__class__, **signal_kwargs)

            for _receiver, response in responses:
                if isinstance(response, HttpResponse):
                    return response

            return None

        except Exception as e:
            response = render(
                request,
                "common/message_fragment.html",
                {
                    "message": "An error occurred while creating stages. Please try again."
                },
            )
            response.status_code = 500
            return response


BASE_STEPS.append({"step": 5, "title": "Lead Stages"})
BASE_STEPS.append({"step": 6, "title": "Opportunity Stages"})


class InitializeDatabaseLeadStages(LoginRequiredMixin, View, ProgressStepsMixin):
    """View to handle the initialization of lead stages during database setup."""

    current_step = 5

    def get(self, request, *_args, **_kwargs):
        """Render the lead stages initialization page if the user has the correct permissions"""
        company_id = request.POST.get("company_id") or request.session.get("company_id")
        if request.session.get("db_password") == settings.DB_INIT_PASSWORD:
            context = {
                "progress_steps": self.get_progress_steps(),
                "current_step": self.current_step,
                "company_id": company_id,
            }
            return render(request, "lead_status/lead_stages_initialize.html", context)
        return redirect("/")


InitializeRoleView.response_template = "lead_status/lead_stages_initialize.html"
InitializeRoleView.push_url = reverse_lazy("leads:initialize_lead_stages")
InitializeRoleView.select_id = "initialize-lead-stages"
