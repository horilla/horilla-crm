"""
Tests for the CRM steps of the home page onboarding guide.

The dashboard app owns the guide but must not depend on ``horilla_crm``, so the
tests that need leads or lead stages live here.
"""

# Third-party imports (Django)
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.test import TestCase
from login_history.models import post_login, post_logout

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.models import Company
from horilla.contrib.dashboard.models import OnboardingState
from horilla.registry.onboarding import build_onboarding
from horilla.urls import reverse
from horilla_crm.leads.models import Lead, LeadStatus
from horilla_crm.leads.onboarding import ImportLeadsOnboarding, LeadStagesOnboarding


class CrmOnboardingTests(TestCase):
    """Lead stages and leads are counted per company."""

    @classmethod
    def setUpClass(cls):
        """Disconnect the login/logout signals so the test client can log in without a user agent."""
        super().setUpClass()
        user_logged_in.disconnect(post_login)
        user_logged_out.disconnect(post_logout)

    @classmethod
    def tearDownClass(cls):
        """Reconnect the login/logout signals so other tests are not affected."""
        user_logged_in.connect(post_login)
        user_logged_out.connect(post_logout)
        super().tearDownClass()

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

    def _done(self, step_cls, company):
        instance = step_cls()
        return instance.is_done(company, self.admin)

    def test_steps_are_registered_in_the_agreed_order(self):
        """Company, Roles, Users, Mail Server, Lead Stages, Opportunity Stages, Import Leads."""
        keys = [s["key"] for s in build_onboarding(self.admin, self.acme)["steps"]]
        self.assertEqual(
            keys,
            [
                "company",
                "roles",
                "users",
                "mail_server",
                "lead_stages",
                "opportunity_stages",
                "leads",
            ],
        )

    def test_lead_stage_step_is_done_only_in_the_company_that_has_one(self):
        """A lead stage in Acme does not complete the step for Beta."""
        LeadStatus.objects.create(name="New", probability=10, company=self.acme)

        self.assertTrue(self._done(LeadStagesOnboarding, self.acme))
        self.assertFalse(self._done(LeadStagesOnboarding, self.beta))

    def test_import_leads_step_is_done_only_in_the_company_that_has_a_lead(self):
        """A lead in Acme does not complete the step for Beta."""
        status = LeadStatus.objects.create(
            name="New", probability=10, company=self.acme
        )
        Lead.objects.create(
            first_name="Ada",
            last_name="Lovelace",
            email="ada@example.com",
            lead_company="Prospect Pioneers",
            lead_source="website",
            industry="technology",
            lead_owner=self.admin,
            lead_status=status,
            company=self.acme,
        )

        self.assertTrue(self._done(ImportLeadsOnboarding, self.acme))
        self.assertFalse(self._done(ImportLeadsOnboarding, self.beta))

    def test_progress_follows_each_companys_own_data(self):
        """Acme has a lead stage, Beta has nothing."""
        LeadStatus.objects.create(name="New", probability=10, company=self.acme)

        acme = build_onboarding(self.admin, self.acme)
        beta = build_onboarding(self.admin, self.beta)

        # Company (required fields filled in), Users (the admin belongs to Acme) and
        # the lead stage are done in Acme; Beta only has its company profile.
        self.assertEqual(acme["done_count"], 3)
        self.assertEqual(beta["done_count"], 1)
        self.assertEqual(acme["next_step"]["key"], "roles")

    def test_home_page_shows_the_guide_per_company(self):
        """Dismissed in Acme shows the small link; Beta still shows the banner."""
        self.client.login(username="admin", password="pass")
        OnboardingState.set_hidden(self.acme, True)

        session = self.client.session
        session["active_company_id"] = self.acme.id
        session.save()
        acme_page = self.client.get(reverse("dashboard:home_view"), follow=True)
        self.assertContains(acme_page, "Show Setup Guide")
        self.assertNotContains(acme_page, f"Get started with {self.acme.name}")

        session["active_company_id"] = self.beta.id
        session.save()
        beta_page = self.client.get(reverse("dashboard:home_view"), follow=True)
        self.assertContains(beta_page, f"Get started with {self.beta.name}")
        self.assertNotContains(beta_page, "Show Setup Guide")
