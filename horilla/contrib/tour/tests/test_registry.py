"""
Tests for the tour registry: validation, permission filtering and URL helpers.

They use fake tours and the tour app's own pages only. The tours of the other apps are
tested in those apps, next to their ``tour.py``.
"""

# Third-party imports (Django)
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

# Local imports
from ..presets import list_page_steps
from ..registry import Step, Tour, _registry, get_tours_for, resolve_view_name
from ..testing import FakeUser, TourOwnershipTestsMixin
from .support import RESTRICTED_PERMISSION, FakeToursMixin


def _valid_attrs(**overrides):
    attrs = {
        "key": "test_tour",
        "title": "Test",
        "match": ("tour:panel",),
        "steps": [Step(title="One", body="Body")],
    }
    attrs.update(overrides)
    return attrs


class TourValidationTests(SimpleTestCase):
    """Malformed tours must fail at import time, not in the browser."""

    def setUp(self):
        """Create the records these tests share."""
        self._snapshot = dict(_registry)

    def tearDown(self):
        """Clear the records these tests created."""
        _registry.clear()
        _registry.update(self._snapshot)

    def make(self, **overrides):
        """Make."""
        return type("TmpTour", (Tour,), _valid_attrs(**overrides))

    def test_valid_tour_registers(self):
        """Valid tour registers."""
        tour = self.make()
        self.assertIs(_registry["test_tour"], tour)

    def test_redefining_same_class_replaces(self):
        """Redefining same class replaces."""
        first = self.make()
        # Same module + qualname (e.g. module reload) must not be a duplicate.
        second = self.make()
        self.assertIsNot(first, second)
        self.assertIs(_registry["test_tour"], second)

    def test_missing_steps_rejected(self):
        """Missing steps rejected."""
        with self.assertRaises(ImproperlyConfigured):
            self.make(steps=[])

    def test_non_step_rejected(self):
        """Non step rejected."""
        with self.assertRaises(ImproperlyConfigured):
            self.make(steps=["nope"])

    def test_invalid_side_rejected(self):
        """Invalid side rejected."""
        with self.assertRaises(ImproperlyConfigured):
            self.make(steps=[Step(title="One", body="Body", side="sideways")])

    def test_invalid_align_rejected(self):
        """Invalid align rejected."""
        with self.assertRaises(ImproperlyConfigured):
            self.make(steps=[Step(title="One", body="Body", align="middle")])

    def test_valid_align_is_serialised(self):
        """Valid align is serialised."""
        step = Step(title="One", body="Body", align="end")
        self.assertEqual(step.to_dict()["align"], "end")
        self.assertIsNone(Step(title="One", body="Body").to_dict()["align"])

    def test_match_must_be_a_list(self):
        """Match must be a list."""
        with self.assertRaises(ImproperlyConfigured):
            self.make(match="tour:panel")

    def test_open_with_needs_both_entries(self):
        """Open with needs both entries."""
        with self.assertRaises(ImproperlyConfigured):
            self.make(open_with={"from": "tour:panel"})

    def test_abstract_subclass_not_registered(self):
        """Abstract subclass not registered."""
        type("AbstractTour", (Tour,), {"abstract": True, "key": "abstract_tour"})
        self.assertNotIn("abstract_tour", _registry)


