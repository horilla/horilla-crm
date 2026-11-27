"""
Lead integration tests for the optional ``horilla.contrib.field_management`` app.

Lead opts in to form layouts from ``horilla_crm/leads/registration.py``. The
app's generic behaviour is tested in the app itself; these tests cover what is
specific to Lead: the opt-in, the create form the editor lists, and the lead
create, edit and duplicate flows. They are skipped when the app is not
installed.
"""

# Standard library imports
import re
from importlib import import_module
from unittest import skipUnless

# Third-party imports (Django)
from django.apps import apps as django_apps
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.test import SimpleTestCase, TestCase
from login_history.models import post_login, post_logout

# First party imports (Horilla)
from horilla.apps import apps
from horilla.auth.models import User
from horilla.contrib.core.models import Company, HorillaContentType
from horilla.contrib.utils.middlewares import _thread_local
from horilla.urls import reverse

FORM_LAYOUTS_INSTALLED = django_apps.is_installed("horilla.contrib.field_management")
FIELD_REQUIREMENTS_INSTALLED = django_apps.is_installed(
    "horilla.contrib.field_management"
)
SKIP_REASON = "horilla.contrib.field_management is not installed"


def _form_layouts(module):
    """Import a form_layouts module only once the app is known to be installed."""
    return import_module(f"horilla.contrib.field_management.{module}.form_layouts")


@skipUnless(FORM_LAYOUTS_INSTALLED, SKIP_REASON)
class LeadFormLayoutRegistrationTests(SimpleTestCase):
    """Lead's opt-in, next to Lead's registration."""

    def test_lead_opts_in_to_form_layouts(self):
        """leads/registration.py lists the form_layouts feature for Lead."""
        lead = apps.get_model("leads", "Lead")

        self.assertTrue(_form_layouts("registry").is_layout_configurable(lead))

    def test_lead_status_does_not_opt_in(self):
        """Only Lead itself is configurable, not its stage model."""
        lead_status = apps.get_model("leads", "LeadStatus")

        self.assertFalse(_form_layouts("registry").is_layout_configurable(lead_status))

    def test_editor_uses_the_lead_single_page_form(self):
        """The Lead wizard's single-page counterpart provides the editor's fields."""
        # Local imports
        from horilla_crm.leads.forms import LeadSingleForm

        lead = apps.get_model("leads", "Lead")
        form_class = _form_layouts("utils").get_create_form_class(lead)

        self.assertTrue(issubclass(form_class, LeadSingleForm))


