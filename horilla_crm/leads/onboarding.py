"""Onboarding steps owned by the leads app: Lead Stages and Import Leads."""

# First party imports (Horilla)
from horilla.registry.onboarding import OnboardingSteps
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import Lead, LeadStatus


class LeadStagesOnboarding(OnboardingSteps):
    """Every lead needs a stage, so the stages come first."""

    key = "lead_stages"
    headline = _("Set up your lead stages")
    description = _("Define the stages your leads move through.")
    url_name = "leads:lead_stage_view"
    icon = "fa-filter"
    order = 50
    model = LeadStatus


class ImportLeadsOnboarding(OnboardingSteps):
    """An empty CRM has nothing to work on until leads are added or imported."""

    key = "leads"
    title = _("Import Leads")
    headline = _("Add your first leads")
    description = _("Add leads one by one, or import them from a CSV or Excel file.")
    url_name = "leads:leads_view"
    icon = "fa-upload"
    order = 60
    model = Lead
