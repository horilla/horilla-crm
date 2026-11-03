"""
Tests for the form layouts app.

The suite stays module-agnostic. It uses the platform's own ``Company`` model
as the fixture: core ships a multi-step create view for it
(``core:create_company_multi_step``) that names a single-page counterpart
(``core:create_company``), which is exactly the shape any opting-in module
provides. ``Company`` is opted in only while a test runs, by patching the
feature registry, so no module's real opt-in is assumed or changed.

Lead and Opportunity scenarios live next to their registration, in
``horilla_crm``'s own test modules.
"""

# Standard library imports
import html
import re
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

# Third-party imports (Django)
from django import forms
from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import AnonymousUser, Permission
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.test import RequestFactory, SimpleTestCase, TestCase
from login_history.models import post_login, post_logout

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.forms.company import CompanyFormClassSingle
from horilla.contrib.core.models import Company, HorillaContentType
from horilla.contrib.field_management.extensions.form_layouts import (
    get_prefilled_field_names,
    is_layoutable_request,
)
from horilla.contrib.field_management.models import FormLayoutField
from horilla.contrib.field_management.registry.form_layouts import (
    REGISTRY_KEY,
    get_configurable_models,
    is_layout_configurable,
)
from horilla.contrib.field_management.utils.form_layouts import (
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
from horilla.extension.view.registry import VIEW_EXTENSION_REGISTRY
from horilla.registry import feature as feature_registry
from horilla.registry.feature import (
    FEATURE_CONFIG,
    FEATURE_REGISTRY,
    register_model_for_feature,
)
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


def _opt_in(*models):
    """Make exactly ``models`` configurable while the returned patch is active."""
    return mock.patch.dict(FEATURE_REGISTRY, {REGISTRY_KEY: list(models)})


def _isolated_registries():
    """Patch the feature registries with copies, so a test may register freely."""
    return (
        mock.patch.dict(
            FEATURE_REGISTRY,
            {key: list(models) for key, models in FEATURE_REGISTRY.items()},
            clear=True,
        ),
        mock.patch.dict(feature_registry.ALL_FEATURES_MODELS, {}),
    )


class CompanyOptInMixin:
    """Opt the platform Company model in to form layouts for each test."""

    def opt_in_company(self):
        """Opt the Company model in to form layouts, restored after the test."""
        patcher = _opt_in(Company)
        patcher.start()
        self.addCleanup(patcher.stop)


class LoginSignalsMixin:
    """Disconnect django-login-history, which needs a User-Agent header."""

    @classmethod
    def setUpClass(cls):
        """Disconnect the login-history signal handlers for the test class."""
        super().setUpClass()
        user_logged_in.disconnect(post_login)
        user_logged_out.disconnect(post_logout)

    @classmethod
    def tearDownClass(cls):
        """Reconnect the login-history signal handlers after the test class."""
        user_logged_in.connect(post_login)
        user_logged_out.connect(post_logout)
        super().tearDownClass()


class FeatureRegistrationTests(SimpleTestCase):
    """Tests for the selective feature registration."""

    def test_feature_is_registered(self):
        """The contrib app registers the feature against the shared registry."""
        self.assertEqual(FEATURE_CONFIG.get("form_layouts"), REGISTRY_KEY)

    def test_feature_does_not_auto_register_models(self):
        """Models must opt in explicitly."""
        self.assertIs(feature_registry.FEATURE_AUTO_REGISTER_ALL["form_layouts"], False)

    def test_explicit_opt_in_makes_a_model_configurable(self):
        """register_model_for_feature(features=["form_layouts"]) opts a model in."""
        registry_patch, all_models_patch = _isolated_registries()
        with registry_patch, all_models_patch:
            FEATURE_REGISTRY[REGISTRY_KEY] = []
            self.assertFalse(is_layout_configurable(Company))

            register_model_for_feature(model_class=Company, features=["form_layouts"])

            self.assertTrue(is_layout_configurable(Company))
            self.assertIn(Company, get_configurable_models())

    def test_all_true_does_not_opt_a_model_in(self):
        """A model registered with all=True is not configurable without opting in."""
        registry_patch, all_models_patch = _isolated_registries()
        with registry_patch, all_models_patch:
            FEATURE_REGISTRY[REGISTRY_KEY] = []

            register_model_for_feature(model_class=Company, all=True)

            self.assertFalse(is_layout_configurable(Company))

    def test_object_without_meta_is_not_configurable(self):
        """Only model classes can be configurable."""
        self.assertFalse(is_layout_configurable(object()))
        self.assertFalse(is_layout_configurable(None))

    def test_view_extensions_are_registered(self):
        """The generic form views are extended through _inherit_view, not patched."""
        single_form_path = (
            "horilla.contrib.generics.views.single_form.HorillaSingleFormView"
        )
        multi_form_path = (
            "horilla.contrib.generics.views.multi_form.HorillaMultiStepFormView"
        )
        self.assertIn(single_form_path, VIEW_EXTENSION_REGISTRY)
        self.assertIn(multi_form_path, VIEW_EXTENSION_REGISTRY)
        self.assertFalse(
            hasattr(HorillaSingleFormView, "_form_layouts_original_get_form")
        )
        self.assertFalse(
            hasattr(HorillaMultiStepFormView, "_form_layouts_original_get")
        )


class ViewExtensionHelperTests(SimpleTestCase):
    """Tests for the request checks the view extensions rely on."""

    def _view(self, **attrs):
        defaults = {"kwargs": {}, "object": None, "duplicate_mode": False}
        defaults.update(attrs)
        return SimpleNamespace(**defaults)

    def test_layoutable_request_allows_create_and_edit_but_not_duplicate(self):
        """A layout applies to create and edit requests, never a duplicate."""
        self.assertTrue(is_layoutable_request(self._view()))
        self.assertTrue(is_layoutable_request(self._view(kwargs={"pk": 3})))
        self.assertTrue(is_layoutable_request(self._view(object=object())))
        self.assertFalse(is_layoutable_request(self._view(duplicate_mode=True)))

    def test_prefilled_fields_are_the_non_empty_initial_values(self):
        """Empty initial values do not protect a field."""
        view = SimpleNamespace(
            get_initial=lambda: {"website": "https://x.test", "fax": "", "hq": None}
        )
        self.assertEqual(get_prefilled_field_names(view), {"website"})


class LayoutResolutionTests(CompanyOptInMixin, TestCase):
    """Tests for get_form_layout."""

    def setUp(self):
        self.opt_in_company()
        self.company_a = Company.objects.create(
            name="Company A", email="a@example.com", country="US"
        )
        self.company_b = Company.objects.create(
            name="Company B", email="b@example.com", country="GB"
        )
        self.company_ct = HorillaContentType.objects.get_for_model(Company)
        _activate_company(self.company_a)

    def tearDown(self):
        _clear_thread_request()
        super().tearDown()

    def _row(self, field_name, sequence, is_visible=True, company=None, **kwargs):
        return FormLayoutField.objects.create(
            content_type=self.company_ct,
            field_name=field_name,
            sequence=sequence,
            is_visible=is_visible,
            company=company or self.company_a,
            **kwargs,
        )

    def test_model_without_rows_has_no_layout(self):
        """Nothing changes until a layout has been saved."""
        self.assertIsNone(get_form_layout(Company))

    def test_model_that_did_not_opt_in_has_no_layout(self):
        """Models outside the registry are never looked up."""
        self.assertIsNone(get_form_layout(User))
        self.assertIsNone(get_form_layout(None))

    def test_rows_become_an_ordered_layout(self):
        """Rows are ordered by sequence and invisible ones are collected."""
        self._row("email", 2)
        self._row("fax", 3, is_visible=False)
        self._row("name", 1)

        layout = get_form_layout(Company)

        self.assertEqual(layout.order, ("name", "email", "fax"))
        self.assertEqual(layout.hidden, frozenset({"fax"}))

    def test_layout_is_scoped_to_the_active_company(self):
        """Another company's layout never applies."""
        self._row("fax", 1, is_visible=False, company=self.company_b)
        self.assertIsNone(get_form_layout(Company))

        _activate_company(self.company_b)
        self.assertEqual(get_form_layout(Company).hidden, frozenset({"fax"}))

    def test_inactive_rows_are_ignored(self):
        """Archived rows do not form a layout."""
        self._row("fax", 1, is_visible=False, is_active=False)
        self.assertIsNone(get_form_layout(Company))

    def test_layout_is_cached_on_the_request(self):
        """A second lookup in the same request does not see later writes."""
        self.assertIsNone(get_form_layout(Company))
        self._row("fax", 1, is_visible=False)
        self.assertIsNone(get_form_layout(Company))

        clear_form_layout_cache()
        self.assertIsNotNone(get_form_layout(Company))


class ApplyFormLayoutTests(CompanyOptInMixin, TestCase):
    """Tests for apply_form_layout on a platform create form."""

    def setUp(self):
        self.opt_in_company()
        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        self.user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
            company=self.company,
        )
        _activate_company(self.company, self.user)
        apply_form_extensions(force=True)

    def tearDown(self):
        _clear_thread_request()
        super().tearDown()

    def _form(self, data=None):
        return get_create_form_class(Company)(data=data, request=_thread_local.request)

    def _layout(self, order=(), hidden=()):
        return FormLayout(order=tuple(order), hidden=frozenset(hidden))

    def test_hidden_optional_field_is_removed(self):
        """An optional field marked hidden is left off the form."""
        form = self._form()
        removed = apply_form_layout(form, self._layout(hidden={"fax", "website"}))

        self.assertCountEqual(removed, ["fax", "website"])
        self.assertNotIn("fax", form.fields)
        self.assertNotIn("website", form.fields)

    def test_required_field_is_never_removed(self):
        """A required field stays even when the layout hides it."""
        form = self._form()
        apply_form_layout(form, self._layout(hidden={"name", "email"}))

        self.assertIn("name", form.fields)
        self.assertIn("email", form.fields)

    def test_requiredness_is_read_from_the_built_form(self):
        """A field another app made optional on the form can then be hidden."""
        form = self._form()
        form.fields["email"].required = False
        apply_form_layout(form, self._layout(hidden={"email"}))

        self.assertNotIn("email", form.fields)

    def test_hidden_input_fields_are_kept(self):
        """Fields that already render as hidden inputs are not removed."""
        form = self._form()
        form.fields["fax"].widget = forms.HiddenInput()
        apply_form_layout(form, self._layout(hidden={"fax"}))

        self.assertIn("fax", form.fields)

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
        before = [name for name in form.fields if name not in {"email", "website"}]
        apply_form_layout(form, self._layout(order=("email", "website")))

        self.assertEqual(list(form.fields)[:2], ["email", "website"])
        self.assertEqual(list(form.fields)[2:], before)

    def test_removed_fields_never_block_validation(self):
        """Only fields still on the form can produce errors."""
        form = self._form(data={})
        removed = apply_form_layout(form, self._layout(hidden={"fax", "website"}))

        form.is_valid()
        self.assertTrue(removed)
        self.assertFalse(set(removed) & set(form.errors))
        self.assertIn("name", form.errors)


