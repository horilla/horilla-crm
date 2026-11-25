"""
Tests for the Forecast tour (``horilla_crm/forecast/tour.py``).
"""

# Third-party imports (Django)
from django.test import SimpleTestCase

# First party imports (Horilla)
from horilla.contrib.tour.registry import _registry, get_tours_for
from horilla.contrib.tour.testing import FakeUser, TourOwnershipTestsMixin


class ForecastTourOwnershipTests(TourOwnershipTestsMixin, SimpleTestCase):
    """The Forecast tour comes from this app and starts by itself once."""

    MODULE = "horilla_crm.forecast.tour"
    KEYS = ("forecast",)


class ForecastTourTests(SimpleTestCase):
    """The Forecast tour points at the table by column position, in header order."""

    def test_columns_are_explained_in_header_order(self):
        """Each column step targets the header cell in the position of its title."""
        positions = {
            "Target": 2,
            "Achievement": 3,
            "Gap": 4,
            "Closed": 5,
            "Commit Forecast": 6,
            "Best Case": 7,
            "Open Pipeline": 8,
        }
        steps = {str(step.title): step for step in _registry["forecast"].steps}
        for title, position in positions.items():
            self.assertTrue(
                steps[title].target.endswith(f"th:nth-child({position})"), title
            )

    def test_forecast_needs_permission_to_view_opportunities(self):
        """Only users who can see opportunities are offered the Forecast tour."""
        tour = _registry["forecast"]
        self.assertNotIn(tour, get_tours_for(FakeUser()))
        self.assertIn(
            tour, get_tours_for(FakeUser(["opportunities.view_own_opportunity"]))
        )


class ForecastLitTogetherTests(SimpleTestCase):
    """A step can light a control and the pop-up it opens as one area."""

    def test_forecast_dropdown_steps_light_the_control_with_its_pop_up(self):
        """The user and period steps light the box or button together with its list."""
        steps = {str(step.title): step for step in _registry["forecast"].steps}
        self.assertEqual(steps["Whose Forecast"].target, "#user-data-container")
        self.assertEqual(steps["Whose Forecast"].also, ".select2-dropdown")
        self.assertEqual(steps["Periods"].target, "#forecast-period-range-trigger")
        self.assertIn("dropdown-content", steps["Periods"].also)
