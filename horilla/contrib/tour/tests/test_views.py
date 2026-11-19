"""
Tests for the tour app views: the panel, the current-page lookup (which decides
whether a tour starts by itself), the tour definition and the "seen" record.
"""

# Standard library imports
import json

# Third-party imports (Django)
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.test import TestCase
from login_history.models import post_login, post_logout

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.models import Company
from horilla.urls import reverse

# Local imports
from ..models import TourSeen

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
HTMX = {"HTTP_HX_REQUEST": "true"}


class TourViewTestCase(TestCase):
    """Base: a company, a superuser and a user without permissions."""

    @classmethod
    def setUpClass(cls):
        """Disconnect login-history signals so the test client can log in."""
        super().setUpClass()
        user_logged_in.disconnect(post_login)
        user_logged_out.disconnect(post_logout)

    @classmethod
    def tearDownClass(cls):
        """Reconnect the login-history signals."""
        user_logged_in.connect(post_login)
        user_logged_out.connect(post_logout)
        super().tearDownClass()

    def setUp(self):
        """Create the records these tests share."""
        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        self.admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
            company=self.company,
        )
        self.plain = User.objects.create_user(
            username="plain",
            email="plain@example.com",
            password="pass",
            company=self.company,
        )
        self.client.login(username="admin", password="pass")

    def post_json(self, name, payload):
        """POST a JSON body to the named tour URL."""
        return self.client.post(
            reverse(f"tour:{name}"),
            data=json.dumps(payload),
            content_type="application/json",
            **AJAX,
        )


class PanelTests(TourViewTestCase):
    """The panel opened from the profile menu (an HTML fragment)."""

    LEADS = "/crm/leads/leads-view/"

    def panel(self, path="", **extra):
        """Panel."""
        return self.client.get(reverse("tour:panel"), {"path": path}, **HTMX, **extra)

    def test_login_required(self):
        """Login required."""
        self.client.logout()
        # A normal request is redirected to the login page ...
        response = self.client.get(reverse("tour:panel"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])
        # ... and an htmx request gets an empty 204 so htmx can redirect.
        response = self.panel()
        self.assertEqual(response.status_code, 204)
        self.assertNotIn(b"Product tours", response.content)

    def test_panel_is_a_fragment(self):
        """Panel is a fragment."""
        response = self.panel()
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<html")

    def test_panel_shows_no_status_or_progress(self):
        """Panel shows no status or progress."""
        response = self.panel(self.LEADS)
        for text in (
            "Resume",
            "Reset",
            "Replay",
            "Completed",
            "Dismissed",
            "Not started",
        ):
            self.assertNotContains(response, text)

    def test_page_tours_come_first(self):
        """Page tours come first."""
        content = self.panel(self.LEADS).content.decode()
        leads = content.index("Working with the Leads list")
        # Reachable from the list through its first record, so listed here too.
        detail = content.index("Inside a lead")
        # Tours for other pages come after the ones for this page.
        shell = content.index("Find your way around")
        home = content.index("Your home page")
        self.assertLess(max(leads, detail), min(shell, home))

    def test_other_pages_get_the_default_order_without_page_tours(self):
        """Other pages get the default order without page tours."""
        content = self.panel("/no/such/page/").content.decode()
        order = [
            content.index(title)
            for title in (
                "Find your way around",
                "Your home page",
                "Working with the Leads list",
                "Inside a lead",
            )
        ]
        self.assertEqual(order, sorted(order))

    def test_home_lists_its_own_tours_first(self):
        """Home lists its own tours first."""
        content = self.panel("/dashboard/").content.decode()
        self.assertLess(
            max(content.index("Find your way around"), content.index("Your home page")),
            content.index("Working with the Leads list"),
        )

    def test_non_path_values_are_ignored(self):
        """Non path values are ignored."""
        response = self.panel("javascript:alert(1)")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "javascript:alert")

    def test_panel_hides_tours_the_user_cannot_use(self):
        """Panel hides tours the user cannot use."""
        self.client.login(username="plain", password="pass")
        response = self.panel(self.LEADS)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Working with the Leads list")
        self.assertContains(response, "Find your way around")

    def test_panel_text_does_not_mention_the_company_name(self):
        """Panel text does not mention the company name."""
        self.assertNotIn("horilla", self.panel(self.LEADS).content.decode().lower())

    def test_no_template_comment_leaks_into_the_page(self):
        # Django's {# ... #} is single-line only: a multi-line one is printed as text.
        """No template comment leaks into the page."""
        content = self.panel(self.LEADS).content.decode()
        for marker in ("{#", "#}", "{%", "%}"):
            self.assertNotIn(marker, content)
        page = self.client.get("/dashboard/", {"section": "home"}).content.decode()
        launcher = page[page.index('id="horilla-tour-launcher"') :]
        launcher = launcher[: launcher.index("</div>") + 6]
        for marker in ("{#", "#}", "{%", "%}"):
            self.assertNotIn(marker, launcher)

    def test_truncated_card_text_has_a_tooltip(self):
        # The app's tooltip script shows a title attribute as a black pill, so the
        # truncated title and description give the full text on hover. The link
        # itself has none, so the pill does not flash as the pointer crosses a card.
        """Truncated card text has a tooltip."""
        content = self.panel(self.LEADS).content.decode()
        self.assertIn('title="Working with the Leads list"', content)
        self.assertIn('title="Search, filter, switch layouts', content)
        link = content[content.index("<a") : content.index(">", content.index("<a"))]
        self.assertNotIn("title=", link)
        self.assertNotIn('aria-label="Product tours"', content)
        page = self.client.get("/dashboard/", {"section": "home"})
        self.assertNotContains(page, 'aria-label="Product tours"')
        self.assertContains(page, 'aria-labelledby="tour-panel-title"')

    def test_each_card_is_one_link_that_starts_its_tour(self):
        """Each card is one link that starts its tour."""
        content = self.panel(self.LEADS).content.decode()
        self.assertIn('data-tour-start="leads_list"', content)
        # The card itself is the link: no separate Start button.
        self.assertNotIn("htp-btn", content)
        before_marker = content[: content.index('data-tour-card="leads_list"')]
        self.assertTrue(before_marker.rstrip().rsplit("<", 1)[-1].startswith("a"))
        self.assertIn("tour=leads_list", content)

    def test_only_the_inner_card_lifts_so_the_hover_area_is_stable(self):
        """Only the inner card lifts so the hover area is stable."""
        content = self.panel(self.LEADS).content.decode()
        self.assertIn("data-tour-card", content)
        # Hover effects are group-hover on the inner card, never on the link itself.
        self.assertNotIn(" hover:-translate-y-1", content)

    def test_cards_have_the_app_hover_effect(self):
        """Cards have the app hover effect."""
        content = self.panel(self.LEADS).content.decode()
        for cls in (
            "group-hover:border-primary-600",
            "group-hover:-translate-y-1",
            "group-hover:shadow-lg",
        ):
            self.assertIn(cls, content)

    def test_launcher_is_rendered_on_authenticated_pages(self):
        """Launcher is rendered on authenticated pages."""
        response = self.client.get("/dashboard/", {"section": "home"})
        self.assertContains(response, 'id="horilla-tour-launcher"')
        self.assertContains(response, 'id="horilla-tour-panel"')
        # The button loads the list with htmx into the panel's content box, with a spinner.
        self.assertContains(response, 'hx-get="/tour/"')
        self.assertContains(response, 'hx-target="#tour-panel-content"')
        self.assertContains(response, 'id="tour-panel-content"')
        self.assertContains(response, 'id="tour-panel-loading"')
        # The app's own themed spinner, not the white icon made for the red buttons.
        self.assertNotContains(response, "assets/icons/spinner.svg")
        self.assertNotContains(response, "data-loading=")
        self.assertContains(response, "tour/assets/js/tour.js")

    def test_launcher_is_not_rendered_for_anonymous_visitors(self):
        """Launcher is not rendered for anonymous visitors."""
        self.client.logout()
        response = self.client.get("/login/")
        self.assertNotContains(response, "horilla-tour-launcher")

    def test_no_sidebar_entry(self):
        """No sidebar entry."""
        response = self.client.get("/dashboard/", {"section": "home"})
        self.assertNotContains(response, 'id="tour"')