class TourBehaviourTests(FakeToursMixin, SimpleTestCase):
    """Permission filtering, matching and start links."""

    def test_every_tour_builds_a_start_link(self):
        """Every tour builds a start link."""
        for key, tour in _registry.items():
            link = tour.start_link()
            self.assertIsNotNone(link, key)
            self.assertIn(f"tour={key}", link)

    def test_permission_filters_tours(self):
        """Permission filters tours."""
        everyone = FakeUser()
        privileged = FakeUser([RESTRICTED_PERMISSION])
        restricted = self.tours["restricted_tour"]
        self.assertNotIn(restricted, get_tours_for(everyone))
        self.assertIn(restricted, get_tours_for(privileged))
        self.assertIn(self.tours["page_tour"], get_tours_for(everyone))

    def test_tours_are_listed_by_order_then_title(self):
        """The display order is ``order``, then the title."""
        keys = [tour.key for tour in get_tours_for(FakeUser([RESTRICTED_PERMISSION]))]
        self.assertEqual(
            keys,
            [
                "other_page_tour",
                "restricted_tour",
                "page_tour",
                "second_page_tour",
                "manual_tour",
            ],
        )

    def test_anonymous_user_sees_nothing(self):
        """Anonymous user sees nothing."""
        user = FakeUser()
        user.is_authenticated = False
        self.assertEqual(get_tours_for(user), [])

    def test_to_dict_is_json_ready(self):
        """To dict is json ready."""
        data = self.tours["page_tour"].to_dict()
        self.assertEqual(data["key"], "page_tour")
        self.assertNotIn("next_tour", data)
        for step in data["steps"]:
            self.assertIsInstance(step["title"], str)
            self.assertIsInstance(step["body"], str)

    def test_a_tour_matches_only_its_own_pages(self):
        """``matches`` is true for the URL names in ``match`` and nothing else."""
        tour = self.tours["page_tour"]
        self.assertTrue(tour.matches("tour:panel"))
        self.assertFalse(tour.matches("tour:current"))
        self.assertFalse(tour.matches(None))

    def test_resolve_view_name_handles_arguments(self):
        """Resolve view name handles arguments."""
        self.assertEqual(
            resolve_view_name("/tour/definition/some_tour/"), "tour:definition"
        )
        self.assertEqual(resolve_view_name("/tour/"), "tour:panel")
        self.assertEqual(resolve_view_name("/tour/current/"), "tour:current")
        self.assertIsNone(resolve_view_name("/definitely/not/a/page/"))


class AppShellOwnershipTests(TourOwnershipTestsMixin, SimpleTestCase):
    """The shell tour belongs to no app: it lives in the tour app's own ``tour.py``."""

    MODULE = "horilla.contrib.tour.tour"
    KEYS = ("app_shell",)


class ShellTourTests(SimpleTestCase):
    """The shell tour walks through the sidebar and every header action."""

    def titles(self):
        """Titles."""
        return [str(step.title) for step in _registry["app_shell"].steps]

    def test_covers_every_header_action(self):
        """Covers every header action."""
        titles = self.titles()
        for expected in (
            "Global Search",
            "Toggle Theme",
            "Settings",
            "Recently Viewed",
            "Language",
            "Switch Company",
            "Notifications",
            "Your Profile",
        ):
            self.assertIn(expected, titles)

    def test_header_steps_run_left_to_right(self):
        """Header steps run left to right."""
        titles = self.titles()
        order = [
            titles.index(name)
            for name in (
                "Global Search",
                "Toggle Theme",
                "Settings",
                "Recently Viewed",
                "Language",
                "Switch Company",
                "Notifications",
                "Your Profile",
            )
        ]
        self.assertEqual(order, sorted(order))

    def test_sidebar_step_points_at_the_sidebar(self):
        """Sidebar step points at the sidebar."""
        step = next(
            s for s in _registry["app_shell"].steps if str(s.title) == "Sidebar"
        )
        self.assertTrue(step.target.startswith("#sidebar"), step.target)

    def test_header_buttons_are_found_by_icon_not_by_translated_text(self):
        """Header buttons are found by icon not by translated text."""
        for step in _registry["app_shell"].steps:
            if step.target and step.target.startswith("#header button"):
                self.assertIn(".fa-", step.target)
                self.assertNotIn("aria-label", step.target)
                self.assertNotIn("title=", step.target)


class ListPresetTests(SimpleTestCase):
    """Steps that point at table rows must skip at once when the list is empty."""

    def test_table_steps_skip_when_there_are_no_records(self):
        steps = {
            str(step.title): step
            for step in list_page_steps("item-list", "item-create", "items")
        }
        for title in (
            "Sort",
            "Select Rows",
            "Bulk Actions",
            "Open a Record",
            "Row Actions",
        ):
            step = steps[title]
            self.assertTrue(step.only_if or (step.target and not step.before), title)


class LitTogetherTests(SimpleTestCase):
    """A step can light a control and the pop-up it opens as one area."""

    def test_also_is_sent_to_the_browser(self):
        """The ``also`` selector is part of the step's JSON, empty when unused."""
        self.assertIsNone(Step(title="One", body="Body").to_dict()["also"])
        step = Step(title="One", body="Body", target="#a", also="#b")
        self.assertEqual(step.to_dict()["also"], "#b")
