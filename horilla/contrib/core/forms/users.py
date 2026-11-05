"""
Forms for managing users in the Horilla core module.
"""

# Standard library imports
import logging

# Third-party imports (Django)
from django import forms
from django.contrib.auth.password_validation import validate_password

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.generics.forms import (
    HorillaModelForm,
    HorillaMultiStepForm,
    PasswordInputWithEye,
)

# First-party imports (Horilla)
from horilla.core.exceptions import ValidationError
from horilla.urls import reverse_lazy
from horilla.utils.choices import get_subdivision_choices, resolve_subdivision_choice
from horilla.utils.translation import gettext_lazy as _

# Local imports
from ..models import Company, Department, MultipleCurrency, Role

logger = logging.getLogger(__name__)


class UserFormClass(HorillaMultiStepForm):
    """Form class for User model with password fields."""

    class Meta:
        """Meta options for UserFormClass."""

        model = User
        fields = "__all__"
        exclude = [
            "password",
            "last_login",
            "date_joined",
            "is_superuser",
            "username",
            "is_staff",
            "number_format",
        ]
        keep_on_form = ["is_active"]

    step_fields = {
        1: [
            "profile",
            "email",
            "first_name",
            "last_name",
            "contact_number",
            "is_active",
        ],
        2: ["country", "state", "city", "zip_code"],
        3: ["department", "role"],
        4: [
            "language",
            "time_zone",
            "date_format",
            "time_format",
            "date_time_format",
            "currency",
        ],
    }

    def clean_email(self):
        """Validate that email is unique"""
        email = self.cleaned_data.get("email")

        if email:
            queryset = User.objects.filter(email=email)
            if self.instance and self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)

            if queryset.exists():
                raise ValidationError(_("A user with this email already exists."))

        return email

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in ["first_name", "last_name", "email", "contact_number"]:
            if field in self.fields:
                self.fields[field].required = True

        self.fields["country"].widget.attrs.update(
            {
                "hx-get": reverse_lazy("core:get_country_subdivisions"),
                "hx-target": "#id_state",
                "hx-trigger": "change",
                "hx-swap": "innerHTML",
            }
        )

        self.fields["state"] = forms.ChoiceField(
            choices=[],
            required=False,
            widget=forms.Select(
                attrs={"id": "id_state", "class": "js-example-basic-single headselect"}
            ),
        )

        if "country" in self.data:
            country_code = self.data.get("country")
            self.fields["state"].choices = get_subdivision_choices(country_code)
        elif self.instance.pk and self.instance.country:
            self.fields["state"].choices = get_subdivision_choices(
                self.instance.country.code
            )
            self.fields["state"].initial = resolve_subdivision_choice(
                self.fields["state"].choices, self.instance.state
            )


