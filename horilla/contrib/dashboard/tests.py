"""
Tests for the dashboard app.

Contains unit and integration tests for dashboard behavior and permissions.
"""

# Standard library imports
from unittest import mock

# Third-party imports (Django)
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.test import TestCase
from login_history.models import post_login, post_logout

# First party imports (Horilla)
from horilla.apps import apps
from horilla.auth.models import User
from horilla.contrib.core.models import Company
from horilla.registry.onboarding import OnboardingSteps, build_onboarding
from horilla.urls import reverse

# Local imports
from .models import OnboardingState


class _LoginSignalsDisabled(TestCase):
    """Base for tests that log in with the test client."""

    @classmethod
    def setUpClass(cls):
        """Disconnect the login/logout signals so the test client can log in without a user agent."""
        super().setUpClass()
        # django-login-history reads request.META['HTTP_USER_AGENT'] on
        # login/logout, which the test client's bare request doesn't set.
        user_logged_in.disconnect(post_login)
        user_logged_out.disconnect(post_logout)

    @classmethod
    def tearDownClass(cls):
        """Reconnect the login/logout signals so other tests are not affected."""
        user_logged_in.connect(post_login)
        user_logged_out.connect(post_logout)
        super().tearDownClass()


class OnboardingPerCompanyTests(_LoginSignalsDisabled):
    """The home page onboarding guide is tracked separately for every company."""

    def setUp(self):
        """Two companies and a superuser who can work in both."""
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
        self.client.login(username="admin", password="pass")

    def _work_in(self, company):
        session = self.client.session
        session["active_company_id"] = company.id
        session.save()

    def _set_hidden(self, hidden):
        name = "onboarding_hide" if hidden else "onboarding_show"
        return self.client.post(reverse(f"dashboard:{name}"), HTTP_HX_REQUEST="true")

    def test_guide_is_shown_by_default_in_every_company(self):
        """Nobody has touched the guide, so both companies show it."""
        for company in (self.acme, self.beta):
            self.assertFalse(OnboardingState.is_hidden_for(company))

    def test_hiding_in_one_company_leaves_the_other_company_showing(self):
        """Hide in Acme: Acme is hidden, Beta is untouched."""
        self._work_in(self.acme)
        self.assertEqual(self._set_hidden(True).status_code, 200)

        self.assertTrue(OnboardingState.is_hidden_for(self.acme))
        self.assertFalse(OnboardingState.is_hidden_for(self.beta))

    def test_choice_is_saved_for_the_active_company_only(self):
        """Switching company changes which company a click applies to."""
        self._work_in(self.acme)
        self._set_hidden(True)
        self._work_in(self.beta)
        self._set_hidden(False)

        self.assertTrue(OnboardingState.is_hidden_for(self.acme))
        self.assertFalse(OnboardingState.is_hidden_for(self.beta))
        self.assertEqual(OnboardingState.objects.count(), 2)

    def test_show_again_restores_only_that_company(self):
        """Hide in both companies, show again in Acme: Beta stays hidden."""
        for company in (self.acme, self.beta):
            self._work_in(company)
            self._set_hidden(True)

        self._work_in(self.acme)
        self._set_hidden(False)

        self.assertFalse(OnboardingState.is_hidden_for(self.acme))
        self.assertTrue(OnboardingState.is_hidden_for(self.beta))

    def test_choice_is_shared_by_the_companys_superusers(self):
        """A second superuser in the same company sees what the first one saved."""
        second = User.objects.create_superuser(
            username="second",
            email="second@example.com",
            password="pass",
            company=self.acme,
        )
        self._work_in(self.acme)
        self._set_hidden(True)

        self.assertTrue(OnboardingState.is_hidden_for(self.acme))
        self.client.force_login(second)
        self._work_in(self.acme)
        self.assertEqual(self._set_hidden(True).status_code, 200)
        self.assertEqual(OnboardingState.objects.count(), 1)

    def test_dismiss_response_removes_the_guide(self):
        """Dismissing leaves only the "Show Setup Guide" link; showing brings the banner back."""
        self._work_in(self.acme)

        hidden = self._set_hidden(True)
        self.assertNotContains(hidden, "Set Up Now")
        self.assertNotContains(hidden, "Skip For Now")
        self.assertContains(hidden, "Show Setup Guide")

        shown = self._set_hidden(False)
        self.assertContains(shown, f"Get started with {self.acme.name}")
        self.assertContains(shown, "Skip For Now")
        self.assertContains(shown, "Set Up Now")

    def test_skip_is_remembered_for_the_active_company_only(self):
        """Skipping a step in Acme does not skip it in Beta; an unknown step is refused."""
        self._work_in(self.acme)
        url = reverse("dashboard:onboarding_skip", args=["roles"])
        self.assertEqual(self.client.post(url, HTTP_HX_REQUEST="true").status_code, 200)
        self.assertEqual(
            self.client.session["onboarding_skipped"], {str(self.acme.pk): ["roles"]}
        )

        unknown = reverse("dashboard:onboarding_skip", args=["nope"])
        self.assertEqual(
            self.client.post(unknown, HTTP_HX_REQUEST="true").status_code, 400
        )

    def test_toggle_is_for_superusers_only(self):
        """A regular user cannot hide or show the guide."""
        regular = User.objects.create_user(
            username="regular",
            email="regular@example.com",
            password="pass",
            company=self.acme,
        )
        self.client.force_login(regular)
        self._work_in(self.acme)
        self.assertEqual(self._set_hidden(True).status_code, 403)
        self.assertEqual(OnboardingState.objects.count(), 0)

    def test_toggle_requires_login(self):
        """Anonymous requests are sent to the login page and change nothing."""
        self.client.logout()
        response = self._set_hidden(True)
        self.assertNotEqual(response.status_code, 200)
        self.assertEqual(OnboardingState.objects.count(), 0)

    def test_toggle_requires_htmx(self):
        """A plain browser request gets the project's 405 page and changes nothing."""
        self._work_in(self.acme)
        response = self.client.post(reverse("dashboard:onboarding_hide"))
        self.assertTemplateUsed(response, "405.html")
        self.assertTemplateNotUsed(response, "home/onboarding.html")
        self.assertEqual(OnboardingState.objects.count(), 0)