class LayoutEditorHelperTests(CompanyOptInMixin, TestCase):
    """Tests for the helpers behind the settings editor."""

    def setUp(self):
        self.opt_in_company()
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
        self.company_ct = HorillaContentType.objects.get_for_model(Company)
        _activate_company(self.company, self.user)
        apply_form_extensions(force=True)

    def tearDown(self):
        _clear_thread_request()
        super().tearDown()

    def _entries(self):
        return {entry.name: entry for entry in build_layout_entries(Company)}

    def test_create_form_follows_the_wizard_to_its_single_page_view(self):
        """The editor uses the form the wizard's single-page create view renders."""
        self.assertTrue(
            issubclass(get_create_form_class(Company), CompanyFormClassSingle)
        )

    def test_model_without_form_views_gets_a_generic_form(self):
        """A model with no create views falls back to a generic model form."""
        form_class = get_create_form_class(FormLayoutField)

        self.assertIs(form_class._meta.model, FormLayoutField)

    def test_entries_describe_the_create_form(self):
        """Every visible field is listed with its requiredness."""
        entries = self._entries()

        self.assertTrue(entries["name"].required)
        self.assertFalse(entries["fax"].required)
        self.assertTrue(all(entry.visible for entry in entries.values()))
        self.assertFalse(any(entry.is_custom for entry in entries.values()))

    def test_save_orders_fields_and_forces_required_ones_visible(self):
        """Required fields cannot be stored as hidden."""
        saved = save_form_layout(
            Company,
            ordered_names=["email", "name", "fax"],
            visible_names=["email"],
            company=self.company,
        )
        by_name = {entry.name: entry for entry in saved}

        self.assertEqual([entry.name for entry in saved][:3], ["email", "name", "fax"])
        self.assertTrue(by_name["name"].visible)
        self.assertFalse(by_name["fax"].visible)
        row = FormLayoutField.objects.get(
            content_type=self.company_ct, field_name="name"
        )
        self.assertTrue(row.is_visible)
        self.assertEqual(row.sequence, 2)

    def test_save_ignores_unknown_names_and_drops_stale_rows(self):
        """Only fields on the form are stored."""
        FormLayoutField.objects.create(
            content_type=self.company_ct,
            field_name="removed_field",
            company=self.company,
        )
        save_form_layout(
            Company,
            ordered_names=["not_a_field", "fax"],
            visible_names=["not_a_field"],
            company=self.company,
        )
        names = set(
            FormLayoutField.objects.filter(content_type=self.company_ct).values_list(
                "field_name", flat=True
            )
        )

        self.assertNotIn("not_a_field", names)
        self.assertNotIn("removed_field", names)
        self.assertEqual(names, set(self._entries()))

    def test_save_and_reset_only_touch_the_given_company(self):
        """Resetting one company leaves another company's layout alone."""
        save_form_layout(Company, ["fax"], [], company=self.company)
        FormLayoutField.all_objects.create(
            content_type=self.company_ct,
            field_name="fax",
            is_visible=False,
            company=self.other_company,
        )

        reset_form_layout(Company, self.company)

        self.assertFalse(
            FormLayoutField.all_objects.filter(company=self.company).exists()
        )
        self.assertTrue(
            FormLayoutField.all_objects.filter(company=self.other_company).exists()
        )
        self.assertIsNone(get_form_layout(Company))


