"""
Tests for "Assign using rules" on the lead create forms.
"""

# Standard library imports
from types import SimpleNamespace
from unittest import mock

# Third-party imports (Django)
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db import connection
from django.test import RequestFactory, SimpleTestCase, TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from login_history.models import post_login, post_logout

from horilla.apps import apps
from horilla.auth.models import User
from horilla.contrib.core.models import Company, HorillaContentType, Role

# First party imports (Horilla)
from horilla.contrib.field_management.models import CustomFieldDefinition
from horilla.contrib.utils.middlewares import _thread_local
from horilla.extension.forms.resolve import resolve_form_class
from horilla.urls import reverse
from horilla_crm.leads.assignment.evaluation import (
    Match,
    compare,
    condition_result,
    criterion_result,
    explain_failure,
    normalise,
)
from horilla_crm.leads.assignment.pool import (
    MATCHED,
    NO_ASSIGNEES,
    NO_MATCH,
    UNDETERMINED,
    condition_users,
    pick_least_loaded,
    resolve_for_data,
)
from horilla_crm.leads.form_mixins import APPLY_FIELD
from horilla_crm.leads.forms import LeadSingleForm
from horilla_crm.leads.models import (
    Lead,
    LeadAssignmentCondition,
    LeadAssignmentMatchCriteria,
    LeadAssignmentRule,
    LeadStatus,
)

NOT_MATCHING = "does not satisfy any active assignment rule"


def _disconnect_login_history():
    """django-login-history needs HTTP_USER_AGENT, which the test client lacks."""
    user_logged_in.disconnect(post_login)
    user_logged_out.disconnect(post_logout)


def _reconnect_login_history():
    user_logged_in.connect(post_login)
    user_logged_out.connect(post_logout)


# ---------------------------------------------------------------------------
# Evaluation (no database)
# ---------------------------------------------------------------------------


def _criteria(field, operator, value, logical_operator="and"):
    """A stand-in for a LeadAssignmentMatchCriteria row."""
    return SimpleNamespace(
        field=field,
        operator=operator,
        value=value,
        logical_operator=logical_operator,
        get_field_label=lambda: field.replace("_", " ").title(),
        get_display_value=lambda: value or "-",
    )


def _condition(*rows):
    """A stand-in for a LeadAssignmentCondition with the given criteria rows."""
    return SimpleNamespace(criteria=SimpleNamespace(all=lambda: list(rows)))


class CompareTests(SimpleTestCase):
    """``compare`` keeps the operator semantics the engine always had."""

    TABLE = [
        ("exact", "website", "website", True),
        ("exact", "Website", "website", False),
        ("ne", "website", "referral", True),
        ("ne", "website", "website", False),
        ("icontains", "Big Corp Ltd", "corp", True),
        ("icontains", "Big Corp Ltd", "acme", False),
        ("not_contains", "Big Corp Ltd", "acme", True),
        ("not_contains", "Big Corp Ltd", "corp", False),
        ("istartswith", "Big Corp", "BIG", True),
        ("istartswith", "Big Corp", "corp", False),
        ("iendswith", "Big Corp", "CORP", True),
        ("iendswith", "Big Corp", "big", False),
        ("isnull", "", "", True),
        ("isnull", "   ", "", True),
        ("isnull", "x", "", False),
        ("isnotnull", "x", "", True),
        ("isnotnull", "", "", False),
        ("gt", "10", "5", True),
        ("gt", "5", "5", False),
        ("gte", "5", "5", True),
        ("lt", "4", "5", True),
        ("lt", "5", "5", False),
        ("lte", "5", "5", True),
        ("gt", "abc", "5", False),
        ("between", "5", "1, 10", True),
        ("between", "11", "1, 10", False),
        ("between", "5", "1", False),
        ("between", "abc", "1,10", False),
        ("unknown-operator", "x", "x", False),
    ]

    def test_operator_table(self):
        """Each operator gives the same answer the engine gave before the move."""
        for operator, actual, expected, result in self.TABLE:
            with self.subTest(operator=operator, actual=actual, expected=expected):
                self.assertIs(compare(operator, actual, expected), result)

    def test_none_is_empty(self):
        """A missing value compares as an empty string."""
        self.assertTrue(compare("isnull", None, ""))
        self.assertFalse(compare("exact", None, "x"))


class NormaliseTests(SimpleTestCase):
    """``normalise`` turns form values into the strings the engine compares."""

    def test_values(self):
        """None, related objects, lists and plain values."""
        self.assertEqual(normalise(None), "")
        self.assertEqual(normalise(SimpleNamespace(pk=7)), "7")
        self.assertEqual(normalise(["a", "b"]), "a,b")
        self.assertEqual(normalise(12), "12")
        self.assertEqual(normalise(True), "True")


