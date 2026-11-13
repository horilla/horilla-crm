"""
Views for all account actions
"""

# Standard library imports
import logging
from functools import cached_property

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaMultiStepFormView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
)
from horilla.contrib.generics.views.details import (
    check_record_change_access,
    check_record_delete_access,
)
from horilla.core.exceptions import ValidationError
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse_lazy
from horilla.utils import timezone
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import FormView, View
from horilla.web import Http404, HxTriggerResponse, ScriptResponse

# Local imports
from horilla_crm.accounts.forms import (
    AccountFormClass,
    AccountSingleForm,
    AddChildAccountForm,
)
from horilla_crm.accounts.models import Account, PartnerAccountRelationship
from horilla_crm.contacts.models import ContactAccountRelationship

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
class AccountFormView(LoginRequiredMixin, HorillaMultiStepFormView):
    """
    form view for account
    """

    form_class = AccountFormClass
    model = Account
    fullwidth_fields = ["description"]
    detail_url_name = "accounts:account_detail_view"
    total_steps = 4
    step_titles = {
        "1": _("Account Information"),
        "2": _("Address Information"),
        "3": _("Additional Information"),
        "4": _("Description"),
    }

    form_mode = [
        {
            "title": _("Single-Step Form"),
            "url_name": {
                "create": "accounts:account_single_create_form_view",
                "edit": "accounts:account_single_edit_form_view",
            },
            "active": False,
        },
        {
            "title": _("Multi-Step Form"),
            "url_name": {
                "create": "accounts:account_create_form_view",
                "edit": "accounts:account_edit_form_view",
            },
            "active": True,
        },
    ]

    @cached_property
    def form_url(self):
        """Return the URL for the account form (edit if PK exists, else create)."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("accounts:account_edit_form_view", kwargs={"pk": pk})
        return reverse_lazy("accounts:account_create_form_view")


@method_decorator(htmx_required, name="dispatch")
class AccountsSingleFormView(LoginRequiredMixin, HorillaSingleFormView):
    """Account Create/Update Single Page View"""

    model = Account
    form_class = AccountSingleForm
    full_width_fields = ["description"]
    detail_url_name = "accounts:account_detail_view"

    form_mode = [
        {
            "title": _("Single-Step Form"),
            "url_name": {
                "create": "accounts:account_single_create_form_view",
                "edit": "accounts:account_single_edit_form_view",
            },
            "active": True,
        },
        {
            "title": _("Multi-Step Form"),
            "url_name": {
                "create": "accounts:account_create_form_view",
                "edit": "accounts:account_edit_form_view",
            },
            "active": False,
        },
    ]

    @cached_property
    def form_url(self):
        """Form URL for lead"""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "accounts:account_single_edit_form_view", kwargs={"pk": pk}
            )
        return reverse_lazy("accounts:account_single_create_form_view")


@method_decorator(htmx_required, name="dispatch")
class AccountChangeOwnerForm(LoginRequiredMixin, HorillaSingleFormView):
    """
    Change owner form
    """

    model = Account
    fields = ["account_owner"]
    full_width_fields = ["account_owner"]
    modal_height = False
    form_title = _("Change Owner")

    @cached_property
    def form_url(self):
        """Return the URL for the account form (edit if PK exists, else create)."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("accounts:account_change_owner", kwargs={"pk": pk})
        return None

    def has_permission(self):
        user = self.request.user
        if user.is_superuser:
            return True
        if user.has_perm("accounts.change_account") or user.has_perm(
            "accounts.add_account"
        ):
            return True
        account_id = self.kwargs.get("pk")
        if account_id:
            account = get_object_or_404(Account, pk=account_id)
            return check_record_change_access(user, account)
        return False