class OnboardingBuilderTests(TestCase):
    """What ``build_onboarding`` shows for a user in a company."""

    def setUp(self):
        """A company, a superuser and a user with no permissions."""
        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        self.admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
            company=self.company,
        )
        self.plain = User.objects.create_user(
            username="plain",
            email="plain@example.com",
            password="pass",
            company=self.company,
        )

    @staticmethod
    def _patched_steps(steps):
        return mock.patch(
            "horilla.registry.onboarding.get_onboarding_steps",
            return_value=[step() for step in steps],
        )

    @staticmethod
    def _step(key, done=False, **attrs):
        attrs.setdefault("url_name", "dashboard:home_view")
        attrs.update(
            key=key,
            title=key.title(),
            abstract=True,
            is_done=lambda self, company, user: done,
        )
        return type(f"Step{key}", (OnboardingSteps,), attrs)

    def test_only_superusers_get_a_guide(self):
        """A regular user gets no guide, whatever permissions they hold."""
        with self._patched_steps([self._step("open", permission=None)]):
            self.assertIsNone(build_onboarding(self.plain, self.company))
            self.assertIsNotNone(build_onboarding(self.admin, self.company))

    def test_step_without_permission_is_dropped_and_not_counted(self):
        """Steps the user cannot open are dropped from the list and the progress."""
        steps = [
            self._step("open", permission=None),
            self._step("locked", permission="core.view_company"),
        ]
        non_super = mock.Mock(is_superuser=True)
        non_super.has_perm.side_effect = lambda perm: False
        with self._patched_steps(steps):
            guide = build_onboarding(non_super, self.company)
            admin_guide = build_onboarding(self.admin, self.company)

        self.assertEqual([s["key"] for s in guide["steps"]], ["open"])
        self.assertEqual(guide["total"], 1)
        self.assertEqual([s["key"] for s in admin_guide["steps"]], ["open", "locked"])

    def test_all_done_means_no_guide(self):
        """Once everything visible is done the guide disappears."""
        done = [self._step("a", done=True), self._step("b", done=True)]
        with self._patched_steps(done):
            self.assertIsNone(build_onboarding(self.admin, self.company))

    def test_progress_and_next_step(self):
        """The next step is the first one that is not done."""
        steps = [
            self._step("a", done=True),
            self._step("b", done=False),
            self._step("c", done=False),
        ]
        with self._patched_steps(steps):
            guide = build_onboarding(self.admin, self.company)

        self.assertEqual(
            (guide["done_count"], guide["total"], guide["percent"]), (1, 3, 33)
        )
        self.assertEqual(guide["next_step"]["key"], "b")
        self.assertEqual([s["is_next"] for s in guide["steps"]], [False, True, False])

    def test_skipped_step_moves_the_guide_to_the_next_unfinished_step(self):
        """A skipped step leaves the next-step card but stays in the stepper."""
        steps = [
            self._step("a", done=True),
            self._step("b", done=False),
            self._step("c", done=False),
        ]
        with self._patched_steps(steps):
            guide = build_onboarding(self.admin, self.company, skipped=["b"])

        self.assertEqual(guide["next_step"]["key"], "c")
        self.assertEqual([s["key"] for s in guide["steps"]], ["a", "b", "c"])
        self.assertEqual([s["is_next"] for s in guide["steps"]], [False, False, True])
        self.assertEqual(guide["done_count"], 1)

    def test_skipping_every_unfinished_step_leaves_no_next_step(self):
        """With nothing left to offer the guide stays, without a next-step card."""
        steps = [self._step("a", done=True), self._step("b", done=False)]
        with self._patched_steps(steps):
            guide = build_onboarding(self.admin, self.company, skipped=["b"])

        self.assertIsNone(guide["next_step"])
        self.assertEqual(len(guide["steps"]), 2)

    def test_a_step_with_an_unresolvable_url_is_skipped(self):
        """A bad ``url_name`` is skipped instead of failing."""
        bad = self._step("bad", url_name="nope:missing")
        with self._patched_steps([bad, self._step("good")]):
            guide = build_onboarding(self.admin, self.company)

        self.assertEqual([s["key"] for s in guide["steps"]], ["good"])

    def test_no_company_means_no_guide(self):
        """A user without a company gets no guide."""
        self.assertIsNone(build_onboarding(self.admin, None))

    def test_basic_steps_show_when_horilla_crm_is_not_installed(self):
        """Without horilla_crm: no import errors, only the basic steps."""
        real = apps.get_containing_app_config

        def without_crm(module):
            return None if module.startswith("horilla_crm") else real(module)

        with mock.patch.object(
            apps, "get_containing_app_config", side_effect=without_crm
        ):
            guide = build_onboarding(self.admin, self.company)

        self.assertEqual(
            [s["key"] for s in guide["steps"]],
            ["company", "roles", "users", "mail_server"],
        )

    def test_installed_apps_contribute_their_steps_in_order(self):
        """Basic steps always show; CRM steps join them when horilla_crm is installed."""
        guide = build_onboarding(self.admin, self.company)
        crm_installed = any(
            config.name.startswith("horilla_crm") for config in apps.get_app_configs()
        )

        expected = ["company", "roles", "users", "mail_server"]
        if crm_installed:
            expected += ["lead_stages", "opportunity_stages", "leads"]
        self.assertEqual([s["key"] for s in guide["steps"]], expected)