class ConditionFoldingTests(SimpleTestCase):
    """AND/OR folding, with values that are not known yet."""

    def test_known_values(self):
        """Left-to-right folding as the engine does it."""
        both = _condition(_criteria("a", "exact", "1"), _criteria("b", "exact", "2"))
        known = {"a": "1", "b": "2"}
        self.assertIs(condition_result(both, known, final=True), Match.YES)
        self.assertIs(condition_result(both, {**known, "b": "9"}, final=True), Match.NO)

        either = _condition(
            _criteria("a", "exact", "1"), _criteria("b", "exact", "2", "or")
        )
        second = {"a": "9", "b": "2"}
        self.assertIs(condition_result(either, second, final=True), Match.YES)
        self.assertIs(
            condition_result(either, {**second, "b": "9"}, final=True), Match.NO
        )

    def test_no_criteria_always_matches(self):
        """A condition without criteria matches every lead."""
        self.assertIs(condition_result(_condition(), {}, final=True), Match.YES)

    def test_unknown_only_decides_when_it_can(self):
        """UNKNOWN and NO is NO; UNKNOWN or YES is YES; otherwise UNKNOWN."""
        and_cond = _condition(
            _criteria("a", "exact", "1"), _criteria("b", "exact", "2")
        )
        self.assertIs(condition_result(and_cond, {"a": "9"}, final=False), Match.NO)
        self.assertIs(
            condition_result(and_cond, {"a": "1"}, final=False), Match.UNKNOWN
        )

        or_cond = _condition(
            _criteria("a", "exact", "1"), _criteria("b", "exact", "2", "or")
        )
        self.assertIs(condition_result(or_cond, {"a": "1"}, final=False), Match.YES)
        self.assertIs(condition_result(or_cond, {"a": "9"}, final=False), Match.UNKNOWN)

    def test_missing_value_is_empty_when_final(self):
        """With every value known, a missing key is an empty value."""
        row = _criteria("lead_source", "isnull", "")
        self.assertIs(criterion_result(row, {}, final=True), Match.YES)
        self.assertIs(criterion_result(row, {}, final=False), Match.UNKNOWN)

    def test_unknown_field_never_matches(self):
        """A criterion on a field the Lead does not have never matches."""
        row = _criteria("no_such_field", "isnull", "")
        self.assertIs(criterion_result(row, {}, final=True), Match.NO)

    def test_explain_failure(self):
        """The reason names the criteria that did not match."""
        cond = _condition(
            _criteria("lead_source", "exact", "website"),
            _criteria("industry", "exact", "education"),
        )
        text = explain_failure(
            cond, {"lead_source": "referral", "industry": "education"}, final=True
        )
        self.assertEqual(text, "Lead Source is not Website")


# ---------------------------------------------------------------------------
# Fixtures shared by the database tests
# ---------------------------------------------------------------------------


class AssignmentFixtureMixin:
    """A company, some people, and helpers to build rules and lead data."""

    def create_fixture(self):
        """Create the company, users, a lead stage and an empty rule set."""
        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        self.admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
            company=self.company,
        )
        self.sales_role = Role.objects.create(role_name="Sales", company=self.company)
        self.support_role = Role.objects.create(
            role_name="Support", company=self.company
        )
        self.sales = [
            self.make_user(f"sales{i}", role=self.sales_role) for i in range(3)
        ]
        self.support = self.make_user("support0", role=self.support_role)
        self.direct = self.make_user("direct")
        self.outsider = self.make_user("outsider")
        self.status = LeadStatus.objects.create(
            name="New", order=1, probability=10, company=self.company
        )

    def make_user(self, username, **extra):
        """Create an ordinary (non-superuser) user of the company."""
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="pass",
            company=self.company,
            **extra,
        )

    def add_condition(
        self,
        rule,
        criteria=(("lead_source", "exact", "website"),),
        users=(),
        roles=(),
        notify_method="",
    ):
        """Add a condition to ``rule``; rows are (field, op, value[, logic])."""
        condition = LeadAssignmentCondition.objects.create(
            rule=rule,
            assign_to_type="role" if roles else "user",
            notify_method=notify_method,
            company=self.company,
        )
        condition.assign_to_users.set(users)
        condition.assign_to_roles.set(roles)
        for row in criteria:
            field, operator, value, *logic = row
            LeadAssignmentMatchCriteria.objects.create(
                condition=condition,
                field=field,
                operator=operator,
                value=value,
                logical_operator=logic[0] if logic else "and",
                company=self.company,
            )
        return condition

    def make_rule(
        self, name="Website leads", *, active=True, rule=None, **condition_kwargs
    ):
        """Create a rule with one condition and return the condition.

        Only one rule of a company can be active, so pass ``rule`` to add a
        further condition to an existing rule.
        """
        if rule is None:
            rule = LeadAssignmentRule.objects.create(
                name=name, company=self.company, is_active=active
            )
        return self.add_condition(rule, **condition_kwargs)

    def lead_payload(self, **overrides):
        """Valid form data for a new lead (owner: the first sales user)."""
        payload = {
            "lead_owner": self.sales[0].pk,
            "first_name": "Sara",
            "last_name": "Ahmadi",
            "email": "sara@example.com",
            "lead_source": "website",
            "lead_status": self.status.pk,
            "lead_company": "Example Ltd",
            "industry": "other",
            "country": "US",
        }
        payload.update(overrides)
        return payload

    def request_for(self, user=None):
        """A request as the form sees it."""
        request = RequestFactory().get("/")
        request.user = user or self.admin
        request.active_company = self.company
        return request

    def single_form(self, data=None, user=None, **kwargs):
        """The single-step lead form as the view builds it."""
        form_class = resolve_form_class(LeadSingleForm)
        return form_class(data=data, request=self.request_for(user), **kwargs)

    def create_lead(self, owner, **overrides):
        """Create a lead for ``owner`` without going through a form."""
        values = {
            "lead_owner": owner,
            "first_name": "Seed",
            "last_name": "Lead",
            "email": "seed@example.com",
            "lead_source": "website",
            "lead_status": self.status,
            "lead_company": "Seed Ltd",
            "industry": "other",
            "country": "US",
            "company": self.company,
        }
        values.update(overrides)
        return Lead.all_objects.create(**values)


# ---------------------------------------------------------------------------
# Pool and resolution
# ---------------------------------------------------------------------------