@method_decorator(htmx_required, name="dispatch")
class AddRelatedContactFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Create and update form for adding related accounts into contacts
    """

    model = ContactAccountRelationship
    modal_height = False
    fields = ["contact", "account", "role"]
    form_title = _("Add Contact Relationships")
    full_width_fields = ["account", "contact", "role"]
    hidden_fields = ["account"]
    save_and_new = False

    def _get_account(self):
        pk = self.kwargs.get("pk")
        account_id = self.request.GET.get("id")

        if pk:
            rel = get_object_or_404(ContactAccountRelationship, pk=pk)
            return rel.account

        if account_id:
            return get_object_or_404(Account, pk=account_id)
        return None

    def has_permission(self):
        user = self.request.user
        if user.is_superuser:
            return True
        account = self._get_account()
        if account:
            return check_record_change_access(user, account)
        return False

    def form_valid(self, form):
        super().form_valid(form)
        return ScriptResponse(
            extra=HxTriggerResponse.build(id="tab-contact_relationships-btn"),
            close=True,
        )

    def get_initial(self):
        """Prefill relationship form with selected account id from query params."""
        initial = super().get_initial()
        obj_id = self.request.GET.get("id")
        if obj_id:
            initial["account"] = obj_id
        return initial

    @cached_property
    def form_url(self):
        """
        Return the URL for the contact-account relationship form
        (edit if PK exists, else create).
        """
        if self.kwargs.get("pk"):
            return reverse_lazy(
                "accounts:edit_account_contact_relation",
                kwargs={"pk": self.kwargs.get("pk")},
            )
        return reverse_lazy("accounts:create_account_contact_relation")


@method_decorator(htmx_required, name="dispatch")
class AddChildAccountFormView(LoginRequiredMixin, FormView):
    """
    Form view to select an existing account and assign it as a child account.
    """

    template_name = "single_form_view.html"
    form_class = AddChildAccountForm
    header = True

    def get(self, request, *args, **kwargs):
        """Authorize child-account form access based on parent record permissions."""
        account_id = request.GET.get("id")
        if account_id:
            try:
                account = get_object_or_404(Account, pk=account_id)
            except Http404:
                messages.error(request, _("Account not found or no longer exists."))
                return ScriptResponse(reload=True, close=True)
            if check_record_change_access(request.user, account):
                return super().get(request, *args, **kwargs)
        return render(request, "403.html")

    def get_form_kwargs(self):
        """
        Pass the request to the form for queryset filtering and validation.
        """
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def get_initial(self):
        """
        Prepopulate the form with initial data if needed.
        """
        initial = super().get_initial()
        parent_id = self.request.GET.get("id")

        if parent_id:
            try:
                parent_account = Account.objects.get(pk=parent_id)
                initial["parent_account"] = parent_account
            except Account.DoesNotExist:
                logger.error("Parent account with ID %s not found", parent_id)

        return initial

    def get_context_data(self, **kwargs):
        """
        Add context data for the template.
        """
        context = super().get_context_data(**kwargs)
        context["form_title"] = _("Add Child Account")
        context["full_width_fields"] = ["account"]
        form_url = self.get_form_url()
        context["form_url"] = form_url
        context["modal_height"] = False
        context["view_id"] = "add-child-account-form-view"
        context["condition_fields"] = []
        context["header"] = self.header
        context["field_permissions"] = {}
        context["hx_attrs"] = {
            "hx-post": str(form_url),
            "hx-target": "#modalBox",
            "hx-swap": "innerHTML",
        }

        return context

    def form_valid(self, form):
        """Update the selected account's parent_account field and return HTMX response."""
        selected_account = form.cleaned_data["account"]
        parent_account = form.cleaned_data["parent_account"]

        if not parent_account:
            form.add_error(None, _("No parent account specified in the request."))
            return self.form_invalid(form)

        if not check_record_change_access(self.request.user, parent_account):
            return render(self.request, "403.html")

        try:
            if selected_account.id == parent_account.id:
                form.add_error("account", _("An account cannot be its own parent."))
                response = self.form_invalid(form)
            elif selected_account.parent_account:
                form.add_error(
                    "account", _("This account already has a parent account.")
                )
                response = self.form_invalid(form)
            else:
                # Update the selected account
                selected_account.parent_account = parent_account
                selected_account.updated_at = timezone.now()
                selected_account.updated_by = self.request.user
                selected_account.company = self.request.active_company
                selected_account.save()
                messages.success(
                    self.request, _("Child account assigned successfully.")
                )
                response = ScriptResponse(
                    extra=HxTriggerResponse.build(id="tab-child_accounts-btn"),
                    close=True,
                )
        except ValidationError as e:
            msg = (
                next(iter(e.message_dict.values()))[0]
                if hasattr(e, "message_dict")
                else e.message
            )
            form.add_error("account", msg)
            response = self.form_invalid(form)
        except ValueError:
            form.add_error(None, _("Invalid parent account ID format."))
            response = self.form_invalid(form)

        return response

    def get_form_url(self):
        """
        Get the form URL for submission.
        """
        if self.kwargs.get("pk"):
            return reverse_lazy(
                "accounts:edit_child_account", kwargs={"pk": self.kwargs.get("pk")}
            )
        return reverse_lazy("accounts:create_child_accounts")


