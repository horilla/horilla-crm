"""Tests for Lead web-to-lead field parsing, RTL assets, and field requirements."""

# Standard library imports
import importlib
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import skipUnless

# Third-party imports (Django)
from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase, override_settings
from login_history.models import post_login, post_logout

# First party imports (Horilla)
from horilla.apps import apps
from horilla.auth.models import User
from horilla.contrib.core.models import Company, HorillaContentType
from horilla.contrib.utils.middlewares import _thread_local
from horilla.core.exceptions import ValidationError
from horilla.extension.forms import resolve_form_class
from horilla.extension.forms.bootstrap import apply_form_extensions
from horilla.extension.forms.registry import FORM_EXTENSION_REGISTRY
from horilla.registry.feature import FEATURE_CONFIG, FEATURE_REGISTRY
from horilla.urls import reverse
from horilla.utils import timezone

# Local imports
from ..models import Lead, LeadCaptureForm, LeadStatus
from ..views.web_to_lead import parse_selected_fields, render_form_preview

_FIELD_REQUIREMENTS_INSTALLED = apps.is_installed("horilla.contrib.field_management")

if _FIELD_REQUIREMENTS_INSTALLED:
    from horilla.contrib.field_management.extensions.field_requirements import (
        iter_configurable_model_forms,
        register_discovered_form_extensions,
    )
    from horilla.contrib.field_management.filters import FieldRequirementFilter
    from horilla.contrib.field_management.forms import (
        FieldRequirementForm,
        get_field_choices,
    )
    from horilla.contrib.field_management.models import FieldRequirement
    from horilla.contrib.field_management.registry.field_requirements import (
        REGISTRY_KEY,
        can_relax_requirement,
        get_configurable_fields,
        get_configurable_models,
        is_requirement_configurable,
    )
    from horilla.contrib.field_management.utils.field_requirements import (
        get_field_requirements_for_model,
    )


class ParseSelectedFieldsTests(SimpleTestCase):
    """Edit Form must not 500 when selected_fields is empty or invalid JSON."""

    def test_empty_and_invalid_values_become_an_empty_list(self):
        """Blank, null, and invalid JSON all parse to an empty list."""
        self.assertEqual(parse_selected_fields(""), [])
        self.assertEqual(parse_selected_fields(None), [])
        self.assertEqual(parse_selected_fields("   "), [])
        self.assertEqual(parse_selected_fields("not-json"), [])
        self.assertEqual(parse_selected_fields("{}"), [])

    def test_valid_json_list_is_returned(self):
        """A JSON array of field names is returned as a Python list."""
        self.assertEqual(
            parse_selected_fields('["first_name", "email"]'),
            ["first_name", "email"],
        )


class WebToLeadRtlTemplateTests(SimpleTestCase):
    """Standalone public form follows the same LANGUAGE_BIDI dir pattern as login."""

    def test_public_form_template_uses_language_bidi_dir(self):
        """public_lead_form.html sets dir from LANGUAGE_BIDI and loads rtl assets."""
        path = (
            Path(settings.BASE_DIR)
            / "horilla_crm"
            / "leads"
            / "templates"
            / "web_to_lead"
            / "public_lead_form.html"
        )
        text = path.read_text(encoding="utf-8")
        self.assertIn('dir="{% if LANGUAGE_BIDI %}rtl{% else %}ltr{% endif %}"', text)
        self.assertIn("inject_html/rtl_assets.html", text)

    def test_form_preview_sets_dir_from_language_bidi(self):
        """form_preview.html renders dir=rtl when LANGUAGE_BIDI is true."""
        html = render_to_string(
            "web_to_lead/form_preview.html",
            {"fields": [], "form_name": "Contact Us", "LANGUAGE_BIDI": True},
        )
        self.assertIn('dir="rtl"', html)

    def test_edit_preview_uses_form_language_direction(self):
        """render_form_preview sets dir from the form language code."""
        html = render_form_preview([], "Contact Us", "", "fa")
        self.assertIn('dir="rtl"', html)
        html = render_form_preview([], "Contact Us", "", "en")
        self.assertIn('dir="ltr"', html)

    def test_edit_form_button_has_persian_translation(self):
        """leads/fa django.po translates the Edit Form button label."""
        po = (
            Path(settings.BASE_DIR)
            / "horilla_crm"
            / "leads"
            / "locale"
            / "fa"
            / "LC_MESSAGES"
            / "django.po"
        )
        text = po.read_text(encoding="utf-8")
        self.assertIn('msgid "Edit Form"', text)
        self.assertIn('msgstr "ویرایش فرم"', text)


