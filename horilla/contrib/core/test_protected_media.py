"""Uploads are served only after a session or a JWT."""

from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.test import TestCase
from login_history.models import post_login, post_logout
from rest_framework_simplejwt.tokens import AccessToken

from horilla import settings as horilla_settings
from horilla.auth.models import User


class ProtectedMediaTests(TestCase):
    """Anonymous requests never receive the file bytes."""

    marker = b"private-marker"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # django-login-history reads request.META['HTTP_USER_AGENT'] on login.
        user_logged_in.disconnect(post_login)
        user_logged_out.disconnect(post_logout)

    @classmethod
    def tearDownClass(cls):
        user_logged_in.connect(post_login)
        user_logged_out.connect(post_logout)
        super().tearDownClass()

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # The view reads horilla.settings, which override_settings does not wrap.
        self.addCleanup(
            setattr, horilla_settings, "MEDIA_ROOT", horilla_settings.MEDIA_ROOT
        )
        horilla_settings.MEDIA_ROOT = self.tmp.name

        folder = Path(self.tmp.name) / "notes"
        folder.mkdir()
        (folder / "file.txt").write_bytes(self.marker)
        (folder / "secret.py").write_bytes(self.marker)

        self.user = User.objects.create_user(
            username="reader",
            email="reader@example.com",
            password="reader-pass-123",
        )

    def test_anonymous_request_for_a_real_file_redirects(self):
        response = self.client.get("/media/notes/file.txt")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])
        self.assertNotIn(self.marker, response.content)

    def test_anonymous_request_for_a_missing_file_redirects(self):
        response = self.client.get("/media/notes/missing.txt")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_signed_in_user_receives_the_file(self):
        self.client.force_login(self.user)
        response = self.client.get("/media/notes/file.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), self.marker)
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Cache-Control"], "private")

    def test_signed_in_user_gets_404_for_a_missing_file(self):
        self.client.force_login(self.user)
        response = self.client.get("/media/notes/missing.txt")
        self.assertEqual(response.status_code, 404)

    def test_bearer_token_receives_the_file(self):
        token = AccessToken.for_user(self.user)
        response = self.client.get(
            "/media/notes/file.txt",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), self.marker)

    def test_signed_in_user_cannot_read_a_blocked_extension(self):
        self.client.force_login(self.user)
        response = self.client.get("/media/notes/secret.py")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(self.marker, response.content)