class CreateViewHookTests(LoginSignalsMixin, CompanyOptInMixin, TestCase):
    """HTTP tests: a saved layout changes create requests only."""

    def setUp(self):
        self.opt_in_company()
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
        self.company_ct = HorillaContentType.objects.get_for_model(Company)
        self.client.force_login(self.user)

    def tearDown(self):
        _clear_thread_request()
        super().tearDown()

    def _htmx(self):
        return {"HTTP_HX_REQUEST": "true"}

    def _hide(self, field_name, *, company=None):
        return FormLayoutField.all_objects.create(
            content_type=self.company_ct,
            field_name=field_name,
            sequence=1,
            is_visible=False,
            company=company or self.company,
        )

    def _wizard_create(self):
        return self.client.get(
            f"{reverse('core:create_company_multi_step')}?new=true", **self._htmx()
        )

    def test_wizard_opens_when_there_is_no_layout(self):
        """Without a layout the create request keeps opening the wizard."""
        self.assertContains(
            self._wizard_create(), 'id="company-form-view-multi-container"'
        )

    def test_wizard_create_stays_the_wizard_even_with_a_layout(self):
        """A saved layout never redirects the wizard; it stays the default form."""
        self._hide("website")
        response = self._wizard_create()

        self.assertContains(response, 'id="company-form-view-multi-container"')
        self.assertContains(response, 'name="website"')

    def test_wizard_offers_a_custom_layout_mode_link(self):
        """The wizard's mode switcher links to the custom layout when one exists."""
        self._hide("website")
        response = self._wizard_create()

        self.assertContains(response, "Custom Layout")
        self.assertContains(
            response,
            f"{reverse('core:create_company')}?new=true&amp;form_layout=1",
        )

    def test_wizard_has_no_custom_layout_mode_without_a_layout(self):
        """Without a saved layout the mode switcher has nothing extra to offer."""
        self.assertNotContains(self._wizard_create(), "Custom Layout")

    def test_single_page_create_ignores_the_layout_by_default(self):
        """Visiting the single-page create URL directly shows every field."""
        self._hide("website")
        response = self.client.get(reverse("core:create_company"), **self._htmx())

        self.assertContains(response, 'name="website"')

    def test_single_page_create_applies_the_layout_when_requested(self):
        """Following the Custom Layout mode link trims the single-page form."""
        self._hide("website")
        response = self.client.get(
            f"{reverse('core:create_company')}?form_layout=1", **self._htmx()
        )

        self.assertContains(response, 'name="name"')
        self.assertNotContains(response, 'name="website"')

    def test_layout_of_another_company_does_not_apply(self):
        """Layouts are per company."""
        self._hide("website", company=self.other_company)

        response = self.client.get(
            f"{reverse('core:create_company')}?form_layout=1", **self._htmx()
        )
        self.assertContains(response, 'name="website"')

    def test_edit_forms_default_to_showing_every_field(self):
        """Without following the Custom Layout mode, edit forms are untouched."""
        self._hide("website")
        kwargs = {"pk": self.company.pk}

        single = self.client.get(
            reverse("core:edit_company", kwargs=kwargs), **self._htmx()
        )
        wizard = self.client.get(
            reverse("core:edit_company_multi_step", kwargs=kwargs), **self._htmx()
        )

        self.assertContains(single, 'name="website"')
        self.assertContains(wizard, 'id="company-form-view-multi-container"')

    def test_custom_layout_mode_trims_the_edit_form_too(self):
        """Following Custom Layout on an edit request trims that form as well."""
        self._hide("website")
        url = reverse("core:edit_company", kwargs={"pk": self.company.pk})
        response = self.client.get(f"{url}?form_layout=1", **self._htmx())

        self.assertContains(response, 'name="name"')
        self.assertNotContains(response, 'name="website"')

    def test_editing_through_the_custom_layout_keeps_the_hidden_fields_value(self):
        """Saving the trimmed edit form never blanks a field it left out."""
        self.company.website = "https://acme.example.com"
        self.company.save(update_fields=["website"])
        self._hide("website")

        edit_response = self.client.get(
            f"{reverse('core:edit_company', kwargs={'pk': self.company.pk})}"
            "?form_layout=1",
            **self._htmx(),
        )
        form = edit_response.context["form"]
        payload = {
            name: value
            for name, value in form.initial.items()
            if name in form.fields and name != "icon" and value is not None
        }
        payload["name"] = "Acme Renamed"

        response = self.client.post(
            f"{reverse('core:edit_company', kwargs={'pk': self.company.pk})}"
            "?form_layout=1",
            payload,
            **self._htmx(),
        )

        self.assertNotContains(response, "errorlist")
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, "Acme Renamed")
        self.assertEqual(self.company.website, "https://acme.example.com")

    def test_duplicate_form_shows_every_field(self):
        """Duplicating a record keeps all of its copied values."""
        self._hide("website")
        url = reverse("core:edit_company", kwargs={"pk": self.company.pk})
        response = self.client.get(f"{url}?duplicate=true", **self._htmx())

        self.assertContains(response, 'name="website"')