class CurrentViewTests(TourViewTestCase):
    """``current/`` resolves the page and says which tour (if any) starts by itself."""

    def current(self, path):
        """Current."""
        return self.client.get(reverse("tour:current"), {"path": path}, **AJAX)

    def test_resolves_list_and_detail_pages(self):
        """Resolves list and detail pages."""
        self.assertEqual(
            self.current("/crm/leads/leads-view/").json()["view_name"],
            "leads:leads_view",
        )
        self.assertEqual(
            self.current("/crm/leads/leads-detail/12/").json()["view_name"],
            "leads:leads_detail",
        )

    def test_home_starts_the_shell_tour_then_the_home_tour(self):
        """Home starts the shell tour then the home tour."""
        data = self.current("/dashboard/").json()
        self.assertEqual(data["view_name"], "dashboard:home_view")
        self.assertEqual(data["auto"], ["app_shell", "dashboard_home"])
        self.assertIn("labels", data)

    def test_tours_do_not_start_again_once_shown(self):
        """Tours do not start again once shown."""
        TourSeen.objects.create(user=self.admin, tour_key="app_shell")
        self.assertEqual(self.current("/dashboard/").json()["auto"], ["dashboard_home"])
        TourSeen.objects.create(user=self.admin, tour_key="dashboard_home")
        self.assertEqual(self.current("/dashboard/").json()["auto"], [])

    def test_seen_is_per_user(self):
        """Seen is per user."""
        TourSeen.objects.create(user=self.plain, tour_key="app_shell")
        self.assertEqual(
            self.current("/dashboard/").json()["auto"], ["app_shell", "dashboard_home"]
        )

    def test_every_user_gets_the_home_tours_on_their_first_login(self):
        """Every user gets the home tours on their first login."""
        self.client.login(username="plain", password="pass")
        self.assertEqual(
            self.current("/dashboard/").json()["auto"], ["app_shell", "dashboard_home"]
        )

    def test_each_page_tour_starts_by_itself_on_the_first_visit(self):
        """Each page tour starts by itself on the first visit."""
        self.assertEqual(
            self.current("/crm/leads/leads-view/").json()["auto"], ["leads_list"]
        )
        self.assertEqual(
            self.current("/crm/leads/leads-detail/1/").json()["auto"], ["leads_detail"]
        )
        TourSeen.objects.create(user=self.admin, tour_key="leads_list")
        self.assertEqual(self.current("/crm/leads/leads-view/").json()["auto"], [])
        # Seeing one page's tour does not use up another page's.
        self.assertEqual(
            self.current("/crm/leads/leads-detail/1/").json()["auto"], ["leads_detail"]
        )

    def test_users_without_lead_access_are_not_offered_the_leads_tours(self):
        """Users without lead access are not offered the leads tours."""
        self.client.login(username="plain", password="pass")
        self.assertEqual(self.current("/crm/leads/leads-view/").json()["auto"], [])
        self.assertEqual(self.current("/crm/leads/leads-detail/1/").json()["auto"], [])

    def test_unknown_path_has_no_view_name(self):
        """Unknown path has no view name."""
        data = self.current("/no/such/page/").json()
        self.assertIsNone(data["view_name"])
        self.assertEqual(data["auto"], [])


