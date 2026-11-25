"""
Helpers for tests of the apps that own tours.

The tour app's own tests use none of the other apps. What a tour of the leads,
forecast, reports, ... app says and points at is tested in that app, next to its
``tour.py``, with the mixins below. Import this module from a test only, never from
application code.
"""

# Local imports
from .registry import _registry


class FakeUser:
    """Minimal user object for permission checks."""

    is_authenticated = True

    def __init__(self, perms=()):
        self._perms = set(perms)

    def has_perm(self, perm):
        """Has perm."""
        return perm in self._perms


class TourOwnershipTestsMixin:
    """
    Checks every app should run on its own tours. Mix into a ``SimpleTestCase`` and set:

    ``MODULE``     the ``tour`` module of the app, which must define the tours
    ``KEYS``       the keys of the tours the app owns
    ``AUTO_START`` whether each tour starts by itself on a user's first visit
    """

    MODULE = None
    KEYS = ()
    AUTO_START = True
    BRAND = "horilla"

    def test_tours_are_registered_by_the_app_that_owns_them(self):
        """Each tour is registered and comes from the app's own ``tour.py``."""
        for key in self.KEYS:
            self.assertIn(key, _registry, key)
            self.assertEqual(_registry[key].__module__, self.MODULE, key)

    def test_every_tour_starts_by_itself_once(self):
        """Each tour starts by itself on a first visit (the tour app remembers it)."""
        for key in self.KEYS:
            self.assertEqual(_registry[key].auto_start, self.AUTO_START, key)

    def test_every_tour_builds_a_start_link(self):
        """The Start link of each tour can be built."""
        for key in self.KEYS:
            link = _registry[key].start_link()
            self.assertIsNotNone(link, key)
            self.assertIn(f"tour={key}", link)

    def test_no_tour_text_mentions_the_company_name(self):
        """The product name must not appear in anything a user reads in a tour."""
        for key in self.KEYS:
            tour = _registry[key]
            texts = [str(tour.title), str(tour.description), str(tour.group)]
            for step in tour.steps:
                texts += [str(step.title), str(step.body)]
            for text in texts:
                self.assertNotIn(self.BRAND, text.lower(), f"{key}: {text!r}")

    def test_detail_tours_open_through_the_first_row_of_their_list(self):
        """Each detail tour is reached by clicking the first record of its list."""
        for key in self.KEYS:
            if key.endswith("_detail"):
                open_with = _registry[key].open_with
                self.assertIn("tr:first-child td[hx-get]", open_with["click"], key)


class RelatedListStepsMixin:
    """
    Each list of a Related Lists tab is explained by its own step. Mix into a
    ``SimpleTestCase`` and set ``EXPECTED``: ``{tour key: [list step titles]}``.
    """

    EXPECTED = {}

    def test_list_steps_follow_the_related_lists_tab(self):
        """The list steps come right after the Related Lists tab step, in order."""
        for key, titles in self.EXPECTED.items():
            steps = [str(step.title) for step in _registry[key].steps]
            start = steps.index("Related Lists") + 1
            self.assertEqual(steps[start : start + len(titles)], titles, key)

    def test_a_list_step_opens_its_list_and_is_skipped_when_it_is_missing(self):
        """Each list step clicks the list's button, and needs that button to show."""
        for key in self.EXPECTED:
            steps = {str(step.title): step for step in _registry[key].steps}
            for title in self.EXPECTED[key]:
                step = steps[title]
                self.assertRegex(step.target, r"^#tab-[a-z_]+-btn$", f"{key}: {title}")
                self.assertEqual(step.only_if, step.target, f"{key}: {title}")
                clicked = [action["click"] for action in step.before]
                self.assertEqual(
                    clicked, ["#tab-related-lists", step.target], f"{key}: {title}"
                )