class PoolTests(AssignmentFixtureMixin, TestCase):
    """Who a condition can assign to, and who is picked."""

    def setUp(self):
        """Create the company, users, and a lead stage."""
        self.create_fixture()

    def test_role_condition_uses_role_members_only(self):
        """A role condition assigns to the active members of its roles."""
        condition = self.make_rule(roles=[self.sales_role], users=[self.direct])
        pks = set(condition_users(condition).values_list("pk", flat=True))
        self.assertEqual(pks, {user.pk for user in self.sales})

    def test_user_condition_uses_selected_users(self):
        """A user condition assigns to the users picked on it."""
        condition = self.make_rule(users=[self.direct, self.outsider])
        pks = set(condition_users(condition).values_list("pk", flat=True))
        self.assertEqual(pks, {self.direct.pk, self.outsider.pk})

    def test_inactive_users_are_left_out(self):
        """Inactive people are never offered."""
        condition = self.make_rule(roles=[self.sales_role])
        User.objects.filter(pk=self.sales[0].pk).update(is_active=False)
        pks = set(condition_users(condition).values_list("pk", flat=True))
        self.assertNotIn(self.sales[0].pk, pks)

    def test_other_company_is_left_out_when_scoped(self):
        """With a company given, people of other companies are not offered."""
        other = Company.objects.create(
            name="Other", email="o@example.com", country="GB"
        )
        stranger = User.objects.create_user(
            username="stranger",
            email="stranger@example.com",
            password="pass",
            company=other,
            role=self.sales_role,
        )
        condition = self.make_rule(roles=[self.sales_role])
        scoped = condition_users(condition, self.company).values_list("pk", flat=True)
        unscoped = condition_users(condition).values_list("pk", flat=True)
        self.assertNotIn(stranger.pk, set(scoped))
        self.assertIn(stranger.pk, set(unscoped))

    def test_least_loaded_wins_and_ties_go_to_lowest_pk(self):
        """The person owning the fewest leads is picked; ties by pk."""
        users = User.objects.filter(pk__in=[u.pk for u in self.sales])
        self.assertEqual(pick_least_loaded(users), self.sales[0])

        self.create_lead(self.sales[0])
        self.create_lead(self.sales[0], email="two@example.com")
        self.create_lead(self.sales[1], email="three@example.com")
        self.assertEqual(pick_least_loaded(users), self.sales[2])

    def test_nobody_to_pick(self):
        """An empty pool has no least-loaded person."""
        self.assertIsNone(pick_least_loaded(User.objects.none()))


class ResolveTests(AssignmentFixtureMixin, TestCase):
    """``resolve_for_data`` follows the engine's "first match wins"."""

    def setUp(self):
        """Create the company, users, and a lead stage."""
        self.create_fixture()

    def test_matched(self):
        """The matching condition's people are the pool; least loaded preselected."""
        condition = self.make_rule(roles=[self.sales_role])
        self.create_lead(self.sales[0])
        result = resolve_for_data({"lead_source": "website"}, final=True)

        self.assertEqual(result.state, MATCHED)
        self.assertEqual(result.condition, condition)
        self.assertEqual(
            set(result.users.values_list("pk", flat=True)),
            {user.pk for user in self.sales},
        )
        self.assertEqual(result.default_owner, self.sales[1])
        self.assertEqual(result.rule, condition.rule)

    def test_first_matching_condition_wins(self):
        """Rules are tried by creation date; the first match decides."""
        first = self.make_rule("First", users=[self.direct])
        self.make_rule("Second", rule=first.rule, users=[self.outsider])
        result = resolve_for_data({"lead_source": "website"}, final=True)
        self.assertEqual(result.condition, first)

    def test_no_match_gives_a_reason(self):
        """When nothing matches the reason says which value is wrong."""
        self.make_rule(users=[self.direct])
        result = resolve_for_data({"lead_source": "referral"}, final=True)
        self.assertEqual(result.state, NO_MATCH)
        self.assertEqual(result.reason, "Lead Source is not Website")

    def test_inactive_rule_is_ignored(self):
        """Inactive rules never count."""
        self.make_rule(active=False, users=[self.direct])
        result = resolve_for_data({"lead_source": "website"}, final=True)
        self.assertEqual(result.state, NO_MATCH)

    def test_condition_without_people_is_skipped(self):
        """As in the engine, a match with nobody to assign to falls through."""
        self.make_rule("Empty", users=[])
        later = self.make_rule("Later", users=[self.direct])
        result = resolve_for_data({"lead_source": "website"}, final=True)
        self.assertEqual(result.state, MATCHED)
        self.assertEqual(result.condition, later)

    def test_only_conditions_without_people(self):
        """A match that has nobody to assign to is reported as such."""
        self.make_rule("Empty", users=[])
        result = resolve_for_data({"lead_source": "website"}, final=True)
        self.assertEqual(result.state, NO_ASSIGNEES)
        self.assertIn("Empty", result.reason)

    def test_undetermined_until_values_are_known(self):
        """A condition that depends on a missing value stays a candidate."""
        first = self.make_rule(
            "First",
            criteria=[
                ("lead_source", "exact", "website"),
                ("industry", "exact", "education"),
            ],
            users=[self.direct],
        )
        second = self.make_rule(
            "Second", rule=first.rule, criteria=[], users=[self.outsider]
        )
        result = resolve_for_data({"lead_source": "website"}, final=False)

        self.assertEqual(result.state, UNDETERMINED)
        self.assertEqual(result.conditions, [first, second])
        self.assertEqual(
            set(result.users.values_list("pk", flat=True)),
            {self.direct.pk, self.outsider.pk},
        )

    def test_groups_name_the_source(self):
        """The pool is listed by rule and role / users, each person once."""
        self.make_rule(roles=[self.sales_role])
        result = resolve_for_data({"lead_source": "website"}, final=True)
        labels = [label for label, _members in result.groups]
        self.assertEqual(labels, ["Website leads · Sales"])


# ---------------------------------------------------------------------------
# Single-step form
# ---------------------------------------------------------------------------


