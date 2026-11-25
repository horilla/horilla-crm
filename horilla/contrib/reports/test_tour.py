"""
Tests for the Reports tours (``horilla/contrib/reports/tour.py``).
"""

# Third-party imports (Django)
from django.test import SimpleTestCase

# First party imports (Horilla)
from horilla.contrib.tour.registry import _registry
from horilla.contrib.tour.testing import TourOwnershipTestsMixin


class ReportsTourOwnershipTests(TourOwnershipTestsMixin, SimpleTestCase):
    """The Reports tours come from this app and start by themselves once."""

    MODULE = "horilla.contrib.reports.tour"
    KEYS = (
        "reports_list",
        "reports_detail",
    )


class ReportsTourTests(SimpleTestCase):
    """The Reports tours explain the gear menu, the default reports and each part of a report."""

    def test_list_tour_goes_from_the_gear_to_the_default_reports_window(self):
        """The list tour is short: the gear, its menu, then the window that loads reports."""
        titles = [str(step.title) for step in _registry["reports_list"].steps]
        self.assertEqual(
            titles,
            [
                "Reports",
                "Settings",
                "Load Default Reports",
                "Select Default Reports",
                "Select All",
                "The Reports",
                "Create",
            ],
        )

    def test_the_gear_menu_step_lights_the_gear_with_its_menu(self):
        """The menu step lights the gear together with the menu it opens."""
        steps = {str(step.title): step for step in _registry["reports_list"].steps}
        self.assertEqual(steps["Load Default Reports"].target, "#dropdown")
        self.assertEqual(steps["Load Default Reports"].also, "#dropdownDefaultButton")

    def test_only_the_first_step_of_the_window_opens_it(self):
        """The window opens once; the steps inside it just find their part."""
        steps = {str(step.title): step for step in _registry["reports_list"].steps}
        self.assertTrue(steps["Select Default Reports"].before)
        for title in ("Select All", "The Reports", "Create"):
            self.assertFalse(steps[title].before, title)
        self.assertTrue(steps["Create"].after)

    def test_detail_tour_covers_each_part_of_a_report(self):
        """Every part of the report page has a step, in the order it appears."""
        titles = [str(step.title) for step in _registry["reports_detail"].steps]
        self.assertEqual(
            titles,
            [
                "Your Report",
                "Back",
                "Reload",
                "Edit",
                "Download",
                "Total Count",
                "Grouping",
                "Filters",
                "No Data Yet",
                "Pivot, Details, Chart",
                "Pivot",
                "Details",
                "Add to Dashboard",
                "Chart",
                "Chart Options",
            ],
        )

    def test_views_are_opened_by_clicking_their_tab(self):
        """Pivot, Details and Chart are shown one at a time, so each step clicks its tab."""
        steps = {str(step.title): step for step in _registry["reports_detail"].steps}
        for title, view in (
            ("Pivot", "pivot"),
            ("Details", "detail"),
            ("Chart", "chart"),
        ):
            clicks = [action["click"] for action in steps[title].before]
            self.assertEqual(clicks, [f'#rpt-summary [data-view="{view}"]'], title)

    def test_a_report_with_no_data_gets_its_own_step(self):
        """The no-data step points at the box shown instead of the tables."""
        steps = {str(step.title): step for step in _registry["reports_detail"].steps}
        self.assertEqual(
            steps["No Data Yet"].target, "#rpt-summary + div:not(#rpt-grid)"
        )
