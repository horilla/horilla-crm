"""
Lead assignment skips people who are unavailable at assignment time.
"""

# Standard library imports
from datetime import timedelta
from unittest import mock

# Third-party imports (Django)
from django.test import TestCase, TransactionTestCase

# First party imports (Horilla)
from horilla.apps import apps
from horilla.contrib.utils.middlewares import _thread_local
from horilla.urls import reverse
from horilla.utils import timezone
from horilla_crm.leads.assignment.pool import (
    NO_ASSIGNEES,
    UNDETERMINED,
    condition_users,
    condition_users_for_role,
    resolve_for_data,
    skipped_users,
)
from horilla_crm.leads.form_mixins import APPLY_FIELD
from horilla_crm.leads.tests.test_assignment_on_forms import (
    AssignmentFixtureMixin,
    ViewFixtureMixin,
    _disconnect_login_history,
    _reconnect_login_history,
)


def display_name(user):
    """The name the form shows: the full name, else the username."""
    return str(user).strip() or user.username


def mark_away(users, company, *, start_hours=-1, end_hours=24, now=None):
    """Mark ``users`` unavailable from ``now + start_hours`` to ``now + end_hours``."""
    now = now or timezone.now()
    model = apps.get_model("calendar", "UserAvailability")
    for user in users:
        model.all_objects.create(
            user=user,
            from_datetime=now + timedelta(hours=start_hours),
            to_datetime=now + timedelta(hours=end_hours),
            reason="Leave",
            company=company,
        )


