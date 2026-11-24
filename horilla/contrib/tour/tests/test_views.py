"""
Tests for the tour app views: the panel, the current-page lookup (which decides
whether a tour starts by itself), the tour definition and the "seen" record.

The views are called directly with fake tours that point at the tour app's own pages,
so no other app, page or model is involved. The only database rows are the users the
tour model itself points at.
"""

# Standard library imports
import json

# Third-party imports (Django)
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase
from django.urls import reverse

# Local imports
from ..models import TourSeen
from ..views import TourCurrentView, TourDefinitionView, TourPanelView, TourSeenView
from .support import OTHER_PAGE, PAGE, FakeToursMixin

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
HTMX = {"HTTP_HX_REQUEST": "true"}


class TourViewTestCase(FakeToursMixin, TestCase):
    """Base: a superuser (holds every permission), a user without any, and fake tours."""

    def setUp(self):
        """Create the users these tests share."""
        super().setUp()
        user_model = get_user_model()
        self.factory = RequestFactory()
        self.admin = user_model.objects.create_superuser(
            username="admin", email="admin@example.com", password="pass"
        )
        self.plain = user_model.objects.create_user(
            username="plain", email="plain@example.com", password="pass"
        )

    def post_json(self, payload, user=None):
        """POST a JSON body to the ``seen`` view."""
        request = self.factory.post(
            reverse("tour:seen"),
            data=json.dumps(payload),
            content_type="application/json",
            **AJAX,
        )
        request.user = self.admin if user is None else user
        return TourSeenView.as_view()(request)


class PanelTests(TourViewTestCase):
    """The panel opened from the profile menu (an HTML fragment)."""

    def panel(self, path="", user=None, **extra):
        """The panel for the page at ``path``, as an htmx request."""
        request = self.factory.get(
            reverse("tour:panel"), {"path": path}, **HTMX, **extra
        )
        request.user = self.admin if user is None else user
        return TourPanelView.as_view()(request)

    def html(self, path="", user=None):
        """The panel's HTML."""
        return self.panel(path, user).content.decode()

    def test_login_required(self):
        """Login required."""
        # A normal request is redirected to the login page ...
        request = self.factory.get(reverse("tour:panel"))
        request.user = AnonymousUser()
        response = TourPanelView.as_view()(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])
        # ... and an htmx request gets an empty 204 so htmx can redirect.
        response = self.panel(user=AnonymousUser())
        self.assertEqual(response.status_code, 204)
        self.assertNotIn(b"Product tours", response.content)

    def test_panel_is_a_fragment(self):
        """Panel is a fragment."""
        response = self.panel()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"<html", response.content)

    def test_panel_shows_no_status_or_progress(self):
        """Panel shows no status or progress."""
        content = self.html(PAGE)
        for text in (
            "Resume",
            "Reset",
            "Replay",
            "Completed",
            "Dismissed",
            "Not started",
        ):
            self.assertNotIn(text, content)

    def test_page_tours_come_first(self):
        """Page tours come first."""
        content = self.html(PAGE)
        on_page = max(
            content.index("Working with the Panel"), content.index("Inside an Item")
        )
        # Tours for other pages come after the ones for this page.
        other = content.index("Finding Your Way Around")
        self.assertLess(on_page, other)
        self.assertIn("On this page", content)

    def test_other_pages_get_the_default_order_without_page_tours(self):
        """Other pages get the default order without page tours."""
        content = self.html("/no/such/page/")
        self.assertNotIn("On this page", content)
        order = [
            content.index(title)
            for title in (
                "Finding Your Way Around",
                "Working with the Panel",
                "Inside an Item",
            )
        ]
        self.assertEqual(order, sorted(order))

    def test_a_page_lists_its_own_tours_first(self):
        """The tours of the page the user is on are listed before the others."""
        content = self.html(OTHER_PAGE)
        self.assertLess(
            content.index("Finding Your Way Around"),
            content.index("Working with the Panel"),
        )

    def test_non_path_values_are_ignored(self):
        """Non path values are ignored."""
        response = self.panel("javascript:alert(1)")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"javascript:alert", response.content)

    def test_panel_hides_tours_the_user_cannot_use(self):
        """Panel hides tours the user cannot use."""
        self.assertIn("Restricted Tour", self.html(PAGE, user=self.admin))
        content = self.html(PAGE, user=self.plain)
        self.assertNotIn("Restricted Tour", content)
        self.assertIn("Working with the Panel", content)

    def test_panel_text_does_not_mention_the_company_name(self):
        """Panel text does not mention the company name."""
        self.assertNotIn("horilla", self.html(PAGE).lower())

    def test_no_template_comment_leaks_into_the_page(self):
        """Django's {# ... #} is single-line only: a multi-line one is printed as text."""
        content = self.html(PAGE)
        for marker in ("{#", "#}", "{%", "%}"):
            self.assertNotIn(marker, content)

    def test_truncated_card_text_has_a_tooltip(self):
        """
        The app's tooltip script shows a title attribute as a black pill, so the
        truncated title and description give the full text on hover. The link itself
        has none, so the pill does not flash as the pointer crosses a card.
        """
        content = self.html(PAGE)
        self.assertIn('title="Working with the Panel"', content)
        self.assertIn('title="Search, filter, switch layouts', content)
        link = content[content.index("<a") : content.index(">", content.index("<a"))]
        self.assertNotIn("title=", link)
        self.assertNotIn('aria-label="Product tours"', content)

    def test_each_card_is_one_link_that_starts_its_tour(self):
        """Each card is one link that starts its tour."""
        content = self.html(PAGE)
        self.assertIn('data-tour-start="page_tour"', content)
        # The card itself is the link: no separate Start button.
        self.assertNotIn("htp-btn", content)
        before_marker = content[: content.index('data-tour-card="page_tour"')]
        self.assertTrue(before_marker.rstrip().rsplit("<", 1)[-1].startswith("a"))
        self.assertIn("tour=page_tour", content)

    def test_only_the_inner_card_lifts_so_the_hover_area_is_stable(self):
        """Only the inner card lifts so the hover area is stable."""
        content = self.html(PAGE)
        self.assertIn("data-tour-card", content)
        # Hover effects are group-hover on the inner card, never on the link itself.
        self.assertNotIn(" hover:-translate-y-1", content)

    def test_cards_have_the_app_hover_effect(self):
        """Cards have the app hover effect."""
        content = self.html(PAGE)
        for cls in (
            "group-hover:border-primary-600",
            "group-hover:-translate-y-1",
            "group-hover:shadow-lg",
        ):
            self.assertIn(cls, content)


