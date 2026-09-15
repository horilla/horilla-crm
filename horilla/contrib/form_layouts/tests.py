"""
Tests for the form layouts app.

Covers feature-registry opt-in, how a saved layout is resolved per company,
the rules deciding which fields may be left off a create form, the helpers
behind the settings editor, and the view hooks that apply a layout to real
create requests while leaving edit and duplicate requests alone.
"""

# Standard library imports
from pathlib import Path

# Third-party imports (Django)
from django.conf import settings
from django.contrib.auth.models import AnonymousUser, Permission
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.test import RequestFactory, SimpleTestCase, TestCase
from login_history.models import post_login, post_logout

# First party imports (Horilla)
from horilla.apps import apps
from horilla.auth.models import User
from horilla.contrib.core.models import Company, HorillaContentType
from horilla.contrib.field_requirements.models import FieldRequirement
from horilla.contrib.form_layouts.models import FormLayoutField
from horilla.contrib.form_layouts.registry import (
    REGISTRY_KEY,
    get_configurable_models,
    is_layout_configurable,
)
from horilla.contrib.form_layouts.utils import (
    FormLayout,
    apply_form_layout,
    build_layout_entries,
    clear_form_layout_cache,
    get_create_form_class,
    get_form_layout,
    reset_form_layout,
    save_form_layout,
)
from horilla.contrib.generics.views.multi_form import HorillaMultiStepFormView
from horilla.contrib.generics.views.single_form import HorillaSingleFormView
from horilla.contrib.utils.middlewares import _thread_local
from horilla.extension.forms.bootstrap import apply_form_extensions
from horilla.registry.feature import FEATURE_CONFIG, FEATURE_REGISTRY
from horilla.urls import reverse


def _activate_company(company, user=None):
    """Point CompanyFilteredManager and form code at ``company`` for this thread."""
    request = RequestFactory().get("/")
    request.active_company = company
    request.session = {}
    request.user = user if user is not None else AnonymousUser()
    _thread_local.request = request


def _clear_thread_request():
    if hasattr(_thread_local, "request"):
        del _thread_local.request


class FeatureRegistrationTests(SimpleTestCase):
    """Tests that form layouts is a selective feature."""

    def test_feature_is_registered(self):
        """The contrib app registers the feature against the shared registry."""
        self.assertEqual(FEATURE_CONFIG.get("form_layouts"), REGISTRY_KEY)

    def test_lead_and_opportunity_opt_in(self):
        """Lead and Opportunity are the models that opted in."""
        lead = apps.get_model("leads", "Lead")
        opportunity = apps.get_model("opportunities", "Opportunity")
        registered = FEATURE_REGISTRY.get(REGISTRY_KEY, [])

        self.assertIn(lead, registered)
        self.assertIn(opportunity, registered)
        self.assertIn(lead, get_configurable_models())

    def test_all_true_models_do_not_opt_in_automatically(self):
        """Account uses all=True but must not become configurable."""
        account = apps.get_model("accounts", "Account")
        self.assertFalse(is_layout_configurable(account))
        self.assertFalse(is_layout_configurable(object()))

    def test_view_hooks_are_installed(self):
        """The generic form views are wrapped once when the app loads."""
        self.assertTrue(
            hasattr(HorillaSingleFormView, "_form_layouts_original_get_form")
        )
        self.assertTrue(hasattr(HorillaMultiStepFormView, "_form_layouts_original_get"))