class PoolAvailabilityTests(AssignmentFixtureMixin, TestCase):
    """``condition_users`` and the resolution leave out unavailable people."""

    def setUp(self):
        """Create the company, users, and a lead stage."""
        self.create_fixture()

    def pks(self, condition, **kwargs):
        """Ids of the condition's people."""
        return set(condition_users(condition, **kwargs).values_list("pk", flat=True))

    def test_role_members_are_checked_one_by_one(self):
        """With some members away the others still make up the pool."""
        condition = self.make_rule(roles=[self.sales_role])
        mark_away(self.sales[:2], self.company)
        self.assertEqual(self.pks(condition), {self.sales[2].pk})

    def test_user_condition_leaves_out_unavailable_users(self):
        """A user condition drops the people who are away."""
        condition = self.make_rule(users=[self.direct, self.outsider])
        mark_away([self.direct], self.company)
        self.assertEqual(self.pks(condition), {self.outsider.pk})

    def test_include_unavailable_keeps_everyone(self):
        """The unfiltered pool tells "nobody eligible" from "everybody away"."""
        condition = self.make_rule(roles=[self.sales_role])
        mark_away(self.sales, self.company)
        self.assertEqual(self.pks(condition), set())
        self.assertEqual(
            self.pks(condition, include_unavailable=True), {u.pk for u in self.sales}
        )

    def test_single_user_rule_where_the_user_is_away(self):
        """A rule naming one person has nobody to assign to while they are away."""
        condition = self.make_rule(users=[self.direct])
        mark_away([self.direct], self.company)
        self.assertEqual(self.pks(condition), set())
        self.assertEqual(
            self.pks(condition, include_unavailable=True), {self.direct.pk}
        )

    def test_multi_user_rule_with_one_away(self):
        """The others of a multi-user rule stay eligible."""
        condition = self.make_rule(users=[self.direct, self.outsider, self.support])
        mark_away([self.outsider], self.company)
        self.assertEqual(self.pks(condition), {self.direct.pk, self.support.pk})

    def test_role_label_variant_follows_the_same_rule(self):
        """The per-role pool agrees with ``condition_users``."""
        mark_away([self.sales[0]], self.company)
        self.assertEqual(
            set(condition_users_for_role(self.sales_role).values_list("pk", flat=True)),
            {self.sales[1].pk, self.sales[2].pk},
        )
        self.assertEqual(
            condition_users_for_role(self.sales_role, include_unavailable=True).count(),
            len(self.sales),
        )

    def test_suggested_owner_comes_from_available_people(self):
        """Neither method suggests someone who is away."""
        for method in ("least_leads", "round_robin"):
            with self.subTest(method=method):
                condition = self.make_rule(
                    name=f"Rule {method}",
                    roles=[self.sales_role],
                    assignment_method=method,
                )
                mark_away([self.sales[0]], self.company)
                resolution = resolve_for_data(
                    {"lead_source": "website"}, final=True, company=self.company
                )
                self.assertNotEqual(resolution.default_owner, self.sales[0])
                self.assertEqual(
                    {u.pk for u, _ in resolution.unavailable}, {self.sales[0].pk}
                )
                condition.rule.delete()
                apps.get_model(
                    "calendar", "UserAvailability"
                ).all_objects.all().delete()

    def test_leave_in_the_future_or_past_does_not_count(self):
        """Only leave covering the assignment time matters."""
        condition = self.make_rule(roles=[self.sales_role])
        mark_away([self.sales[0]], self.company, start_hours=5, end_hours=10)
        mark_away([self.sales[1]], self.company, start_hours=-10, end_hours=-5)
        self.assertEqual(self.pks(condition), {u.pk for u in self.sales})

    def test_at_decides_the_moment(self):
        """The check uses the time given, not only the current one."""
        condition = self.make_rule(roles=[self.sales_role])
        mark_away([self.sales[0]], self.company, start_hours=5, end_hours=10)
        later = timezone.now() + timedelta(hours=6)
        self.assertNotIn(self.sales[0].pk, self.pks(condition, at=later))

    def test_all_away_is_no_assignees(self):
        """A matching condition whose people are all away reports no assignees."""
        self.make_rule(roles=[self.sales_role])
        mark_away(self.sales, self.company)
        resolution = resolve_for_data(
            {"lead_source": "website"}, final=True, company=self.company
        )
        self.assertEqual(resolution.state, NO_ASSIGNEES)
        self.assertEqual(
            resolution.reason,
            "All users selected in the “Website leads” assignment rule are "
            "currently unavailable. Untick “Assign using rules” and select "
            "another user as the owner.",
        )
        # No names: many people away until different times would make a long list.
        for user in self.sales:
            self.assertNotIn(display_name(user), resolution.reason)

    def test_away_wins_when_one_condition_is_away_and_another_empty(self):
        """One rule with an away condition and an empty one gives one clear reason."""
        rule = self.make_rule(roles=[self.sales_role]).rule
        self.add_condition(rule, users=[])
        mark_away(self.sales, self.company)
        resolution = resolve_for_data(
            {"lead_source": "website"}, final=True, company=self.company
        )
        self.assertEqual(resolution.state, NO_ASSIGNEES)
        self.assertIn("currently unavailable", resolution.reason)
        self.assertNotIn("no active people", resolution.reason)

    def test_empty_pool_keeps_the_no_people_message(self):
        """A rule with nobody in it is not blamed on leave."""
        self.make_rule(users=[])
        resolution = resolve_for_data(
            {"lead_source": "website"}, final=True, company=self.company
        )
        self.assertEqual(resolution.state, NO_ASSIGNEES)
        self.assertIn("no active people", resolution.reason)

    def test_all_away_is_not_reported_before_the_rule_is_known_to_apply(self):
        """While the value a rule looks at is unknown nothing is said about leave."""
        self.make_rule(roles=[self.sales_role])
        mark_away(self.sales, self.company)
        resolution = resolve_for_data({}, final=False, company=self.company)
        self.assertEqual(resolution.state, UNDETERMINED)
        self.assertEqual(resolution.reason, "")
        # Once the value is known and matches, everybody being away is reported.
        resolution = resolve_for_data(
            {"lead_source": "website"}, final=False, company=self.company
        )
        self.assertEqual(resolution.state, NO_ASSIGNEES)

    def test_skipped_users_lists_who_is_away_and_until_when(self):
        """The preview can name the people left out and when they are back."""
        condition = self.make_rule(roles=[self.sales_role])
        mark_away([self.sales[1]], self.company, end_hours=30)
        skipped = skipped_users(condition, self.company)
        self.assertEqual([user for user, _ in skipped], [self.sales[1]])
        self.assertIsNotNone(skipped[0][1])