class CurrentViewTests(TourViewTestCase):
    """``current/`` resolves the page and says which tour (if any) starts by itself."""

    def current(self, path, user=None):
        """The JSON answer for ``path``."""
        request = self.factory.get(reverse("tour:current"), {"path": path}, **AJAX)
        request.user = self.admin if user is None else user
        response = TourCurrentView.as_view()(request)
        return json.loads(response.content)

    def test_resolves_pages_with_and_without_arguments(self):
        """Resolves pages with and without arguments."""
        self.assertEqual(self.current(PAGE)["view_name"], "tour:panel")
        self.assertEqual(
            self.current("/tour/definition/some_tour/")["view_name"], "tour:definition"
        )

    def test_a_page_starts_its_tours_in_display_order(self):
        """The tours of a page that start by themselves are listed in display order."""
        data = self.current(PAGE)
        self.assertEqual(data["view_name"], "tour:panel")
        self.assertEqual(
            data["auto"], ["restricted_tour", "page_tour", "second_page_tour"]
        )
        self.assertIn("labels", data)

    def test_a_tour_that_does_not_start_by_itself_is_not_listed(self):
        """``manual_tour`` is for the panel only."""
        self.assertNotIn("manual_tour", self.current(PAGE)["auto"])

    def test_tours_do_not_start_again_once_shown(self):
        """Tours do not start again once shown."""
        TourSeen.objects.create(user=self.admin, tour_key="restricted_tour")
        self.assertEqual(self.current(PAGE)["auto"], ["page_tour", "second_page_tour"])
        TourSeen.objects.create(user=self.admin, tour_key="page_tour")
        TourSeen.objects.create(user=self.admin, tour_key="second_page_tour")
        self.assertEqual(self.current(PAGE)["auto"], [])

    def test_seen_is_per_user(self):
        """Seen is per user."""
        TourSeen.objects.create(user=self.plain, tour_key="page_tour")
        self.assertEqual(
            self.current(PAGE)["auto"],
            ["restricted_tour", "page_tour", "second_page_tour"],
        )

    def test_every_user_gets_the_public_tours_on_their_first_visit(self):
        """A user without permissions still gets the tours that need none."""
        self.assertEqual(
            self.current(PAGE, user=self.plain)["auto"],
            ["page_tour", "second_page_tour"],
        )

    def test_each_page_tour_starts_by_itself_on_the_first_visit(self):
        """Seeing one page's tour does not use up another page's."""
        self.assertEqual(self.current(OTHER_PAGE)["auto"], ["other_page_tour"])
        TourSeen.objects.create(user=self.admin, tour_key="other_page_tour")
        self.assertEqual(self.current(OTHER_PAGE)["auto"], [])
        self.assertIn("page_tour", self.current(PAGE)["auto"])

    def test_users_without_the_permission_are_not_offered_the_tour(self):
        """Users without the permission are not offered the restricted tour."""
        self.assertNotIn("restricted_tour", self.current(PAGE, user=self.plain)["auto"])
        self.assertIn("restricted_tour", self.current(PAGE)["auto"])

    def test_unknown_path_has_no_view_name(self):
        """Unknown path has no view name."""
        data = self.current("/no/such/page/")
        self.assertIsNone(data["view_name"])
        self.assertEqual(data["auto"], [])