class DefinitionTests(TourViewTestCase):
    """``definition/<key>/`` returns the steps and the UI labels."""

    def test_returns_steps_and_labels(self):
        """Returns steps and labels."""
        response = self.client.get(
            reverse("tour:definition", args=["leads_list"]), **AJAX
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["key"], "leads_list")
        self.assertGreater(len(data["steps"]), 5)
        self.assertIn("finish", data["labels"])
        self.assertTrue(data["start_url"].endswith("tour=leads_list"))

    def test_carries_no_progress(self):
        """Carries no progress."""
        data = self.client.get(
            reverse("tour:definition", args=["leads_list"]), **AJAX
        ).json()
        for key in ("status", "last_step", "next_tour"):
            self.assertNotIn(key, data)

    def test_unknown_tour_is_404(self):
        """Unknown tour is 404."""
        response = self.client.get(reverse("tour:definition", args=["nope"]), **AJAX)
        self.assertEqual(response.status_code, 404)

    def test_forbidden_tour_is_404(self):
        """Forbidden tour is 404."""
        self.client.login(username="plain", password="pass")
        response = self.client.get(
            reverse("tour:definition", args=["leads_list"]), **AJAX
        )
        self.assertEqual(response.status_code, 404)


class SeenTests(TourViewTestCase):
    """``seen/`` remembers that a tour already started by itself."""

    def test_records_the_tour_once(self):
        """Records the tour once."""
        self.assertEqual(self.post_json("seen", {"key": "app_shell"}).status_code, 200)
        self.assertEqual(self.post_json("seen", {"key": "app_shell"}).status_code, 200)
        self.assertEqual(
            TourSeen.objects.filter(user=self.admin, tour_key="app_shell").count(), 1
        )

    def test_is_per_user(self):
        """Is per user."""
        self.post_json("seen", {"key": "app_shell"})
        self.assertFalse(TourSeen.objects.filter(user=self.plain).exists())

    def test_makes_the_tour_stop_starting_by_itself(self):
        """Makes the tour stop starting by itself."""

        def auto():
            """Auto."""
            return self.client.get(
                reverse("tour:current"), {"path": "/dashboard/"}, **AJAX
            ).json()["auto"]

        self.post_json("seen", {"key": "app_shell"})
        self.assertEqual(auto(), ["dashboard_home"])
        self.post_json("seen", {"key": "dashboard_home"})
        self.assertEqual(auto(), [])

    def test_rejects_invalid_payloads(self):
        """Rejects invalid payloads."""
        self.assertEqual(self.post_json("seen", {}).status_code, 400)
        response = self.client.post(
            reverse("tour:seen"),
            data="{not json",
            content_type="application/json",
            **AJAX,
        )
        self.assertEqual(response.status_code, 400)

    def test_rejects_unknown_or_forbidden_tour(self):
        """Rejects unknown or forbidden tour."""
        self.assertEqual(self.post_json("seen", {"key": "nope"}).status_code, 404)
        self.assertEqual(self.post_json("seen", {"key": 5}).status_code, 404)
        self.client.login(username="plain", password="pass")
        self.assertEqual(self.post_json("seen", {"key": "leads_list"}).status_code, 404)
        self.assertFalse(TourSeen.objects.exists())

    def test_old_endpoints_are_gone(self):
        """Old endpoints are gone."""
        for name in ("progress", "reset", "preference"):
            with self.assertRaises(Exception):
                reverse(f"tour:{name}")