@skipUnless(FORM_LAYOUTS_INSTALLED, SKIP_REASON)
class LeadCreateFormLayoutTests(TestCase):
    """HTTP tests: a saved Lead layout trims lead creation only."""

    @classmethod
    def setUpClass(cls):
        """Disconnect the login/logout signals so the test client can log in without a user agent."""
        super().setUpClass()
        # django-login-history reads request.META['HTTP_USER_AGENT'] on
        # login/logout, which the test client does not send.
        user_logged_in.disconnect(post_login)
        user_logged_out.disconnect(post_logout)

    @classmethod
    def tearDownClass(cls):
        """Reconnect the login/logout signals so other tests are not affected."""
        user_logged_in.connect(post_login)
        user_logged_out.connect(post_logout)
        super().tearDownClass()

    def setUp(self):
        """Create a company, a superuser, a lead and an activity related to that lead."""
        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        self.other_company = Company.objects.create(
            name="Other", email="other@example.com", country="GB"
        )
        self.user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
            company=self.company,
        )
        self.lead = apps.get_model("leads", "Lead")
        self.lead_ct = HorillaContentType.objects.get_for_model(self.lead)
        self.layout_field = apps.get_model("field_management", "FormLayoutField")
        self.status = apps.get_model("leads", "LeadStatus").objects.create(
            name="New", order=1, probability=10, company=self.company
        )
        self.client.force_login(self.user)

    def tearDown(self):
        """Clear the thread-local request so other tests are not affected."""
        if hasattr(_thread_local, "request"):
            del _thread_local.request
        super().tearDown()

    def _htmx(self):
        return {"HTTP_HX_REQUEST": "true"}

    def _hide(self, field_name, *, company=None):
        return self.layout_field.all_objects.create(
            content_type=self.lead_ct,
            field_name=field_name,
            sequence=1,
            is_visible=False,
            company=company or self.company,
        )

    def _create(self):
        return self.client.get(
            f"{reverse('leads:leads_create')}?new=true", **self._htmx()
        )

    def _payload(self, **overrides):
        payload = {
            "lead_owner": self.user.pk,
            "title": "Prospect",
            "first_name": "Grace",
            "last_name": "Hopper",
            "email": "grace@example.com",
            "lead_source": "website",
            "lead_status": self.status.pk,
            "lead_company": "Navy",
            "industry": "education",
            "country": "US",
        }
        payload.update(overrides)
        return payload

    def _existing_lead(self):
        return self.lead.all_objects.create(
            lead_owner=self.user,
            first_name="Ada",
            last_name="Lovelace",
            email="ada@example.com",
            lead_source="website",
            lead_status=self.status,
            lead_company="Analytical Engines",
            industry="education",
            country="US",
            city="Paris",
            company=self.company,
        )

    def test_create_button_opens_the_wizard_without_a_layout(self):
        """Nothing changes for Lead until a layout is saved."""
        self.assertContains(self._create(), 'id="lead-form-view-multi-container"')

    def test_create_button_still_opens_the_wizard_with_a_layout(self):
        """A saved layout never redirects the create button; it stays the wizard."""
        self._hide("city")
        response = self._create()

        self.assertContains(response, 'id="lead-form-view-multi-container"')
        self.assertContains(response, 'name="city"')
        self.assertContains(response, "Custom Layout")

    def test_custom_layout_mode_opens_the_trimmed_single_form(self):
        """Following the Custom Layout mode link renders the trimmed form."""
        self._hide("city")
        response = self.client.get(
            f"{reverse('leads:leads_create_single')}?form_layout=1", **self._htmx()
        )

        self.assertContains(response, 'id="lead-form-view-container"')
        self.assertContains(response, 'name="first_name"')
        self.assertNotContains(response, 'name="city"')

    def test_only_custom_layout_mode_is_active_once_followed(self):
        """
        Lead declares its own Single-Step/Multi-Step form_mode; following
        Custom Layout must not leave one of those marked active too.
        """
        self._hide("city")
        response = self.client.get(
            f"{reverse('leads:leads_create_single')}?form_layout=1", **self._htmx()
        )
        content = response.content.decode()

        active_titles = re.findall(
            r"text-white bg-primary-600[^>]*>\s*([^<]+?)\s*</a>", content
        )
        self.assertEqual(active_titles, ["Custom Layout"])

    def test_layout_of_another_company_does_not_apply(self):
        """Lead layouts are per company."""
        self._hide("city", company=self.other_company)

        response = self.client.get(
            f"{reverse('leads:leads_create_single')}?form_layout=1", **self._htmx()
        )
        self.assertContains(response, 'name="city"')

    def test_trimmed_form_creates_the_lead(self):
        """Posting the trimmed form saves the lead with the hidden field empty."""
        self._hide("city")
        response = self.client.post(
            reverse("leads:leads_create_single"), self._payload(), **self._htmx()
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("HX-Redirect", response)
        self.assertEqual(self.lead.all_objects.get(email="grace@example.com").city, "")

    def test_lead_stage_cannot_be_hidden(self):
        """A non-nullable key like Lead Stage stays on the form."""
        self._hide("lead_status")

        self.assertContains(self._create(), 'name="lead_status"')

    @skipUnless(
        FIELD_REQUIREMENTS_INSTALLED, "horilla.contrib.field_management not installed"
    )
    def test_email_is_optional_so_a_layout_can_hide_it_until_it_is_required(self):
        """Email is optional, so the layout hides it; Field Requirements bring it back."""

        def _custom_layout():
            return self.client.get(
                f"{reverse('leads:leads_create_single')}?form_layout=1",
                **self._htmx(),
            )

        self._hide("email")
        self.assertNotContains(_custom_layout(), 'name="email"')
        post = self.client.post(
            reverse("leads:leads_create_single"),
            self._payload(email="", last_name="Without Email"),
            **self._htmx(),
        )
        self.assertIn("HX-Redirect", post)
        self.assertTrue(
            self.lead.all_objects.filter(last_name="Without Email").exists()
        )

        apps.get_model("field_management", "FieldRequirement").objects.create(
            content_type=self.lead_ct,
            field_name="email",
            is_required=True,
            company=self.company,
        )
        self.assertContains(_custom_layout(), 'name="email"')

    def test_edit_forms_show_every_field(self):
        """Lead edit forms are not affected by the layout."""
        self._hide("city")
        lead = self._existing_lead()

        single = self.client.get(
            reverse("leads:leads_edit_single", kwargs={"pk": lead.pk}), **self._htmx()
        )
        wizard = self.client.get(
            reverse("leads:leads_edit", kwargs={"pk": lead.pk}), **self._htmx()
        )

        self.assertContains(single, 'name="city"')
        self.assertContains(wizard, 'id="lead-form-view-multi-container"')

    def test_duplicate_form_shows_every_field(self):
        """Duplicating a lead keeps all of its copied values."""
        self._hide("city")
        lead = self._existing_lead()
        url = reverse("leads:leads_edit_single", kwargs={"pk": lead.pk})
        response = self.client.get(f"{url}?duplicate=true", **self._htmx())

        self.assertContains(response, 'name="city"')

    def test_settings_editor_lists_lead_fields(self):
        """The settings editor offers Lead with its create form fields."""
        response = self.client.get(
            f"{reverse('field_management:form_layout_editor')}?model={self.lead_ct.pk}",
            **self._htmx(),
        )

        self.assertContains(response, 'data-field="first_name"')
        self.assertContains(response, 'data-field="lead_company"')
        self.assertNotContains(response, 'data-field="lead_score"')
