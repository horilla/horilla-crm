"""
Tests for the shared availability helper.
"""

# Standard library imports
from datetime import timedelta
from unittest import mock

# Third-party imports (Django)
from django.core.exceptions import ValidationError
from django.test import TestCase

# First-party / Horilla imports
from horilla.apps import apps
from horilla.auth.models import User
from horilla.contrib.core.availability import (
    exclude_unavailable,
    unavailable_until,
    unavailable_user_ids,
)
from horilla.contrib.core.availability_select import (
    availability_choices,
    availability_select,
    ensure_available,
)
from horilla.contrib.core.models import Company
from horilla.utils import timezone


class AvailabilityHelperTests(TestCase):
    """Overlap rules of ``[start, end]`` against a user's unavailability."""

    def setUp(self):
        """Create a company, three users and a fixed "now"."""
        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        self.users = [
            User.objects.create_user(
                username=f"u{i}",
                email=f"u{i}@example.com",
                password="pass",
                company=self.company,
            )
            for i in range(3)
        ]
        self.model = apps.get_model("calendar", "UserAvailability")
        self.now = timezone.now().replace(microsecond=0)

    def away(self, user, start_hours, end_hours):
        """Mark ``user`` away from ``now + start_hours`` to ``now + end_hours``."""
        return self.model.all_objects.create(
            user=user,
            from_datetime=self.now + timedelta(hours=start_hours),
            to_datetime=self.now + timedelta(hours=end_hours),
            reason="Leave",
            company=self.company,
        )

    def ids(self, start_hours, end_hours=None):
        """Ids unavailable in the window given in hours from now."""
        end = None if end_hours is None else self.now + timedelta(hours=end_hours)
        return unavailable_user_ids(self.now + timedelta(hours=start_hours), end)

    def test_point_in_time_is_inclusive_at_both_ends(self):
        """A period covers its first and last instant."""
        user = self.users[0]
        self.away(user, 0, 10)
        self.assertEqual(self.ids(0), {user.pk})
        self.assertEqual(self.ids(10), {user.pk})
        self.assertEqual(self.ids(-1), set())
        self.assertEqual(self.ids(11), set())

    def test_window_overlap_cases(self):
        """Inside, straddling either end and covering the window all count."""
        inside, straddle_start, straddle_end, covering, before, after = (
            User.objects.create_user(
                username=f"w{i}",
                email=f"w{i}@example.com",
                password="pass",
                company=self.company,
            )
            for i in range(6)
        )
        self.away(inside, 2, 3)
        self.away(straddle_start, -5, 2)
        self.away(straddle_end, 8, 20)
        self.away(covering, -5, 20)
        self.away(before, -10, -1)
        self.away(after, 11, 20)
        self.assertEqual(
            self.ids(0, 10),
            {inside.pk, straddle_start.pk, straddle_end.pk, covering.pk},
        )

    def test_window_touching_a_period_counts(self):
        """A period ending exactly when the window starts overlaps it."""
        user = self.users[0]
        self.away(user, -5, 0)
        self.assertEqual(self.ids(0, 10), {user.pk})

    def test_users_narrows_the_search(self):
        """Only the given users are reported."""
        first, second, _ = self.users
        self.away(first, -1, 1)
        self.away(second, -1, 1)
        self.assertEqual(unavailable_user_ids(self.now, users=[second.pk]), {second.pk})
        self.assertEqual(
            unavailable_user_ids(self.now, users=User.objects.filter(pk=first.pk)),
            {first.pk},
        )

    def test_several_rows_for_one_user_are_reported_once(self):
        """Two overlapping rows do not duplicate the user."""
        user = self.users[0]
        self.away(user, -1, 1)
        self.away(user, 0, 2)
        self.assertEqual(self.ids(0), {user.pk})
        qs = exclude_unavailable(User.objects.filter(company=self.company), self.now)
        self.assertEqual(qs.count(), 2)

    def test_exclude_unavailable(self):
        """People who are away at the time leave the queryset."""
        first, second, third = self.users
        self.away(first, -1, 1)
        self.away(second, 5, 6)
        qs = exclude_unavailable(User.objects.filter(company=self.company), self.now)
        self.assertEqual({u.pk for u in qs}, {second.pk, third.pk})
        qs = exclude_unavailable(
            User.objects.filter(company=self.company),
            self.now,
            self.now + timedelta(hours=10),
        )
        self.assertEqual({u.pk for u in qs}, {third.pk})

    def test_unavailable_until_chains_back_to_back_periods(self):
        """Leave entered in pieces reports when the person is really back."""
        user = self.users[0]
        self.away(user, -1, 5)
        self.away(user, 5, 10)
        self.away(user, 9, 12)
        self.away(user, 20, 30)  # after a gap: not part of this leave
        back = unavailable_until([user.pk], self.now)
        self.assertEqual(back, {user.pk: self.now + timedelta(hours=12)})

    def test_unavailable_until_leaves_out_available_people(self):
        """Someone whose leave starts later, or is over, is not listed."""
        first, second, _ = self.users
        self.away(first, 3, 5)
        self.away(second, -5, -1)
        self.assertEqual(unavailable_until([first.pk, second.pk], self.now), {})

    def test_company_scoped_default_manager_does_not_hide_leave(self):
        """Leave counts even when the current request belongs to another company."""
        user = self.users[0]
        self.away(user, -1, 1)
        with mock.patch.object(
            self.model.objects, "get_queryset", side_effect=AssertionError
        ):
            self.assertEqual(self.ids(0), {user.pk})

    def test_calendar_app_missing_means_nobody_is_away(self):
        """Without the calendar app every helper reports "available"."""
        user = self.users[0]
        self.away(user, -1, 1)
        with mock.patch(
            "horilla.contrib.core.availability.calendar_installed", return_value=False
        ):
            self.assertEqual(self.ids(0), set())
            qs = User.objects.filter(company=self.company)
            self.assertEqual(exclude_unavailable(qs, self.now).count(), 3)
            self.assertEqual(unavailable_until([user.pk], self.now), {})