class SingleFormTests(AssignmentFixtureMixin, TestCase):
    """The option on the single-step lead form."""

    def setUp(self):
        """Create the company, users, and a lead stage."""
        self.create_fixture()

    def owner_pks(self, form):
        """Primary keys the form's owner field accepts."""
        return set(form.fields["lead_owner"].queryset.values_list("pk", flat=True))

    def test_field_absent_without_active_rule(self):
        """No rule at all, or only inactive rules: the form is as before."""
        self.assertNotIn(APPLY_FIELD, self.single_form().fields)

        self.make_rule(active=False, users=[self.direct])
        self.assertNotIn(APPLY_FIELD, self.single_form().fields)

    def test_field_absent_when_editing(self):
        """The option is only for new leads."""
        self.make_rule(users=[self.direct])
        lead = self.create_lead(self.direct)
        self.assertNotIn(APPLY_FIELD, self.single_form(instance=lead).fields)

    def test_checkbox_is_drawn_under_the_owner(self):
        """With an active rule the checkbox is drawn right under the owner select."""
        self.make_rule(users=[self.direct])
        form = self.single_form()
        html = str(form["lead_owner"])

        self.assertIn(f'name="{APPLY_FIELD}"', html)
        self.assertIn("Assign using rules", html)
        self.assertLess(html.index("<select"), html.index(f'name="{APPLY_FIELD}"'))
        # The form field only reads the checkbox; it draws nothing on its own.
        self.assertTrue(form[APPLY_FIELD].is_hidden)
        self.assertEqual(str(form[APPLY_FIELD]), "")

    def test_switch_off_leaves_the_owner_field_alone(self):
        """Unticked, the owner list and widget are what the form always had."""
        self.make_rule(roles=[self.sales_role])
        form = self.single_form(self.lead_payload())
        everyone = User.objects.filter(is_active=True, company=self.company)
        self.assertEqual(self.owner_pks(form), {user.pk for user in everyone})
        self.assertIn("data-url", str(form["lead_owner"]))

    def test_switch_on_limits_the_owner_to_the_pool(self):
        """Ticked, the owner is limited to the matching condition's people."""
        self.make_rule(roles=[self.sales_role])
        form = self.single_form(self.lead_payload(**{APPLY_FIELD: "on"}))
        self.assertTrue(form.is_valid(), form.errors)

        self.assertEqual(form.assignment_resolution.state, MATCHED)
        self.assertEqual(self.owner_pks(form), {user.pk for user in self.sales})
        html = str(form["lead_owner"])
        self.assertNotIn("data-url", html)
        self.assertNotIn("Website leads · Sales", html)
        self.assertNotIn("<optgroup", html)
        self.assertIn(f'<option value="{self.sales[1].pk}"', html)
        self.assertNotIn(f'<option value="{self.outsider.pk}"', html)

    def test_lead_that_matches_no_condition_is_rejected(self):
        """Ticked, a lead that fits no condition gets an explanation."""
        self.make_rule(users=[self.direct])
        form = self.single_form(
            self.lead_payload(
                lead_source="referral", lead_owner=self.direct.pk, **{APPLY_FIELD: "on"}
            )
        )
        self.assertFalse(form.is_valid())
        message = " ".join(form.non_field_errors())
        self.assertIn(NOT_MATCHING, message)
        self.assertIn("Lead Source is not Website", message)
        self.assertIn("untick", message)

    def test_unticked_lead_is_not_checked_against_rules(self):
        """Unticked, a lead that fits no condition is saved as usual."""
        self.make_rule(users=[self.direct])
        form = self.single_form(self.lead_payload(lead_source="referral"))
        self.assertTrue(form.is_valid(), form.errors)

    def test_owner_must_be_in_the_matching_pool(self):
        """A person of another condition is not accepted for this lead."""
        website = self.make_rule("Website", users=[self.direct])
        self.make_rule(
            "Referral",
            rule=website.rule,
            criteria=[("lead_source", "exact", "referral")],
            users=[self.outsider],
        )
        form = self.single_form(
            self.lead_payload(lead_owner=self.outsider.pk, **{APPLY_FIELD: "on"})
        )
        self.assertFalse(form.is_valid())
        self.assertIn("lead_owner", form.errors)
        self.assertIn("Website", form.errors["lead_owner"][0])

    def test_person_outside_every_pool_is_rejected(self):
        """Somebody no rule assigns to can not be chosen while the switch is on."""
        self.make_rule(users=[self.direct])
        form = self.single_form(
            self.lead_payload(lead_owner=self.outsider.pk, **{APPLY_FIELD: "on"})
        )
        self.assertFalse(form.is_valid())
        self.assertIn("lead_owner", form.errors)

    def test_pool_member_beyond_the_users_own_reach(self):
        """
        A user who may only assign to themselves can still pick a person of the
        rule when the switch is on, but not when it is off.
        """
        limited = self.make_user("limited")
        self.make_rule(users=[self.direct])

        on = self.single_form(
            self.lead_payload(lead_owner=self.direct.pk, **{APPLY_FIELD: "on"}),
            user=limited,
        )
        self.assertTrue(on.is_valid(), on.errors)

        off = self.single_form(
            self.lead_payload(lead_owner=self.direct.pk), user=limited
        )
        self.assertFalse(off.is_valid())
        self.assertIn("lead_owner", off.errors)

    def test_decision_is_stored_on_the_lead(self):
        """Saving a matched form records the condition and how the owner was chosen."""
        condition = self.make_rule(roles=[self.sales_role])
        form = self.single_form(
            self.lead_payload(lead_owner=self.sales[2].pk, **{APPLY_FIELD: "on"})
        )
        self.assertTrue(form.is_valid(), form.errors)
        lead = form.save(commit=False)

        self.assertEqual(lead._assignment_condition_id, condition.pk)
        info = lead.additional_info["assignment"]
        self.assertEqual(info["rule_id"], condition.rule_id)
        self.assertEqual(info["rule_name"], "Website leads")
        self.assertEqual(info["condition_id"], condition.pk)
        self.assertEqual(info["assigned_user_id"], self.sales[2].pk)
        self.assertEqual(info["via"], "form")

    def test_unticked_form_leaves_no_decision(self):
        """Without the switch nothing is recorded; the engine decides later."""
        self.make_rule(roles=[self.sales_role])
        form = self.single_form(self.lead_payload())
        self.assertTrue(form.is_valid(), form.errors)
        lead = form.save(commit=False)
        self.assertFalse(hasattr(lead, "_assignment_condition_id"))
        self.assertIsNone(lead.additional_info)

    def test_custom_field_in_a_rule(self):
        """A rule on a custom field is checked against what was typed in the form."""
        field = CustomFieldDefinition.objects.create(
            content_type=HorillaContentType.objects.get_for_model(Lead),
            name="Product",
            field_type="choice",
            choices="Widget Pro,Other",
            company=self.company,
        )
        key = f"cf_{field.pk}"
        self.make_rule(criteria=[(key, "icontains", "Widget Pro")], users=[self.direct])

        match = self.single_form(
            self.lead_payload(
                lead_owner=self.direct.pk, **{APPLY_FIELD: "on", key: ["Widget Pro"]}
            )
        )
        self.assertTrue(match.is_valid(), match.errors)

        other = self.single_form(
            self.lead_payload(
                lead_owner=self.direct.pk, **{APPLY_FIELD: "on", key: ["Other"]}
            )
        )
        self.assertFalse(other.is_valid())
        self.assertIn(NOT_MATCHING, " ".join(other.non_field_errors()))