class FormLayoutSettingsViewTests(LoginSignalsMixin, CompanyOptInMixin, TestCase):
    """HTTP tests for the settings page, editor, save and reset."""

    def setUp(self):
        self.opt_in_company()
        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        self.user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
            company=self.company,
        )
        self.company_ct = HorillaContentType.objects.get_for_model(Company)
        self.client.force_login(self.user)

    def tearDown(self):
        _clear_thread_request()
        super().tearDown()

    def _htmx(self):
        return {"HTTP_HX_REQUEST": "true"}

    def _detail_url(self):
        return reverse(
            "field_management:form_layout_detail", kwargs={"ct": self.company_ct.pk}
        )

    def _editor(self, mode=""):
        url = f"{reverse('field_management:form_layout_editor')}?model={self.company_ct.pk}"
        if mode:
            url = f"{url}&mode={mode}"
        return self.client.get(url, **self._htmx())

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
                    content_type__app_label="field_management", codename=codename
                )
            )
        return staff

    def test_anonymous_user_is_sent_to_login(self):
        """The settings page requires an authenticated user."""
        self.client.logout()
        response = self.client.get(reverse("field_management:form_layout_view"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_user_without_permission_is_denied(self):
        """View permission is required to open the settings page."""
        self.client.force_login(self._staff())
        response = self.client.get(reverse("field_management:form_layout_view"))

        self.assertContains(response, "Permission Denied")

    def test_settings_page_opens_read_only(self):
        """The detail page lists the fields without letting them change until Edit."""
        response = self.client.get(self._detail_url())

        self.assertContains(response, 'id="form-layout-view"')
        self.assertContains(response, 'id="form-layout-editor"')
        self.assertContains(response, 'data-field="name"')
        self.assertContains(
            response,
            reverse(
                "field_management:form_layout_detail_nav",
                kwargs={"ct": self.company_ct.pk},
            ),
        )
        self.assertNotContains(response, 'name="field_order"')
        self.assertNotContains(response, 'name="visible"')
        self.assertNotContains(response, "Save Layout")

    def test_list_page_loads_navbar_and_list(self):
        """The menu page is the Custom Fields style shell."""
        response = self.client.get(reverse("field_management:form_layout_view"))

        self.assertContains(response, reverse("field_management:form_layout_navbar"))
        self.assertContains(response, reverse("field_management:form_layout_list"))

    def test_navbar_has_a_new_button(self):
        """The list navbar's New button opens the create modal."""
        response = self.client.get(
            reverse("field_management:form_layout_navbar"), **self._htmx()
        )

        self.assertContains(response, reverse("field_management:form_layout_create"))

    def test_list_shows_only_saved_layouts(self):
        """A model appears in the list once it has a layout."""
        url = reverse("field_management:form_layout_list")
        self.assertNotContains(self.client.get(url, **self._htmx()), self._detail_url())

        FormLayoutField.all_objects.create(
            content_type=self.company_ct,
            field_name="name",
            sequence=1,
            company=self.company,
        )
        response = self.client.get(url, **self._htmx())

        self.assertContains(response, self._detail_url())

    def test_create_offers_only_models_without_a_layout(self):
        """The create form lists unconfigured models."""
        url = reverse("field_management:form_layout_create")
        self.assertContains(
            self.client.get(url, **self._htmx()), f'value="{self.company_ct.pk}"'
        )

        FormLayoutField.all_objects.create(
            content_type=self.company_ct,
            field_name="name",
            sequence=1,
            company=self.company,
        )
        self.assertNotContains(
            self.client.get(url, **self._htmx()), f'value="{self.company_ct.pk}"'
        )

    def test_create_stores_the_layout_and_opens_its_detail_page(self):
        """Picking a model stores every field as shown and opens the detail view."""
        response = self.client.post(
            reverse("field_management:form_layout_create"),
            {"content_type": self.company_ct.pk},
            **self._htmx(),
        )

        self.assertContains(response, self._detail_url())
        rows = FormLayoutField.objects.filter(content_type=self.company_ct)
        self.assertTrue(rows.exists())
        self.assertFalse(rows.filter(is_visible=False).exists())
        self.assertEqual(rows.filter(sequence=1).count(), 1)

    def test_detail_navbar_has_edit_and_delete(self):
        """The detail navbar carries Edit Layout and Delete for an admin."""
        url = reverse(
            "field_management:form_layout_detail_nav", kwargs={"ct": self.company_ct.pk}
        )
        response = self.client.get(url, **self._htmx())

        self.assertContains(response, "Edit Layout")
        self.assertContains(
            response,
            reverse(
                "field_management:form_layout_edit", kwargs={"ct": self.company_ct.pk}
            ),
        )
        self.assertContains(response, "formLayoutDelete")

    def test_detail_navbar_shows_save_and_cancel_while_editing(self):
        """Edit mode swaps Edit Layout/Delete for Save and Cancel."""
        url = reverse(
            "field_management:form_layout_detail_nav", kwargs={"ct": self.company_ct.pk}
        )
        response = self.client.get(f"{url}?mode=edit", **self._htmx())

        self.assertContains(response, "Save Layout")
        self.assertContains(response, "Cancel")
        self.assertNotContains(response, "Edit Layout")
        self.assertNotContains(response, "formLayoutDelete")

    def test_editor_reloads_the_navbar_for_its_mode(self):
        """Edit mode swaps the navbar out of band; the first page load does not."""
        edit = self._editor(mode="edit")
        self.assertContains(edit, 'hx-swap-oob="true"')
        self.assertContains(edit, "?mode=edit")
        self.assertNotContains(self.client.get(self._detail_url()), "hx-swap-oob")

    def test_detail_navbar_hides_buttons_from_a_viewer(self):
        """Without change/delete permission the navbar has no buttons."""
        self.client.force_login(self._staff("view_formlayoutfield"))
        url = reverse(
            "field_management:form_layout_detail_nav", kwargs={"ct": self.company_ct.pk}
        )
        response = self.client.get(url, **self._htmx())

        self.assertNotContains(response, "Edit Layout")
        self.assertNotContains(response, "formLayoutDelete")

    def test_settings_menu_links_to_the_page(self):
        """The settings sidebar lists Form Layout under the Field Management group."""
        response = self.client.get(reverse("field_management:form_layout_view"))

        self.assertContains(response, "Field Management")
        self.assertContains(
            response, f'hx-get="{reverse("field_management:form_layout_view")}"'
        )

    def test_edit_mode_renders_the_sortable_form(self):
        """Edit mode has the drag handles, switches, arrows and save button."""
        response = self._editor(mode="edit")
        content = response.content.decode()

        self.assertContains(response, 'id="form-layout-form"')
        self.assertContains(response, 'name="field_order" value="name"')
        # Optional fields get a visibility switch; required ones only a lock.
        self.assertRegex(content, r'name="visible"\s+value="website"')
        self.assertNotRegex(content, r'name="visible"\s+value="name"')
        # The sr-only checkbox must sit in a positioned label so it scrolls with
        # its row; otherwise clicking a switch scrolls the whole page.
        self.assertRegex(
            content,
            r'<label[^>]*class="relative [^"]*"[^>]*>\s*<input\s+type="checkbox"',
        )
        self.assertContains(response, "fa-grip-vertical")
        self.assertContains(response, 'data-layout-move="up"')
        # Save and Cancel live in the navbar, which the editor loads over HTMX.
        navbar_url = re.search(r'id="navBar".*?hx-get="([^"]+)"', content, re.S)
        self.assertIsNotNone(navbar_url)
        navbar = self.client.get(
            html.unescape(navbar_url.group(1)), HTTP_HX_REQUEST="true"
        )
        self.assertContains(navbar, "data-layout-cancel")
        self.assertContains(navbar, "Save Layout")
        self.assertNotContains(navbar, "Edit Layout")
        # The drag handle must not be a natively draggable image.
        self.assertNotContains(response, "drag.svg")

    def test_viewer_cannot_open_edit_mode(self):
        """Without change permission, mode=edit falls back to the read-only view."""
        self.client.force_login(self._staff("view_formlayoutfield"))
        response = self._editor(mode="edit")

        self.assertContains(response, 'data-field="name"')
        self.assertNotContains(response, 'name="field_order"')
        self.assertNotContains(response, "Edit Layout")

    def test_viewer_sees_a_read_only_editor(self):
        """Without change permission the editor offers no way to edit."""
        self.client.force_login(self._staff("view_formlayoutfield"))
        response = self.client.get(self._detail_url())

        self.assertContains(response, 'id="form-layout-editor"')
        self.assertNotContains(response, "Edit Layout")
        self.assertNotContains(response, "Save Layout")

    def test_save_stores_the_layout_and_create_uses_it(self):
        """Saving from the editor changes what the create request renders."""
        response = self.client.post(
            reverse("field_management:form_layout_save"),
            {
                "model": self.company_ct.pk,
                "field_order": ["email", "name", "website"],
                "visible": ["email", "name"],
            },
            **self._htmx(),
        )

        self.assertContains(response, "Create form layout saved.")
        self.assertNotContains(response, 'name="field_order"')
        row = FormLayoutField.objects.get(
            content_type=self.company_ct, field_name="website"
        )
        self.assertFalse(row.is_visible)
        self.assertEqual(
            FormLayoutField.objects.get(
                content_type=self.company_ct, field_name="email"
            ).sequence,
            1,
        )

        create = self.client.get(
            f"{reverse('core:create_company_multi_step')}?new=true", **self._htmx()
        )
        self.assertContains(create, 'id="company-form-view-multi-container"')
        self.assertContains(create, 'name="website"')
        self.assertContains(create, "Custom Layout")

        custom_layout = self.client.get(
            f"{reverse('core:create_company')}?form_layout=1", **self._htmx()
        )
        self.assertContains(custom_layout, 'id="company-form-view-container"')
        self.assertNotContains(custom_layout, 'name="website"')

    def test_save_rejects_an_unknown_model(self):
        """A write never falls back to another model."""
        response = self.client.post(
            reverse("field_management:form_layout_save"),
            {"model": "999999", "field_order": ["website"]},
            **self._htmx(),
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(FormLayoutField.all_objects.exists())

    def test_save_requires_change_permission(self):
        """A viewer cannot store a layout."""
        self.client.force_login(self._staff("view_formlayoutfield"))
        response = self.client.post(
            reverse("field_management:form_layout_save"),
            {"model": self.company_ct.pk, "field_order": ["website"]},
            **self._htmx(),
        )

        self.assertContains(response, "Permission Denied")
        self.assertFalse(FormLayoutField.all_objects.exists())

    def test_reset_removes_the_layout(self):
        """Resetting brings back the default wizard."""
        FormLayoutField.all_objects.create(
            content_type=self.company_ct,
            field_name="website",
            is_visible=False,
            company=self.company,
        )
        response = self.client.post(
            reverse("field_management:form_layout_reset"),
            {"model": self.company_ct.pk},
            **self._htmx(),
        )

        self.assertEqual(
            response["HX-Redirect"], reverse("field_management:form_layout_view")
        )
        self.assertFalse(FormLayoutField.all_objects.exists())

    def test_write_endpoints_require_post(self):
        """Save only accepts POST requests."""
        response = self.client.get(
            reverse("field_management:form_layout_save"), **self._htmx()
        )
        self.assertEqual(response.status_code, 405)


class IsolationFromPlatformTests(SimpleTestCase):
    """The feature is a generic contrib app: no platform or module coupling."""

    def test_core_and_generics_do_not_mention_form_layouts(self):
        """Platform code never refers to this app."""
        base = Path(settings.BASE_DIR)
        for path in (
            base / "horilla" / "contrib" / "generics",
            base / "horilla" / "contrib" / "core",
        ):
            for file in path.rglob("*.py"):
                with self.subTest(file=str(file.relative_to(base))):
                    self.assertNotIn("form_layout", file.read_text(encoding="utf-8"))

    def test_app_does_not_reference_any_module(self):
        """The app's code and templates never import or route to another app.

        Markers are derived from Django's own app registry: every installed
        app whose dotted name is not this app, not under the ``horilla``
        platform namespace, and not a Django/third-party framework app is
        foreign, and this contrib app must never name it in a string. No
        business-module name is hardcoded here, so adding, renaming, or
        removing an app is covered automatically.

        """
        this_file = Path(__file__).resolve()
        app_dir = this_file.parent
        own_name = apps.get_containing_app_config(__name__).name
        allowed_soft_dependencies = set()
        foreign_labels = sorted(
            {
                cfg.label
                for cfg in apps.get_app_configs()
                if cfg.name != own_name
                and cfg.name != "horilla"
                and not cfg.name.startswith("horilla.")
                and not cfg.name.startswith("django.")
                and cfg.label not in allowed_soft_dependencies
            }
        )
        # Only the quoted-string form (a real reference: an app label used as
        # a dict/registry key, module path, or URL namespace) counts — the
        # bare word would false-positive on ordinary English in a docstring,
        # and an unquoted label can coincide with an unrelated template name
        # (e.g. "messages.html", included by every app, not this app naming
        # the "messages" app).
        markers = []
        for label in foreign_labels:
            markers.extend([f'"{label}', f"'{label}"])
        files = [*app_dir.rglob("*.py"), *app_dir.rglob("*.html")]
        for file in files:
            # Skip migrations and this module, which spells out the markers.
            if "migrations" in file.parts or file.resolve() == this_file:
                continue
            text = file.read_text(encoding="utf-8")
            for marker in markers:
                with self.subTest(file=file.name, marker=marker):
                    self.assertNotIn(marker, text)
