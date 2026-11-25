"""
Tests for the Dashboards and Home tours (``horilla/contrib/dashboard/tour.py``).
"""

# Third-party imports (Django)
from django.test import SimpleTestCase

# First party imports (Horilla)
from horilla.contrib.tour.registry import _registry
from horilla.contrib.tour.testing import TourOwnershipTestsMixin


class DashboardTourOwnershipTests(TourOwnershipTestsMixin, SimpleTestCase):
    """The Dashboards and Home tours come from this app and start by themselves once."""

    MODULE = "horilla.contrib.dashboard.tour"
    KEYS = (
        "dashboards_list",
        "dashboards_detail",
        "dashboard_home",
    )


class DashboardsTourTests(SimpleTestCase):
    """The Dashboards tours explain the list and the parts of one dashboard."""

    def test_list_tour_steps(self):
        """The list tour covers the buttons, the table and the sidebar."""
        titles = [str(step.title) for step in _registry["dashboards_list"].steps]
        self.assertEqual(
            titles,
            [
                "Dashboards",
                "New Dashboard",
                "New Folder",
                "Open a Dashboard",
                "Is Default",
                "Actions",
                "Browse",
            ],
        )

    def test_is_default_explains_the_home_page(self):
        """The default dashboard is the one shown on Home, and only one can be."""
        steps = {str(step.title): step for step in _registry["dashboards_list"].steps}
        body = str(steps["Is Default"].body)
        self.assertIn("Home", body)
        self.assertIn("one", body)

    def test_detail_tour_steps(self):
        """The detail tour covers the header, reorder mode and each kind of card."""
        titles = [str(step.title) for step in _registry["dashboards_detail"].steps]
        self.assertEqual(
            titles,
            [
                "Your Dashboard",
                "Add Components",
                "Reorder",
                "Save or Cancel",
                "Drag",
                "A Number",
                "Number Options",
                "A Chart",
                "Chart Options",
                "A Table",
                "Table Options",
            ],
        )

    def test_reorder_mode_is_opened_and_left_by_the_tour(self):
        """Reorder mode is turned on for the Save/Cancel step and off after the Drag step."""
        steps = {str(step.title): step for step in _registry["dashboards_detail"].steps}
        self.assertEqual(steps["Save or Cancel"].target, "#editModeActions")
        self.assertEqual(steps["Save or Cancel"].before[0]["click"], "#editLayoutBtn")
        # Nothing is saved: the tour leaves reorder mode with Cancel.
        self.assertEqual(steps["Drag"].after[0]["click"], "#cancelEditBtn")
        self.assertEqual(steps["Reorder"].before[0]["click"], "#cancelEditBtn")

    def test_each_kind_of_card_has_a_menu_step_that_lights_the_button_with_its_menu(
        self,
    ):
        """Number, chart and table each explain their "…" menu."""
        steps = {str(step.title): step for step in _registry["dashboards_detail"].steps}
        for title in ("Number Options", "Chart Options", "Table Options"):
            step = steps[title]
            self.assertIn("dropdownbtn", step.target, title)
            self.assertTrue(step.also.endswith(".dropdown-content"), title)
            self.assertTrue(step.before and step.after, title)

    def test_dashboard_tours_share_the_home_page_group(self):
        """The Home tour and the Dashboards tours are listed under one heading."""
        groups = {
            str(_registry[key].group)
            for key in ("dashboard_home", "dashboards_list", "dashboards_detail")
        }
        self.assertEqual(len(groups), 1)
