"""
Tests for the mobile shell: login and logout, layout pages, manifest and
service worker.

The mobile app is off by default, so these tests run only when
``horilla.contrib.mobile`` is in ``INSTALLED_APPS``.
"""

# Standard library imports
import json
from unittest import mock, skipUnless

# Third-party imports (Django)
from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.contrib.staticfiles.storage import StaticFilesStorage
from django.core.cache import cache
from django.template import Context, Template
from django.templatetags.static import static
from django.test import TestCase, override_settings
from django.utils.html import escape
from django.utils.http import urlencode
from login_history.models import post_login, post_logout

# First party imports (Horilla)
from horilla.apps import apps
from horilla.auth.models import User
from horilla.contrib.core.models import Company

MOBILE_INSTALLED = apps.is_installed("horilla.contrib.mobile")


class QueryStaticStorage(StaticFilesStorage):
    """Static storage whose ``url()`` already carries a query string."""

    def url(self, name):
        base = super().url(name)
        separator = "&" if "?" in base else "?"
        return f"{base}{separator}v=storage"


if MOBILE_INSTALLED:
    from horilla.contrib.mobile import utils as mobile_utils
    from horilla.contrib.mobile.templatetags.mobile_tags import mobile_static
    from horilla.contrib.mobile.utils import CACHE_PREFIX, get_asset_version

    def expected_mobile_static(path):
        """The URL ``mobile_static`` should build for the active static storage."""
        url = static(path)
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}{urlencode({'v': get_asset_version()})}"


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
class MobileShellTestBase(TestCase):
    """A signed-out client and a user who can sign in."""

    password = "mobile-pass-123"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # django-login-history reads request.META['HTTP_USER_AGENT'] on
        # login/logout, which the test client's bare request doesn't set.
        user_logged_in.disconnect(post_login)
        user_logged_out.disconnect(post_logout)

    @classmethod
    def tearDownClass(cls):
        user_logged_in.connect(post_login)
        user_logged_out.connect(post_logout)
        super().tearDownClass()

    def setUp(self):
        cache.clear()
        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        self.user = User.objects.create_user(
            username="salesperson",
            email="salesperson@example.com",
            password=self.password,
            company=self.company,
        )


