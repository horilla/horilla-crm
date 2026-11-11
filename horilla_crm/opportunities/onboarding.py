"""Onboarding step owned by the opportunities app: Opportunity Stages."""

# First party imports (Horilla)
from horilla.registry.onboarding import OnboardingSteps
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import OpportunityStage


class OpportunityStagesOnboarding(OnboardingSteps):
    """Deals need stages before the team can create and move them."""

    key = "opportunity_stages"
    headline = _("Set up your opportunity stages")
    description = _("Define the stages your deals move through.")
    url_name = "opportunities:opportunity_stage_view"
    icon = "fa-bullseye"
    order = 55
    model = OpportunityStage
