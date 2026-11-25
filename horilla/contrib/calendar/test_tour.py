"""
Tests for the Calendar tour (``horilla/contrib/calendar/tour.py``).
"""

# Third-party imports (Django)
from django.test import SimpleTestCase

# First party imports (Horilla)
from horilla.contrib.tour.registry import _registry
from horilla.contrib.tour.testing import TourOwnershipTestsMixin


class CalendarTourOwnershipTests(TourOwnershipTestsMixin, SimpleTestCase):
    """The Calendar tour comes from this app and starts by itself once."""

    MODULE = "horilla.contrib.calendar.tour"
    KEYS = ("calendar",)


class CalendarTourTests(SimpleTestCase):
    """The Calendar tour explains the grid, its menus and the side panel."""

    def steps(self):
        return {str(step.title): step for step in _registry["calendar"].steps}

    def test_steps_in_order(self):
        """The tour goes from the header, to the grid, to the side panel."""
        titles = [str(step.title) for step in _registry["calendar"].steps]
        self.assertEqual(
            titles,
            [
                "Calendar",
                "This Period",
                "Move Around",
                "Day, Week, Month, Year",
                "Click Any Day",
                "New Activity",
                "Mark as Unavailable",
                "An Event",
                "Event Details",
                "Show",
                "Team Members",
                "Choose Members",
                "Color by",
                "Status Colours",
                "My Calendars",
                "Add a Calendar",
                "Calendar Options",
            ],
        )

    def test_a_day_is_clicked_with_a_tap_and_each_menu_step_reopens_the_menu(self):
        """A day needs a real tap, and the menu closes on any outside click."""
        steps = self.steps()
        for title in ("Click Any Day", "New Activity", "Mark as Unavailable"):
            self.assertIn("tap", steps[title].before[0], title)
        self.assertTrue(steps["Mark as Unavailable"].after)

    def test_the_member_window_is_a_single_step(self):
        """The window that picks team members is one step, not one per control."""
        steps = self.steps()
        self.assertEqual(steps["Choose Members"].target, "#horillaModalBox")
        for title in ("Search", "Select All", "Select"):
            self.assertNotIn(title, steps)

    def test_the_tour_gives_back_your_scope_and_colour_mode(self):
        """Team and Status are switched on for the tour, then back to Mine and Type."""
        steps = self.steps()
        after = [action["click"] for action in steps["Choose Members"].after]
        self.assertIn('.calendar-scope-btn[data-scope="mine"]', after)
        after = [action["click"] for action in steps["Status Colours"].after]
        self.assertEqual(after, ['.color-by-btn[data-color-by="type"]'])