class MobileLoginTests(MobileShellTestBase):
    """The phone login reuses the desktop login logic on its own page."""

    def test_pages_send_signed_out_users_to_the_mobile_login(self):
        response = self.client.get("/m/more/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/m/login/?next="))

    def test_login_page_uses_the_mobile_template(self):
        response = self.client.get("/m/login/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "mobile/login.html")
        self.assertTemplateNotUsed(response, "login.html")
        self.assertContains(response, 'name="next" value="/m/"')

    def test_login_page_can_show_the_password(self):
        response = self.client.get("/m/login/")
        self.assertContains(response, 'id="mobile-password-toggle"')
        self.assertContains(response, 'aria-controls="mobile-password"')

    def test_login_page_sets_its_own_required_message(self):
        # The browser's built-in message follows the browser language.
        response = self.client.get("/m/login/")
        self.assertContains(
            response, 'const requiredMessage = "This field is required.";'
        )

    def test_wrong_password_returns_to_the_mobile_login(self):
        response = self.client.post(
            "/m/login/",
            {"username": "salesperson", "password": "wrong", "next": "/m/"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/m/login/?next="))

    def test_valid_login_opens_the_mobile_home(self):
        response = self.client.post(
            "/m/login/",
            {"username": "salesperson", "password": self.password},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/m/")
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_signed_in_user_skips_the_login_form(self):
        self.client.force_login(self.user)
        response = self.client.get("/m/login/")
        self.assertRedirects(response, "/m/", fetch_redirect_response=False)

    def test_logout_returns_to_the_mobile_login(self):
        self.client.force_login(self.user)
        response = self.client.get("/m/logout/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'content="0;url=/m/login/"')
        self.assertNotIn("_auth_user_id", self.client.session)


class MobileLayoutTests(MobileShellTestBase):
    """Pages in the phone layout."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_home_opens_the_first_page(self):
        response = self.client.get("/m/")
        self.assertRedirects(response, "/m/today/", fetch_redirect_response=False)

    def test_more_page_links_full_version_language_and_logout(self):
        response = self.client.get("/m/more/", follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "mobile/more.html")
        self.assertContains(response, 'href="/m/logout/"')
        self.assertContains(response, 'name="language"')
        self.assertContains(response, 'rel="manifest" href="/m/manifest.webmanifest"')

    def test_layout_registers_the_worker_for_the_mobile_scope_only(self):
        response = self.client.get("/m/more/", follow=True)
        self.assertContains(response, '.register("/m/sw.js", {scope: "/m/"})')

    def test_layout_static_files_carry_the_asset_version(self):
        response = self.client.get("/m/more/", follow=True)
        # The template escapes & to &amp; when the storage URL already has a query.
        expected = expected_mobile_static("assets/js/htmx/htmx.min.js").replace(
            "&", "&amp;"
        )
        self.assertContains(response, expected)


class MobileManifestTests(MobileShellTestBase):
    """The web app manifest behind "Add to Home Screen"."""

    def test_manifest_is_public_and_scoped_to_mobile(self):
        response = self.client.get("/m/manifest.webmanifest")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response["Content-Type"].startswith("application/manifest+json")
        )
        manifest = json.loads(response.content)
        self.assertEqual(manifest["start_url"], "/m/")
        self.assertEqual(manifest["scope"], "/m/")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(
            sorted(icon["sizes"] for icon in manifest["icons"]),
            ["192x192", "512x512"],
        )

    def test_manifest_follows_the_language_direction(self):
        response = self.client.get("/m/manifest.webmanifest", HTTP_ACCEPT_LANGUAGE="fa")
        manifest = json.loads(response.content)
        if manifest["lang"].startswith("fa"):
            self.assertEqual(manifest["dir"], "rtl")


class MobileServiceWorkerTests(MobileShellTestBase):
    """The worker only ever serves versioned static files from its cache."""

    def get_worker(self, **extra):
        response = self.client.get("/m/sw.js", **extra)
        self.assertEqual(response.status_code, 200)
        return response

    def test_worker_is_served_as_uncached_javascript(self):
        response = self.get_worker()
        self.assertTrue(response["Content-Type"].startswith("application/javascript"))
        self.assertEqual(response["Cache-Control"], "no-cache")
        # Its scope must stay /m/: no header that widens it.
        self.assertFalse(response.has_header("Service-Worker-Allowed"))

    def test_worker_is_not_redirected_for_signed_in_users(self):
        # Browsers refuse a worker script behind a redirect.
        self.client.force_login(self.user)
        response = self.client.get("/m/sw.js")
        self.assertEqual(response.status_code, 200)

    def test_worker_names_its_cache_after_the_asset_version(self):
        body = self.get_worker().content.decode()
        version = get_asset_version()
        self.assertIn(f"const ASSET_VERSION = {json.dumps(version)};", body)
        self.assertIn(f"const CACHE_NAME = {json.dumps(CACHE_PREFIX + version)};", body)
        self.assertIn('const STATIC_BASE = new URL("/static/"', body)

    @override_settings(DEBUG=False)
    def test_worker_caches_when_debug_is_off(self):
        self.assertIn("const CACHE_ENABLED = true;", self.get_worker().content.decode())

    @override_settings(DEBUG=True)
    def test_worker_does_not_cache_while_debugging(self):
        self.assertIn(
            "const CACHE_ENABLED = false;", self.get_worker().content.decode()
        )


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
class MobileStaticTagTests(TestCase):
    """``mobile_static`` adds the version the worker caches by."""

    def render(self, path):
        return Template("{% load mobile_tags %}{% mobile_static path %}").render(
            Context({"path": path})
        )

    def test_adds_the_asset_version(self):
        path = "assets/css/style.css"
        # The template escapes the URL, which shows when the active static
        # storage's URL already carries a query ("&" becomes "&amp;").
        self.assertEqual(self.render(path), escape(expected_mobile_static(path)))

    def test_uses_ampersand_when_the_static_url_already_has_a_query(self):
        storages = {
            alias: dict(config) for alias, config in settings.STORAGES.items()
        }
        storages["staticfiles"] = {
            "BACKEND": "horilla.contrib.mobile.tests.test_shell.QueryStaticStorage",
        }
        path = "assets/css/style.css"
        with override_settings(STORAGES=storages):
            expected = expected_mobile_static(path)
            self.assertIn("&v=", expected)
            self.assertEqual(mobile_static(path), expected)
            self.assertEqual(self.render(path), expected.replace("&", "&amp;"))

    def test_the_stamp_changes_with_the_apps_own_static_files(self):
        # A changed mobile.css must not be served from a phone's old cache.
        before = get_asset_version()
        mobile_utils._own_static_digest.cache_clear()
        self.addCleanup(mobile_utils._own_static_digest.cache_clear)
        with mock.patch.object(mobile_utils.Path, "read_bytes", return_value=b"edited"):
            after = get_asset_version()
        self.assertNotEqual(before, after)
        self.assertTrue(after.startswith(before.rsplit("-", 1)[0]))
