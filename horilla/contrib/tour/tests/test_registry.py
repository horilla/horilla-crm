"""
Tests for the tour registry: validation, permission filtering and URL helpers.
"""

# Third-party imports (Django)
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

# Local imports
from ..presets import list_page_steps
from ..registry import Step, Tour, _registry, get_tours_for, resolve_view_name


class FakeUser:
    """Minimal user object for permission checks."""

    is_authenticated = True

    def __init__(self, perms=()):
        self._perms = set(perms)

    def has_perm(self, perm):
        """Has perm."""
        return perm in self._perms


def _valid_attrs(**overrides):
    attrs = {
        "key": "test_tour",
        "title": "Test",
        "match": ("dashboard:home_view",),
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
            self.make(match="dashboard:home_view")

    def test_open_with_needs_both_entries(self):
        """Open with needs both entries."""
        with self.assertRaises(ImproperlyConfigured):
            self.make(open_with={"from": "dashboard:home_view"})

    def test_abstract_subclass_not_registered(self):
        """Abstract subclass not registered."""
        type("AbstractTour", (Tour,), {"abstract": True, "key": "abstract_tour"})
        self.assertNotIn("abstract_tour", _registry)


class TourBehaviourTests(SimpleTestCase):
    """Permission filtering, matching and start links."""

    def test_shipped_tours_are_registered(self):
        """Shipped tours are registered."""
        for key in ("app_shell", "dashboard_home", "leads_list", "leads_detail"):
            self.assertIn(key, _registry)

    def test_every_tour_builds_a_start_link(self):
        """Every tour builds a start link."""
        for key, tour in _registry.items():
            link = tour.start_link()
            self.assertIsNotNone(link, key)
            self.assertIn(f"tour={key}", link)

    def test_permission_filters_tours(self):
        """Permission filters tours."""
        everyone = FakeUser()
        sales = FakeUser(["leads.view_lead"])
        self.assertNotIn(_registry["leads_list"], get_tours_for(everyone))
        self.assertIn(_registry["leads_list"], get_tours_for(sales))
        self.assertIn(_registry["app_shell"], get_tours_for(everyone))

    def test_anonymous_user_sees_nothing(self):
        """Anonymous user sees nothing."""
        user = FakeUser()
        user.is_authenticated = False
        self.assertEqual(get_tours_for(user), [])

    def test_to_dict_is_json_ready(self):
        """To dict is json ready."""
        data = _registry["leads_list"].to_dict(FakeUser(["leads.view_lead"]))
        self.assertEqual(data["key"], "leads_list")
        self.assertNotIn("next_tour", data)
        for step in data["steps"]:
            self.assertIsInstance(step["title"], str)
            self.assertIsInstance(step["body"], str)

    def test_resolve_view_name_handles_arguments(self):
        """Resolve view name handles arguments."""
        self.assertEqual(
            resolve_view_name("/crm/leads/leads-detail/5/"), "leads:leads_detail"
        )
        self.assertEqual(
            resolve_view_name("/crm/leads/leads-view/"), "leads:leads_view"
        )
        self.assertIsNone(resolve_view_name("/definitely/not/a/page/"))


class TourTextTests(SimpleTestCase):
    """The product name must not appear in anything a user reads in a tour."""

    BRAND = "horilla"

    def test_no_tour_text_mentions_the_company_name(self):
        """No tour text mentions the company name."""
        for key, tour in _registry.items():
            texts = [str(tour.title), str(tour.description), str(tour.group)]
            for step in tour.steps:
                texts += [str(step.title), str(step.body)]
            for text in texts:
                self.assertNotIn(self.BRAND, text.lower(), f"{key}: {text!r}")


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
            "Recently viewed",
            "Language",
            "Switch company",
            "Notifications",
            "Your profile",
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
                "Recently viewed",
                "Language",
                "Switch company",
                "Notifications",
                "Your profile",
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


class TourOwnershipTests(SimpleTestCase):
    """Each app's tours are loaded from its own ``tour.py``."""

    def test_every_shipped_tour_starts_by_itself_once(self):
        """Every shipped tour starts by itself once."""
        for key in ("app_shell", "dashboard_home", "leads_list", "leads_detail"):
            self.assertTrue(_registry[key].auto_start, key)

    def test_tours_come_from_the_apps_that_own_them(self):
        """Tours come from the apps that own them."""
        expected = {
            "dashboard_home": "horilla.contrib.dashboard.tour",
            "leads_list": "horilla_crm.leads.tour",
            "leads_detail": "horilla_crm.leads.tour",
            "app_shell": "horilla.contrib.tour.tour",
        }
        for key, module in expected.items():
            self.assertEqual(_registry[key].__module__, module, key)


class ListPresetTests(SimpleTestCase):
    """Steps that point at table rows must skip at once when the list is empty."""

    def test_table_steps_skip_when_there_are_no_records(self):
        steps = {
            str(step.title): step
            for step in list_page_steps("leads-list", "lead-create", "leads")
        }
        for title in (
            "Sort",
            "Select rows",
            "Bulk actions",
            "Open a record",
            "Row actions",
        ):
            step = steps[title]
            self.assertTrue(step.only_if or (step.target and not step.before), title)