class LayoutResolutionTests(TestCase):
    """Tests for get_form_layout."""

    def setUp(self):
        self.company_a = Company.objects.create(
            name="Company A", email="a@example.com", country="US"
        )
        self.company_b = Company.objects.create(
            name="Company B", email="b@example.com", country="GB"
        )
        self.lead = apps.get_model("leads", "Lead")
        self.lead_ct = HorillaContentType.objects.get_for_model(self.lead)
        _activate_company(self.company_a)

    def tearDown(self):
        _clear_thread_request()
        super().tearDown()

    def _row(self, field_name, sequence, is_visible=True, company=None, **kwargs):
        return FormLayoutField.objects.create(
            content_type=self.lead_ct,
            field_name=field_name,
            sequence=sequence,
            is_visible=is_visible,
            company=company or self.company_a,
            **kwargs,
        )

    def test_model_without_rows_has_no_layout(self):
        """Nothing changes until a layout has been saved."""
        self.assertIsNone(get_form_layout(self.lead))

    def test_unregistered_model_has_no_layout(self):
        """Models that did not opt in are never looked up."""
        self.assertIsNone(get_form_layout(apps.get_model("accounts", "Account")))
        self.assertIsNone(get_form_layout(None))

    def test_rows_become_an_ordered_layout(self):
        """Rows are ordered by sequence and invisible ones are collected."""
        self._row("last_name", 2)
        self._row("fax", 3, is_visible=False)
        self._row("first_name", 1)

        layout = get_form_layout(self.lead)

        self.assertEqual(layout.order, ("first_name", "last_name", "fax"))
        self.assertEqual(layout.hidden, frozenset({"fax"}))

    def test_layout_is_scoped_to_the_active_company(self):
        """Another company's layout never applies."""
        self._row("fax", 1, is_visible=False, company=self.company_b)
        self.assertIsNone(get_form_layout(self.lead))

        _activate_company(self.company_b)
        self.assertEqual(get_form_layout(self.lead).hidden, frozenset({"fax"}))

    def test_inactive_rows_are_ignored(self):
        """Archived rows do not form a layout."""
        self._row("fax", 1, is_visible=False, is_active=False)
        self.assertIsNone(get_form_layout(self.lead))

    def test_layout_is_cached_on_the_request(self):
        """A second lookup in the same request does not see later writes."""
        self.assertIsNone(get_form_layout(self.lead))
        self._row("fax", 1, is_visible=False)
        self.assertIsNone(get_form_layout(self.lead))

        clear_form_layout_cache()
        self.assertIsNotNone(get_form_layout(self.lead))


class ApplyFormLayoutTests(TestCase):
    """Tests for apply_form_layout on the real Lead create form."""

    def setUp(self):
        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        self.user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
            company=self.company,
        )
        self.lead = apps.get_model("leads", "Lead")
        self.status = apps.get_model("leads", "LeadStatus").objects.create(
            name="New", order=1, probability=10, company=self.company
        )
        _activate_company(self.company, self.user)
        apply_form_extensions(force=True)

    def tearDown(self):
        _clear_thread_request()
        super().tearDown()

    def _form(self, data=None):
        form_class = get_create_form_class(self.lead)
        return form_class(data=data, request=_thread_local.request)

    def _layout(self, order=(), hidden=()):
        return FormLayout(order=tuple(order), hidden=frozenset(hidden))

    def test_hidden_optional_field_is_removed(self):
        """An optional field marked hidden is left off the form."""
        form = self._form()
        removed = apply_form_layout(form, self._layout(hidden={"fax", "city"}))

        self.assertCountEqual(removed, ["fax", "city"])
        self.assertNotIn("fax", form.fields)
        self.assertNotIn("city", form.fields)

    def test_required_field_is_never_removed(self):
        """A required field stays even when the layout hides it."""
        form = self._form()
        apply_form_layout(form, self._layout(hidden={"first_name", "lead_status"}))

        self.assertIn("first_name", form.fields)
        self.assertIn("lead_status", form.fields)

    def test_field_made_optional_by_field_requirements_can_be_hidden(self):
        """Email becomes hideable once Field Requirements relaxes it."""
        FieldRequirement.objects.create(
            content_type=HorillaContentType.objects.get_for_model(self.lead),
            field_name="email",
            is_required=False,
            company=self.company,
        )
        form = self._form()
        apply_form_layout(form, self._layout(hidden={"email"}))

        self.assertNotIn("email", form.fields)

    def test_protected_field_is_kept(self):
        """Names the view protects (e.g. pre-filled values) are not removed."""
        form = self._form()
        apply_form_layout(form, self._layout(hidden={"fax"}), protected={"fax"})

        self.assertIn("fax", form.fields)

    def test_unknown_names_are_ignored(self):
        """Stale rows for fields the form no longer has are harmless."""
        form = self._form()
        before = list(form.fields)
        apply_form_layout(form, self._layout(order=("gone",), hidden={"gone"}))

        self.assertEqual(list(form.fields), before)

    def test_fields_follow_the_layout_order(self):
        """Ordered fields come first; the rest keep their relative order."""
        form = self._form()
        before = [name for name in form.fields if name not in {"email", "last_name"}]
        apply_form_layout(form, self._layout(order=("email", "last_name")))

        self.assertEqual(list(form.fields)[:2], ["email", "last_name"])
        self.assertEqual(list(form.fields)[2:], before)

    def test_trimmed_form_still_validates_and_saves(self):
        """Leaving optional fields out does not break the create."""
        data = {
            "lead_owner": self.user.pk,
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
            "lead_source": "website",
            "lead_status": self.status.pk,
            "lead_company": "Analytical Engines",
            "industry": "education",
            "country": "US",
        }
        form = self._form(data=data)
        apply_form_layout(
            form, self._layout(hidden={"fax", "city", "zip_code", "requirements"})
        )

        self.assertTrue(form.is_valid(), form.errors)
        lead = form.save(commit=False)
        lead.company = self.company
        lead.save()
        self.assertEqual(lead.fax, "")
        self.assertEqual(lead.city, "")


