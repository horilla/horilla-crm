"""Failed sign-in limits, trusted client addresses, and the signing key."""

import base64
import warnings
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from login_history.models import post_login, post_logout
from rest_framework.test import APIClient

from horilla.auth.models import User
from horilla.contrib.core.auth_limits import client_ip
from horilla.settings.secret_key import PLACEHOLDER_SECRET_KEYS, resolve_secret_key


class SecretKeyTests(SimpleTestCase):
    """Shipped placeholders must not become the signing key."""

    def test_operator_key_is_kept(self):
        key = "k" * 64
        self.assertEqual(
            resolve_secret_key(key, Path("this-file-is-not-created")),
            key,
        )

    def test_placeholder_is_replaced_and_reused(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "secret"
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                first = resolve_secret_key("django-insecure-default-key", path)
                second = resolve_secret_key("dev-secret-key-change-in-production", path)
            self.assertNotIn(first, PLACEHOLDER_SECRET_KEYS)
            self.assertTrue(any("placeholder" in str(item.message) for item in caught))
            self.assertEqual(path.read_text(encoding="utf-8"), first)
            self.assertEqual(second, first)

    def test_running_settings_do_not_use_a_shipped_key(self):
        self.assertNotIn(settings.SECRET_KEY, PLACEHOLDER_SECRET_KEYS)
        self.assertEqual(settings.SIMPLE_JWT["SIGNING_KEY"], settings.SECRET_KEY)
        classes = settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]
        self.assertFalse(any("BasicAuthentication" in name for name in classes))


class ClientAddressTests(SimpleTestCase):
    """Forwarded headers count only from a trusted peer."""

    def address(self, remote, forwarded="", real=""):
        extra = {"REMOTE_ADDR": remote}
        if forwarded:
            extra["HTTP_X_FORWARDED_FOR"] = forwarded
        if real:
            extra["HTTP_X_REAL_IP"] = real
        return client_ip(RequestFactory().get("/", **extra))

    def test_untrusted_peer_ignores_forwarded_headers(self):
        self.assertEqual(
            self.address("203.0.113.10", forwarded="198.51.100.4", real="198.51.100.8"),
            "203.0.113.10",
        )

    @override_settings(TRUSTED_PROXIES=["10.0.0.8"])
    def test_trusted_proxy_uses_x_real_ip(self):
        self.assertEqual(
            self.address(
                "10.0.0.8",
                forwarded="198.51.100.1, 198.51.100.9",
                real="198.51.100.9",
            ),
            "198.51.100.9",
        )

    @override_settings(TRUSTED_PROXIES=["10.0.0.8"])
    def test_trusted_proxy_without_real_ip_uses_the_rightmost_hop(self):
        self.assertEqual(
            self.address("10.0.0.8", forwarded="198.51.100.1, 198.51.100.9"),
            "198.51.100.9",
        )


