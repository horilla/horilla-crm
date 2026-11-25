"""
Tests for what the tour app adds to the framework: its entry in the header account
menu and the launcher it injects into the page.

Only the tour app and the framework registries are used. What the other rows of the
header menu are is tested by the app that owns them.
"""

# Third-party imports (Django)
from django.apps import apps
from django.template import Context, Template
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

# First party imports (Horilla)
from horilla.menu.header_menu import get_header_menu
from horilla.registry.asset_registry import get_registered_html

LAUNCHER_TEMPLATE = "tour/slots/launcher.html"


class ProductToursHeaderMenuTests(SimpleTestCase):
    """The Product Tours row of the account dropdown."""

    def _row(self):
        return next(
            row
            for row in get_header_menu()
            if str(row["title"]) == str(_("Product Tours"))
        )

    def test_product_tours_attributes_live_on_attrs(self):
        """Tour hx/aria keys come from the class attrs dict."""
        row = self._row()
        self.assertEqual(row["url"], "#")
        self.assertEqual(row["attrs"]["id"], "horilla-tour-launcher")
        self.assertEqual(row["attrs"]["hx-target"], "#tour-panel-content")
        self.assertEqual(str(row["attrs"]["hx-get"]), reverse("tour:panel"))
        self.assertNotIn("order", row["attrs"])
        self.assertNotIn("title", row["attrs"])

        html = Template(
            '<a href="{{ item.url }}"'
            ' {% for attr, value in item.attrs.items %}{{ attr }}="{{ value }}" {% endfor %}>'
        ).render(Context({"item": row}))
        self.assertIn('href="#"', html)
        self.assertIn('id="horilla-tour-launcher"', html)
        self.assertIn('hx-get="/tour/"', html)
        self.assertIn('hx-vals="js:{path: window.location.pathname}"', html)


class LauncherTests(SimpleTestCase):
    """The panel, popover and message card injected at the end of the page."""

    def test_launcher_is_injected_into_the_pages_but_not_the_login_page(self):
        """The slot is registered for the base page, not for the login page."""
        self.assertIn(LAUNCHER_TEMPLATE, get_registered_html("body_end"))
        self.assertNotIn(LAUNCHER_TEMPLATE, get_registered_html("body_end", "login"))

    def test_launcher_has_the_panel_and_its_content_box(self):
        """The button loads the list with htmx into the panel's content box, with a spinner."""
        html = render_to_string(LAUNCHER_TEMPLATE)
        for expected in (
            'id="horilla-tour-panel"',
            'id="tour-panel-content"',
            'id="tour-panel-loading"',
            'aria-labelledby="tour-panel-title"',
            'id="horilla-tour-popover"',
            'id="horilla-tour-card"',
        ):
            self.assertIn(expected, html)
        # The app's own themed spinner, not the white icon made for the red buttons.
        self.assertNotIn("assets/icons/spinner.svg", html)
        self.assertNotIn("data-loading=", html)
        self.assertNotIn('aria-label="Product tours"', html)

    def test_no_template_comment_leaks_into_the_launcher(self):
        """Django's {# ... #} is single-line only: a multi-line one is printed as text."""
        html = render_to_string(LAUNCHER_TEMPLATE)
        for marker in ("{#", "#}", "{%", "%}"):
            self.assertNotIn(marker, html)

    def test_the_engine_is_loaded_on_every_page(self):
        """``tour.js`` is declared as a script of the app, so every page loads it."""
        self.assertEqual(apps.get_app_config("tour").js_files, "tour/assets/js/tour.js")