class UserFormSingle(HorillaModelForm):
    """Form class for User model."""

    field_order = [
        "profile",
        "email",
        "first_name",
        "last_name",
        "contact_number",
        "country",
        "state",
        "city",
        "zip_code",
        "department",
        "role",
        "language",
        "time_zone",
        "date_format",
        "time_format",
        "date_time_format",
        "currency",
        "is_active",
    ]

    class Meta:
        """Meta options for UserFormSingle."""

        model = User
        fields = "__all__"
        exclude = [
            "password",
            "last_login",
            "date_joined",
            "is_superuser",
            "username",
            "is_staff",
            "number_format",
            "groups",
            "user_permissions",
        ]
        keep_on_form = ["is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in ["first_name", "last_name", "email", "contact_number"]:
            if field in self.fields:
                self.fields[field].required = True

        self.fields["country"].widget.attrs.update(
            {
                "hx-get": reverse_lazy("core:get_country_subdivisions"),
                "hx-target": "#id_state",
                "hx-trigger": "change",
                "hx-swap": "innerHTML",
            }
        )

        self.fields["state"] = forms.ChoiceField(
            choices=[],
            required=False,
            widget=forms.Select(
                attrs={"id": "id_state", "class": "js-example-basic-single headselect"}
            ),
        )

        if "country" in self.data:
            country_code = self.data.get("country")
            self.fields["state"].choices = get_subdivision_choices(country_code)
        elif self.instance.pk and self.instance.country:
            self.fields["state"].choices = get_subdivision_choices(
                self.instance.country.code
            )
            self.fields["state"].initial = resolve_subdivision_choice(
                self.fields["state"].choices, self.instance.state
            )


class UserDetailsInlineForm(UserFormSingle):
    """Form used by the user detail page to edit a user's details in place."""

    fieldsets = (
        (
            _("Personal Information"),
            {
                "fields": (
                    "profile",
                    "first_name",
                    "last_name",
                    "email",
                    "contact_number",
                )
            },
        ),
        (
            _("Address"),
            {"fields": ("country", "state", "city", "zip_code")},
        ),
        (
            _("Work Info"),
            {"fields": ("department", "role")},
        ),
        (
            _("Localization"),
            {
                "fields": (
                    "language",
                    "time_zone",
                    "currency",
                    "date_time_format",
                    "date_format",
                    "time_format",
                )
            },
        ),
    )

    class Meta:
        """Meta options for UserDetailsInlineForm."""

        model = User
        fields = [
            "profile",
            "first_name",
            "last_name",
            "email",
            "contact_number",
            "country",
            "state",
            "city",
            "zip_code",
            "department",
            "role",
            "language",
            "time_zone",
            "currency",
            "date_time_format",
            "date_format",
            "time_format",
        ]


class UserFormClassSingle(HorillaModelForm):
    """Form class for User model with password fields."""

    # Add password fields that are not part of the model
    password = forms.CharField(
        widget=PasswordInputWithEye(),
        label=_("Password"),
        help_text=_("Enter a secure password"),
        required=True,
    )

    confirm_password = forms.CharField(
        widget=PasswordInputWithEye(),
        label=_("Confirm Password"),
        help_text=_("Enter the same password again for verification"),
        required=True,
    )

    class Meta:
        """Meta options for UserFormClassSingle."""

        model = User
        fields = [
            "profile",
            "email",
            "first_name",
            "last_name",
            "username",
            "contact_number",
            "password",
            "confirm_password",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Configure username field
        self.fields["username"].widget.attrs.update(
            {
                "class": "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                "placeholder": _("Enter Username"),
            }
        )
        self.fields["username"].required = True
        self.fields["username"].help_text = _(
            "Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only."
        )

        # If this is an edit form (instance exists), don't require passwords
        if self.instance and self.instance.pk:
            self.fields["password"].required = False
            self.fields["confirm_password"].required = False
            self.fields["password"].help_text = _(
                "Leave blank to keep current password"
            )
            self.fields["confirm_password"].help_text = _(
                "Leave blank to keep current password"
            )

    def clean_username(self):
        """Validate that username is unique & required."""
        username = self.cleaned_data.get("username")
        if not username:
            raise ValidationError(_("Username is required."))

        existing_user = User.objects.filter(username=username)
        if self.instance and self.instance.pk:
            existing_user = existing_user.exclude(pk=self.instance.pk)

        if existing_user.exists():
            raise ValidationError(_("A user with this username already exists."))

        return username

    def clean_confirm_password(self):
        """Validate that password and confirm_password match."""
        password = self.cleaned_data.get("password")
        confirm_password = self.cleaned_data.get("confirm_password")

        if password or confirm_password:
            if password != confirm_password:
                raise ValidationError(_("The two password fields must match."))

        return confirm_password

    def clean_password(self):
        """Validate password strength using Django's password validators."""
        password = self.cleaned_data.get("password")

        if not self.instance or not self.instance.pk:
            if not password:
                raise ValidationError(_("Password is required for new users."))

        if password:
            validate_password(password, user=self.instance)

        return password

    def save(self, commit=True):
        """Override save method to handle password setting."""
        user = super().save(commit=False)

        # Handle password
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)

        if commit:
            user.save()
            self.save_m2m()

        return user


class ChangeUserCompanyForm(HorillaModelForm):
    """Form for changing user's company with dynamic role, department, and currency filtering"""

    field_order = ["company", "role", "department", "currency"]

    class Meta:
        """
        Meta class for change user company form
        """

        model = User
        fields = ["company", "role", "department", "currency"]
        keep_on_form = ["company"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "company" in self.fields:
            self.fields["company"].queryset = Company.objects.all().order_by("name")
            if hasattr(self, "field_permissions") and self.field_permissions:
                self.field_permissions["company"] = "readwrite"

        if "company" in self.fields:
            hx_vals = {}
            if self.instance and self.instance.pk:
                hx_vals["user_pk"] = str(self.instance.pk)

            attrs = {
                "hx-get": reverse_lazy("core:get_company_related_fields"),
                "hx-target": "#company-related-fields",
                "hx-swap": "innerHTML",
                "hx-trigger": "change",
                "hx-include": "#id_company",  # Only include the select element by ID
            }

            if hx_vals:
                import json

                attrs["hx-vals"] = json.dumps(hx_vals)

            self.fields["company"].widget.attrs.update(attrs)

        company = None
        if self.data and self.data.get("company"):
            try:
                company = Company.objects.get(pk=self.data.get("company"))
            except (Company.DoesNotExist, ValueError, TypeError):
                pass

        if not company and self.instance and self.instance.pk and self.instance.company:
            company = self.instance.company

        if company:
            self._filter_fields_by_company(company)

    def _filter_fields_by_company(self, company):
        """Filter role, department, and currency fields by company"""

        if "role" in self.fields:
            self.fields["role"].queryset = Role.all_objects.filter(
                company=company, is_active=True
            )

        if "department" in self.fields:
            self.fields["department"].queryset = Department.all_objects.filter(
                company=company, is_active=True
            )

        if "currency" in self.fields:
            self.fields["currency"].queryset = MultipleCurrency.all_objects.filter(
                company=company, is_active=True
            )

    def _get_fresh_queryset(self, field_name, related_model):
        """
        Override to bypass permission filtering for role, department, and currency fields.
        These fields are filtered by company, not by user permissions.
        """
        if field_name in ["role", "department", "currency"]:
            company = None
            if self.data and self.data.get("company"):
                try:
                    company_id = self.data.get("company")
                    if isinstance(company_id, list):
                        company_id = company_id[-1] if company_id else None
                    if company_id:
                        company = Company.objects.get(pk=company_id)
                except (Company.DoesNotExist, ValueError, TypeError):
                    pass
            elif self.instance and self.instance.pk and self.instance.company:
                company = self.instance.company

            if company:
                return related_model.all_objects.filter(company=company, is_active=True)

            return related_model.all_objects.none()

        return super()._get_fresh_queryset(field_name, related_model)

    def clean(self):
        cleaned_data = super().clean()
        company = cleaned_data.get("company")
        role = cleaned_data.get("role")
        department = cleaned_data.get("department")
        currency = cleaned_data.get("currency")

        if company and role:
            if role.company != company:
                self.add_error(
                    "role", f"Selected role does not belong to {company.name}"
                )

        if company and department:
            if department.company != company:
                self.add_error(
                    "department",
                    f"Selected department does not belong to {company.name}",
                )

        if company and currency:
            if currency.company != company:
                self.add_error(
                    "currency", f"Selected currency does not belong to {company.name}"
                )

        if self.instance and self.instance.pk and role:
            current_role = getattr(self.instance, "role", None)

            if current_role != role:
                username = self.instance.username
                existing_user = User.all_objects.filter(
                    username=username, role=role
                ).exclude(pk=self.instance.pk)
                if existing_user.exists():
                    self.add_error(
                        "role",
                        f'Another user with username "{username}" already has this role. Please select a different role.',
                    )

        return cleaned_data