@method_decorator(htmx_required, name="dispatch")
class AccountPartnerFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    create and update from view for Account partner
    """

    model = PartnerAccountRelationship
    fields = ["partner", "role", "account"]
    full_width_fields = ["partner", "role", "account"]
    modal_height = False
    form_title = _("Account Partner")
    hidden_fields = ["account"]
    save_and_new = False

    def _get_account(self):
        pk = self.kwargs.get("pk")
        account_id = self.request.GET.get("id")
        if pk:
            rel = get_object_or_404(PartnerAccountRelationship, pk=pk)
            return rel.account
        if account_id:
            return get_object_or_404(Account, pk=account_id)
        return None

    def has_permission(self):
        user = self.request.user
        if user.is_superuser:
            return True
        account = self._get_account()
        if account:
            return check_record_change_access(user, account)
        return False

    def form_valid(self, form):
        account = form.cleaned_data.get("account")
        role = form.cleaned_data.get("role")

        existing = PartnerAccountRelationship.objects.filter(account=account, role=role)
        if self.object:  # If update, exclude current instance
            existing = existing.exclude(pk=self.object.pk)

        super().form_valid(form)
        return ScriptResponse(
            extra=HxTriggerResponse.build(id="tab-partner-btn"),
            close=True,
        )

    def get_initial(self):
        """Set initial form data for the account form."""
        initial = super().get_initial()
        obj_id = self.request.GET.get("id")
        if obj_id:
            initial["account"] = obj_id
        return initial

    @cached_property
    def form_url(self):
        """
        Return the URL for the account partner form
        (edit if PK exists, else create).
        """
        if self.kwargs.get("pk"):
            return reverse_lazy(
                "accounts:account_partner_update_form",
                kwargs={"pk": self.kwargs.get("pk")},
            )
        return reverse_lazy("accounts:account_partner_create_form")


@method_decorator(htmx_required, name="dispatch")
class ChildAccountDeleteView(LoginRequiredMixin, View):
    """
    View to remove parent-child relationship from a account.
    """

    def delete(self, request, pk, *args, **kwargs):
        """
        Handle DELETE request to remove parent account relationship.
        """
        child_account = get_object_or_404(Account, pk=pk)

        parent_account = child_account.parent_account or child_account
        has_permission = check_record_delete_access(request.user, parent_account)

        if not has_permission:
            messages.error(
                request, _("You don't have permission to perform this action.")
            )
            return HxTriggerResponse(id="tab-child_accounts-btn")

        parent_account = child_account.parent_account

        if not parent_account:
            messages.warning(request, _("This contact doesn't have a parent account."))
            return HxTriggerResponse(id="tab-child_accounts-btn")

        try:
            child_account.parent_account = None
            child_account.updated_at = timezone.now()
            child_account.updated_by = request.user
            child_account.save()

            messages.success(
                request,
                _(
                    f"Successfully removed {child_account} from {parent_account}'s child accounts."
                ),
            )

            return HxTriggerResponse(id="tab-child_accounts-btn")

        except Exception:
            messages.error(
                request, _("An error occurred while removing the child account.")
            )
            return HxTriggerResponse(id="tab-child_accounts-btn")


@method_decorator(htmx_required, name="dispatch")
class PartnerAccountDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete view for partner account
    """

    model = PartnerAccountRelationship

    def dispatch(self, request, *args, **kwargs):
        """Require delete access on the related account before proceeding."""
        rel = get_object_or_404(PartnerAccountRelationship, pk=self.kwargs.get("pk"))
        if not check_record_delete_access(request.user, rel.account):
            return render(request, "403.html", {"modal": True})
        return super().dispatch(request, *args, **kwargs)

    def get_post_delete_response(self):
        """Reload the partner tab after deleting the relationship."""
        return HxTriggerResponse(id="tab-partner-btn")


@method_decorator(htmx_required, name="dispatch")
class AccountDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete view for account
    """

    model = Account

    def get_post_delete_response(self):
        return ScriptResponse(reload=True)
