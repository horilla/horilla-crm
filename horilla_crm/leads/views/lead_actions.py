"""Lead Actions Views for Horilla CRM"""

# First party imports (Horilla)
from django.contrib import messages

from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaMultiStepFormView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
)
from horilla.db import transaction
from horilla.urls import reverse_lazy
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.functional import cached_property
from horilla.utils.translation import gettext_lazy as _
from horilla.web import HxTriggerResponse, ScriptResponse

# Local imports
from horilla_crm.leads.assignment.owner_lock import owner_locked
from horilla_crm.leads.assignment.pool import has_active_rules
from horilla_crm.leads.form_mixins import APPLY_FIELD
from horilla_crm.leads.forms import LeadFormClass, LeadSingleForm
from horilla_crm.leads.models import Lead, LeadStatus


class ConvertedLeadLockMixin:
    """Refuse to edit, delete or reassign a lead once it has been converted."""

    def dispatch(self, request, *args, **kwargs):
        """Check if the lead is converted and read-only, and if so, refuse to edit it."""
        pk = kwargs.get("pk") or request.GET.get("id")
        is_duplicate = request.GET.get("duplicate", "false").lower() == "true"
        if (
            pk
            and not is_duplicate
            and Lead.objects.filter(pk=pk, is_convert=True).exists()
        ):
            messages.error(
                request, _("A converted lead is read-only and cannot be changed.")
            )
            return ScriptResponse(reload=True, msgs=True, close=True)
        return super().dispatch(request, *args, **kwargs)


class OwnerReassignmentLockMixin:
    """Refuse to change the owner of a lead its assignment rule keeps fixed."""

    def dispatch(self, request, *args, **kwargs):
        """Refuse when the lead's rule does not let this user change its owner."""
        pk = kwargs.get("pk") or request.GET.get("id")
        lead = Lead.objects.filter(pk=pk).first() if pk else None
        if lead is not None and owner_locked(lead, request.user):
            messages.error(
                request,
                _(
                    "The owner of a lead assigned by an assignment rule "
                    "cannot be changed."
                ),
            )
            return ScriptResponse(reload=True, msgs=True, close=True)
        return super().dispatch(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
class LeadDeleteView(
    LoginRequiredMixin, ConvertedLeadLockMixin, HorillaSingleDeleteView
):
    """Lead Delete View"""

    model = Lead

    def get_post_delete_response(self):
        return HxTriggerResponse()


@method_decorator(htmx_required, name="dispatch")
# Keeps instance.save() and form.save_m2m() (which persists custom field
# values) in one transaction, so the post_save assignment-rule signal's
# on_commit callback fires only after custom fields are readable.
@method_decorator(transaction.atomic, name="form_valid")
class LeadFormView(
    LoginRequiredMixin, ConvertedLeadLockMixin, HorillaMultiStepFormView
):
    """Lead Create/Update View"""

    form_class = LeadFormClass
    model = Lead
    fullwidth_fields = ["requirements"]
    dynamic_create_fields = ["lead_status"]
    detail_url_name = "leads:leads_detail"
    dynamic_create_field_mapping = {
        "lead_status": {
            "fields": ["name", "order", "probability"],
            "initial": {
                "order": LeadStatus.get_next_order_for_company,
            },
        },
    }

    form_mode = [
        {
            "title": _("Single-Step Form"),
            "url_name": {
                "create": "leads:leads_create_single",
                "edit": "leads:leads_edit_single",
            },
            "active": False,
        },
        {
            "title": _("Multi-Step Form"),
            "url_name": {"create": "leads:leads_create", "edit": "leads:leads_edit"},
            "active": True,
        },
    ]

    @cached_property
    def form_url(self):
        """Form URL for lead"""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("leads:leads_edit", kwargs={"pk": pk})
        return reverse_lazy("leads:leads_create")

    step_titles = {
        "1": _("Basic Information"),
        "2": _("Company Details"),
        "3": _("Location"),
        "4": _("Requirements"),
    }

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        self._store_unticked_assignment_switch(kwargs)
        return kwargs

    def _store_unticked_assignment_switch(self, kwargs):
        """
        Remember that "Assign using rules" was unticked.

        A browser sends nothing for an unticked checkbox, and the wizard only
        resets checkboxes that are model fields, so a checkbox ticked earlier
        would stay on in the stored step data. The checkbox is on step 1, so a
        step 1 submission without it means it is unticked.
        """
        request = self.request
        if (
            request.method != "POST"
            or "reset" in request.GET
            or "previous" in request.POST
            or self.get_initial_step() != 1
            or APPLY_FIELD in request.POST
            or not has_active_rules()
        ):
            return
        form_data = kwargs.get("form_data")
        if form_data is None:
            return
        form_data[APPLY_FIELD] = False
        request.session[self.storage_key] = form_data
        request.session.modified = True


@method_decorator(htmx_required, name="dispatch")
# See LeadFormView above: keeps custom field persistence and the
# assignment-rule signal in the same transaction.
@method_decorator(transaction.atomic, name="form_valid")
class LeadsSingleFormView(
    LoginRequiredMixin, ConvertedLeadLockMixin, HorillaSingleFormView
):
    """Lead Create/Update Single Page View"""

    model = Lead
    form_class = LeadSingleForm
    full_width_fields = ["requirements"]
    dynamic_create_fields = ["lead_status"]
    dynamic_create_field_mapping = {
        "lead_status": {
            "fields": ["name", "order", "probability", "is_final"],
            "initial": {
                "order": LeadStatus.get_next_order_for_company,
            },
        },
    }

    detail_url_name = "leads:leads_detail"

    form_mode = [
        {
            "title": _("Single-Step Form"),
            "url_name": {
                "create": "leads:leads_create_single",
                "edit": "leads:leads_edit_single",
            },
            "active": True,
        },
        {
            "title": _("Multi-Step Form"),
            "url_name": {"create": "leads:leads_create", "edit": "leads:leads_edit"},
            "active": False,
        },
    ]

    @cached_property
    def form_url(self):
        """Form URL for lead"""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("leads:leads_edit_single", kwargs={"pk": pk})
        return reverse_lazy("leads:leads_create_single")


@method_decorator(htmx_required, name="dispatch")
class LeadChangeOwnerForm(
    LoginRequiredMixin,
    ConvertedLeadLockMixin,
    OwnerReassignmentLockMixin,
    HorillaSingleFormView,
):
    """
    change owner form for lead
    """

    model = Lead
    fields = ["lead_owner"]
    full_width_fields = ["lead_owner"]
    modal_height = False
    form_title = _("Change Owner")

    @cached_property
    def form_url(self):
        """Form URL for lead change owner"""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("leads:lead_change_owner", kwargs={"pk": pk})
        return None