class WebToLeadDuplicateSubmissionTests(TestCase):
    """Repeated clicks on the embedded form must not create duplicate leads."""

    @classmethod
    def setUpTestData(cls):
        """Create a company, a lead owner, a lead status, and a public form."""
        cls.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        cls.owner = User.objects.create_user(
            username="owner", email="owner@example.com", password="x"
        )
        LeadStatus.all_objects.create(name="New", probability=0, company=cls.company)
        cls.form_config = LeadCaptureForm.all_objects.create(
            company=cls.company,
            form_name="Contact Us",
            selected_fields=json.dumps(
                ["first_name", "last_name", "email", "lead_company"]
            ),
            header_color="#ed4f38",
            success_message="Thanks",
            success_description="We will contact you.",
            lead_owner=cls.owner,
        )
        cls.url = reverse(
            "leads:public_lead_form", kwargs={"form_id": cls.form_config.id}
        )

    def submit(self, **overrides):
        """POST the public lead form via HTMX with optional field overrides."""
        data = {
            "first_name": "Sara",
            "last_name": "Ahmadi",
            "email": "sara@example.com",
            "lead_company": "Example Ltd",
        }
        data.update(overrides)
        return self.client.post(self.url, data, HTTP_HX_REQUEST="true")

    def test_identical_resubmission_creates_one_lead(self):
        """Same payload (email case-insensitive) creates only one lead."""
        self.assertEqual(self.submit().status_code, 200)
        response = self.submit(email="SARA@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Thanks")
        self.assertEqual(Lead.all_objects.count(), 1)

    def test_different_data_creates_a_new_lead(self):
        """A different email creates a second lead."""
        self.submit()
        self.submit(email="other@example.com")
        self.assertEqual(Lead.all_objects.count(), 2)

    def test_old_submission_is_not_treated_as_duplicate(self):
        """Submissions outside the duplicate window are allowed again."""
        self.submit()
        Lead.all_objects.update(created_at=timezone.now() - timedelta(hours=1))
        self.submit()
        self.assertEqual(Lead.all_objects.count(), 2)

    @override_settings(WEB_TO_LEAD_DUPLICATE_WINDOW=0)
    def test_check_can_be_disabled(self):
        """Zero duplicate window disables deduplication entirely."""
        self.submit()
        self.submit()
        self.assertEqual(Lead.all_objects.count(), 2)

    def test_public_form_drops_clicks_while_a_request_is_in_flight(self):
        """Public form markup uses hx-sync drop to ignore double-clicks."""
        self.assertContains(self.client.get(self.url), 'hx-sync="this:drop"')


class WebToLeadFormBuilderFieldListTests(TestCase):
    """The builder must offer the Lead fields whether or not a form is saved."""

    def setUp(self):
        """Log in a superuser of a company that has no capture form yet."""
        user_logged_in.disconnect(post_login)
        user_logged_out.disconnect(post_logout)
        self.addCleanup(user_logged_in.connect, post_login)
        self.addCleanup(user_logged_out.connect, post_logout)
        self.company, self.user = _create_company_and_user()
        self.client.force_login(self.user)
        session = self.client.session
        session["active_company_id"] = self.company.pk
        session.save()

    def get_builder(self, **params):
        """GET the form builder page."""
        return self.client.get(reverse("leads:form_builder"), params)

    def test_company_without_a_saved_form_sees_every_field(self):
        """First-time creation lists the Lead fields as available to add."""
        response = self.get_builder()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-field="first_name"')
        self.assertContains(response, 'data-field="email"')

    def test_editing_a_saved_form_leaves_out_the_selected_fields(self):
        """When editing, a field already on the form is not offered again."""
        LeadCaptureForm.all_objects.create(
            company=self.company,
            form_name="Contact Us",
            selected_fields=json.dumps(["email"]),
            header_color="#ed4f38",
            success_message="Thanks",
            success_description="We will contact you.",
            lead_owner=self.user,
        )
        response = self.get_builder(edit=1)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-field="first_name"')
        self.assertNotContains(response, 'data-field="email"')


class WebToLeadRtlCssTests(SimpleTestCase):
    """Form preview and public-form labels are aligned in rtl.css."""

    def test_form_preview_rtl_rules_are_in_rtl_css(self):
        """rtl.css includes label alignment rules for form preview."""
        css_path = Path(settings.BASE_DIR) / "static" / "assets" / "css" / "rtl.css"
        css = css_path.read_text(encoding="utf-8")
        self.assertIn('[dir="rtl"] #formPreview label', css)
        self.assertIn('[dir="rtl"] .form-label', css)