class AvailabilitySelectTests(AvailabilityHelperTests):
    """The reusable select, its choices and the server-side check."""

    def test_choices_list_available_people_first_then_the_away(self):
        """People who are away come last, with a tooltip saying until when."""
        first, second, third = self.users
        self.away(first, -1, 5)
        choices, unavailable = availability_choices(self.users, at=self.now)
        self.assertEqual(
            [value for value, _label in choices],
            ["", second.pk, third.pk, first.pk],
        )
        self.assertEqual(list(unavailable), [first.pk])
        self.assertIn("Unavailable until", unavailable[first.pk])

    def test_choices_without_the_blank_entry(self):
        """``empty_label=None`` leaves out the blank choice."""
        choices, _ = availability_choices(self.users, empty_label=None)
        self.assertNotIn("", [value for value, _label in choices])

    def test_widget_disables_the_away_and_ships_the_pill_css(self):
        """Away people are disabled with a tooltip; the pill CSS is sent too."""
        first = self.users[0]
        self.away(first, -1, 5)
        html = str(availability_select(self.users).render("who", None))
        self.assertIn('title="Unavailable until', html)
        self.assertIn("<style>", html)
        # The pill is keyed to the dropdown, not to ``title``: the tooltip script
        # removes the title while a row is hovered, and the pill must stay.
        self.assertIn('data-dropdown-css-class="availability-select"', html)
        self.assertNotIn("[title]", html)
        # Only the one away person is disabled (the CSS mentions it too).
        self.assertEqual(html.split("<style>")[0].count("disabled"), 1)

    def test_widget_adds_nothing_when_everyone_is_available(self):
        """No CSS and no disabled option without anyone away."""
        html = str(availability_select(self.users).render("who", None))
        self.assertNotIn("<style>", html)
        self.assertNotIn("disabled", html)

    def test_ensure_available_names_the_user_and_the_date(self):
        """An away person is refused with who and until when."""
        user = self.users[0]
        self.away(user, -1, 5)
        with self.assertRaises(ValidationError) as caught:
            ensure_available(user)
        message = caught.exception.messages[0]
        self.assertIn("u0", message)
        self.assertIn("unavailable until", message)

    def test_ensure_available_accepts_available_people_and_none(self):
        """Nothing is raised for an available person, a later moment or None."""
        user = self.users[0]
        self.away(user, -1, 5)
        ensure_available(self.users[1])
        ensure_available(None)
        ensure_available(user, at=self.now + timedelta(hours=10))
