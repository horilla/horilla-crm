"""Tests for Opportunity field requirements and the phone mode."""

from types import SimpleNamespace
from unittest import skipUnless

from django.contrib.auth.models import Permission
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from login_history.models import post_login, post_logout

from horilla.apps import apps
from horilla.auth.models import User
from horilla.contrib.core.models import Company, HorillaContentType
from horilla.contrib.utils.middlewares import _thread_local
from horilla.extension.forms import resolve_form_class
from horilla.extension.forms.bootstrap import apply_form_extensions
from horilla.extension.forms.registry import FORM_EXTENSION_REGISTRY
from horilla.registry.delivery import (
    ADDRESS_PHONE,
    DeliveryChannel,
    get_delivery_channel,
)
from horilla_crm.contacts.models import Contact
from horilla_crm.opportunities.models import (
    Opportunity,
    OpportunityContactRole,
    OpportunityStage,
)

_FIELD_REQUIREMENTS_INSTALLED = apps.is_installed("horilla.contrib.field_management")

if _FIELD_REQUIREMENTS_INSTALLED:
    from horilla.contrib.field_management.extensions.field_requirements import (
        iter_configurable_model_forms,
        register_discovered_form_extensions,
    )
    from horilla.contrib.field_management.models import FieldRequirement


def _activate_company(company):
    """Point CompanyFilteredManager at ``company`` for the current thread."""
    from types import SimpleNamespace

    _thread_local.request = SimpleNamespace(
        active_company=company,
        session={},
        user=None,
    )


@skipUnless(
    _FIELD_REQUIREMENTS_INSTALLED, "horilla.contrib.field_management not installed"
)
class OpportunityFieldRequirementFormExtensionTests(TestCase):
    """Tests that stored overrides actually change Opportunity forms."""

    def setUp(self):
        self.company = Company.objects.create(
            name="Acme",
            email="acme@example.com",
            country="US",
        )
        self.user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
            company=self.company,
        )
        self.opportunity = apps.get_model("opportunities", "Opportunity")
        self.opportunity_ct = HorillaContentType.objects.get_for_model(self.opportunity)
        _activate_company(self.company)
        register_discovered_form_extensions()
        apply_form_extensions(force=True)

    def tearDown(self):
        if hasattr(_thread_local, "request"):
            del _thread_local.request
        super().tearDown()

    def _override(self, field_name, is_required):
        return FieldRequirement.objects.create(
            content_type=self.opportunity_ct,
            field_name=field_name,
            is_required=is_required,
            company=self.company,
        )

    def test_required_description_override_on_opportunity_form(self):
        """A blank=True field can be made required without touching the model."""
        self._override("description", True)
        from horilla_crm.opportunities.forms import OpportunitySingleForm

        form = resolve_form_class(OpportunitySingleForm)()
        self.assertTrue(form.fields["description"].required)

    def test_opportunity_email_override_applies_on_create_form(self):
        """Opportunity create/edit forms show email, so a required override applies there."""
        self._override("email", True)
        from horilla_crm.opportunities.forms import OpportunitySingleForm

        form = resolve_form_class(OpportunitySingleForm)()
        self.assertIn("email", form.fields)
        self.assertTrue(form.fields["email"].required)


@skipUnless(
    _FIELD_REQUIREMENTS_INSTALLED, "horilla.contrib.field_management not installed"
)
class OpportunityFormExtensionDiscoveryTests(TestCase):
    """Discovery registers Opportunity's own forms."""

    def setUp(self):
        register_discovered_form_extensions()
        apply_form_extensions(force=True)

    def test_discovery_registers_opportunity_forms(self):
        """Opportunity and Account create-edit forms are extended."""
        discovered = {
            f"{form.__module__}.{form.__name__}"
            for form in iter_configurable_model_forms()
        }
        self.assertIn(
            "horilla_crm.opportunities.forms.OpportunitySingleForm", discovered
        )
        self.assertIn(
            "horilla_crm.opportunities.forms.OpportunityFormClass", discovered
        )
        self.assertIn("horilla_crm.accounts.forms.AccountFormClass", discovered)

        self.assertIn(
            "horilla_crm.accounts.forms.AccountFormClass", FORM_EXTENSION_REGISTRY
        )


_MOBILE_INSTALLED = apps.is_installed("horilla.contrib.mobile")


