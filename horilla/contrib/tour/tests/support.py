"""
Support for the tour tests.

The tour app is tested on its own: no other app's tours, pages or models. Each test
runs with an empty registry that holds only the fake tours below, and they point at
the tour app's own pages (``tour:panel`` and ``tour:current``).
"""

# Standard library imports
from unittest import mock

# Local imports
from ..registry import Step, Tour, _registry

PAGE = "/tour/"  # the URL of ``tour:panel``
OTHER_PAGE = "/tour/current/"  # the URL of ``tour:current``
RESTRICTED_PERMISSION = "tour.add_tourseen"


def define_fake_tours():
    """Register the fake tours in the (empty) registry and return them by key."""

    class PageTour(Tour):
        """Starts by itself on the panel page, for everyone."""

        key = "page_tour"
        title = "Working with the Panel"
        description = "Search, filter, switch layouts and act on the items of a page."
        group = "Panel"
        order = 10
        match = ("tour:panel",)
        auto_start = True
        steps = [Step(title="One", body="First step."), Step(title="Two", body="Next.")]

    class SecondPageTour(Tour):
        """A second tour of the same page, listed after the first one."""

        key = "second_page_tour"
        title = "Inside an Item"
        description = "What each part of an item page shows."
        group = "Panel"
        order = 11
        match = ("tour:panel",)
        auto_start = True
        steps = [Step(title="One", body="First step.")]

    class OtherPageTour(Tour):
        """Belongs to another page."""

        key = "other_page_tour"
        title = "Finding Your Way Around"
        description = "The other page."
        group = "General"
        order = 0
        match = ("tour:current",)
        auto_start = True
        steps = [Step(title="One", body="First step.")]

    class RestrictedTour(Tour):
        """Only for users who hold a permission."""

        key = "restricted_tour"
        title = "Restricted Tour"
        description = "Needs a permission."
        group = "Panel"
        order = 5
        match = ("tour:panel",)
        permission = RESTRICTED_PERMISSION
        auto_start = True
        steps = [Step(title="One", body="First step.")]

    class ManualTour(Tour):
        """Starts only when a user asks for it."""

        key = "manual_tour"
        title = "Manual Tour"
        description = "Never starts by itself."
        group = "Panel"
        order = 30
        match = ("tour:panel",)
        auto_start = False
        steps = [Step(title="One", body="First step.")]

    return {
        tour.key: tour
        for tour in (
            PageTour,
            SecondPageTour,
            OtherPageTour,
            RestrictedTour,
            ManualTour,
        )
    }


class FakeToursMixin:
    """Run each test with an empty registry holding only the fake tours."""

    def setUp(self):
        """Replace the registry for this test and restore it afterwards."""
        super().setUp()
        patcher = mock.patch.dict(_registry, {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tours = define_fake_tours()