@skipUnless(
    _FIELD_REQUIREMENTS_INSTALLED, "horilla.contrib.field_management not installed"
)
class FeatureRegistrationTests(SimpleTestCase):
    """Tests that field requirements is a selective feature, not a decorator."""

    def test_feature_is_registered(self):
        """The contrib app registers the feature against the shared registry."""
        self.assertEqual(FEATURE_CONFIG.get("field_requirements"), REGISTRY_KEY)

    def test_lead_and_opportunity_opt_in(self):
        """Lead and Opportunity are the models that opted in."""
        lead = apps.get_model("leads", "Lead")
        opportunity = apps.get_model("opportunities", "Opportunity")
        registered = FEATURE_REGISTRY.get(REGISTRY_KEY, [])

        self.assertIn(lead, registered)
        self.assertIn(opportunity, registered)
        self.assertTrue(is_requirement_configurable(lead))
        self.assertTrue(is_requirement_configurable(opportunity))

    def test_all_true_models_do_not_opt_in_automatically(self):
        """Models that did not opt in (Activity, User) are not configurable."""
        activity = apps.get_model("activity", "Activity")
        user = User
        registered = FEATURE_REGISTRY.get(REGISTRY_KEY, [])

        self.assertNotIn(activity, registered)
        self.assertNotIn(user, registered)
        self.assertFalse(is_requirement_configurable(activity))
        self.assertFalse(is_requirement_configurable(user))

    def test_configurable_models_lists_opted_in_models(self):
        """get_configurable_models returns the registry contents."""
        lead = apps.get_model("leads", "Lead")
        opportunity = apps.get_model("opportunities", "Opportunity")
        account = apps.get_model("accounts", "Account")
        activity = apps.get_model("activity", "Activity")
        configured = get_configurable_models()

        self.assertIn(lead, configured)
        self.assertIn(opportunity, configured)
        self.assertIn(account, configured)
        self.assertNotIn(activity, configured)

    def test_legacy_decorator_registry_does_not_exist(self):
        """Opt-in no longer lives in a dedicated registry module."""
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("horilla.registry.field_requirement_registry")

    def test_crm_model_modules_do_not_import_this_app(self):
        """Lead and Opportunity model files stay free of this feature."""
        lead = apps.get_model("leads", "Lead")
        opportunity = apps.get_model("opportunities", "Opportunity")
        self.assertNotIn("field_requirement", lead.__module__)
        self.assertNotIn("field_requirement", opportunity.__module__)

    def test_reverse_accessors_come_from_the_core_base_model(self):
        """The audit fields are inherited from HorillaCoreModel, not redeclared."""
        self.assertTrue(hasattr(Company, "fieldrequirement_set"))
        self.assertEqual(
            FieldRequirement._meta.get_field("created_by").remote_field.related_name,
            "fieldrequirement_created",
        )


@skipUnless(
    _FIELD_REQUIREMENTS_INSTALLED, "horilla.contrib.field_management not installed"
)
class LeadCanRelaxRequirementTests(SimpleTestCase):
    """Field-requirement relaxation rules, exercised against real Lead columns."""

    def test_lead_email_can_be_relaxed(self):
        """Lead.email is a text-like column, so making it optional is safe."""
        lead = apps.get_model("leads", "Lead")
        self.assertTrue(can_relax_requirement(lead._meta.get_field("email")))

    def test_lead_status_cannot_be_relaxed(self):
        """Lead Stage is a non-nullable FK with nowhere to store an empty value."""
        lead = apps.get_model("leads", "Lead")
        self.assertFalse(can_relax_requirement(lead._meta.get_field("lead_status")))


@skipUnless(
    _FIELD_REQUIREMENTS_INSTALLED, "horilla.contrib.field_management not installed"
)
class LeadConfigurableFieldsTests(SimpleTestCase):
    """Which Lead fields appear as configurable."""

    def test_lead_user_fields_are_configurable_and_audit_fields_are_not(self):
        """Lead email is offered; company, pk, and audit columns are not."""
        lead = apps.get_model("leads", "Lead")
        names = {field.name for field in get_configurable_fields(lead)}

        self.assertIn("email", names)
        self.assertIn("first_name", names)
        self.assertIn("lead_status", names)
        self.assertNotIn("id", names)
        self.assertNotIn("company", names)
        self.assertNotIn("created_at", names)
        self.assertNotIn("is_active", names)


def _activate_company(company):
    """Point CompanyFilteredManager at ``company`` for the current thread."""
    _thread_local.request = SimpleNamespace(
        active_company=company,
        session={},
        user=None,
    )