@skipUnless(_MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
class OpportunityOnThePhoneTests(TestCase):
    """
    An opportunity owner finds and opens their opportunity in the optional
    phone mode, with the settings in ``opportunities/mobile.py``.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # django-login-history reads request.META['HTTP_USER_AGENT'] on
        # login/logout, which the test client's bare request doesn't set.
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
        self.seller = User.objects.create_user(
            username="seller",
            email="seller@example.com",
            password="pass",
            company=self.company,
        )
        permission, _created = Permission.objects.get_or_create(
            codename="view_own_opportunity",
            content_type=ContentType.objects.get_for_model(Opportunity),
            defaults={"name": "Can view own opportunity"},
        )
        self.seller.user_permissions.add(permission)
        stage = OpportunityStage.objects.create(
            name="Needs Analysis", order=1, probability=30, company=self.company
        )
        self.opportunity = Opportunity.objects.create(
            name="License renewal",
            email="it@example.com",
            stage=stage,
            owner=self.seller,
            company=self.company,
        )
        self.client.force_login(self.seller)

    def test_the_list_shows_the_opportunity_and_its_stage(self):
        response = self.client.get(
            "/m/records/", {"model": "opportunities.opportunity"}
        )
        self.assertContains(response, "License renewal")
        self.assertContains(response, "Needs Analysis")

    def test_the_opportunity_page_has_email_and_the_stage(self):
        response = self.client.get(
            f"/m/records/opportunities/opportunity/{self.opportunity.pk}/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="mailto:it@example.com"')
        self.assertEqual(response.context["status"]["field"], "stage")


class PrimaryContactPhoneChannel(DeliveryChannel):
    """A phone channel, like an SMS app would register; sends nothing."""

    key = "primary_contact_test_sms"
    label = "Test SMS"
    address_kind = ADDRESS_PHONE

    def send(self, automation, instance, recipients, context, user):
        """Not used: these tests only read and resolve recipients."""


class OpportunityPrimaryContactRecipientTests(TestCase):
    """
    The opportunity's primary contact is offered in the "Send to" picker of
    mail and phone channels, and resolves through ``Opportunity.primary_contact``.
    """

    def setUp(self):
        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        self.seller = User.objects.create_user(
            username="seller",
            email="seller@example.com",
            password="pass",
            company=self.company,
        )
        stage = OpportunityStage.objects.create(
            name="Needs Analysis", order=1, probability=30, company=self.company
        )
        self.opportunity = Opportunity.objects.create(
            name="License renewal", stage=stage, owner=self.seller, company=self.company
        )
        self.buyer = self.contact("Sara", "09121111111", "sara@example.com")
        self.other = self.contact("Reza", "09122222222", "reza@example.com")
        self.sms = PrimaryContactPhoneChannel()
        self.mail = get_delivery_channel("mail")

    def contact(self, name, phone, email):
        return Contact.objects.create(
            first_name=name,
            last_name="Test",
            email=email,
            contact_number=phone,
            contact_owner=self.seller,
            company=self.company,
        )

    def role(self, contact, is_primary=True, **fields):
        return OpportunityContactRole.objects.create(
            contact=contact,
            opportunity=self.opportunity,
            is_primary=is_primary,
            company=self.company,
            **fields,
        )

    def send_to(self, channel, spec):
        opportunity = Opportunity.all_objects.get(pk=self.opportunity.pk)
        return channel.resolve_recipients(spec, opportunity, None)

    def test_the_picker_offers_the_primary_contact(self):
        sms = dict(self.sms.get_recipient_choices(Opportunity))
        self.assertEqual(
            str(sms["instance.primary_contact.contact_number"]),
            "Primary Contact - Contact Number",
        )
        self.assertIn("instance.primary_contact.secondary_contact_number", sms)
        # The account phone from the relation one away is still there.
        self.assertIn("instance.account.contact_number", sms)
        mail = dict(self.mail.get_recipient_choices(Opportunity))
        self.assertIn("instance.primary_contact.email", mail)
        notification = dict(
            get_delivery_channel("notification").get_recipient_choices(Opportunity)
        )
        self.assertFalse([key for key in notification if "primary_contact" in key])

    def test_the_primary_contact_receives_the_message(self):
        self.role(self.other, is_primary=False)
        self.role(self.buyer)
        self.assertEqual(
            self.send_to(self.sms, "instance.primary_contact.contact_number"),
            ["09121111111"],
        )
        self.assertEqual(
            self.send_to(self.mail, "instance.primary_contact.email"),
            ["sara@example.com"],
        )

    def test_without_a_primary_contact_nobody_is_sent_to(self):
        self.assertEqual(
            self.send_to(self.sms, "instance.primary_contact.contact_number"), []
        )
        self.role(self.other, is_primary=False)
        self.assertIsNone(self.opportunity.primary_contact)
        self.assertEqual(
            self.send_to(self.sms, "instance.primary_contact.contact_number"), []
        )

    def test_a_primary_contact_without_a_phone_gives_nobody(self):
        self.buyer.contact_number = ""
        self.buyer.save()
        self.role(self.buyer)
        self.assertEqual(
            self.send_to(self.sms, "instance.primary_contact.contact_number"), []
        )

    def test_several_primary_roles_use_the_one_added_first(self):
        self.role(self.other)
        self.role(self.buyer)
        self.assertEqual(self.opportunity.primary_contact, self.other)

    def test_inactive_roles_and_contacts_are_skipped(self):
        self.role(self.other, is_active=False)
        self.role(self.buyer)
        self.assertEqual(self.opportunity.primary_contact, self.buyer)
        Contact.all_objects.filter(pk=self.buyer.pk).update(is_active=False)
        self.assertIsNone(self.opportunity.primary_contact)

    def test_an_unsaved_opportunity_has_none_and_reads_nothing(self):
        with self.assertNumQueries(0):
            self.assertIsNone(Opportunity(name="Draft").primary_contact)

    def test_read_without_the_active_company_filter(self):
        """Workflow and Cadences may send while another company is active."""
        self.role(self.buyer)
        other = Company.objects.create(
            name="Other", email="other@example.com", country="US"
        )
        previous = getattr(_thread_local, "request", None)
        _thread_local.request = SimpleNamespace(active_company=other, user=None)
        try:
            self.assertEqual(self.opportunity.primary_contact, self.buyer)
        finally:
            _thread_local.request = previous
