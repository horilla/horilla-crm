"""
Tests for the core app.
"""

# Standard library imports
import socket
import threading
from io import StringIO
from types import SimpleNamespace
from unittest import mock

# Third-party imports
import environ

# Third-party imports (Django)
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

# First-party / Horilla imports
from horilla.contrib.core.management.commands import wait_for_db


class WaitTargetTests(SimpleTestCase):
    """get_wait_target resolves the host/port Django itself connects to."""

    def test_database_url_host_and_port(self):
        """A DATABASE_URL pointing at a non-"db" host is used as-is."""
        config = environ.Env.db_url_config("postgres://dbhost:55432/crm")
        self.assertEqual(wait_for_db.get_wait_target(config), ("dbhost", 55432))

    def test_database_url_without_port_uses_engine_default(self):
        """A DATABASE_URL with no port falls back to the driver's default."""
        config = environ.Env.db_url_config("postgres://dbhost/crm")
        self.assertEqual(wait_for_db.get_wait_target(config), ("dbhost", 5432))

    def test_mysql_url_without_port_uses_mysql_default(self):
        """The default port follows the engine, not a hard-coded 5432."""
        config = environ.Env.db_url_config("mysql://dbhost/crm")
        self.assertEqual(wait_for_db.get_wait_target(config), ("dbhost", 3306))

    def test_db_host_and_db_port_settings(self):
        """The DB_HOST/DB_PORT settings (string port) are honoured."""
        config = {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": "postgres.internal",
            "PORT": "6543",
        }
        self.assertEqual(
            wait_for_db.get_wait_target(config), ("postgres.internal", 6543)
        )

    def test_sqlite_has_nothing_to_wait_for(self):
        """The default SQLite setup has no server, so there is no target."""
        config = {"ENGINE": "django.db.backends.sqlite3", "HOST": "", "PORT": ""}
        self.assertIsNone(wait_for_db.get_wait_target(config))

    def test_unix_socket_host_has_nothing_to_wait_for(self):
        """A socket directory is not a TCP host."""
        config = {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": "/var/run/postgresql",
            "PORT": "",
        }
        self.assertIsNone(wait_for_db.get_wait_target(config))


class WaitForDbCommandTests(SimpleTestCase):
    """The wait_for_db management command run by docker/entrypoint.sh."""

    def run_command(self, databases, *args):
        """Run wait_for_db against the given DATABASES and return its output."""
        out = StringIO()
        fake_settings = SimpleNamespace(DATABASES=databases)
        with mock.patch.object(wait_for_db, "settings", fake_settings):
            call_command("wait_for_db", *args, stdout=out)
        return out.getvalue()

    def start_listener(self):
        """Accept TCP connections on a free local port; return that port."""
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen()
        server.settimeout(0.1)
        stop = threading.Event()

        def accept_loop():
            while not stop.is_set():
                try:
                    conn, _ = server.accept()
                except OSError:
                    continue
                conn.close()

        thread = threading.Thread(target=accept_loop, daemon=True)
        thread.start()

        def cleanup():
            stop.set()
            thread.join()
            server.close()

        self.addCleanup(cleanup)
        return server.getsockname()[1]

    def free_port(self):
        """Return a local port with nothing listening on it."""
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]

    def test_waits_on_configured_host_and_port(self):
        """The command connects to the configured server, not to db:5432."""
        port = self.start_listener()
        config = environ.Env.db_url_config(f"postgres://127.0.0.1:{port}/crm")

        output = self.run_command({"default": config}, "--attempts", "3")

        self.assertIn(f"Database is ready at 127.0.0.1:{port}", output)

    def test_fails_after_attempts_when_database_is_down(self):
        """An unreachable database fails the start-up after --attempts tries."""
        port = self.free_port()
        config = {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": "127.0.0.1",
            "PORT": str(port),
        }

        with mock.patch.object(wait_for_db.time, "sleep") as sleep:
            with self.assertRaisesMessage(
                CommandError, f"127.0.0.1:{port} not available after 3 attempts"
            ):
                self.run_command(
                    {"default": config}, "--attempts", "3", "--interval", "0"
                )
        self.assertEqual(sleep.call_count, 2)

    def test_skips_wait_for_sqlite(self):
        """With the default SQLite database the command returns immediately."""
        config = {"ENGINE": "django.db.backends.sqlite3", "HOST": "", "PORT": ""}

        with mock.patch.object(wait_for_db.socket, "create_connection") as connect:
            output = self.run_command({"default": config})

        connect.assert_not_called()
        self.assertIn("skipping the wait", output)

    def test_unknown_database_alias(self):
        """Asking for an alias that is not configured is an error."""
        with self.assertRaisesMessage(CommandError, "Unknown database alias: other"):
            self.run_command({"default": {}}, "--database", "other")


class LoginLogoutPageDefaultsTests(TestCase):
    """
    The desktop login and logout keep their own page and URLs. Subclasses can
    point ``template_name`` / ``login_url_name`` / ``redirect_url`` elsewhere.
    """

    def setUp(self):
        cache.clear()

    def test_login_page_uses_the_desktop_template(self):
        """GET /login/ still renders login.html."""
        response = self.client.get("/login/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "login.html")

    def test_failed_login_returns_to_the_desktop_login(self):
        """A wrong password still sends the user back to /login/."""
        response = self.client.post(
            "/login/", {"username": "nobody", "password": "wrong"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/login/?next=/")

    def test_logout_returns_to_the_desktop_login(self):
        """Logging out still refreshes to /login."""
        response = self.client.get("/logout/")
        self.assertContains(response, 'content="0;url=/login"')