class EngineAvailabilityTests(ViewFixtureMixin, TransactionTestCase):
    """The post-save engine and the lead form skip people who are away."""

    def owner_of(self, lead):
        """The lead's owner id after the engine ran."""
        lead.refresh_from_db()
        return lead.lead_owner_id

    def test_round_robin_skips_unavailable_user_and_advances(self):
        """The turn passes over someone who is away and the pointer moves on."""
        condition = self.make_rule(
            roles=[self.sales_role], assignment_method="round_robin"
        )
        first, second, third = self.sales
        mark_away([second], self.company)
        owners = [
            self.owner_of(self.create_lead(self.direct, email=f"rr{i}@example.com"))
            for i in range(4)
        ]
        self.assertEqual(owners, [first.pk, third.pk, first.pk, third.pk])
        condition.refresh_from_db()
        self.assertEqual(condition.last_assigned_user_id, third.pk)

    def test_round_robin_pointer_on_unavailable_user_still_advances(self):
        """A pointer left on someone who is now away does not break the rotation."""
        condition = self.make_rule(
            roles=[self.sales_role], assignment_method="round_robin"
        )
        first, second, third = self.sales
        condition.last_assigned_user = second
        condition.save()
        mark_away([second], self.company)
        lead = self.create_lead(self.direct, email="ptr@example.com")
        self.assertEqual(self.owner_of(lead), third.pk)

    def test_least_leads_skips_unavailable_user(self):
        """The person with the fewest leads is passed over while away."""
        self.make_rule(roles=[self.sales_role])
        self.create_lead(self.sales[1], email="a@example.com")
        self.create_lead(self.sales[2], email="b@example.com")
        mark_away([self.sales[0]], self.company)
        lead = self.create_lead(self.direct, email="new@example.com")
        self.assertIn(self.owner_of(lead), {self.sales[1].pk, self.sales[2].pk})

    def test_all_away_falls_through_to_next_condition(self):
        """The next condition is tried when the first one's people are all away."""
        rule = self.make_rule(roles=[self.sales_role]).rule
        self.add_condition(rule, users=[self.support])
        mark_away(self.sales, self.company)
        lead = self.create_lead(self.direct, email="next@example.com")
        self.assertEqual(self.owner_of(lead), self.support.pk)
        lead.refresh_from_db()
        self.assertNotIn("assignment_skipped", lead.additional_info or {})

    def test_all_away_keeps_default_owner_and_records_why(self):
        """With nobody left the lead keeps its owner and says why."""
        condition = self.make_rule(roles=[self.sales_role])
        mark_away(self.sales, self.company)
        lead = self.create_lead(self.direct, email="none@example.com")
        self.assertEqual(self.owner_of(lead), self.direct.pk)
        lead.refresh_from_db()
        self.assertEqual(
            lead.additional_info["assignment_skipped"],
            {
                "condition_id": condition.pk,
                "rule_name": condition.rule.name,
                "reason": "all_unavailable",
            },
        )
        self.assertNotIn("assignment", lead.additional_info)

    def test_no_skip_note_when_pool_is_simply_empty(self):
        """A condition with nobody active is not reported as "unavailable"."""
        self.make_rule(users=[])
        lead = self.create_lead(self.direct, email="empty@example.com")
        lead.refresh_from_db()
        self.assertNotIn("assignment_skipped", lead.additional_info or {})

    def owner_options(self, form):
        """``{value: (label, disabled)}`` of the rendered Owner select."""
        widget = form.fields["lead_owner"].widget
        options = {}
        for _group, group_options, _index in widget.optgroups("lead_owner", []):
            for option in group_options:
                options[str(option["value"])] = (
                    option["label"],
                    bool(option["attrs"].get("disabled")),
                    option["attrs"],
                )
        return options

    def test_form_labels_and_disables_unavailable_people(self):
        """Unavailable people are listed disabled with a tooltip; the pill CSS goes with them."""
        self.make_rule(roles=[self.sales_role])
        away = self.sales[0]
        mark_away([away], self.company, end_hours=30)
        form = self.single_form(data=self.lead_payload(**{APPLY_FIELD: "on"}))
        form.is_valid()
        options = self.owner_options(form)
        label, disabled, attrs = options[str(away.pk)]
        self.assertTrue(disabled)
        self.assertEqual(label, display_name(away))
        self.assertIn("Unavailable until", attrs["title"])
        self.assertIn("<style>", str(form["lead_owner"]))
        for user in self.sales[1:]:
            label, disabled, attrs = options[str(user.pk)]
            self.assertEqual((label, disabled), (display_name(user), False))
            self.assertNotIn("title", attrs)

    def test_form_prefers_an_available_owner(self):
        """The pre-selected suggestion is never someone who is away."""
        self.make_rule(roles=[self.sales_role])
        mark_away([self.sales[0]], self.company)
        form = self.single_form(data=self.lead_payload(**{APPLY_FIELD: "on"}))
        form._assignment_preview = True
        form.is_valid()
        self.assertNotEqual(str(form.data.get("lead_owner")), str(self.sales[0].pk))

    def test_all_away_form_shows_the_generic_message(self):
        """With nobody available the form says so, without listing people."""
        self.make_rule(roles=[self.sales_role])
        mark_away(self.sales, self.company)
        form = self.single_form(data=self.lead_payload(**{APPLY_FIELD: "on"}))
        self.assertFalse(form.is_valid())
        text = " ".join(str(e) for errs in form.errors.values() for e in errs)
        self.assertIn("All users selected in the", text)
        self.assertIn("currently unavailable", text)
        self.assertIn("select another user", text)
        self.assertNotIn("no active people", text)
        self.assertNotIn(display_name(self.sales[0]), text)

    def test_form_rejects_owner_who_became_unavailable(self):
        """Submitting a person who is away now is refused at save time."""
        self.make_rule(roles=[self.sales_role])
        away = self.sales[0]
        mark_away([away], self.company)
        with mock.patch(
            "horilla_crm.leads.assignment.notify.deliver_assignment_notifications"
        ):
            response = self.post_single(lead_owner=away.pk, **{APPLY_FIELD: "on"})
        self.assertNotIn("HX-Redirect", response)
        self.assertFalse(
            apps.get_model("leads", "Lead")
            .all_objects.filter(email="sara@example.com")
            .exists()
        )

    def test_form_validate_names_the_unavailable_owner(self):
        """The error says who is away and until when, not just "invalid"."""
        self.make_rule(roles=[self.sales_role])
        away = self.sales[0]
        mark_away([away], self.company)
        form = self.single_form(
            data=self.lead_payload(lead_owner=away.pk, **{APPLY_FIELD: "on"})
        )
        self.assertFalse(form.is_valid())
        text = " ".join(str(e) for errs in form.errors.values() for e in errs)
        self.assertIn("unavailable until", text)
        self.assertIn(display_name(away), text)