@skipUnless(
    _FIELD_REQUIREMENTS_INSTALLED, "horilla.contrib.field_management not installed"
)
class FieldRequirementModelTests(TestCase):
    """Tests for FieldRequirement.clean and unique_together."""

    def setUp(self):
        """Create a company and a Lead content type for the tests."""
        self.company = Company.objects.create(
            name="Acme",
            email="acme@example.com",
            country="US",
        )
        self.lead = apps.get_model("leads", "Lead")
        self.lead_ct = HorillaContentType.objects.get_for_model(self.lead)
        _activate_company(self.company)

    def tearDown(self):
        """Clear the thread-local request so that the next test does not see the previous test's company."""
        if hasattr(_thread_local, "request"):
            del _thread_local.request
        super().tearDown()

    def _requirement(self, **kwargs):
        """Return a FieldRequirement row for the Lead model, with optional extra kwargs."""
        defaults = {
            "content_type": self.lead_ct,
            "field_name": "email",
            "is_required": False,
            "company": self.company,
        }
        defaults.update(kwargs)
        return FieldRequirement(**defaults)

    def _clean(self, row):
        """Run model validation without Horilla audit FKs, which save() fills."""
        row.full_clean(exclude=["created_by", "updated_by"])

    def test_valid_optional_email_passes_clean(self):
        """Lead email can be stored as an empty string, so optional is allowed."""
        row = self._requirement()
        self._clean(row)

    def test_non_configurable_model_is_rejected(self):
        """Activity did not opt in, so it cannot have overrides."""
        activity = apps.get_model("activity", "Activity")
        row = self._requirement(
            content_type=HorillaContentType.objects.get_for_model(activity),
            field_name="email",
        )
        with self.assertRaises(ValidationError) as ctx:
            self._clean(row)
        self.assertIn("content_type", ctx.exception.error_dict)

    def test_unknown_field_is_rejected(self):
        """A field that is not on the model cannot be configured."""
        row = self._requirement(field_name="not_a_real_field")
        with self.assertRaises(ValidationError) as ctx:
            self._clean(row)
        self.assertIn("field_name", ctx.exception.error_dict)

    def test_excluded_audit_field_is_rejected(self):
        """Bookkeeping columns are never configurable."""
        row = self._requirement(field_name="company")
        with self.assertRaises(ValidationError) as ctx:
            self._clean(row)
        self.assertIn("field_name", ctx.exception.error_dict)

    def test_relaxing_lead_status_is_rejected(self):
        """A non-nullable FK has nowhere to store an empty value."""
        row = self._requirement(field_name="lead_status", is_required=False)
        with self.assertRaises(ValidationError) as ctx:
            self._clean(row)
        self.assertIn("is_required", ctx.exception.error_dict)

    def test_requiring_lead_status_is_allowed(self):
        """Making a field required never needs an empty-value storage path."""
        row = self._requirement(field_name="lead_status", is_required=True)
        self._clean(row)

    def test_duplicate_override_for_same_company_is_rejected(self):
        """One override per model, field, and company."""
        self._requirement().save()
        duplicate = self._requirement()
        with self.assertRaises(ValidationError) as ctx:
            self._clean(duplicate)
        self.assertIn("__all__", ctx.exception.error_dict)

    def test_same_field_can_be_configured_for_another_company(self):
        """Overrides are company-scoped."""
        self._requirement().save()
        other = Company.objects.create(
            name="Other Co",
            email="other@example.com",
            country="GB",
        )
        row = self._requirement(company=other)
        self._clean(row)
        row.save()
        self.assertEqual(
            FieldRequirement.all_objects.filter(field_name="email").count(),
            2,
        )


@skipUnless(
    _FIELD_REQUIREMENTS_INSTALLED, "horilla.contrib.field_management not installed"
)
class FieldRequirementResolverTests(TestCase):
    """Tests for get_field_requirements_for_model."""

    def setUp(self):
        """Create two companies and a Lead content type for the tests."""
        self.company_a = Company.objects.create(
            name="Company A",
            email="a@example.com",
            country="US",
        )
        self.company_b = Company.objects.create(
            name="Company B",
            email="b@example.com",
            country="GB",
        )
        self.lead = apps.get_model("leads", "Lead")
        self.lead_ct = HorillaContentType.objects.get_for_model(self.lead)
        _activate_company(self.company_a)

    def tearDown(self):
        """Clear the thread-local request so that the next test does not see the previous test's company."""
        if hasattr(_thread_local, "request"):
            del _thread_local.request
        super().tearDown()

    def _create(self, company, field_name, is_required, **kwargs):
        """Create a FieldRequirement row for the given company and field, with optional extra kwargs."""
        return FieldRequirement.objects.create(
            content_type=self.lead_ct,
            field_name=field_name,
            is_required=is_required,
            company=company,
            **kwargs,
        )

    def test_returns_empty_for_unconfigured_model(self):
        """No rows means no overrides."""
        self.assertEqual(get_field_requirements_for_model(self.lead), {})

    def test_returns_empty_for_non_configurable_model(self):
        """A model that is not opted in has no overrides."""
        activity = apps.get_model("activity", "Activity")
        self.assertEqual(get_field_requirements_for_model(activity), {})

    def test_returns_empty_for_none(self):
        """A missing model is treated as unconfigured."""
        self.assertEqual(get_field_requirements_for_model(None), {})

    def test_optional_email_override_is_returned(self):
        """A valid relaxation is exposed as False."""
        self._create(self.company_a, "email", False)
        self.assertEqual(
            get_field_requirements_for_model(self.lead),
            {"email": False},
        )

    def test_required_override_is_returned(self):
        """An explicit required row is exposed as True."""
        self._create(self.company_a, "title", True)
        self.assertEqual(
            get_field_requirements_for_model(self.lead),
            {"title": True},
        )

    def test_overrides_are_scoped_to_the_active_company(self):
        """Company B does not see Company A's rows."""
        self._create(self.company_a, "email", False)
        self._create(self.company_b, "title", True)

        self.assertEqual(
            get_field_requirements_for_model(self.lead),
            {"email": False},
        )

        _activate_company(self.company_b)
        self.assertEqual(
            get_field_requirements_for_model(self.lead),
            {"title": True},
        )

    def test_inactive_rows_are_ignored(self):
        """Soft-deactivated overrides do not apply."""
        self._create(self.company_a, "email", False, is_active=False)
        self.assertEqual(get_field_requirements_for_model(self.lead), {})

    def test_unsafe_relaxation_is_dropped(self):
        """A stale row that relaxes a non-nullable FK is not applied."""
        FieldRequirement.all_objects.create(
            content_type=self.lead_ct,
            field_name="lead_status",
            is_required=False,
            company=self.company_a,
        )
        self.assertEqual(get_field_requirements_for_model(self.lead), {})

    def test_unknown_field_row_is_dropped(self):
        """A row pointing at a removed field is skipped."""
        FieldRequirement.all_objects.create(
            content_type=self.lead_ct,
            field_name="removed_field",
            is_required=False,
            company=self.company_a,
        )
        self.assertEqual(get_field_requirements_for_model(self.lead), {})

    def test_request_cache_avoids_seeing_mid_request_writes(self):
        """The first resolve on a request is reused until the request ends."""
        self._create(self.company_a, "email", False)
        first = get_field_requirements_for_model(self.lead)
        self._create(self.company_a, "title", True)
        second = get_field_requirements_for_model(self.lead)
        self.assertEqual(first, {"email": False})
        self.assertEqual(second, {"email": False})

        delattr(_thread_local.request, "_field_requirement_overrides")
        self.assertEqual(
            get_field_requirements_for_model(self.lead),
            {"email": False, "title": True},
        )