class DefinitionTests(TourViewTestCase):
    """``definition/<key>/`` returns the steps and the UI labels."""

    def definition(self, key, user=None):
        """The definition view's response for ``key``."""
        request = self.factory.get(reverse("tour:definition", args=[key]), **AJAX)
        request.user = self.admin if user is None else user
        return TourDefinitionView.as_view()(request, key=key)

    def test_returns_steps_and_labels(self):
        """Returns steps and labels."""
        response = self.definition("page_tour")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["key"], "page_tour")
        self.assertEqual(len(data["steps"]), 2)
        self.assertIn("finish", data["labels"])
        self.assertTrue(data["start_url"].endswith("tour=page_tour"))

    def test_carries_no_progress(self):
        """Carries no progress."""
        data = json.loads(self.definition("page_tour").content)
        for key in ("status", "last_step", "next_tour"):
            self.assertNotIn(key, data)

    def test_unknown_tour_is_404(self):
        """Unknown tour is 404."""
        self.assertEqual(self.definition("nope").status_code, 404)

    def test_forbidden_tour_is_404(self):
        """Forbidden tour is 404."""
        self.assertEqual(
            self.definition("restricted_tour", user=self.plain).status_code, 404
        )
        self.assertEqual(self.definition("restricted_tour").status_code, 200)


class SeenTests(TourViewTestCase):
    """``seen/`` remembers that a tour already started by itself."""

    def test_records_the_tour_once(self):
        """Records the tour once."""
        self.assertEqual(self.post_json({"key": "page_tour"}).status_code, 200)
        self.assertEqual(self.post_json({"key": "page_tour"}).status_code, 200)
        self.assertEqual(
            TourSeen.objects.filter(user=self.admin, tour_key="page_tour").count(), 1
        )

    def test_is_per_user(self):
        """Is per user."""
        self.post_json({"key": "page_tour"})
        self.assertFalse(TourSeen.objects.filter(user=self.plain).exists())

    def test_makes_the_tour_stop_starting_by_itself(self):
        """Makes the tour stop starting by itself."""

        def auto():
            """The tours that would start by themselves on the page."""
            request = self.factory.get(reverse("tour:current"), {"path": PAGE}, **AJAX)
            request.user = self.plain
            return json.loads(TourCurrentView.as_view()(request).content)["auto"]

        self.post_json({"key": "page_tour"}, user=self.plain)
        self.assertEqual(auto(), ["second_page_tour"])
        self.post_json({"key": "second_page_tour"}, user=self.plain)
        self.assertEqual(auto(), [])

    def test_rejects_invalid_payloads(self):
        """Rejects invalid payloads."""
        self.assertEqual(self.post_json({}).status_code, 400)
        request = self.factory.post(
            reverse("tour:seen"),
            data="{not json",
            content_type="application/json",
            **AJAX,
        )
        request.user = self.admin
        self.assertEqual(TourSeenView.as_view()(request).status_code, 400)

    def test_rejects_unknown_or_forbidden_tour(self):
        """Rejects unknown or forbidden tour."""
        self.assertEqual(self.post_json({"key": "nope"}).status_code, 404)
        self.assertEqual(self.post_json({"key": 5}).status_code, 404)
        self.assertEqual(
            self.post_json({"key": "restricted_tour"}, user=self.plain).status_code, 404
        )
        self.assertFalse(TourSeen.objects.exists())

    def test_old_endpoints_are_gone(self):
        """Old endpoints are gone."""
        for name in ("progress", "reset", "preference"):
            with self.assertRaises(Exception):
                reverse(f"tour:{name}")