@override_settings(TRUSTED_PROXIES=[])
class LoginLockoutTests(TestCase):
    """The page login, admin login, and token login share one counter."""

    password = "correct-horse-battery"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # django-login-history reads request.META['HTTP_USER_AGENT'] on
        # login/logout, which a bare test request does not set.
        user_logged_in.disconnect(post_login)
        user_logged_out.disconnect(post_logout)

    @classmethod
    def tearDownClass(cls):
        user_logged_in.connect(post_login)
        user_logged_out.connect(post_logout)
        super().tearDownClass()

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="ada",
            email="ada@example.com",
            password=self.password,
        )
        self.staff = User.objects.create_user(
            username="root",
            email="root@example.com",
            password=self.password,
            is_staff=True,
            is_superuser=True,
        )

    def fail_login(self, username="ada", remote="203.0.113.10", forwarded=""):
        extra = {"REMOTE_ADDR": remote}
        if forwarded:
            extra["HTTP_X_FORWARDED_FOR"] = forwarded
        return self.client.post(
            "/login/",
            {"username": username, "password": "wrong"},
            **extra,
        )

    def test_changing_forwarded_for_still_locks_the_login(self):
        for hop in range(5):
            self.fail_login(forwarded=f"198.51.100.{hop}")
        response = self.client.post(
            "/login/",
            {"username": "ada", "password": self.password},
            REMOTE_ADDR="203.0.113.10",
            HTTP_X_FORWARDED_FOR="198.51.100.99",
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)
        page = self.client.get(response["Location"])
        self.assertContains(page, "Too many failed login attempts")

    @override_settings(TRUSTED_PROXIES=["10.0.0.8"])
    def test_trusted_proxy_locks_only_the_real_client(self):
        for _hop in range(5):
            self.client.post(
                "/login/",
                {"username": "ada", "password": "wrong"},
                REMOTE_ADDR="10.0.0.8",
                HTTP_X_REAL_IP="198.51.100.20",
                HTTP_X_FORWARDED_FOR="198.51.100.1",
            )
        other = self.client.post(
            "/login/",
            {"username": "ada", "password": self.password},
            REMOTE_ADDR="10.0.0.8",
            HTTP_X_REAL_IP="198.51.100.21",
        )
        self.assertEqual(other["Location"], "/")
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_successful_login_clears_the_counter(self):
        for _hop in range(4):
            self.fail_login()
        response = self.client.post(
            "/login/",
            {"username": "ada", "password": self.password},
            REMOTE_ADDR="203.0.113.10",
        )
        self.assertEqual(response["Location"], "/")
        self.client.logout()
        for _hop in range(3):
            self.fail_login()
        page = self.client.get(self.fail_login()["Location"])
        self.assertContains(page, "Invalid credentials")
        self.assertNotContains(page, "Too many failed login attempts")

    @override_settings(LOGIN_ACCOUNT_LIMIT=3)
    def test_account_limit_follows_the_username_across_addresses(self):
        for hop in range(3):
            self.fail_login(remote=f"203.0.113.{hop}")
        response = self.client.post(
            "/login/",
            {"username": "ada", "password": self.password},
            REMOTE_ADDR="198.51.100.50",
        )
        self.assertNotIn("_auth_user_id", self.client.session)
        page = self.client.get(response["Location"])
        self.assertContains(page, "Too many failed login attempts")

    def test_mobile_login_reuses_the_page_login(self):
        """The phone sign-in page does not replace the shared lockout."""
        from horilla.contrib.core.views.core import LoginUserView
        from horilla.contrib.mobile.views import MobileLoginView

        self.assertIs(MobileLoginView.post, LoginUserView.post)

    def test_admin_login_locks(self):
        for _hop in range(4):
            self.client.post(
                "/admin/login/",
                {"username": "root", "password": "wrong"},
                REMOTE_ADDR="203.0.113.20",
            )
        response = self.client.post(
            "/admin/login/",
            {"username": "root", "password": "wrong"},
            REMOTE_ADDR="203.0.113.20",
        )
        self.assertContains(response, "Too many failed login attempts")
        response = self.client.post(
            "/admin/login/",
            {"username": "root", "password": self.password},
            REMOTE_ADDR="203.0.113.20",
        )
        self.assertContains(response, "Too many failed login attempts")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unavailable_store_refuses_the_password_check(self):
        with mock.patch(
            "horilla.contrib.core.auth_limits.cache.get",
            side_effect=ConnectionError("redis down"),
        ):
            with mock.patch(
                "horilla.contrib.core.views.core.authenticate"
            ) as authenticate:
                with self.assertLogs("horilla.contrib.core.auth_limits", level="ERROR"):
                    response = self.fail_login()
        authenticate.assert_not_called()
        page = self.client.get(response["Location"])
        self.assertContains(page, "Sign-in is temporarily unavailable")

    def test_token_login_locks_and_basic_auth_does_not_check_a_password(self):
        client = APIClient()
        for hop in range(4):
            failed = client.post(
                "/api/core/token/",
                {"username": "ada", "password": "wrong"},
                format="json",
                REMOTE_ADDR="203.0.113.30",
                HTTP_X_FORWARDED_FOR=f"198.51.100.{hop}",
            )
            self.assertEqual(failed.status_code, 401)
        locked = client.post(
            "/api/core/token/",
            {"username": "ada", "password": "wrong"},
            format="json",
            REMOTE_ADDR="203.0.113.30",
            HTTP_X_FORWARDED_FOR="198.51.100.77",
        )
        self.assertEqual(locked.status_code, 429)
        still_locked = client.post(
            "/api/core/token/",
            {"username": "ada", "password": self.password},
            format="json",
            REMOTE_ADDR="203.0.113.30",
            HTTP_X_FORWARDED_FOR="198.51.100.78",
        )
        self.assertEqual(still_locked.status_code, 429)

        cache.clear()
        issued = client.post(
            "/api/core/token/",
            {"username": "ada", "password": self.password},
            format="json",
            REMOTE_ADDR="203.0.113.31",
        )
        self.assertEqual(issued.status_code, 200)
        self.assertIn("access", issued.data)

        raw = base64.b64encode(b"ada:" + self.password.encode()).decode()
        basic = client.get(
            "/api/core/users/",
            HTTP_AUTHORIZATION=f"Basic {raw}",
            REMOTE_ADDR="203.0.113.32",
        )
        self.assertEqual(basic.status_code, 401)

        client.credentials(HTTP_AUTHORIZATION=f"Bearer {issued.data['access']}")
        authed = client.get("/api/core/users/", REMOTE_ADDR="203.0.113.32")
        self.assertNotEqual(authed.status_code, 401)