# ---------------------------------------------------------------------------
# Preview endpoint
# ---------------------------------------------------------------------------


class OwnerPreviewViewTests(AssignmentFixtureMixin, TestCase):
    """The view that redraws the Owner field when the switch is toggled."""

    @classmethod
    def setUpClass(cls):
        """Disconnect the login history signals, which need HTTP_USER_AGENT that the test client does not provide."""
        super().setUpClass()
        _disconnect_login_history()

    @classmethod
    def tearDownClass(cls):
        """Reconnect the login history signals, so other tests are not affected."""
        _reconnect_login_history()
        super().tearDownClass()

    def setUp(self):
        """Create the company, users, and a lead stage, and log in as the admin."""
        self.create_fixture()
        self.client.force_login(self.admin)
        self.url = reverse("leads:assignment_rule_owner")

    def tearDown(self):
        """Clear the thread-local request, so other tests are not affected."""
        if hasattr(_thread_local, "request"):
            del _thread_local.request
        super().tearDown()

    def get(self, params=None, client=None, **extra):
        """Call the endpoint like htmx does."""
        return (client or self.client).get(
            self.url, params or {}, HTTP_HX_REQUEST="true", **extra
        )

    def test_requires_htmx_and_login(self):
        """A plain request or an anonymous one is not served."""
        # Without the HX-Request header the app redirects (section middleware)
        # or answers 405; either way the fragment is not served.
        self.assertIn(self.client.get(self.url).status_code, (302, 405))
        self.client.logout()
        anonymous = self.get()
        self.assertIn("login", anonymous["HX-Redirect"])

    def test_requires_permission_to_create_leads(self):
        """A user who can not create leads gets nothing."""
        self.client.force_login(self.make_user("nobody"))
        self.assertEqual(self.get().status_code, 403)

    def test_switch_off_returns_the_normal_owner_field(self):
        """Untick: the ajax owner select comes back."""
        self.make_rule(roles=[self.sales_role])
        response = self.get({"lead_owner": self.direct.pk, "mode": "single"})
        html = response.content.decode()
        self.assertContains(response, "data-url")
        self.assertNotContains(response, "Website leads · Sales")
        self.assertIn(f'data-initial="{self.direct.pk}"', html)

    def test_switch_on_returns_the_pool_with_least_loaded_selected(self):
        """Tick: the owner is limited to the pool and the least-loaded is selected."""
        self.make_rule(roles=[self.sales_role])
        self.create_lead(self.sales[0])
        response = self.get(
            {
                APPLY_FIELD: "on",
                "lead_source": "website",
                "lead_owner": self.direct.pk,
                "mode": "single",
            }
        )
        html = response.content.decode()
        self.assertNotContains(response, "Website leads · Sales")
        self.assertNotContains(response, "data-url")
        self.assertNotContains(response, f'<option value="{self.outsider.pk}"')
        self.assertContains(
            response, "applies. The owner is picked from its people by the fewest leads"
        )
        self.assertRegex(html, rf'<option value="{self.sales[1].pk}"[^>]*selected')

    def test_switch_on_loads_the_rule_people_once(self):
        """Tick: the rules' people are read once, not once per step of the form."""
        self.make_rule(roles=[self.sales_role])
        with CaptureQueriesContext(connection) as queries:
            self.get(
                {
                    APPLY_FIELD: "on",
                    "lead_source": "website",
                    "lead_owner": self.direct.pk,
                    "mode": "single",
                }
            )
        for table in ("assign_to_users", "assign_to_roles"):
            hits = [
                q
                for q in queries
                if f'SELECT ("leads_leadassignmentcondition_{table}"' in q["sql"]
            ]
            self.assertEqual(len(hits), 1, table)

    def test_current_pick_is_kept_when_in_the_pool(self):
        """A person already chosen who is in the pool stays selected."""
        self.make_rule(roles=[self.sales_role])
        response = self.get(
            {
                APPLY_FIELD: "on",
                "lead_source": "website",
                "lead_owner": self.sales[2].pk,
                "mode": "single",
            }
        )
        self.assertRegex(
            response.content.decode(),
            rf'<option value="{self.sales[2].pk}"[^>]*selected',
        )

    def test_no_match_gives_a_notice_and_the_normal_field(self):
        """Tick with values no rule accepts: a notice, and the normal owner field."""
        self.make_rule(roles=[self.sales_role])
        response = self.get(
            {APPLY_FIELD: "on", "lead_source": "referral", "mode": "single"}
        )
        self.assertContains(response, NOT_MATCHING)
        self.assertContains(response, "data-url")

    def test_nobody_is_listed_until_a_condition_is_settled(self):
        """A value not filled in yet never fails the preview, and lists nobody."""
        self.make_rule(
            criteria=[("industry", "exact", "education")], users=[self.direct]
        )
        response = self.get({APPLY_FIELD: "on", "mode": "single"})
        self.assertNotContains(response, NOT_MATCHING)
        self.assertNotContains(response, f'<option value="{self.direct.pk}"')
        self.assertContains(response, "confirmed when the remaining fields")

    def test_people_are_listed_once_the_condition_is_settled(self):
        """Filling in the value the rule looks at lists the rule's people."""
        self.make_rule(
            criteria=[("industry", "exact", "education")], users=[self.direct]
        )
        response = self.get(
            {APPLY_FIELD: "on", "industry": "education", "mode": "single"}
        )
        self.assertContains(response, f'<option value="{self.direct.pk}"')
        self.assertContains(
            response, "applies. The owner is picked from its people by the fewest leads"
        )

    def test_nobody_is_suggested_until_a_rule_is_settled(self):
        """While the rule is undecided, no owner is preselected."""
        self.make_rule(roles=[self.sales_role])
        response = self.get(
            {APPLY_FIELD: "on", "lead_owner": self.admin.pk, "mode": "single"}
        )
        self.assertNotContains(response, "Website leads · Sales")
        self.assertNotRegex(response.content.decode(), r"<option[^>]*selected")
        self.assertContains(response, "confirmed when the remaining fields")

    def test_blank_optional_value_is_not_judged_in_the_preview(self):
        """A blank field the user has not reached yet does not fail the preview."""
        self.make_rule(criteria=[("city", "exact", "Paris")], users=[self.direct])
        response = self.get({APPLY_FIELD: "on", "city": "", "mode": "single"})
        self.assertNotContains(response, NOT_MATCHING)
        self.assertNotContains(response, f'<option value="{self.direct.pk}"')

    def test_garbage_owner_value_does_not_break_the_preview(self):
        """A tampered owner value is ignored rather than raising."""
        self.make_rule(users=[self.direct])
        response = self.get(
            {
                APPLY_FIELD: "on",
                "lead_source": "website",
                "lead_owner": "abc",
                "mode": "single",
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'<option value="{self.direct.pk}"')

    def test_form_class_comes_from_a_whitelist(self):
        """The class is never taken from the request."""
        self.make_rule(users=[self.direct])
        response = self.get(
            {
                APPLY_FIELD: "on",
                "lead_source": "website",
                "mode": "os.system",
                "form_class": "horilla.contrib.core.forms.Anything",
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'<option value="{self.direct.pk}"')

    def test_multi_step_mode(self):
        """The wizard's form can be previewed too, with later steps still unknown."""
        self.make_rule(criteria=[("country", "exact", "US")], users=[self.direct])
        response = self.get({APPLY_FIELD: "on", "mode": "multi"})
        self.assertNotContains(response, NOT_MATCHING)
        self.assertContains(response, f'<option value="{self.direct.pk}"')


# ---------------------------------------------------------------------------
# Saving through the views (needs real commits for the post-save engine)
# ---------------------------------------------------------------------------


class ViewFixtureMixin(AssignmentFixtureMixin):
    """Login handling and request helpers for the view tests."""

    @classmethod
    def setUpClass(cls):
        """Disconnect the login history signals, which need HTTP_USER_AGENT that the test client does not provide."""
        super().setUpClass()
        _disconnect_login_history()

    @classmethod
    def tearDownClass(cls):
        """Reconnect the login history signals, so other tests are not affected."""
        _reconnect_login_history()
        super().tearDownClass()

    def setUp(self):
        """Create the company, users, and a lead stage, and log in as the admin."""
        self.create_fixture()
        self.client.force_login(self.admin)

    def tearDown(self):
        """Clear the thread-local request, so other tests are not affected."""
        if hasattr(_thread_local, "request"):
            del _thread_local.request
        super().tearDown()

    def post_single(self, **overrides):
        """Submit the single-step create form."""
        return self.client.post(
            reverse("leads:leads_create_single"),
            self.lead_payload(**overrides),
            HTTP_HX_REQUEST="true",
        )

    def saved_lead(self, email="sara@example.com"):
        """The lead created by the test, fresh from the database."""
        return Lead.all_objects.get(email=email)


class SingleFormSaveTests(ViewFixtureMixin, TransactionTestCase):
    """What happens to a lead saved from the single-step form."""

    def test_ticked_form_keeps_the_chosen_pool_member(self):
        """The engine does not pick again; the person chosen in the form is kept."""
        condition = self.make_rule(roles=[self.sales_role])
        # sales0 owns a lead, so the engine would pick sales1: choose sales2 instead.
        self.create_lead(self.sales[0])
        chosen = self.sales[2]

        with mock.patch(
            "horilla_crm.leads.assignment.notify.deliver_assignment_notifications"
        ) as notify:
            response = self.post_single(lead_owner=chosen.pk, **{APPLY_FIELD: "on"})

        self.assertIn("HX-Redirect", response)
        lead = self.saved_lead()
        self.assertEqual(lead.lead_owner_id, chosen.pk)
        info = lead.additional_info["assignment"]
        self.assertEqual(info["via"], "form")
        self.assertEqual(info["rule_name"], "Website leads")
        self.assertEqual(info["assigned_user_id"], chosen.pk)
        notify.assert_called_once()
        called_condition, called_lead, called_user = notify.call_args.args
        self.assertEqual(called_condition, condition)
        self.assertEqual(called_lead.pk, lead.pk)
        self.assertEqual(called_user, chosen)

    def test_ticked_form_that_matches_nothing_saves_nothing(self):
        """A lead fitting no condition is not created, and the form says why."""
        self.make_rule(users=[self.direct])
        response = self.post_single(
            lead_owner=self.direct.pk, lead_source="referral", **{APPLY_FIELD: "on"}
        )

        self.assertNotIn("HX-Redirect", response)
        self.assertContains(response, "does not satisfy any active assignment rule")
        self.assertFalse(Lead.all_objects.filter(email="sara@example.com").exists())

    def test_unticked_form_still_gets_the_engine(self):
        """Unticked, rules keep applying after save, as they always did."""
        self.make_rule(roles=[self.sales_role])
        with mock.patch(
            "horilla_crm.leads.signals.deliver_assignment_notifications"
        ) as notify:
            response = self.post_single(lead_owner=self.direct.pk)

        self.assertIn("HX-Redirect", response)
        lead = self.saved_lead()
        self.assertIn(lead.lead_owner_id, {user.pk for user in self.sales})
        self.assertEqual(lead.additional_info["assignment"]["via"], "auto")
        notify.assert_called_once()

    def test_unticked_form_without_a_match_keeps_the_chosen_owner(self):
        """No rule fits and the box is off: the owner is the one picked."""
        self.make_rule(roles=[self.sales_role])
        response = self.post_single(lead_owner=self.direct.pk, lead_source="referral")

        self.assertIn("HX-Redirect", response)
        lead = self.saved_lead()
        self.assertEqual(lead.lead_owner_id, self.direct.pk)
        self.assertIsNone(lead.additional_info)

    def test_creation_outside_the_forms_still_uses_the_engine(self):
        """Import, API, web-to-lead and the like are untouched."""
        self.make_rule(roles=[self.sales_role])
        lead = self.create_lead(self.direct, email="api@example.com")

        lead.refresh_from_db()
        self.assertIn(lead.lead_owner_id, {user.pk for user in self.sales})
        self.assertEqual(lead.additional_info["assignment"]["via"], "auto")

    def test_editing_a_lead_does_not_reassign_it(self):
        """Rules run when a lead is created, not each time it is saved."""
        self.make_rule(roles=[self.sales_role])
        lead = self.create_lead(self.direct, email="edit@example.com")
        lead.refresh_from_db()
        lead.lead_owner = self.direct
        lead.save()

        lead.refresh_from_db()
        self.assertEqual(lead.lead_owner_id, self.direct.pk)

    def test_edit_form_has_no_switch(self):
        """The option is offered on new leads only."""
        self.make_rule(users=[self.direct])
        lead = self.create_lead(self.direct, email="edit@example.com")
        response = self.client.get(
            reverse("leads:leads_edit_single", kwargs={"pk": lead.pk}),
            HTTP_HX_REQUEST="true",
        )
        self.assertNotContains(response, f'name="{APPLY_FIELD}"')

    def test_create_form_shows_the_switch_only_with_an_active_rule(self):
        """The switch appears on the create form when a rule is active."""
        url = reverse("leads:leads_create_single")
        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertNotContains(response, f'name="{APPLY_FIELD}"')

        self.make_rule(users=[self.direct])
        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertContains(response, f'name="{APPLY_FIELD}"')
        self.assertContains(response, reverse("leads:assignment_rule_owner"))


# ---------------------------------------------------------------------------
# Multi-step form
# ---------------------------------------------------------------------------


class WizardTests(ViewFixtureMixin, TransactionTestCase):
    """The same option on the four-step form."""

    def setUp(self):
        super().setUp()
        self.url = reverse("leads:leads_create")

    def start(self):
        """Open the wizard with a clean session."""
        return self.client.get(f"{self.url}?new=true", HTTP_HX_REQUEST="true")

    def post_step(self, step, **data):
        """Submit one step of the wizard."""
        return self.client.post(
            self.url, {"step": str(step), **data}, HTTP_HX_REQUEST="true"
        )

    def step_one(self, **overrides):
        """Submit step 1 with the usual values."""
        payload = {
            "lead_owner": self.sales[2].pk,
            "first_name": "Sara",
            "last_name": "Ahmadi",
            "email": "sara@example.com",
            "lead_source": "website",
            "lead_status": self.status.pk,
        }
        payload.update(overrides)
        return self.post_step(1, **payload)

    def finish(self, **requirements):
        """Submit steps 2 to 4 and return the response of the last one."""
        self.post_step(2, lead_company="Example Ltd", industry="other")
        self.post_step(3, country="US")
        notes = requirements.get("requirements", "Call back")
        return self.post_step(4, requirements=notes)

    def test_switch_is_shown_on_the_first_step_only(self):
        """The wizard offers the switch on step 1 after Owner."""
        self.make_rule(roles=[self.sales_role])
        first = self.start()
        self.assertContains(first, f'name="{APPLY_FIELD}"')
        content = first.content.decode()
        self.assertLess(
            content.index('name="lead_owner"'), content.index(f'name="{APPLY_FIELD}"')
        )

        second = self.step_one(**{APPLY_FIELD: "on"})
        self.assertNotContains(second, f'name="{APPLY_FIELD}"')

    def test_switch_absent_without_rules(self):
        """Without an active rule the wizard is as before."""
        self.assertNotContains(self.start(), f'name="{APPLY_FIELD}"')

    def test_ticked_wizard_assigns_from_the_pool(self):
        """Ticked on step 1, the lead is created for the chosen person of the pool."""
        condition = self.make_rule(roles=[self.sales_role])
        self.start()
        with mock.patch(
            "horilla_crm.leads.assignment.notify.deliver_assignment_notifications"
        ) as notify:
            self.step_one(**{APPLY_FIELD: "on"})
            response = self.finish()

        self.assertIn("HX-Redirect", response)
        lead = self.saved_lead()
        self.assertEqual(lead.lead_owner_id, self.sales[2].pk)
        info = lead.additional_info["assignment"]
        self.assertEqual(info["via"], "form")
        self.assertEqual(info["condition_id"], condition.pk)
        notify.assert_called_once()

    def test_value_that_rules_out_every_condition_stops_the_wizard_early(self):
        """Once a known value rules every condition out, the step shows the reason."""
        self.make_rule(roles=[self.sales_role])
        self.start()
        response = self.step_one(lead_source="referral", **{APPLY_FIELD: "on"})

        self.assertContains(response, "does not satisfy any active assignment rule")
        self.assertContains(response, 'name="step" value="1"')

    def test_values_from_later_steps_are_not_judged_early(self):
        """A rule on a later step's field does not fail step 1 or 2."""
        self.make_rule(
            criteria=[("industry", "exact", "other")], roles=[self.sales_role]
        )
        self.start()
        first = self.step_one(**{APPLY_FIELD: "on"})
        self.assertNotContains(first, "does not satisfy any active assignment rule")
        self.assertContains(first, 'name="step" value="2"')

    def test_final_step_checks_values_from_every_step(self):
        """A rule on a last-step field is judged when the form is submitted."""
        self.make_rule(
            criteria=[("requirements", "icontains", "urgent")], roles=[self.sales_role]
        )
        self.start()
        self.step_one(**{APPLY_FIELD: "on"})
        response = self.finish(requirements="Call back")

        self.assertNotIn("HX-Redirect", response)
        self.assertContains(response, "does not satisfy any active assignment rule")
        self.assertFalse(Lead.all_objects.filter(email="sara@example.com").exists())

    def test_owner_must_still_be_in_the_pool_at_the_end(self):
        """Later steps can change the pool; the owner is checked at the end."""
        us = self.make_rule(
            "US",
            criteria=[("country", "exact", "US")],
            users=[self.direct],
        )
        self.make_rule(
            "Elsewhere",
            rule=us.rule,
            criteria=[("country", "exact", "GB")],
            users=[self.outsider],
        )
        self.start()
        self.step_one(lead_owner=self.outsider.pk, **{APPLY_FIELD: "on"})
        response = self.finish()

        self.assertNotIn("HX-Redirect", response)
        self.assertContains(response, "Choose one of the people rule")
        self.assertFalse(Lead.all_objects.filter(email="sara@example.com").exists())

    def test_unticking_on_step_one_clears_the_stored_switch(self):
        """A switch ticked once and unticked later does not stay on in the session."""
        self.make_rule(roles=[self.sales_role])
        self.start()
        self.step_one(**{APPLY_FIELD: "on"})
        # The view may be composed with extensions, which renames its storage key.
        key = next(
            name for name in self.client.session.keys() if name.endswith("_form_data")
        )
        self.assertEqual(self.client.session[key][APPLY_FIELD], "on")

        self.post_step(
            1,
            lead_owner=self.direct.pk,
            first_name="Sara",
            last_name="Ahmadi",
            email="sara@example.com",
            lead_source="referral",
            lead_status=self.status.pk,
        )
        self.assertIs(self.client.session[key][APPLY_FIELD], False)

        response = self.finish()
        self.assertIn("HX-Redirect", response)
        lead = self.saved_lead()
        self.assertEqual(lead.lead_owner_id, self.direct.pk)
        self.assertIsNone(lead.additional_info)

    def test_unticked_wizard_still_gets_the_engine(self):
        """Without the switch the engine decides after save, as before."""
        self.make_rule(roles=[self.sales_role])
        self.start()
        self.step_one(lead_owner=self.direct.pk)
        response = self.finish()

        self.assertIn("HX-Redirect", response)
        lead = self.saved_lead()
        self.assertIn(lead.lead_owner_id, {user.pk for user in self.sales})
        self.assertEqual(lead.additional_info["assignment"]["via"], "auto")


# ---------------------------------------------------------------------------
# Form Layout (Custom Layout)
# ---------------------------------------------------------------------------


class FormLayoutTests(ViewFixtureMixin, TransactionTestCase):
    """The checkbox follows the Owner field in Custom Layout."""

    def setUp(self):
        super().setUp()
        self.layout_field = apps.get_model("field_management", "FormLayoutField")
        self.lead_ct = HorillaContentType.objects.get_for_model(Lead)
        self.make_rule(roles=[self.sales_role])
        self.url = f"{reverse('leads:leads_create_single')}?form_layout=1"

    def layout(self, field_name, *, sequence, visible=True):
        """Save one layout row for the lead form."""
        return self.layout_field.all_objects.create(
            content_type=self.lead_ct,
            field_name=field_name,
            sequence=sequence,
            is_visible=visible,
            company=self.company,
        )

    def custom_layout(self):
        """Open the Custom Layout form."""
        return self.client.get(self.url, HTTP_HX_REQUEST="true")

    def test_without_a_saved_layout(self):
        """Custom Layout shows the checkbox under the owner."""
        content = self.custom_layout().content.decode()
        self.assertIn(f'name="{APPLY_FIELD}"', content)
        self.assertLess(
            content.index('name="lead_owner"'), content.index(f'name="{APPLY_FIELD}"')
        )

    def test_checkbox_moves_with_the_owner(self):
        """A layout that puts the owner after another field takes the checkbox along."""
        self.layout("city", sequence=1)
        self.layout("lead_owner", sequence=2)
        content = self.custom_layout().content.decode()

        self.assertLess(
            content.index('name="city"'), content.index('name="lead_owner"')
        )
        self.assertLess(
            content.index('name="lead_owner"'), content.index(f'name="{APPLY_FIELD}"')
        )

    def test_layout_that_does_not_mention_the_checkbox_keeps_it(self):
        """A rule added after the layout was saved still shows its checkbox."""
        self.layout("city", sequence=1, visible=False)
        self.assertContains(self.custom_layout(), f'name="{APPLY_FIELD}"')

    def test_owner_cannot_be_hidden_so_the_pool_always_has_a_field(self):
        """The owner is required, so a layout can not remove it."""
        self.layout("lead_owner", sequence=1, visible=False)
        content = self.custom_layout().content.decode()
        self.assertIn('name="lead_owner"', content)
        self.assertIn(f'name="{APPLY_FIELD}"', content)