@skipUnless(
    _FIELD_REQUIREMENTS_INSTALLED, "horilla.contrib.field_management not installed"
)
class FieldRequirementFormTests(TestCase):
    """Tests for the settings form and field picker labels."""

    def setUp(self):
        """Create a company and a superuser for the settings page tests, and log in."""
        self.lead = apps.get_model("leads", "Lead")
        self.lead_ct = HorillaContentType.objects.get_for_model(self.lead)
        self.other_model = apps.get_model("activity", "Activity")
        self.other_ct = HorillaContentType.objects.get_for_model(self.other_model)

    def test_field_picker_lists_lead_fields_and_marks_unsafe_ones(self):
        """Lead email is offered; Lead Stage is labelled always required."""
        choices = dict(get_field_choices(self.lead))
        self.assertIn("email", choices)
        self.assertIn("first_name", choices)
        self.assertIn("lead_status", choices)
        self.assertIn("always required", str(choices["lead_status"]).lower())
        self.assertNotIn("always required", str(choices["email"]).lower())

    def test_form_model_choices_are_limited_to_opted_in_models(self):
        """Activity did not opt in, so it is not a model the admin can pick."""
        form = FieldRequirementForm()
        pks = set(form.fields["content_type"].queryset.values_list("pk", flat=True))
        self.assertIn(self.lead_ct.pk, pks)
        self.assertNotIn(self.other_ct.pk, pks)

    def test_optional_email_is_valid(self):
        """The form accepts making Lead email optional."""
        form = FieldRequirementForm(
            data={
                "content_type": self.lead_ct.pk,
                "field_name": "email",
                "is_required": False,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_relaxing_lead_status_is_rejected(self):
        """The form refuses to make Lead Stage optional."""
        form = FieldRequirementForm(
            data={
                "content_type": self.lead_ct.pk,
                "field_name": "lead_status",
                "is_required": False,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("is_required", form.errors)

    def test_filter_model_choices_are_limited_to_opted_in_models(self):
        """Filter Records must not snapshot an empty Model queryset at import."""
        filterset = FieldRequirementFilter(data={})
        pks = set(
            filterset.filters["content_type"].field.queryset.values_list(
                "pk", flat=True
            )
        )
        self.assertIn(self.lead_ct.pk, pks)
        self.assertNotIn(self.other_ct.pk, pks)


def _create_company_and_user(*, superuser=True):
    """Create a company-scoped user for settings-page request tests."""
    company = Company.objects.create(
        name="Acme",
        email="acme@example.com",
        country="US",
    )
    create = User.objects.create_superuser if superuser else User.objects.create_user
    user = create(
        username="admin" if superuser else "staff",
        email="admin@example.com" if superuser else "staff@example.com",
        password="pass",
        company=company,
    )
    return company, user


@skipUnless(
    _FIELD_REQUIREMENTS_INSTALLED, "horilla.contrib.field_management not installed"
)
class FieldRequirementViewTests(TestCase):
    """HTTP tests for the settings page, field picker, and create flow."""

    @classmethod
    def setUpClass(cls):
        """Disconnect the login/logout signals so django-login-history does not KeyError on test client requests."""
        super().setUpClass()
        # django-login-history reads request.META['HTTP_USER_AGENT'] on
        # login/logout. Django's test client builds a bare HttpRequest, so
        # those signals KeyError unless they are disconnected here.
        user_logged_in.disconnect(post_login)
        user_logged_out.disconnect(post_logout)

    @classmethod
    def tearDownClass(cls):
        """Reconnect the login/logout signals so other tests are not broken."""
        user_logged_in.connect(post_login)
        user_logged_out.connect(post_logout)
        super().tearDownClass()

    def setUp(self):
        """Create a company and a superuser for the settings page tests, and log in."""
        self.company, self.user = _create_company_and_user()
        self.lead = apps.get_model("leads", "Lead")
        self.lead_ct = HorillaContentType.objects.get_for_model(self.lead)
        self.client.force_login(self.user)

    def _htmx(self):
        """Return a dict of headers that make the request look like HTMX."""
        return {"HTTP_HX_REQUEST": "true"}

    def test_anonymous_user_is_sent_to_login(self):
        """The settings page requires an authenticated user."""
        self.client.logout()
        response = self.client.get(reverse("field_management:field_requirement_view"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_user_without_permission_is_denied(self):
        """View permission is required to open the settings page."""
        _, staff = _create_company_and_user(superuser=False)
        staff.username = "viewer"
        staff.email = "viewer@example.com"
        staff.save()
        self.client.force_login(staff)
        response = self.client.get(reverse("field_management:field_requirement_view"))
        self.assertContains(response, "Permission Denied", status_code=200)

    def test_user_with_view_permission_can_open_the_page(self):
        """A non-superuser with the view permission sees the settings shell."""
        _, staff = _create_company_and_user(superuser=False)
        staff.username = "allowed"
        staff.email = "allowed@example.com"
        staff.save()
        staff.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="field_management",
                codename="view_fieldrequirement",
            )
        )
        self.client.force_login(staff)
        response = self.client.get(reverse("field_management:field_requirement_view"))
        self.assertContains(response, "field-requirement-view")

    def test_settings_page_renders_the_shell(self):
        """The page includes the HTMX shell the settings sidebar swaps in."""
        response = self.client.get(reverse("field_management:field_requirement_view"))
        self.assertContains(response, 'id="field-requirement-view"')
        self.assertContains(
            response, reverse("field_management:field_requirement_nav_view")
        )
        self.assertContains(
            response, reverse("field_management:field_requirement_list_view")
        )

    def test_list_without_htmx_is_rejected(self):
        """Navbar and list fragments are HTMX-only."""
        response = self.client.get(
            reverse("field_management:field_requirement_list_view")
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Method Not Allowed")

    def test_list_view_includes_existing_override(self):
        """A saved Lead email override appears on the list."""
        row = FieldRequirement.objects.create(
            content_type=self.lead_ct,
            field_name="email",
            is_required=False,
            company=self.company,
        )
        response = self.client.get(
            reverse("field_management:field_requirement_list_view"),
            **self._htmx(),
        )
        self.assertContains(response, "Email")
        self.assertContains(response, "Optional")
        self.assertContains(response, str(row.get_edit_url()))
        self.assertContains(response, str(row.get_delete_url()))

    def test_field_choices_list_lead_fields(self):
        """Selecting Lead fills the field picker with Lead columns."""
        response = self.client.get(
            reverse("field_management:field_requirement_field_choices"),
            {"content_type": self.lead_ct.pk},
            **self._htmx(),
        )
        self.assertContains(response, 'value="email"')
        self.assertContains(response, 'value="first_name"')
        self.assertContains(response, 'value="lead_status"')
        self.assertContains(response, "always required")

    def test_create_optional_lead_email(self):
        """Posting Lead → Email → Optional stores the override for the company."""
        response = self.client.post(
            reverse("field_management:field_requirement_create_form"),
            {
                "content_type": self.lead_ct.pk,
                "field_name": "email",
            },
            **self._htmx(),
        )
        self.assertEqual(response.status_code, 200)
        row = FieldRequirement.objects.get(
            content_type=self.lead_ct, field_name="email", company=self.company
        )
        self.assertFalse(row.is_required)

    def test_create_rejects_optional_lead_status(self):
        """Posting Lead Stage as optional is refused and stores nothing."""
        response = self.client.post(
            reverse("field_management:field_requirement_create_form"),
            {
                "content_type": self.lead_ct.pk,
                "field_name": "lead_status",
            },
            **self._htmx(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "empty value")
        self.assertFalse(
            FieldRequirement.objects.filter(field_name="lead_status").exists()
        )

    def test_settings_page_is_linked_from_the_settings_shell(self):
        """Settings → Field Requirements is in the sidebar for a permitted user."""
        response = self.client.get(reverse("core:settings_view"))
        self.assertContains(
            response, reverse("field_management:field_requirement_view")
        )
        self.assertContains(response, "Field Requirements")

    def test_filter_records_model_select2_lists_lead(self):
        """Filter Records → Model → Equals loads opted-in models, not an empty list."""
        response = self.client.get(
            reverse(
                "generics:model_select2",
                kwargs={"app_label": "core", "model_name": "HorillaContentType"},
            ),
            {
                "q": "",
                "page": 1,
                "field_name": "content_type",
                "filter_class": (
                    "horilla.contrib.field_management.filters." "FieldRequirementFilter"
                ),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        texts = [row["text"] for row in payload["results"]]
        ids = [row["id"] for row in payload["results"]]
        self.assertIn("Lead", texts)
        self.assertIn(self.lead_ct.pk, ids)

    def test_filter_records_model_select2_search_finds_lead(self):
        """Typing Lead in the Model value picker still matches after opt-in."""
        response = self.client.get(
            reverse(
                "generics:model_select2",
                kwargs={"app_label": "core", "model_name": "HorillaContentType"},
            ),
            {
                "q": "Lead",
                "page": 1,
                "field_name": "content_type",
                "filter_class": (
                    "horilla.contrib.field_management.filters." "FieldRequirementFilter"
                ),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        texts = [row["text"] for row in response.json()["results"]]
        self.assertIn("Lead", texts)


@skipUnless(
    _FIELD_REQUIREMENTS_INSTALLED, "horilla.contrib.field_management not installed"
)
class LeadFieldRequirementFormExtensionTests(TestCase):
    """Tests that stored overrides actually change Lead forms."""

    def setUp(self):
        """Create a company, user, and LeadStatus for the tests. Activate the company so that the form resolver sees it. Register the form extensions and apply them to the Lead forms."""
        self.company = Company.objects.create(
            name="Acme",
            email="acme@example.com",
            country="US",
        )
        self.other_company = Company.objects.create(
            name="Other Co",
            email="other@example.com",
            country="GB",
        )
        self.user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
            company=self.company,
        )
        self.lead = apps.get_model("leads", "Lead")
        self.lead_ct = HorillaContentType.objects.get_for_model(self.lead)
        self.status = apps.get_model("leads", "LeadStatus").objects.create(
            name="New",
            order=1,
            probability=10,
            company=self.company,
        )
        _activate_company(self.company)
        register_discovered_form_extensions()
        apply_form_extensions(force=True)

    def tearDown(self):
        """Clear the thread-local request so that the next test does not see the previous test's company."""
        if hasattr(_thread_local, "request"):
            del _thread_local.request
        super().tearDown()

    def _override(self, field_name, is_required, *, company=None):
        """Create a FieldRequirement row for the given field and requirement, scoped to the given company or self.company."""
        return FieldRequirement.objects.create(
            content_type=self.lead_ct,
            field_name=field_name,
            is_required=is_required,
            company=company or self.company,
        )

    def _lead_single_form(self, data=None):
        """Return a LeadSingleForm instance with optional data."""
        from ..forms import LeadSingleForm

        return resolve_form_class(LeadSingleForm)(data=data)

    def _lead_multi_form(self, *, step, data=None):
        """Return a LeadFormClass instance for the given wizard step, with optional data."""
        from ..forms import LeadFormClass

        return resolve_form_class(LeadFormClass)(data=data, step=step)

    def _lead_payload(self, email=""):
        """Return a valid payload for the Lead form, with an optional email override."""
        return {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": email,
            "lead_source": "website",
            "lead_status": self.status.pk,
            "lead_company": "Analytical Engines",
            "industry": "education",
            "country": "US",
            "lead_owner": self.user.pk,
        }

    def test_resolve_returns_a_composed_lead_form(self):
        """Views call resolve_form_class; the result is the composed subclass."""
        from ..forms import LeadFormClass, LeadSingleForm

        single = resolve_form_class(LeadSingleForm)
        multi = resolve_form_class(LeadFormClass)
        self.assertTrue(getattr(single, "__horilla_composed__", False))
        self.assertTrue(getattr(multi, "__horilla_composed__", False))
        self.assertTrue(single.__name__.endswith("Extended"))
        self.assertIsNot(single, LeadSingleForm)

    def test_email_stays_required_without_an_override(self):
        """Lead.email is blank=False, so the form still requires it by default."""
        form = self._lead_single_form()
        self.assertTrue(form.fields["email"].required)

        bound = self._lead_single_form(data=self._lead_payload(email=""))
        self.assertFalse(bound.is_valid())
        self.assertIn("email", bound.errors)

    def test_optional_email_is_not_required_on_lead_single_form(self):
        """A company-scoped optional email row drops required on LeadSingleForm."""
        self._override("email", False)
        form = self._lead_single_form()
        self.assertFalse(form.fields["email"].required)
        self.assertNotIn("required", form.fields["email"].widget.attrs)

    def test_optional_email_allows_an_empty_value_to_validate(self):
        """Empty email must pass both form and model validation when optional."""
        self._override("email", False)
        form = self._lead_single_form(data=self._lead_payload(email=""))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data.get("email") or "", "")

    def test_optional_email_does_not_apply_to_another_company(self):
        """Company B still requires email when only Company A stored an override."""
        self._override("email", False)
        _activate_company(self.other_company)
        form = self._lead_single_form()
        self.assertTrue(form.fields["email"].required)

    def test_optional_email_applies_to_the_multi_step_lead_form(self):
        """LeadFormClass is discovered the same way as the single-step form."""
        self._override("email", False)
        form = self._lead_multi_form(step=1)
        self.assertFalse(form.fields["email"].required)

    def test_required_override_does_not_rerequire_hidden_wizard_steps(self):
        """Title is on step 1; a required override must not break step 2."""
        self._override("title", True)
        step_two = self._lead_multi_form(step=2)
        self.assertIn("title", step_two._step_hidden_fields)
        self.assertFalse(step_two.fields["title"].required)

        step_one = self._lead_multi_form(step=1)
        self.assertTrue(step_one.fields["title"].required)

    def test_optional_email_on_step_one_stays_optional_on_later_steps(self):
        """Hidden wizard fields stay optional when the override relaxes them."""
        self._override("email", False)
        form = self._lead_multi_form(step=2)
        self.assertFalse(form.fields["email"].required)

    def test_optional_email_lead_saves_to_the_database(self):
        """An optional empty email must persist, not just pass form.is_valid()."""
        self._override("email", False)
        form = self._lead_single_form(data=self._lead_payload(email=""))
        self.assertTrue(form.is_valid(), form.errors)
        lead = form.save(commit=False)
        lead.company = self.company
        lead.created_by = self.user
        lead.updated_by = self.user
        lead.save()
        saved = self.lead.all_objects.get(pk=lead.pk)
        self.assertEqual(saved.email, "")
        self.assertEqual(saved.first_name, "Ada")

    def test_lead_without_override_cannot_be_saved_with_empty_email(self):
        """Default Lead email still cannot be stored empty."""
        form = self._lead_single_form(data=self._lead_payload(email=""))
        self.assertFalse(form.is_valid())
        self.assertFalse(self.lead.all_objects.filter(first_name="Ada").exists())

    def _login_client(self):
        """Log in through the test client and point it at this company."""
        user_logged_in.disconnect(post_login)
        user_logged_out.disconnect(post_logout)
        self.addCleanup(user_logged_in.connect, post_login)
        self.addCleanup(user_logged_out.connect, post_logout)
        self.client.force_login(self.user)
        session = self.client.session
        session["active_company_id"] = self.company.pk
        session.save()

    def _lead_create(self, method, data=None):
        """Hit the Lead single-create view the way the UI does (HTMX + section)."""
        url = reverse("leads:leads_create_single") + "?section=sales"
        headers = {"HTTP_HX_REQUEST": "true"}
        if method == "get":
            return self.client.get(url, **headers)
        return self.client.post(url, data, **headers)

    def test_create_view_uses_composed_form_with_optional_email(self):
        """The Lead create view resolves the FormExtension and drops email required."""
        self._override("email", False)
        self._login_client()
        response = self._lead_create("get")
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertTrue(getattr(form.__class__, "__horilla_composed__", False))
        self.assertFalse(form.fields["email"].required)

    def test_create_view_saves_a_lead_without_email_when_optional(self):
        """Posting the real create view with empty email stores the lead."""
        self._override("email", False)
        self._login_client()
        response = self._lead_create("post", self._lead_payload(email=""))
        self.assertNotEqual(response.status_code, 500)
        saved = self.lead.all_objects.filter(first_name="Ada", last_name="Lovelace")
        self.assertEqual(saved.count(), 1, response.content[:2000])
        self.assertEqual(saved.get().email, "")

    def test_create_view_still_requires_email_without_an_override(self):
        """The same create view rejects empty email when nothing is configured."""
        self._login_client()
        response = self._lead_create("post", self._lead_payload(email=""))
        self.assertFalse(
            self.lead.all_objects.filter(
                first_name="Ada", last_name="Lovelace"
            ).exists(),
            response.content[:2000],
        )


@skipUnless(
    _FIELD_REQUIREMENTS_INSTALLED, "horilla.contrib.field_management not installed"
)
class LeadFormExtensionDiscoveryTests(TestCase):
    """Discovery registers Lead's own forms, and correctly excludes LeadStatus."""

    def setUp(self):
        """Force discovery to run so we can inspect the registry."""
        register_discovered_form_extensions()
        apply_form_extensions(force=True)

    def test_discovery_registers_lead_forms_only(self):
        """Lead create-edit forms are extended; LeadStatus is not."""
        discovered = {
            f"{form.__module__}.{form.__name__}"
            for form in iter_configurable_model_forms()
        }
        self.assertIn("horilla_crm.leads.forms.LeadSingleForm", discovered)
        self.assertIn("horilla_crm.leads.forms.LeadFormClass", discovered)
        self.assertNotIn("horilla_crm.leads.forms.LeadStatusForm", discovered)

        self.assertIn("horilla_crm.leads.forms.LeadSingleForm", FORM_EXTENSION_REGISTRY)
        self.assertNotIn(
            "horilla_crm.leads.forms.LeadStatusForm", FORM_EXTENSION_REGISTRY
        )
