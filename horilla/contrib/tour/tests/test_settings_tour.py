"""
Tests for the Settings and My Settings tours (``settings_tour.py`` in the tour app).

These tours explain pages that the core app owns, so they point at its page names. The
core app itself never imports the tour app.
"""

# Third-party imports (Django)
from django.test import SimpleTestCase

# Local imports
from ..registry import _registry
from ..testing import TourOwnershipTestsMixin
from ..views import build_panel_context


class SettingsTourOwnershipTests(TourOwnershipTestsMixin, SimpleTestCase):
    """The Settings tours come from the tour app and start by themselves once."""

    MODULE = "horilla.contrib.tour.settings_tour"
    KEYS = ("settings", "my_settings")


class SettingsToursTests(SimpleTestCase):
    """The Settings tours explain the page layout, not each settings page."""

    def test_settings_tour_steps(self):
        """The tour goes from the search box, to the menu, to the page area."""
        titles = [str(step.title) for step in _registry["settings"].steps]
        self.assertEqual(
            titles,
            [
                "Settings",
                "Search Settings",
                "Sections",
                "Open a Page",
                "Open or Close a Section",
                "The Page",
            ],
        )

    def test_my_settings_tour_steps(self):
        """The tour goes from the profile card, to the menu, to the page area."""
        titles = [str(step.title) for step in _registry["my_settings"].steps]
        self.assertEqual(
            titles, ["My Settings", "Your Profile", "Your Pages", "The Page"]
        )

    def test_settings_tour_needs_the_settings_permission(self):
        """Only users who may open Settings are offered its tour."""
        self.assertEqual(
            _registry["settings"].permission, "core.can_view_horilla_settings"
        )
        self.assertIsNone(_registry["my_settings"].permission)

    def test_each_tour_belongs_to_its_page(self):
        """The tours start from the page they explain."""
        self.assertEqual(_registry["settings"].match, ("core:settings_view",))
        self.assertEqual(_registry["my_settings"].match, ("core:my_settings_view",))
        for key in ("settings", "my_settings"):
            self.assertTrue(_registry[key].start_link(), key)

    def test_the_tours_follow_the_page_that_settings_opens(self):
        """Settings pushes the URL of the page it opens, and the tour must still match it."""
        settings = _registry["settings"]
        self.assertTrue(settings.matches("core:settings_view"))
        self.assertTrue(settings.matches("core:company_information"))
        self.assertTrue(settings.matches("core:user_view"))
        self.assertFalse(settings.matches("core:my_profile_view"))
        self.assertFalse(settings.matches("dashboard:home_view"))
        self.assertIn("core:company_information", settings.to_dict()["match"])

        my_settings = _registry["my_settings"]
        self.assertTrue(my_settings.matches("core:my_settings_view"))
        self.assertTrue(my_settings.matches("core:my_profile_view"))
        self.assertTrue(my_settings.matches("core:user_holiday_view"))
        self.assertFalse(my_settings.matches("core:company_information"))

    def test_the_panel_lists_the_tour_on_the_page_settings_opened(self):
        """On the company page the Settings tour is listed under "On this page"."""
        user = type(
            "User", (), {"is_authenticated": True, "has_perm": lambda *_: True}
        )()
        groups = build_panel_context(user, "/company-information/")["groups"]
        on_page = [tour["key"] for tour in groups[0]["tours"]]
        self.assertEqual(str(groups[0]["name"]), "On this page")
        self.assertIn("settings", on_page)
        self.assertNotIn("my_settings", on_page)
