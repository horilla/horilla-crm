"""
Tests for the Activities tours (``horilla/contrib/activity/tour.py``).
"""

# Third-party imports (Django)
from django.test import SimpleTestCase

# First party imports (Horilla)
from horilla.contrib.tour.registry import _registry
from horilla.contrib.tour.testing import TourOwnershipTestsMixin


class ActivityTourOwnershipTests(TourOwnershipTestsMixin, SimpleTestCase):
    """The Activities tours come from this app and start by themselves once."""

    MODULE = "horilla.contrib.activity.tour"
    KEYS = (
        "activities_list",
        "activities_detail",
    )


class ActivitiesTourTests(SimpleTestCase):
    """The Activities tours explain the tabs, the columns of an activity and its record."""

    def test_list_tour_steps(self):
        """The list tour covers the tabs, New, the layouts and the columns special to activities."""
        titles = [str(step.title) for step in _registry["activities_list"].steps]
        self.assertEqual(
            titles,
            [
                "Activities",
                "Tabs",
                "New",
                "Layouts",
                "Pick a Layout",
                "Open an Activity",
                "Related To",
                "Actions",
            ],
        )

    def test_layouts_button_and_menu_are_two_steps(self):
        """Lighting the button and its menu together would light the buttons between them."""
        steps = {str(step.title): step for step in _registry["activities_list"].steps}
        self.assertEqual(steps["Layouts"].target, "#layoutDropdownButton")
        self.assertIsNone(steps["Layouts"].also)
        self.assertEqual(steps["Pick a Layout"].target, "#layoutDropdown")

    def test_related_to_tab_follows_the_details_tab(self):
        """The detail tour adds the Related To tab of an activity right after Details."""
        titles = [str(step.title) for step in _registry["activities_detail"].steps]
        self.assertEqual(titles[titles.index("Details") + 1], "Related To")
