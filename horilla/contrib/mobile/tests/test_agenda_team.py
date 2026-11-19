"""
Tests for the Agenda's Mine / Team switch: who gets it, what each shows (the
desktop calendar's rule), the members filter, the choice kept in the session,
and marking a teammate's activity done.
"""

# Standard library imports
from unittest import skipUnless

# Third-party imports (Django)
from django.test import override_settings

from .base import MOBILE_INSTALLED
from .test_agenda import AgendaTestBase, agenda_url

if MOBILE_INSTALLED:
    from horilla.contrib.activity.models import Activity
    from horilla.contrib.core.models import Role


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
@override_settings(ROOT_URLCONF="horilla.contrib.mobile.tests.urls")
class AgendaTeamTests(AgendaTestBase):
    """A manager whose role is above the seller's, and a peer outside the team."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        manager_role = Role.objects.create(role_name="Manager", company=self.company)
        rep_role = Role.objects.create(
            role_name="Rep", parent_role=manager_role, company=self.company
        )
        peer_role = Role.objects.create(role_name="Support", company=self.company)
        self.manager = self.make_user("manager")
        self.manager.first_name, self.manager.last_name = "Mina", "Karimi"
        self.manager.role = manager_role
        self.manager.save()
        self.seller.first_name, self.seller.last_name = "Sara", "Ahmadi"
        self.seller.role = rep_role
        self.seller.save()
        self.other_seller.role = peer_role
        self.other_seller.save()
        self.grant(self.manager, Activity, "view_own")
        self.activity("Manager review", "task", self.at(9), owner=self.manager)
        self.rep_task = self.activity("Rep visit", "task", self.at(10))
        self.activity("Peer call", "task", self.at(11), owner=self.other_seller)

    def titles_for(self, user, query=""):
        """Titles for."""
        self.client.force_login(user)
        response = self.client.get(agenda_url(self.day) + query)
        context = response.context
        return self.titles(context["all_day_items"] + context["timed_items"])

    def test_no_switch_without_a_team(self):
        """No switch without a team."""
        self.client.force_login(self.seller)
        response = self.client.get(agenda_url(self.day))
        self.assertFalse(response.context["team_available"])
        self.assertNotContains(response, "scope=team")
        # Asking for it changes nothing.
        self.assertEqual(self.titles_for(self.seller, "&scope=team"), ["Rep visit"])

    def test_mine_shows_the_managers_own_and_team_adds_subordinates(self):
        """Mine shows the managers own and team adds subordinates."""
        self.client.force_login(self.manager)
        response = self.client.get(agenda_url(self.day))
        self.assertTrue(response.context["team_available"])
        self.assertContains(response, "scope=team")
        self.assertEqual(self.titles_for(self.manager), ["Manager review"])
        self.assertEqual(
            self.titles_for(self.manager, "&scope=team"),
            ["Manager review", "Rep visit"],
        )

    def test_team_rows_say_whose_activity_it_is(self):
        """Team rows say whose activity it is."""
        self.client.force_login(self.manager)
        response = self.client.get(agenda_url(self.day) + "&scope=team")
        people = {
            item["row"].title: item["row"].person
            for item in response.context["timed_items"]
        }
        self.assertEqual(people, {"Manager review": "You", "Rep visit": "Sara Ahmadi"})
        self.assertContains(response, "Sara Ahmadi")

    def test_the_choice_is_kept_between_visits(self):
        """The choice is kept between visits."""
        self.titles_for(self.manager, "&scope=team")
        self.assertEqual(self.titles_for(self.manager), ["Manager review", "Rep visit"])
        self.titles_for(self.manager, "&scope=mine")
        self.assertEqual(self.titles_for(self.manager), ["Manager review"])

    def test_the_members_filter_narrows_team(self):
        """The members filter narrows team."""
        self.titles_for(self.manager, "&scope=team")
        self.assertEqual(
            self.titles_for(self.manager, f"&members_set=1&members={self.seller.pk}"),
            ["Rep visit"],
        )
        # The filter lists only the team; clearing it shows everyone again.
        self.client.force_login(self.manager)
        response = self.client.get(agenda_url(self.day))
        self.assertEqual(
            {member["id"] for member in response.context["members"]},
            {self.manager.pk, self.seller.pk},
        )
        self.assertTrue(response.context["filter_active"])
        self.assertEqual(
            self.titles_for(self.manager, "&members_set=1"),
            ["Manager review", "Rep visit"],
        )

    def test_members_outside_the_team_are_ignored(self):
        """Members outside the team are ignored."""
        self.titles_for(self.manager, "&scope=team")
        self.assertEqual(
            self.titles_for(
                self.manager, f"&members_set=1&members={self.other_seller.pk}"
            ),
            ["Manager review", "Rep visit"],
        )

    def test_view_activity_shows_the_whole_company(self):
        """View activity shows the whole company."""
        self.grant(self.manager, Activity, "view")
        self.assertEqual(
            self.titles_for(self.manager, "&scope=team"),
            ["Manager review", "Rep visit", "Peer call"],
        )

    def test_a_teammates_activity_is_read_only_without_change_rights(self):
        """A teammates activity is read only without change rights."""
        self.client.force_login(self.manager)
        response = self.client.get(agenda_url(self.day) + "&scope=team")
        rows = {
            item["row"].title: item["row"] for item in response.context["timed_items"]
        }
        self.assertFalse(rows["Rep visit"].can_change)
        status = self.client.post(
            f"/m/activities/{self.rep_task.pk}/status/",
            {"status": "completed", "view": "agenda", "date": self.day.isoformat()},
        )
        self.assertEqual(status.status_code, 403)
        self.rep_task.refresh_from_db()
        self.assertEqual(self.rep_task.status, "not_started")

    def test_a_manager_with_change_own_marks_a_teammates_activity_done(self):
        """A manager with change own marks a teammates activity done."""
        self.grant(self.manager, Activity, "change_own")
        self.client.force_login(self.manager)
        self.client.get(agenda_url(self.day) + "&scope=team")
        response = self.client.post(
            f"/m/activities/{self.rep_task.pk}/status/",
            {"status": "completed", "view": "agenda", "date": self.day.isoformat()},
        )
        self.assertEqual(response.status_code, 200)
        self.rep_task.refresh_from_db()
        self.assertEqual(self.rep_task.status, "completed")
        # The refreshed Agenda is still the Team view.
        self.assertTrue(response.context["team"])
