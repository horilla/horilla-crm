"""
Forms for the Accounts app.

Includes forms for creating/editing accounts and assigning child accounts,
with validation and dynamic queryset setup to prevent circular references.
"""

# Third-party imports (Django)
from django import forms

from horilla.contrib.core.mixins import OwnerQuerysetMixin
from horilla.contrib.generics.forms import HorillaModelForm, HorillaMultiStepForm

# First party imports (Horilla)
from horilla.core.exceptions import ValidationError
from horilla.urls import reverse_lazy
from horilla.utils.text import select_placeholder_lazy
from horilla.utils.translation import gettext_lazy as _

# Local imports
from horilla_crm.accounts.models import Account


def _would_create_cycle(account_instance, new_parent):
    """Return True if setting new_parent as the parent of account_instance creates a cycle."""
    ancestor = new_parent
    while ancestor is not None:
        if ancestor.pk == account_instance.pk:
            return True
        ancestor = ancestor.parent_account
    return False


class AccountFormClass(OwnerQuerysetMixin, HorillaMultiStepForm):
    """Multi-step form for creating or editing an Account."""

    class Meta:
        """Meta options for the Account form."""

        model = Account
        fields = "__all__"
        exclude = [
            "is_customer_portal",
            "account_score",
            "customer_priority",
            "operating_hours",
        ]

    step_fields = {
        1: [
            "account_owner",
            "name",
            "account_source",
            "account_type",
            "rating",
            "contact_number",
            "parent_account",
            "fax",
            "account_number",
            "website",
            "site",
        ],
        2: [
            "billing_city",
            "billing_state",
            "billing_district",
            "billing_zip",
            "shipping_city",
            "shipping_state",
            "shipping_district",
            "shipping_zip",
        ],
        3: [
            "annual_revenue",
            "is_partner",
            "industry",
            "number_of_employees",
            "ownership",
        ],
        4: ["description"],
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.current_step < len(self.step_fields):
            self.fields["is_partner"].required = False
            if self.instance and self.instance.pk and "is_partner" not in self.initial:
                self.initial["is_partner"] = self.instance.is_partner

    def clean_parent_account(self):
        """Reject parent accounts that would create a circular hierarchy."""
        parent_account = self.cleaned_data.get("parent_account")
        if parent_account and self.instance.pk:
            if _would_create_cycle(self.instance, parent_account):
                raise ValidationError(
                    _(
                        "Invalid parent account. This relationship would create a circular hierarchy."
                    )
                )
        return parent_account


class AccountSingleForm(OwnerQuerysetMixin, HorillaModelForm):
    """
    Custom form for Lead to add HTMX attributes
    Inherits from HorillaModelForm to preserve all existing behavior.
    """

    field_order = [
        "account_owner",
        "name",
        "account_source",
        "account_type",
        "rating",
        "contact_number",
        "parent_account",
        "fax",
        "account_number",
        "website",
        "site",
        "billing_city",
        "billing_state",
        "billing_district",
        "billing_zip",
        "shipping_city",
        "shipping_state",
        "shipping_district",
        "shipping_zip",
        "annual_revenue",
        "is_partner",
        "industry",
        "number_of_employees",
        "ownership",
        "description",
    ]

    class Meta:
        """Meta class for LeadStatusForm"""

        model = Account
        fields = "__all__"
        exclude = [
            "is_customer_portal",
            "account_score",
            "customer_priority",
            "operating_hours",
        ]

    def clean_parent_account(self):
        """Reject parent accounts that would create a circular hierarchy."""
        parent_account = self.cleaned_data.get("parent_account")
        if parent_account and self.instance.pk:
            if _would_create_cycle(self.instance, parent_account):
                raise ValidationError(
                    _(
                        "Invalid parent account. This relationship would create a circular hierarchy."
                    )
                )
        return parent_account


class AddChildAccountForm(forms.Form):
    """
    Form to select an existing account and assign it as a child account.
    """

    account = forms.ModelChoiceField(
        queryset=Account.objects.none(),  # Will be set in __init__
        label=_("Select Account"),
        widget=forms.Select(
            attrs={
                "class": "select2-pagination w-full text-sm",
                "data-placeholder": select_placeholder_lazy(Account._meta.verbose_name),
                "data-url": reverse_lazy(
                    "generics:model_select2",
                    kwargs={"app_label": "accounts", "model_name": "Account"},
                ),
                "data-field-name": "account",
                "id": "id_account",
            }
        ),
        help_text=_("Select the account to assign as a child account."),
    )

    parent_account = forms.ModelChoiceField(
        queryset=Account.objects.all(),
        required=False,
        widget=forms.HiddenInput(),  # Make this a hidden field
    )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)

        generic_attrs = ["full_width_fields", "dynamic_create_fields", "hidden_fields"]
        for attr in generic_attrs:
            kwargs.pop(attr, None)

        super().__init__(*args, **kwargs)

        self.setup_account_queryset()

    def setup_account_queryset(self):
        """
        Set up the account queryset based on the request parameters.
        """
        if not self.request:
            self.fields["account"].queryset = Account.objects.all()
            return

        parent_id = self.request.GET.get("id")
        if not parent_id:
            self.fields["account"].queryset = Account.objects.all()
            return

        try:
            parent_account = Account.objects.get(pk=parent_id)

            queryset = Account.objects.all()
            queryset = queryset.exclude(id=parent_id)

            queryset = queryset.filter(parent_account__isnull=True)
            descendant_ids = self.get_descendant_ids(parent_account)
            if descendant_ids:
                queryset = queryset.exclude(id__in=descendant_ids)

            self.fields["account"].queryset = queryset

        except Account.DoesNotExist:
            # If parent doesn't exist, show all accounts without parents
            self.fields["account"].queryset = Account.objects.filter(
                parent_account__isnull=True
            )

    def get_descendant_ids(self, account):
        """
        Get all descendant IDs of an account to prevent circular references.
        """
        descendant_ids = []
        children = Account.objects.filter(parent_account=account)
        for child in children:
            descendant_ids.append(child.id)
            descendant_ids.extend(self.get_descendant_ids(child))
        return descendant_ids

    def clean_account(self):
        """
        Validate the selected account.
        """
        account = self.cleaned_data.get("account")
        if not account:
            raise ValidationError(_("Please select an account."))

        # Check if account already has a parent
        if account.parent_account:
            raise ValidationError(
                _("This account already has a parent account assigned.")
            )

        # Get parent from hidden field instead of request
        parent_account = self.cleaned_data.get("parent_account")
        if parent_account and str(account.id) == str(parent_account.id):
            raise ValidationError(_("An account cannot be its own parent."))

        return account

    def clean(self):
        """Validate form-level data and ensure an account is selected."""
        cleaned_data = super().clean()
        account = cleaned_data.get("account")

        if not account:
            raise ValidationError(_("Please select a valid account."))

        return cleaned_data
