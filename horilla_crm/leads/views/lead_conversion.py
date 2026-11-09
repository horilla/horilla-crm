"""Lead Conversion View for Horilla CRM"""

# Third-party imports (other)
from dateutil.relativedelta import relativedelta

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.utils import get_allowed_user_ids
from horilla.db import transaction
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse
from horilla.utils import timezone
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import FormView
from horilla.web import Http404, ScriptResponse

# Local imports
from horilla_crm.accounts.models import Account
from horilla_crm.contacts.models import Contact, ContactAccountRelationship
from horilla_crm.leads.forms import LeadConversionForm
from horilla_crm.leads.models import Lead, LeadStatus
from horilla_crm.leads.views.core import missing_convert_targets
from horilla_crm.opportunities.models import (
    Opportunity,
    OpportunityContactRole,
    OpportunityStage,
)


@method_decorator(htmx_required, name="dispatch")
class LeadConversionView(LoginRequiredMixin, FormView):
    """View to handle lead conversion to account, contact, and opportunity."""

    template_name = "lead_convert.html"
    form_class = LeadConversionForm

    def dispatch(self, request, *args, **kwargs):
        """Load the lead and short-circuit with an HTMX error response if missing."""
        try:
            self.lead = Lead.objects.get(pk=self.kwargs["pk"])
        except Exception as e:
            messages.error(self.request, str(e))
            return ScriptResponse(reload=True, extra="closeContentModal();")

        if self.lead.is_convert:
            messages.error(request, _("This lead is already converted."))
            return ScriptResponse(reload=True, msgs=True, extra="closeContentModal();")

        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        """Return redirect target after successful conversion."""
        return reverse("leads:leads_detail", kwargs={"pk": self.lead.pk})

    def get_form_kwargs(self):
        """Inject lead and optional selected account into form kwargs."""
        kwargs = super().get_form_kwargs()
        kwargs["lead"] = self.lead
        kwargs["user"] = self.request.user

        # Get selected account for filtering opportunities
        selected_account_id = self.request.GET.get("existing_account")
        if selected_account_id:
            try:
                kwargs["selected_account"] = Account.objects.get(pk=selected_account_id)
            except Account.DoesNotExist:
                pass

        return kwargs

    def get_context_data(self, **kwargs):
        """Populate template context with lead and selected conversion actions."""
        context = super().get_context_data(**kwargs)
        context["lead"] = self.lead
        context["account_action"] = self.request.GET.get(
            "account_action", self.get_initial().get("account_action", "create_new")
        )
        context["contact_action"] = self.request.GET.get(
            "contact_action", self.get_initial().get("contact_action", "create_new")
        )
        context["opportunity_action"] = self.request.GET.get(
            "opportunity_action",
            self.get_initial().get("opportunity_action", "create_new"),
        )
        context["selected_account_id"] = self.request.GET.get("existing_account")
        return context

    def get(self, request, *args, **kwargs):
        """Handle permission checks and HTMX partial rendering for conversion form."""
        pk = self.kwargs.get("pk")
        if pk:
            try:
                lead = get_object_or_404(Lead, pk=pk)
            except Http404:
                messages.error(request, _("Lead not found or no longer exists."))
                return ScriptResponse(reload=True, close=True)

            if not self._has_perm(
                "leads.convert_lead", "leads.convert_own_lead", lead.lead_owner
            ):
                return render(request, "403.html")

            missing_targets = missing_convert_targets(request.user)
            if missing_targets:
                return render(
                    request,
                    "lead_convert_no_permission.html",
                    {"lead": lead, "missing_targets": missing_targets},
                )

        if "HTTP_HX_REQUEST" in request.META:
            hx_target = request.META.get("HTTP_HX_TARGET", "").replace("#", "")

            if "existing_account" in request.GET and hx_target == "opportunity-field":
                context = self.get_context_data()
                return render(request, "lead_convert_opportunity.html", context)

            if hx_target:
                context = self.get_context_data()
                if hx_target == "account-field":
                    return render(request, "lead_convert_account.html", context)
                if hx_target == "contact-field":
                    return render(request, "lead_convert_contact.html", context)
                if hx_target == "opportunity-field":
                    return render(request, "lead_convert_opportunity.html", context)

        return super().get(request, *args, **kwargs)

    def _has_perm(self, perm, own_perm, owner):
        """Return True if the user holds `perm`, or `own_perm` scoped to `owner`."""
        user = self.request.user
        if user.has_perm(perm):
            return True
        if owner is not None and owner.pk in get_allowed_user_ids(user):
            return user.has_perm(own_perm)
        return False

    def _check_conversion_permissions(self, form):
        """
        Verify the user can create/update the Account, Contact, and
        Opportunity this conversion would touch. Returns a list of
        human-readable reasons for any missing permission (empty if allowed).
        """
        owner = form.cleaned_data.get("owner")
        errors = []

        if not self._has_perm(
            "leads.convert_lead", "leads.convert_own_lead", self.lead.lead_owner
        ):
            errors.append(_("convert this lead"))

        if form.cleaned_data["account_action"] == "create_new":
            if not self._has_perm(
                "accounts.add_account", "accounts.add_own_account", owner
            ):
                errors.append(_("create an account"))
        else:
            existing_account = form.cleaned_data.get("existing_account")
            account_owner = getattr(existing_account, "account_owner", None)
            if not self._has_perm(
                "accounts.change_account", "accounts.change_own_account", account_owner
            ):
                errors.append(_("link the selected account"))

        if form.cleaned_data["contact_action"] == "create_new":
            if not self._has_perm(
                "contacts.add_contact", "contacts.add_own_contact", owner
            ):
                errors.append(_("create a contact"))
        else:
            existing_contact = form.cleaned_data.get("existing_contact")
            contact_owner = getattr(existing_contact, "contact_owner", None)
            if not self._has_perm(
                "contacts.change_contact", "contacts.change_own_contact", contact_owner
            ):
                errors.append(_("link the selected contact"))

        if form.cleaned_data["opportunity_action"] == "create_new":
            if not self._has_perm(
                "opportunities.add_opportunity",
                "opportunities.add_own_opportunity",
                owner,
            ):
                errors.append(_("create an opportunity"))
        else:
            existing_opportunity = form.cleaned_data.get("existing_opportunity")
            opportunity_owner = getattr(existing_opportunity, "owner", None)
            if not self._has_perm(
                "opportunities.change_opportunity",
                "opportunities.change_own_opportunity",
                opportunity_owner,
            ):
                errors.append(_("link the selected opportunity"))

        return errors

    def form_valid(self, form):
        """Convert lead entities in a transaction and return success response."""
        missing = [
            _("create %(model)s") % {"model": label}
            for label in missing_convert_targets(self.request.user)
        ] or self._check_conversion_permissions(form)
        if missing:
            messages.error(
                self.request,
                _("You don't have permission to %(actions)s.")
                % {"actions": ", ".join(missing)},
            )
            return self.form_invalid(form)

        with transaction.atomic():
            try:
                lead_status = LeadStatus.objects.filter(is_final=True).first()
                company = getattr(self.request, "active_company", None)
                account = self._process_account(form, company)
                contact = self._process_contact(form, account, company)
                opportunity = self._process_opportunity(form, account, contact, company)

                # Update only the Lead's conversion status. This view already
                # created the Account/Contact/Opportunity above, so tell the
                # is_convert signal (leads/signals.py handle_lead_conversion)
                # not to run the same conversion a second time.
                self.lead.is_convert = True
                self.lead.updated_at = timezone.now()
                self.lead.lead_status = lead_status
                self.lead.converted_contact = contact
                self.lead.converted_opportunity = opportunity
                self.lead.converted_at = timezone.now()
                self.lead._skip_conversion_signal = True
                self.lead.save()

                messages.success(
                    self.request,
                    f'Lead "{self.lead.title}" has been successfully converted!',
                )
                self.conversion_data = {
                    "account": account,
                    "contact": contact,
                    "opportunity": opportunity,
                    "lead": self.lead,
                }
            except Exception as e:
                messages.error(self.request, f"Error converting lead: {str(e)}")
                return self.form_invalid(form)

        response = super().form_valid(form)
        if "HTTP_HX_REQUEST" in self.request.META:
            return self._render_success_modal()
        return response

    def _render_success_modal(self):
        """Render the success modal with conversion data"""
        context = {
            "account": self.conversion_data["account"],
            "contact": self.conversion_data["contact"],
            "opportunity": self.conversion_data["opportunity"],
            "lead": self.conversion_data["lead"],
        }
        return render(self.request, "lead_convert_success_modal.html", context)

    def _process_account(self, form, company):
        if form.cleaned_data["account_action"] == "create_new":
            return Account.objects.create(
                name=form.cleaned_data["account_name"],
                account_owner=form.cleaned_data.get("owner"),
                contact_number=self.lead.contact_number,
                annual_revenue=self.lead.annual_revenue,
                industry=self.lead.industry,
                number_of_employees=self.lead.no_of_employees,
                fax=self.lead.fax,
                account_source=self.lead.lead_source,
                company=company,
            )
        return form.cleaned_data["existing_account"]

    def _process_contact(self, form, account, company):
        if form.cleaned_data["contact_action"] == "create_new":
            contact = Contact.objects.create(
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                email=self.lead.email,
                contact_number=self.lead.contact_number,
                contact_owner=form.cleaned_data.get("owner"),
                company=company,
            )
            ContactAccountRelationship.objects.get_or_create(
                contact=contact, account=account, company=company
            )
            return contact
        contact = form.cleaned_data["existing_contact"]
        relationship, created = ContactAccountRelationship.objects.get_or_create(
            contact=contact, defaults={"account": account}, company=company
        )
        if not created and relationship.account != account:
            relationship.account = account
            relationship.save()
        return contact

    def _process_opportunity(self, form, account, contact, company):
        if form.cleaned_data["opportunity_action"] == "create_new":
            first_stage = OpportunityStage.objects.filter(order=1).first()
            campaign_member = self.lead.lead_campaign_members.first()
            closed_date = timezone.now().date() + relativedelta(months=1)
            opportunity = Opportunity.objects.create(
                name=form.cleaned_data["opportunity_name"],
                account=account,
                owner=self.lead.lead_owner,
                stage=first_stage,
                primary_campaign_source=(
                    campaign_member.campaign if campaign_member else None
                ),
                close_date=closed_date,
                company=company,
            )
            OpportunityContactRole.objects.get_or_create(
                opportunity=opportunity,
                contact=contact,
                defaults={"is_primary": True},
                company=company,
            )
            return opportunity
        opportunity = form.cleaned_data["existing_opportunity"]
        if opportunity.account != account:
            opportunity.account = account
        role, created = OpportunityContactRole.objects.get_or_create(
            opportunity=opportunity,
            contact=contact,
            defaults={"is_primary": True},
            company=company,
        )
        if not created and role.contact != contact:
            role.contact = contact
            role.save()
        opportunity.save()
        return opportunity

    def get_initial(self):
        """Provide default create-new options for conversion sections."""
        return {
            "account_action": "create_new",
            "contact_action": "create_new",
            "opportunity_action": "create_new",
        }

    def form_invalid(self, form):
        """Re-render form with validation errors, including HTMX responses."""
        if "HTTP_HX_REQUEST" in self.request.META:
            # Re-render the entire form with errors for HTMX requests
            context = self.get_context_data(form=form)
            return render(self.request, self.template_name, context)
        return super().form_invalid(form)