class OwnerWaitsForUntickTests(AssignmentFixtureMixin, TestCase):
    """While nobody can be picked from the rules the Owner is disabled."""

    @classmethod
    def setUpClass(cls):
        """Disconnect the login history signals, which the test client can not feed."""
        super().setUpClass()
        _disconnect_login_history()

    @classmethod
    def tearDownClass(cls):
        """Reconnect the login history signals for other tests."""
        _reconnect_login_history()
        super().tearDownClass()

    def setUp(self):
        """Create the fixture and log in as the admin."""
        self.create_fixture()
        self.client.force_login(self.admin)
        self.url = reverse("leads:assignment_rule_owner")

    def tearDown(self):
        """Clear the thread-local request."""
        if hasattr(_thread_local, "request"):
            del _thread_local.request
        super().tearDown()

    def preview(self, **params):
        """The Owner box the way htmx asks for it."""
        return self.client.get(
            self.url,
            {"mode": "single", **params},
            HTTP_HX_REQUEST="true",
        ).content.decode()

    def owner_select_tag(self, html):
        """The opening tag of the owner select."""
        start = html.index('<select name="lead_owner"')
        return html[start : html.index(">", start)]

    def test_everyone_away_disables_the_owner_and_keeps_the_box_ticked(self):
        """The message shows, the Owner is disabled, the checkbox stays ticked."""
        self.make_rule(roles=[self.sales_role])
        mark_away(self.sales, self.company)
        html = self.preview(**{APPLY_FIELD: "on", "lead_source": "website"})
        self.assertIn("currently unavailable", html)
        self.assertIn("disabled", self.owner_select_tag(html))
        self.assertRegex(html, r'name="apply_assignment_rule"[^>]*checked')

    def test_no_matching_rule_disables_the_owner_too(self):
        """ "No rule matches" works the same way."""
        self.make_rule(roles=[self.sales_role])
        html = self.preview(**{APPLY_FIELD: "on", "lead_source": "referral"})
        self.assertIn("does not satisfy any active assignment rule", html)
        self.assertIn("disabled", self.owner_select_tag(html))

    def test_unticking_brings_the_normal_owner_back(self):
        """Without the box the Owner is the normal, enabled field."""
        self.make_rule(roles=[self.sales_role])
        mark_away(self.sales, self.company)
        html = self.preview(lead_source="website")
        self.assertNotIn("disabled", self.owner_select_tag(html))
        self.assertNotIn("currently unavailable", html)

    def test_someone_available_keeps_the_owner_enabled(self):
        """The Owner is only disabled when nobody can be picked."""
        self.make_rule(roles=[self.sales_role])
        mark_away([self.sales[0]], self.company)
        html = self.preview(**{APPLY_FIELD: "on", "lead_source": "website"})
        # Only the person who is away is disabled, not the whole select.
        self.assertNotIn("disabled", self.owner_select_tag(html))

    def test_saving_while_ticked_gives_the_rule_message_not_a_required_error(self):
        """A disabled Owner is not submitted; its "required" error is dropped."""
        self.make_rule(roles=[self.sales_role])
        mark_away(self.sales, self.company)
        payload = self.lead_payload(**{APPLY_FIELD: "on"})
        del payload["lead_owner"]
        form = self.single_form(data=payload)
        self.assertFalse(form.is_valid())
        self.assertNotIn("lead_owner", form.errors)
        text = " ".join(str(e) for e in form.non_field_errors())
        self.assertIn("currently unavailable", text)
