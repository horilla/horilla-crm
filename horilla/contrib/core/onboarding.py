"""Onboarding steps owned by the core app: Company, Roles and Users."""

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.registry.onboarding import OnboardingSteps
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import Role


class CompanyOnboarding(OnboardingSteps):
    """The company already exists, so it is done once its required fields are filled in."""

    key = "company"
    title = _("Company")
    headline = _("Complete your company profile")
    description = _("Complete your company profile with name, email and country .")
    url_name = "core:company_information"
    icon = "fa-building"
    permission = "core.view_company"
    order = 10

    def is_done(self, company, user):
        """Done when the company has its name, email and country filled in."""
        return bool(company.name and company.email and company.country)


class RolesOnboarding(OnboardingSteps):
    """Roles carry the permissions users get."""

    key = "roles"
    headline = _("Create your roles")
    description = _(
        "Create roles to control what each user can see and do in {company}."
    )
    url_name = "core:roles_view"
    icon = "fa-user-shield"
    order = 20
    model = Role


class UsersOnboarding(OnboardingSteps):
    """Done once the company has a user."""

    key = "users"
    headline = _("Invite your team")
    description = _(
        "Add the people who will work in {company} so they can sign in and get started."
    )
    url_name = "core:user_view"
    icon = "fa-users"
    order = 30
    model = User