class LayoutEditorHelperTests(TestCase):
    """Tests for the helpers behind the settings editor."""

    def setUp(self):
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
        _activate_company(self.company, self.user)
        apply_form_extensions(force=True)

    def tearDown(self):
        _clear_thread_request()
        super().tearDown()

    def _entries(self):
        return {entry.name: entry for entry in build_layout_entries(self.lead)}

    def test_create_form_class_is_the_lead_single_form(self):
        """The single-page form is preferred over the multi-step wizard."""
        # Local imports
        from horilla_crm.leads.forms import LeadSingleForm

        self.assertTrue(issubclass(get_create_form_class(self.lead), LeadSingleForm))

    def test_entries_describe_the_create_form(self):
        """Every visible field is listed with its requiredness."""
        entries = self._entries()

        self.assertTrue(entries["first_name"].required)
        self.assertFalse(entries["fax"].required)
        self.assertTrue(all(entry.visible for entry in entries.values()))
        self.assertNotIn("lead_score", entries)

    def test_save_orders_fields_and_forces_required_ones_visible(self):
        """Required fields cannot be stored as hidden."""
        saved = save_form_layout(
            self.lead,
            ordered_names=["email", "first_name", "fax"],
            visible_names=["email"],
            company=self.company,
        )
        by_name = {entry.name: entry for entry in saved}

        self.assertEqual(
            [entry.name for entry in saved][:3], ["email", "first_name", "fax"]
        )
        self.assertTrue(by_name["first_name"].visible)
        self.assertFalse(by_name["fax"].visible)
        row = FormLayoutField.objects.get(
            content_type=self.lead_ct, field_name="first_name"
        )
        self.assertTrue(row.is_visible)
        self.assertEqual(row.sequence, 2)

    def test_save_ignores_unknown_names_and_drops_stale_rows(self):
        """Only fields on the form are stored."""
        FormLayoutField.objects.create(
            content_type=self.lead_ct,
            field_name="removed_field",
            company=self.company,
        )
        save_form_layout(
            self.lead,
            ordered_names=["not_a_field", "fax"],
            visible_names=["not_a_field"],
            company=self.company,
        )
        names = set(
            FormLayoutField.objects.filter(content_type=self.lead_ct).values_list(
                "field_name", flat=True
            )
        )

        self.assertNotIn("not_a_field", names)
        self.assertNotIn("removed_field", names)
        self.assertIn("fax", names)
        self.assertEqual(names, set(self._entries()))

    def test_save_and_reset_only_touch_the_given_company(self):
        """Resetting one company leaves another company's layout alone."""
        save_form_layout(self.lead, ["fax"], [], company=self.company)
        FormLayoutField.all_objects.create(
            content_type=self.lead_ct,
            field_name="fax",
            is_visible=False,
            company=self.other_company,
        )

        reset_form_layout(self.lead, self.company)

        self.assertFalse(
            FormLayoutField.all_objects.filter(company=self.company).exists()
        )
        self.assertTrue(
            FormLayoutField.all_objects.filter(company=self.other_company).exists()
        )
        self.assertIsNone(get_form_layout(self.lead))


