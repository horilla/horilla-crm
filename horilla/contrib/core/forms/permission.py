"""
Forms for managing user permissions, roles, and superuser status in the Horilla application.
"""

# Standard library imports
import logging

# Third-party imports (Django)
from django import forms

# First-party imports (Horilla)
from horilla.auth.models import User
from horilla.core.exceptions import ValidationError
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _

# Local / relative imports
from ..models import Role

logger = logging.getLogger(__name__)


class AddUsersToRoleForm(forms.Form):
    """Form to add users to a specific role."""

    role = forms.ModelChoiceField(
        queryset=Role.objects.all(),
    )
    users = forms.ModelMultipleChoiceField(
        queryset=User.objects.all(),
        label=_("Users"),
        help_text=_("Select one or more users to assign to the role."),
        widget=forms.SelectMultiple(
            attrs={
                "class": "select2-pagination w-full",
                "data-url": reverse_lazy(
                    "generics:model_select2",
                    kwargs={
                        "app_label": "core",
                        "model_name": str(User.__name__),
                    },
                ),
                "data-placeholder": "Select User",
                "multiple": "multiple",
                "data-field-name": "users",
                "id": "id_users",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        self.full_width_fields = kwargs.pop("full_width_fields", [])
        self.dynamic_create_fields = kwargs.pop("dynamic_create_fields", [])
        self.hidden_fields = kwargs.pop("hidden_fields", [])
        self.condition_fields = kwargs.pop("condition_fields", [])
        self.condition_model = kwargs.pop("condition_model", None)
        self.condition_field_choices = kwargs.pop("condition_field_choices", {})
        self.request = kwargs.pop("request", None)
        self.condition_hx_include = kwargs.pop("condition_hx_include", "")
        self.field_permissions = kwargs.pop("field_permissions", {})
        self.save_and_new = kwargs.pop("save_and_new", "")
        self.duplicate_mode = kwargs.pop("duplicate_mode", False)
        super().__init__(*args, **kwargs)
        for field_name in self.hidden_fields:
            if field_name in self.fields:
                self.fields[field_name].widget = forms.HiddenInput()
                self.fields[field_name].widget.attrs.update({"class": "hidden-input"})

        # Only offer users from the selected role's company
        role = self.initial.get("role")
        if not isinstance(role, Role):
            role_id = self.data.get("role") or role
            role = Role.objects.filter(pk=role_id).first() if role_id else None
        company = (role.company if role else None) or getattr(
            self.request, "active_company", None
        )
        if company:
            self.fields["users"].queryset = User.objects.filter(company=company)

    def clean(self):
        """Ensure no user is already assigned to the selected role."""
        cleaned_data = super().clean()
        role = cleaned_data.get("role")
        users = cleaned_data.get("users")

        if role and users:
            if role.company_id:
                other_company = users.exclude(company_id=role.company_id)
                if other_company.exists():
                    raise ValidationError(
                        _("The following user(s) do not belong to the role's company")
                    )
            duplicates = users.filter(role=role)
            if duplicates.exists():
                raise ValidationError(
                    _("The following user(s) are already assigned to this role")
                )

        return cleaned_data

    def save(self, commit=True):
        """Assign the selected role to the selected users."""
        role = self.cleaned_data["role"]
        users = self.cleaned_data["users"]
        if commit:
            role_permissions = list(role.permissions.all())
            for user in users:
                user.role = role
                user.save()
                if role_permissions:
                    user.user_permissions.add(*role_permissions)
        return users


class AddSuperUsersForm(forms.Form):
    """Form to add users as superusers."""

    users = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(is_superuser=False),
        label=_("Users"),
        help_text=_("Select one or more users to grant superuser privileges."),
        widget=forms.SelectMultiple(
            attrs={
                "class": "select2-pagination w-full",
                "data-url": reverse_lazy(
                    "generics:model_select2",
                    kwargs={
                        "app_label": "core",
                        "model_name": str(User.__name__),
                    },
                ),
                "data-placeholder": "Select Users",
                "multiple": "multiple",
                "data-field-name": "users",
                "data-form-class": "horilla.contrib.core.forms.AddSuperUsersForm",
                "id": "id_users",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        self.full_width_fields = kwargs.pop("full_width_fields", [])
        self.dynamic_create_fields = kwargs.pop("dynamic_create_fields", [])
        self.hidden_fields = kwargs.pop("hidden_fields", [])
        self.condition_fields = kwargs.pop("condition_fields", [])
        self.condition_model = kwargs.pop("condition_model", None)
        self.condition_field_choices = kwargs.pop("condition_field_choices", {})
        self.request = kwargs.pop("request", None)
        self.condition_hx_include = kwargs.pop("condition_hx_include", "")
        self.field_permissions = kwargs.pop("field_permissions", {})
        self.save_and_new = kwargs.pop("save_and_new", "")
        self.duplicate_mode = kwargs.pop("duplicate_mode", False)
        super().__init__(*args, **kwargs)

        # Filter users to only show non-superusers from the same company
        company = (
            getattr(self.request, "active_company", None) if self.request else None
        ) or (
            self.request.user.company
            if self.request and self.request.user.is_authenticated
            else None
        )

        if company:
            self.fields["users"].queryset = User.objects.filter(
                is_superuser=False, company=company
            )
        else:
            self.fields["users"].queryset = User.objects.filter(is_superuser=False)

        for field_name in self.hidden_fields:
            if field_name in self.fields:
                self.fields[field_name].widget = forms.HiddenInput()
                self.fields[field_name].widget.attrs.update({"class": "hidden-input"})

    def clean(self):
        """Ensure selected users are not already superusers."""
        cleaned_data = super().clean()
        users = cleaned_data.get("users")

        if users:
            # Check if any selected users are already superusers
            already_superusers = users.filter(is_superuser=True)
            if already_superusers.exists():
                user_names = ", ".join(
                    [
                        user.get_full_name() or user.username
                        for user in already_superusers
                    ]
                )
                raise ValidationError(
                    _("The following user(s) are already superusers: {users}").format(
                        users=user_names
                    )
                )

        return cleaned_data

    def save(self, commit=True):
        """Add superuser status to the selected users."""
        users = self.cleaned_data["users"]
        if commit:
            for user in users:
                user.is_superuser = True
                user.save()
        return users
