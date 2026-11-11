"""Tests for the Opportunity Stages onboarding step."""

# Third-party imports (Django)
from django.test import TestCase

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.models import Company
from horilla.registry.onboarding import build_onboarding
from horilla_crm.opportunities.models import OpportunityStage
from horilla_crm.opportunities.onboarding import OpportunityStagesOnboarding


class OpportunityStagesOnboardingTests(TestCase):
    """The step is done only in the company that has an opportunity stage."""

    def setUp(self):
        """Two companies and a superuser."""
        self.acme = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        self.beta = Company.objects.create(
            name="Beta", email="beta@example.com", country="US"
        )
        self.admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
            company=self.acme,
        )

    def _done(self, company):
        step = OpportunityStagesOnboarding()
        return step.is_done(company, self.admin)

    def test_done_only_in_the_company_with_a_stage(self):
        """A stage in Acme does not complete the step for Beta."""
        self.assertFalse(self._done(self.acme))

        OpportunityStage.objects.create(
            name="Prospecting", order=1, probability=10, company=self.acme
        )

        self.assertTrue(self._done(self.acme))
        self.assertFalse(self._done(self.beta))

    def test_step_sits_between_lead_stages_and_import_leads(self):
        """Order: ... Lead Stages, Opportunity Stages, Import Leads."""
        keys = [s["key"] for s in build_onboarding(self.admin, self.acme)["steps"]]
        self.assertEqual(
            keys[keys.index("lead_stages") :],
            ["lead_stages", "opportunity_stages", "leads"],
        )