class CreateViewHookTests(TestCase):
    """HTTP tests: a saved layout changes create requests only."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # django-login-history reads request.META['HTTP_USER_AGENT'] on
        # login/logout, which the test client does not send.
        user_logged_in.disconnect(post_login)
        user_logged_out.disconnect(post_logout)

    @classmethod
    def tearDownClass(cls):
        user_logged_in.connect(post_login)
        user_logged_out.connect(post_logout)
        super().tearDownClass()

    def setUp(self):
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
        self.opportunity = apps.get_model("opportunities", "Opportunity")
        self.lead_ct = HorillaContentType.objects.get_for_model(self.lead)
        self.status = apps.get_model("leads", "LeadStatus").objects.create(
            name="New", order=1, probability=10, company=self.company
        )
        self.client.force_login(self.user)

    def tearDown(self):
        _clear_thread_request()
        super().tearDown()

    def _htmx(self):
        return {"HTTP_HX_REQUEST": "true"}

    def _hide(self, field_name, *, model_ct=None, company=None):
        return FormLayoutField.all_objects.create(
            content_type=model_ct or self.lead_ct,
            field_name=field_name,
            sequence=1,
            is_visible=False,
            company=company or self.company,
        )

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

    def test_wizard_opens_when_there_is_no_layout(self):
        """Without a layout the create button keeps opening the wizard."""
        response = self.client.get(
            f"{reverse('leads:leads_create')}?new=true", **self._htmx()
        )

        self.assertContains(response, 'id="lead-form-view-multi-container"')

    def test_create_opens_the_trimmed_single_form_when_a_layout_exists(self):
        """The create button renders the single-page form without hidden fields."""
        self._hide("city")
        response = self.client.get(
            f"{reverse('leads:leads_create')}?new=true", **self._htmx()
        )

        self.assertContains(response, 'id="lead-form-view-container"')
        self.assertNotContains(response, 'id="lead-form-view-multi-container"')
        self.assertContains(response, 'name="first_name"')
        self.assertNotContains(response, 'name="city"')
        self.assertNotContains(response, "Multi-Step Form")
        self.assertContains(response, reverse("leads:leads_create_single"))

    def test_layout_of_another_company_does_not_apply(self):
        """Layouts are per company."""
        self._hide("city", company=self.other_company)
        response = self.client.get(
            f"{reverse('leads:leads_create')}?new=true", **self._htmx()
        )

        self.assertContains(response, 'id="lead-form-view-multi-container"')

    def test_single_create_post_saves_without_hidden_fields(self):
        """Posting the trimmed form creates the lead."""
        self._hide("city")
        response = self.client.post(
            reverse("leads:leads_create_single"),
            {
                "lead_owner": self.user.pk,
                "first_name": "Grace",
                "last_name": "Hopper",
                "email": "grace@example.com",
                "lead_source": "website",
                "lead_status": self.status.pk,
                "lead_company": "Navy",
                "industry": "education",
                "country": "US",
            },
            **self._htmx(),
        )

        self.assertEqual(response.status_code, 200)
        lead = self.lead.all_objects.get(email="grace@example.com")
        self.assertEqual(lead.city, "")
        self.assertIn("HX-Redirect", response)

    def test_edit_forms_show_every_field(self):
        """Neither edit form is affected by the layout."""
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
        """Duplicating a record keeps all of its copied values."""
        self._hide("city")
        lead = self._existing_lead()
        response = self.client.get(
            f"{reverse('leads:leads_edit_single', kwargs={'pk': lead.pk})}?duplicate=true",
            **self._htmx(),
        )

        self.assertContains(response, 'name="city"')

    def test_opportunity_create_opens_the_trimmed_single_form(self):
        """The same hook works for Opportunity."""
        self._hide(
            "next_step",
            model_ct=HorillaContentType.objects.get_for_model(self.opportunity),
        )
        response = self.client.get(
            f"{reverse('opportunities:opportunity_create')}?new=true", **self._htmx()
        )

        self.assertContains(response, 'id="opportunity-form-view-container"')
        self.assertContains(response, 'name="name"')
        self.assertNotContains(response, 'name="next_step"')


class FormLayoutSettingsViewTests(TestCase):
    """HTTP tests for the settings page, editor, save and reset."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        user_logged_in.disconnect(post_login)
        user_logged_out.disconnect(post_logout)

    @classmethod
    def tearDownClass(cls):
        user_logged_in.connect(post_login)
        user_logged_out.connect(post_logout)
        super().tearDownClass()

    def setUp(self):
        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        self.user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
            company=self.company,
        )
        self.lead = apps.get_model("leads", "Lead")
        self.opportunity = apps.get_model("opportunities", "Opportunity")
        self.lead_ct = HorillaContentType.objects.get_for_model(self.lead)
        self.opportunity_ct = HorillaContentType.objects.get_for_model(self.opportunity)
        self.client.force_login(self.user)

    def tearDown(self):
        _clear_thread_request()
        super().tearDown()

    def _htmx(self):
        return {"HTTP_HX_REQUEST": "true"}

    def _staff(self, *codenames):
        staff = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="pass",
            company=self.company,
        )
        for codename in codenames:
            staff.user_permissions.add(
                Permission.objects.get(
                    content_type__app_label="form_layouts", codename=codename
                )
            )
        return staff

    def test_anonymous_user_is_sent_to_login(self):
        """The settings page requires an authenticated user."""
        self.client.logout()
        response = self.client.get(reverse("form_layouts:form_layout_view"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_user_without_permission_is_denied(self):
        """View permission is required to open the settings page."""
        self.client.force_login(self._staff())
        response = self.client.get(reverse("form_layouts:form_layout_view"))

        self.assertContains(response, "Permission Denied")

    def test_settings_page_opens_read_only(self):
        """The page lists the fields without letting them change until Edit."""
        response = self.client.get(reverse("form_layouts:form_layout_view"))

        self.assertContains(response, 'id="form-layout-view"')
        self.assertContains(response, 'id="form-layout-editor"')
        self.assertContains(response, 'data-field="first_name"')
        self.assertContains(response, "Default form in use")
        self.assertContains(response, "Edit Layout")
        self.assertContains(response, f"?model={self.lead_ct.pk}&mode=edit")
        self.assertNotContains(response, 'name="field_order"')
        self.assertNotContains(response, 'name="visible"')
        self.assertNotContains(response, "Save Layout")

    def test_edit_mode_renders_the_sortable_form(self):
        """Edit mode has the drag handles, switches, arrows and save button."""
        response = self.client.get(
            f"{reverse('form_layouts:form_layout_editor')}?model={self.lead_ct.pk}&mode=edit",
            **self._htmx(),
        )

        self.assertContains(response, 'id="form-layout-form"')
        self.assertContains(response, 'name="field_order" value="first_name"')
        content = response.content.decode()
        # Optional fields get a visibility switch; required ones only a lock.
        self.assertRegex(content, r'name="visible"\s+value="city"')
        self.assertNotRegex(content, r'name="visible"\s+value="first_name"')
        # The sr-only checkbox must sit in a positioned label so it scrolls with
        # its row; otherwise clicking a switch scrolls the whole page.
        self.assertRegex(
            content,
            r'<label class="relative [^"]*"[^>]*>\s*<input\s+type="checkbox"',
        )
        self.assertContains(response, "fa-grip-vertical")
        self.assertContains(response, 'data-layout-move="up"')
        self.assertContains(response, "data-layout-cancel")
        self.assertContains(response, "Save Layout")
        self.assertNotContains(response, "Edit Layout")
        # The drag handle must not be a natively draggable image.
        self.assertNotContains(response, "drag.svg")

    def test_viewer_cannot_open_edit_mode(self):
        """Without change permission, mode=edit falls back to the read-only view."""
        self.client.force_login(self._staff("view_formlayoutfield"))
        response = self.client.get(
            f"{reverse('form_layouts:form_layout_editor')}?model={self.lead_ct.pk}&mode=edit",
            **self._htmx(),
        )

        self.assertContains(response, 'data-field="first_name"')
        self.assertNotContains(response, 'name="field_order"')
        self.assertNotContains(response, "Edit Layout")

    def test_settings_menu_links_to_the_page(self):
        """The settings sidebar includes the Create Form Layout entry."""
        response = self.client.get(reverse("form_layouts:form_layout_view"))

        self.assertContains(response, "form-layout.svg")

    def test_editor_switches_to_opportunity(self):
        """The model buttons swap in another model's fields."""
        response = self.client.get(
            f"{reverse('form_layouts:form_layout_editor')}?model={self.opportunity_ct.pk}",
            **self._htmx(),
        )

        self.assertContains(response, 'data-field="next_step"')
        self.assertNotContains(response, 'data-field="lead_company"')
        self.assertNotContains(response, 'name="field_order"')

    def test_save_stores_the_layout_and_create_uses_it(self):
        """Saving from the editor changes the create button's form."""
        response = self.client.post(
            reverse("form_layouts:form_layout_save"),
            {
                "model": self.lead_ct.pk,
                "field_order": ["email", "first_name", "city"],
                "visible": ["email", "first_name"],
            },
            **self._htmx(),
        )

        self.assertContains(response, "Custom layout: Create opens a single-page form")
        self.assertContains(response, "Create form layout saved.")
        self.assertNotContains(response, 'name="field_order"')
        row = FormLayoutField.objects.get(content_type=self.lead_ct, field_name="city")
        self.assertFalse(row.is_visible)
        self.assertEqual(
            FormLayoutField.objects.get(
                content_type=self.lead_ct, field_name="email"
            ).sequence,
            1,
        )

        create = self.client.get(
            f"{reverse('leads:leads_create')}?new=true", **self._htmx()
        )
        self.assertContains(create, 'id="lead-form-view-container"')
        self.assertNotContains(create, 'name="city"')

    def test_save_rejects_an_unknown_model(self):
        """A write never falls back to another model."""
        response = self.client.post(
            reverse("form_layouts:form_layout_save"),
            {"model": "999999", "field_order": ["city"]},
            **self._htmx(),
        )

        self.assertContains(response, "Select a valid model.")
        self.assertFalse(FormLayoutField.all_objects.exists())

    def test_save_requires_change_permission(self):
        """A viewer cannot store a layout."""
        self.client.force_login(self._staff("view_formlayoutfield"))
        response = self.client.post(
            reverse("form_layouts:form_layout_save"),
            {"model": self.lead_ct.pk, "field_order": ["city"]},
            **self._htmx(),
        )

        self.assertContains(response, "Permission Denied")
        self.assertFalse(FormLayoutField.all_objects.exists())

    def test_viewer_sees_a_read_only_editor(self):
        """Without change permission the editor offers no way to edit."""
        self.client.force_login(self._staff("view_formlayoutfield"))
        response = self.client.get(reverse("form_layouts:form_layout_view"))

        self.assertContains(response, 'id="form-layout-editor"')
        self.assertNotContains(response, "Edit Layout")
        self.assertNotContains(response, "Save Layout")

    def test_reset_removes_the_layout(self):
        """Resetting brings back the default wizard."""
        FormLayoutField.all_objects.create(
            content_type=self.lead_ct,
            field_name="city",
            is_visible=False,
            company=self.company,
        )
        response = self.client.post(
            reverse("form_layouts:form_layout_reset"),
            {"model": self.lead_ct.pk},
            **self._htmx(),
        )

        self.assertContains(response, "Default form in use")
        self.assertFalse(FormLayoutField.all_objects.exists())

    def test_write_endpoints_require_htmx_and_post(self):
        """Save only accepts HTMX POST requests."""
        get = self.client.get(reverse("form_layouts:form_layout_save"), **self._htmx())
        self.assertEqual(get.status_code, 405)


class IsolationFromPlatformTests(SimpleTestCase):
    """The feature lives in this app; platform sources stay untouched."""

    def test_generics_and_crm_sources_do_not_mention_form_layouts(self):
        """No generic view, form or CRM model file refers to this app."""
        base = Path(settings.BASE_DIR)
        paths = [
            base / "horilla" / "contrib" / "generics",
            base / "horilla_crm" / "leads" / "models",
            base / "horilla_crm" / "opportunities" / "models.py",
            base / "horilla_crm" / "leads" / "views",
            base / "horilla_crm" / "opportunities" / "views",
        ]
        for path in paths:
            files = [path] if path.is_file() else list(path.rglob("*.py"))
            for file in files:
                with self.subTest(file=str(file.relative_to(base))):
                    self.assertNotIn("form_layout", file.read_text(encoding="utf-8"))
