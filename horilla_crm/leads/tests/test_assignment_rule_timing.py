"""
Regression test for the Lead assignment-rule / custom-field save-ordering race.

Custom field values are written by ``form.save_m2m()``, which the Lead create
views call *after* ``instance.save()``. The assignment-rule engine is wired to
``Lead``'s ``post_save`` signal via ``transaction.on_commit()``. Outside an
atomic block, Django runs ``on_commit`` callbacks immediately, so without the
``transaction.atomic`` wrap on ``LeadFormView``/``LeadsSingleFormView``
``form_valid`` (see ``horilla_crm/leads/views/lead_actions.py``), a rule
keyed on a custom field would always evaluate against an empty value on
create -- never matching -- even though the same rule matches correctly once
the lead is later edited (by which point the custom field row exists).

``TransactionTestCase`` (not ``TestCase``) is required: ``TestCase`` wraps
every test in an outer atomic block, so Django defers *all*
``transaction.on_commit()`` callbacks to test teardown (where they're rolled
back and never run) regardless of any nested ``atomic()`` in the view under
test -- it can't distinguish "ran immediately" from "ran after form_valid()".
``TransactionTestCase`` uses real commits, reproducing the autocommit timing
production actually sees.
"""

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.test import TransactionTestCase
from login_history.models import post_login, post_logout

from horilla.auth.models import User
from horilla.contrib.core.models import Company, HorillaContentType
from horilla.contrib.field_management.models import CustomFieldDefinition
from horilla.contrib.utils.middlewares import _thread_local
from horilla.urls import reverse
from horilla_crm.leads.models import (
    Lead,
    LeadAssignmentCondition,
    LeadAssignmentMatchCriteria,
    LeadAssignmentRule,
    LeadStatus,
)


class LeadAssignmentRuleCustomFieldTimingTests(TransactionTestCase):
    """A custom-field-keyed rule must win over a manual pick on create, not just on edit."""

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
        """Create a company, a superuser, a manual-pick user, a rule-target user, a lead status, a custom field definition, and an assignment rule keyed on that custom field."""
        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        self.admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
            company=self.company,
        )
        self.manual_pick = User.objects.create_user(
            username="manual",
            email="manual@example.com",
            password="pass",
            company=self.company,
        )
        self.rule_target = User.objects.create_user(
            username="target",
            email="target@example.com",
            password="pass",
            company=self.company,
        )
        self.status = LeadStatus.objects.create(
            name="New", order=1, probability=10, company=self.company
        )

        lead_ct = HorillaContentType.objects.get_for_model(Lead)
        self.product_field = CustomFieldDefinition.objects.create(
            content_type=lead_ct,
            name="Product",
            field_type="choice",
            choices="Widget Pro,Other",
            company=self.company,
        )

        rule = LeadAssignmentRule.objects.create(
            name="Widget Pro goes to target", company=self.company
        )
        condition = LeadAssignmentCondition.objects.create(
            rule=rule, assign_to_type="user", company=self.company
        )
        condition.assign_to_users.add(self.rule_target)
        LeadAssignmentMatchCriteria.objects.create(
            condition=condition,
            field=f"cf_{self.product_field.pk}",
            operator="icontains",
            value="Widget Pro",
            company=self.company,
        )

        self.client.force_login(self.admin)

    def tearDown(self):
        """Clear the thread-local request so that the next test does not see the previous test's company."""
        if hasattr(_thread_local, "request"):
            del _thread_local.request
        super().tearDown()

    def _payload(self, **overrides):
        """Return a payload for creating a lead, with optional overrides."""
        payload = {
            "lead_owner": self.manual_pick.pk,
            "title": "Prospect",
            "first_name": "Sara",
            "last_name": "Ahmadi",
            "email": "sara@example.com",
            "lead_source": "website",
            "lead_status": self.status.pk,
            "lead_company": "Example Ltd",
            "industry": "other",
            "country": "US",
            f"cf_{self.product_field.pk}": ["Widget Pro"],
        }
        payload.update(overrides)
        return payload

    def test_matching_custom_field_reassigns_owner_on_create(self):
        """A create-time rule match must override the manually picked owner."""
        response = self.client.post(
            reverse("leads:leads_create_single"),
            self._payload(),
            HTTP_HX_REQUEST="true",
        )

        self.assertIn("HX-Redirect", response)
        lead = Lead.objects.get(email="sara@example.com")
        self.assertEqual(lead.lead_owner_id, self.rule_target.pk)

    def test_non_matching_custom_field_keeps_manual_pick_on_create(self):
        """No rule match on create must leave the manually picked owner alone."""
        response = self.client.post(
            reverse("leads:leads_create_single"),
            self._payload(**{f"cf_{self.product_field.pk}": ["Other"]}),
            HTTP_HX_REQUEST="true",
        )

        self.assertIn("HX-Redirect", response)
        lead = Lead.objects.get(email="sara@example.com")
        self.assertEqual(lead.lead_owner_id, self.manual_pick.pk)
