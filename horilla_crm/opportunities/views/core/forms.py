"""Opportunity create/edit and change-owner form views."""

from decimal import Decimal, InvalidOperation

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaMultiStepFormView,
    HorillaSingleFormView,
)
from horilla.contrib.generics.views.details import check_record_change_access
from horilla.contrib.utils.middlewares import get_active_company
from horilla.shortcuts import get_object_or_404
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.functional import cached_property  # type: ignore
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import HttpResponse, ScriptResponse

# Local imports
from horilla_crm.opportunities.forms import (
    OpportunityFormClass,
    OpportunitySingleForm,
    render_probability_input,
)
from horilla_crm.opportunities.models import Opportunity, OpportunityStage
from horilla_crm.opportunities.signals import set_opportunity_contact_id


@method_decorator(htmx_required, name="dispatch")
class StageProbabilityFieldView(LoginRequiredMixin, View):
    """HTMX endpoint that re-renders the read-only probability input for a stage.

    Wired to the Stage field's ``hx-get`` (see ``_wire_stage_probability_refresh``
    in forms.py) so the Probability field on the opportunity form updates live
    when the user picks a different stage, without requiring a save first.
    """

    def get(self, request, *args, **kwargs):
        """Return the probability input pre-filled with the selected stage's value."""
        stage_id = request.GET.get("stage")
        if not stage_id and request.GET.get("opportunity"):
            stage_id = (
                Opportunity.objects.filter(pk=request.GET["opportunity"])
                .values_list("stage_id", flat=True)
                .first()
            )
        probability = None
        if stage_id:
            queryset = OpportunityStage.objects.filter(pk=stage_id)
            company = get_active_company(request)
            if company:
                queryset = queryset.filter(company=company)
            stage = queryset.first()
            if stage:
                probability = stage.probability
        html = render_probability_input(probability)
        # Out-of-band: the detail page's read-only Expected Revenue
        # (amount x probability). No such element on the create/edit form.
        try:
            amount = Decimal(request.GET.get("amount") or "")
        except InvalidOperation:
            amount = None
        expected = (
            f"{amount * probability / 100:.2f}"
            if amount is not None and probability is not None
            else ""
        )
        html += (
            f'<input type="text" id="id_expected_revenue" value="{expected}" '
            'hx-swap-oob="outerHTML" readonly tabindex="-1" '
            'class="text-color-600 p-2 placeholder:text-xs font-normal w-full border '
            "border-dark-50 bg-gray-50 rounded-md mt-1 outline-0 focus:outline-0 "
            'focus:border-dark-50 focus:ring-0 text-sm cursor-default">'
        )
        return HttpResponse(html)

    def post(self, request, *args, **kwargs):
        """Support POST the same as GET (htmx may include it via an enclosing form)."""
        return self.get(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
class OpportunityMultiStepFormView(LoginRequiredMixin, HorillaMultiStepFormView):
    """Multi-step form view for creating and editing opportunities."""

    form_class = OpportunityFormClass
    model = Opportunity
    total_steps = 3
    fullwidth_fields = ["description"]
    dynamic_create_fields = ["stage"]
    detail_url_name = "opportunities:opportunity_detail_view"
    dynamic_create_field_mapping = {
        "stage": {
            "fields": ["name", "order", "probability", "stage_type", "is_final"],
            "initial": {
                "order": OpportunityStage.get_next_order_for_company,
            },
        },
    }

    form_mode = [
        {
            "title": _("Single-Step Form"),
            "url_name": {
                "create": "opportunities:opportunity_single_create",
                "edit": "opportunities:opportunity_single_edit",
            },
            "active": False,
        },
        {
            "title": _("Multi-Step Form"),
            "url_name": {
                "create": "opportunities:opportunity_create",
                "edit": "opportunities:opportunity_edit",
            },
            "active": True,
        },
    ]

    @cached_property
    def form_url(self):
        """Return form URL for create or update view."""
        pk = self.kwargs.get("pk")
        if pk:
            return reverse_lazy("opportunities:opportunity_edit", kwargs={"pk": pk})
        return reverse_lazy("opportunities:opportunity_create")

    step_titles = {
        "1": _("Opportunity Information"),
        "2": _("Additional Information"),
        "3": _("Description"),
    }

    def get_initial(self):
        """Get initial form data with account ID if provided."""
        initial = super().get_initial()
        account_id = self.request.GET.get("id")
        initial["account"] = account_id
        return initial


@method_decorator(htmx_required, name="dispatch")
class OpportunitySingleFormView(LoginRequiredMixin, HorillaSingleFormView):
    """opportunity Create/Update Single Page View"""

    model = Opportunity
    form_class = OpportunitySingleForm
    full_width_fields = ["description"]
    dynamic_create_fields = ["stage"]
    detail_url_name = "opportunities:opportunity_detail_view"
    dynamic_create_field_mapping = {
        "stage": {
            "fields": ["name", "order", "probability", "stage_type", "is_final"],
            "initial": {
                "order": OpportunityStage.get_next_order_for_company,
            },
        },
    }

    form_mode = [
        {
            "title": _("Single-Step Form"),
            "url_name": {
                "create": "opportunities:opportunity_single_create",
                "edit": "opportunities:opportunity_single_edit",
            },
            "active": True,
        },
        {
            "title": _("Multi-Step Form"),
            "url_name": {
                "create": "opportunities:opportunity_create",
                "edit": "opportunities:opportunity_edit",
            },
            "active": False,
        },
    ]

    @cached_property
    def form_url(self):
        """Form URL for lead"""
        pk = self.kwargs.get("pk")
        if pk:
            return reverse_lazy(
                "opportunities:opportunity_single_edit", kwargs={"pk": pk}
            )
        return reverse_lazy("opportunities:opportunity_single_create")

    def get_initial(self):
        """Get initial form data with account ID from query parameters."""
        initial = super().get_initial()
        account_id = self.request.GET.get("id")
        initial["account"] = account_id
        return initial


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("opportunities.add_opportunity"), name="dispatch"
)
class RelatedOpportunityFormView(LoginRequiredMixin, HorillaMultiStepFormView):
    """Multi-step form view for creating opportunities related to contacts."""

    form_class = OpportunityFormClass
    model = Opportunity
    total_steps = 3
    fullwidth_fields = ["description"]
    dynamic_create_fields = ["stage"]
    save_and_new = False
    dynamic_create_field_mapping = {
        "stage": {"full_width_fields": ["description"]},
    }

    form_mode = [
        {
            "title": _("Single-Step Form"),
            "url_name": {
                "create": "opportunities:related_contact_opportunity_single_create"
            },
            "active": False,
        },
        {
            "title": _("Multi-Step Form"),
            "url_name": {"create": "opportunities:related_contact_opportunity_create"},
            "active": True,
        },
    ]

    @cached_property
    def form_url(self):
        """Return form URL for create or update view."""
        pk = self.kwargs.get("pk")
        if pk:
            return reverse_lazy("opportunities:opportunity_edit", kwargs={"pk": pk})
        return reverse_lazy("opportunities:opportunity_create")

    step_titles = {
        "1": _("Opportunity Information"),
        "2": _("Additional Information"),
        "3": _("Description"),
    }

    def get_initial(self):
        """Get initial form data with contact ID if provided."""
        initial = super().get_initial()
        contact_id = self.request.GET.get("id")
        account_id = None
        if contact_id:
            Contact = apps.get_model("contacts", "Contact")
            contact = Contact.objects.filter(pk=contact_id).first()
            if contact:
                rel = contact.account_relationships.first()
                account_id = rel.account.pk if rel else None
        initial["account"] = account_id
        return initial

    def form_valid(self, form):
        step = self.get_initial_step()

        if step == self.total_steps:
            contact_id = self.request.GET.get("id")
            if contact_id:
                set_opportunity_contact_id(
                    contact_id=contact_id, company=get_active_company(self.request)
                )
            super().form_valid(form)
            return ScriptResponse(
                extra="htmx.trigger('#tab-opportunities-btn','click');",
                close=True,
            )

        return super().form_valid(form)

    def has_permission(self):
        user = self.request.user
        if user.is_superuser:
            return True
        if user.has_perm("opportunities.change_opportunity") or user.has_perm(
            "opportunities.add_opportunity"
        ):
            return True
        opportunity_id = self.kwargs.get("pk")
        if opportunity_id:
            opportunity = get_object_or_404(Opportunity, pk=opportunity_id)
            return check_record_change_access(user, opportunity)
        return True  # create mode — allow if user reached this point


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("opportunities.add_opportunity"), name="dispatch"
)
class RelatedOpportunitySingleFormView(LoginRequiredMixin, HorillaSingleFormView):
    """Single-step form view for creating opportunities related to contacts."""

    model = Opportunity
    form_class = OpportunitySingleForm
    full_width_fields = ["description"]
    dynamic_create_fields = ["stage"]
    save_and_new = False
    dynamic_create_field_mapping = {
        "stage": {"full_width_fields": ["description"]},
    }

    form_mode = [
        {
            "title": _("Single-Step Form"),
            "url_name": {
                "create": "opportunities:related_contact_opportunity_single_create"
            },
            "active": True,
        },
        {
            "title": _("Multi-Step Form"),
            "url_name": {"create": "opportunities:related_contact_opportunity_create"},
            "active": False,
        },
    ]

    @cached_property
    def form_url(self):
        """Form URL for the related-opportunity single-step form"""
        return reverse_lazy("opportunities:related_contact_opportunity_single_create")

    def get_initial(self):
        """Get initial form data with contact ID if provided."""
        initial = super().get_initial()
        contact_id = self.request.GET.get("id")
        account_id = None
        if contact_id:
            Contact = apps.get_model("contacts", "Contact")
            contact = Contact.objects.filter(pk=contact_id).first()
            if contact:
                rel = contact.account_relationships.first()
                account_id = rel.account.pk if rel else None
        initial["account"] = account_id
        return initial

    def form_valid(self, form):
        contact_id = self.request.GET.get("id")
        if contact_id:
            set_opportunity_contact_id(
                contact_id=contact_id, company=get_active_company(self.request)
            )
        super().form_valid(form)
        return ScriptResponse(
            extra="htmx.trigger('#tab-opportunities-btn','click');",
            close=True,
        )

    def has_permission(self):
        user = self.request.user
        if user.is_superuser:
            return True
        if user.has_perm("opportunities.change_opportunity") or user.has_perm(
            "opportunities.add_opportunity"
        ):
            return True
        opportunity_id = self.kwargs.get("pk")
        if opportunity_id:
            opportunity = get_object_or_404(Opportunity, pk=opportunity_id)
            return check_record_change_access(user, opportunity)
        return True  # create mode — allow if user reached this point


@method_decorator(htmx_required, name="dispatch")
class OpportunityChangeOwnerForm(LoginRequiredMixin, HorillaSingleFormView):
    """Form view for changing opportunity owner."""

    model = Opportunity
    fields = ["owner"]
    full_width_fields = ["owner"]
    modal_height = False
    form_title = _("Change Owner")

    @cached_property
    def form_url(self):
        """Return form URL for change owner view."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "opportunities:opportunity_change_owner", kwargs={"pk": pk}
            )
        return None

    def has_permission(self):
        user = self.request.user
        if user.is_superuser:
            return True
        if user.has_perm("opportunities.change_opportunity") or user.has_perm(
            "opportunities.add_opportunity"
        ):
            return True
        opportunity_id = self.kwargs.get("pk")
        if opportunity_id:
            opportunity = get_object_or_404(Opportunity, pk=opportunity_id)
            return check_record_change_access(user, opportunity)
        return False
