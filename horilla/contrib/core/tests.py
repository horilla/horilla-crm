"""
Tests for the core app.
"""

# Standard library imports
import ast
import socket
import threading
from datetime import datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

# Third-party imports
import environ

# Third-party imports (Django)
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import QueryDict
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext_lazy as _

# First-party / Horilla imports
from horilla.auth.models import User
from horilla.contrib.core.api.serializers import HolidaySerializer
from horilla.contrib.core.apps import CoreConfig
from horilla.contrib.core.forms.base import HolidayForm
from horilla.contrib.core.forms.company import (
    CompanyFormClassSingle,
    CompanyMultistepFormClass,
)
from horilla.contrib.core.forms.shift_hour import ShiftHourForm
from horilla.contrib.core.forms.users import UserFormClass, UserFormSingle
from horilla.contrib.core.management.commands import wait_for_db
from horilla.contrib.core.models import BusinessHour, Company, Holiday
from horilla.contrib.core.views.holiday import HolidayDetailView, HolidayNavbar
from horilla.contrib.core.views.import_data.base import ImportDataView
from horilla.contrib.core.views.user_holidays import UserHolidayDetailView
from horilla.contrib.utils.middlewares import _thread_local, get_active_company
from horilla.menu.header_menu import get_header_menu, header_registry, register
from horilla.registry.feature import FEATURE_REGISTRY


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


class StateLabelTests(TestCase):
    """The company and user forms swap state for a subdivision select; it keeps
    the model's "State/Province" label instead of Django's "State" fallback."""

    def setUp(self):
        company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
            company=company,
        )
        self.request = RequestFactory().get("/")
        self.request.user = user
        _thread_local.request = self.request
        self.addCleanup(delattr, _thread_local, "request")

    def test_state_label_comes_from_the_model(self):
        """The label is the model's verbose_name and follows the active language."""
        for form_class in (
            CompanyMultistepFormClass,
            CompanyFormClassSingle,
            UserFormClass,
            UserFormSingle,
        ):
            with self.subTest(form=form_class.__name__):
                verbose_name = form_class._meta.model._meta.get_field(
                    "state"
                ).verbose_name
                label = form_class(request=self.request).fields["state"].label
                self.assertEqual(label, verbose_name)
                self.assertEqual(str(label), "State/Province")
                with translation.override("fa"):
                    self.assertEqual(str(label), "استان")


class _HeaderUser:
    """User stand-in for header-menu permission checks."""

    is_superuser = False

    def __init__(self, perms=(), authenticated=True):
        self._perms = set(perms)
        self.is_authenticated = authenticated

    def has_any_perms(self, perm_list, obj=None):
        """Return True when the user holds any listed permission."""
        return any(perm in self._perms for perm in perm_list)


class HeaderMenuTests(SimpleTestCase):
    """Account dropdown rows: order, permissions, and anchor attributes."""

    def setUp(self):
        """Keep the real registry and drop classes this test adds."""
        self._snapshot = list(header_registry)

    def tearDown(self):
        """Restore the registry."""
        header_registry[:] = self._snapshot

    def test_builtin_rows_keep_logout_last(self):
        """My Settings comes first and Logout last, whatever other apps add between."""
        labels = [str(row["title"]) for row in get_header_menu()]
        self.assertEqual(labels[0], str(_("My Settings")))
        self.assertEqual(labels[-1], str(_("Logout")))

    def test_perm_condition_and_attrs(self):
        """A missing permission or a false condition drops the row. attrs stay on the link."""

        @register
        class HiddenLink:
            title = _("Hidden")
            url = "/hidden/"
            order = 30
            perm = "demo.view_hidden"

        @register
        class OffLink:
            title = _("Off")
            url = "/off/"
            order = 31
            condition = staticmethod(lambda request: False)

        @register
        class HelpLink:
            title = _("Help")
            url = "/help/"
            order = 32
            attrs = {
                "id": "help-link",
                "hx-target": "#mainContent",
                "hx-push-url": "true",
            }

        @register
        class PanelLink:
            title = _("Panel")
            order = 33
            attrs = {"hx-get": "/panel/"}

        request = SimpleNamespace(user=_HeaderUser())
        labels = [str(row["title"]) for row in get_header_menu(request)]
        self.assertNotIn(str(_("Hidden")), labels)
        self.assertNotIn(str(_("Off")), labels)
        self.assertLess(labels.index(str(_("Help"))), labels.index(str(_("Logout"))))

        help_row = next(
            row
            for row in get_header_menu(request)
            if str(row["title"]) == str(_("Help"))
        )
        self.assertEqual(
            help_row["attrs"],
            {"id": "help-link", "hx-target": "#mainContent", "hx-push-url": "true"},
        )
        panel = next(
            row
            for row in get_header_menu(request)
            if str(row["title"]) == str(_("Panel"))
        )
        self.assertEqual(panel["url"], "")
        self.assertEqual(panel["attrs"], {"hx-get": "/panel/"})

        allowed = SimpleNamespace(user=_HeaderUser(["demo.view_hidden"]))
        allowed_labels = [str(row["title"]) for row in get_header_menu(allowed)]
        self.assertIn(str(_("Hidden")), allowed_labels)


class GetActiveCompanyTests(SimpleTestCase):
    """get_active_company is the single reader of the active company."""

    def setUp(self):
        self.switched = SimpleNamespace(pk=1)
        self.home = SimpleNamespace(pk=2)
        self.addCleanup(
            lambda: hasattr(_thread_local, "request")
            and delattr(_thread_local, "request")
        )

    def _request(self, active=None, authenticated=True, company=None):
        user = SimpleNamespace(is_authenticated=authenticated, company=company)
        return SimpleNamespace(active_company=active, user=user)

    def test_switched_company_wins(self):
        """The middleware's company is returned even if the user has another."""
        request = self._request(active=self.switched, company=self.home)
        self.assertIs(get_active_company(request), self.switched)

    def test_falls_back_to_user_company(self):
        """With no active company, an authenticated user's own company is used."""
        request = self._request(active=None, company=self.home)
        self.assertIs(get_active_company(request), self.home)

    def test_anonymous_user_gets_none(self):
        """An anonymous user never resolves a company."""
        request = SimpleNamespace(active_company=None, user=AnonymousUser())
        self.assertIsNone(get_active_company(request))

    def test_user_stand_in_without_is_authenticated(self):
        """Request stand-ins whose user only has a company still resolve it."""
        request = SimpleNamespace(
            active_company=None, user=SimpleNamespace(company=self.home)
        )
        self.assertIs(get_active_company(request), self.home)

    def test_fake_request_with_only_active_company(self):
        """Background fake requests that only define active_company work."""
        request = SimpleNamespace(active_company=self.switched)
        self.assertIs(get_active_company(request), self.switched)

    def test_request_without_user_or_company(self):
        """A bare object does not raise."""
        self.assertIsNone(get_active_company(SimpleNamespace()))

    def test_uses_thread_local_request(self):
        """With no argument the thread-local request is used."""
        _thread_local.request = self._request(active=self.switched)
        self.assertIs(get_active_company(), self.switched)

    def test_no_request_returns_none(self):
        """Outside a request there is no company."""
        if hasattr(_thread_local, "request"):
            del _thread_local.request
        self.assertIsNone(get_active_company())


class ActiveCompanySingleReaderTests(SimpleTestCase):
    """Python code reads the active company only through get_active_company."""

    # The middleware writes request.active_company; the helper is its one reader.
    ALLOWED = (
        "horilla/contrib/core/middlewares.py",
        "horilla/contrib/utils/middlewares.py",
    )
    SKIPPED_DIRS = ("venv", "node_modules", "static", "windows-installer")

    @staticmethod
    def _is_request(node):
        """True for ``request``, ``self.request`` and ``x.request`` expressions."""
        return (isinstance(node, ast.Name) and node.id == "request") or (
            isinstance(node, ast.Attribute) and node.attr == "request"
        )

    def _offences(self, tree):
        """Line numbers that read the active company without the helper."""
        lines = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "active_company"
                and isinstance(node.ctx, ast.Load)
                and self._is_request(node.value)
            ):
                lines.append(node.lineno)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "active_company"
            ):
                lines.append(node.lineno)
        return lines

    def test_no_second_way_to_read_the_active_company(self):
        """Use get_active_company(request) instead of reading the attribute."""
        root = Path(__file__).resolve().parents[3]
        offenders = []
        for path in root.rglob("*.py"):
            rel = path.relative_to(root).as_posix()
            parts = rel.split("/")
            if (
                parts[0] in self.SKIPPED_DIRS
                or "migrations" in parts
                or "tests" in parts
                or rel in self.ALLOWED
                or path.name == "tests.py"
                or path.name.startswith("test_")
            ):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            offenders += [f"{rel}:{n}" for n in self._offences(tree)]
        self.assertEqual(
            offenders,
            [],
            "Use get_active_company(request) instead:\n" + "\n".join(offenders),
        )


class ShiftHourFormTestCase(TestCase):
    """Base for the shift hour form tests: a company, a schedule and post helpers."""

    # Mon 08:30-17:30, Tue-Fri 12:30-13:30 and Sat 08:30-17:30 (Sunday off).
    WORKING = {
        "monday": ("08:30", "17:30"),
        "tuesday": ("12:30", "13:30"),
        "wednesday": ("12:30", "13:30"),
        "thursday": ("12:30", "13:30"),
        "friday": ("12:30", "13:30"),
        "saturday": ("08:30", "17:30"),
    }

    def setUp(self):
        """Create the company the shift belongs to."""
        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )

    def form(self, working=None, **extra):
        """A shift form for the schedule above, with ``extra`` fields posted as well."""
        data = {
            "company": self.company.pk,
            "name": "Test shift",
            "time_zone": "Asia/Kolkata",
            "timing_type": "different",
            "break1_mode": "none",
            "break2_mode": "none",
        }
        for day, (start, end) in (working or self.WORKING).items():
            data[f"{day}_start"], data[f"{day}_end"] = start, end
        data.update(extra)
        post = QueryDict(mutable=True)
        for key, value in data.items():
            post.setlist(key, value if isinstance(value, list) else [value])
        return ShiftHourForm(post)

    @staticmethod
    def diff(slot, **days):
        """Per-day break fields: ``diff("break1", tuesday=("12:30", "13:00"))``."""
        data = {f"{slot}_mode": "different"}
        for day, (start, end) in days.items():
            data[f"{slot}_diff_{day}_start"], data[f"{slot}_diff_{day}_end"] = (
                start,
                end,
            )
        return data

    def messages(self, form, field):
        """The error messages of ``field``."""
        return [str(message) for message in form.errors.get(field, [])]


class ShiftHourBreakValidationTests(ShiftHourFormTestCase):
    """
    Break hours of a shift: only on working days, never the whole shift, and Break 1
    and Break 2 never at the same time.

    The shift is Mon 08:30-17:30, Tue-Fri 12:30-13:30 and Sat 08:30-17:30 (Sunday off).
    """

    # -- break only on some of the working days --------------------------------

    def test_a_break_on_some_working_days_is_valid(self):
        """A break on Monday and Saturday only, none on Tuesday to Friday, is fine."""
        days = {d: ("12:30", "13:30") for d in ("monday", "saturday")}
        form = self.form(**self.diff("break1", **days))
        self.assertTrue(form.is_valid(), form.errors)

    # -- check 1: the day must be a working day ----------------------------------

    def test_a_break_on_a_non_working_day_is_shown_on_that_day(self):
        """The error is on the day's own field, not on the hidden weekday picker."""
        form = self.form(**self.diff("break1", sunday=("12:30", "13:30")))
        self.assertFalse(form.is_valid())
        messages = self.messages(form, "break1_diff_sunday_start")
        self.assertEqual(len(messages), 1)
        self.assertIn("Sunday", messages[0])
        self.assertNotIn("break1_week_days", form.errors)

    def test_every_break_day_outside_the_shift_is_reported(self):
        """Each day that is not a working day gets its own error."""
        working = {d: t for d, t in self.WORKING.items() if d != "saturday"}
        form = self.form(
            working,
            **self.diff(
                "break1", saturday=("09:00", "10:00"), sunday=("09:00", "10:00")
            ),
        )
        self.assertFalse(form.is_valid())
        self.assertIn("break1_diff_saturday_start", form.errors)
        self.assertIn("break1_diff_sunday_start", form.errors)

    def test_the_same_break_on_a_non_working_day_is_refused_on_the_weekday_field(self):
        """With one break for all days the weekday picker is visible, so it shows there."""
        form = self.form(
            break1_mode="same",
            break1_week_days=["sun"],
            break1_default_start="12:30",
            break1_default_end="13:30",
        )
        self.assertFalse(form.is_valid())
        self.assertEqual(
            self.messages(form, "break1_week_days"),
            ["Break days must be among the shift working days."],
        )

    # -- check 2: a break must leave some working time ---------------------------

    def test_a_break_cannot_cover_the_whole_shift_of_a_day(self):
        """Tuesday works 12:30-13:30, so a break of 12:30-13:30 leaves no work."""
        form = self.form(**self.diff("break1", tuesday=("12:30", "13:30")))
        self.assertFalse(form.is_valid())
        messages = self.messages(form, "break1_diff_tuesday_start")
        self.assertEqual(len(messages), 1)
        self.assertIn("cannot cover the whole shift", messages[0])
        self.assertIn("Tuesday", messages[0])

    def test_a_break_cannot_cover_the_whole_of_a_long_shift(self):
        """Monday works 08:30-17:30; a break of the same hours is refused too."""
        form = self.form(**self.diff("break1", monday=("08:30", "17:30")))
        self.assertFalse(form.is_valid())
        self.assertIn(
            "cannot cover the whole shift", form.errors["break1_diff_monday_start"][0]
        )

    def test_one_break_for_all_days_cannot_cover_a_whole_day_either(self):
        """The same rule applies to a break that is the same on every day."""
        form = self.form(
            break1_mode="same",
            break1_week_days=["tue", "mon"],
            break1_default_start="12:30",
            break1_default_end="13:30",
        )
        self.assertFalse(form.is_valid())
        messages = self.messages(form, "break1_default_start")
        self.assertEqual(len(messages), 1)
        self.assertIn("Tuesday", messages[0])

    def test_a_break_that_touches_the_start_or_end_of_the_shift_is_valid(self):
        """Only a break that is the whole shift is refused."""
        form = self.form(
            **self.diff(
                "break1", tuesday=("12:30", "13:00"), saturday=("16:30", "17:30")
            )
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_a_break_outside_the_shift_hours_is_still_refused(self):
        """The existing rule: the break must fall inside the hours of that day."""
        form = self.form(**self.diff("break1", tuesday=("12:00", "12:45")))
        self.assertFalse(form.is_valid())
        self.assertIn(
            "must fall within the shift hours",
            form.errors["break1_diff_tuesday_start"][0],
        )

    # -- check 3: Break 1 and Break 2 must not overlap ---------------------------

    def test_breaks_that_overlap_are_refused(self):
        """Break 1 12:30-13:30 and Break 2 13:00-14:00 share half an hour on Monday."""
        form = self.form(
            **self.diff("break1", monday=("12:30", "13:30")),
            **self.diff("break2", monday=("13:00", "14:00")),
        )
        self.assertFalse(form.is_valid())
        messages = self.messages(form, "break2_diff_monday_start")
        self.assertEqual(messages, ["Break 1 and Break 2 overlap on Monday."])

    def test_breaks_that_only_touch_are_valid(self):
        """Break 2 may start when Break 1 ends."""
        form = self.form(
            **self.diff("break1", monday=("12:30", "13:30")),
            **self.diff("break2", monday=("13:30", "14:00")),
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_breaks_on_different_days_never_overlap(self):
        """The same hours on two different days are fine."""
        form = self.form(
            **self.diff("break1", monday=("12:30", "13:30")),
            **self.diff("break2", saturday=("12:30", "13:30")),
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_a_break_for_all_days_overlapping_a_per_day_break_is_refused(self):
        """The check works across the two break modes."""
        form = self.form(
            break1_mode="same",
            break1_week_days=["mon"],
            break1_default_start="12:30",
            break1_default_end="13:30",
            **self.diff("break2", monday=("13:00", "14:00")),
        )
        self.assertFalse(form.is_valid())
        self.assertEqual(
            self.messages(form, "break2_diff_monday_start"),
            ["Break 1 and Break 2 overlap on Monday."],
        )

    def test_overlap_is_not_reported_while_a_break_is_invalid(self):
        """An invalid break is reported on its own, without a second message about it."""
        form = self.form(
            **self.diff("break1", tuesday=("12:30", "13:30")),
            **self.diff("break2", tuesday=("12:45", "13:15")),
        )
        self.assertFalse(form.is_valid())
        everything = [str(m) for messages in form.errors.values() for m in messages]
        self.assertFalse([m for m in everything if "overlap" in m], everything)


class ShiftHourHalfFilledDayTests(ShiftHourFormTestCase):
    """A day with only a start or only an end time must be reported, not dropped."""

    # -- main hours ------------------------------------------------------------

    def test_a_day_with_only_a_start_is_reported(self):
        """Monday with a start and no end is refused, and the message names the day."""
        working = {**self.WORKING, "monday": ("09:00", "")}
        form = self.form(working)
        self.assertFalse(form.is_valid())
        messages = self.messages(form, "monday_end")
        self.assertEqual(len(messages), 1)
        self.assertIn("Monday", messages[0])
        self.assertIn("both start and end", messages[0])

    def test_a_day_with_only_an_end_is_reported(self):
        """The message is on the start field when that is the empty one."""
        working = {**self.WORKING, "tuesday": ("", "13:30")}
        form = self.form(working)
        self.assertFalse(form.is_valid())
        self.assertIn("Tuesday", self.messages(form, "tuesday_start")[0])
        self.assertNotIn("tuesday_end", form.errors)

    def test_a_day_left_completely_empty_is_a_closed_day(self):
        """Both empty is still allowed: that is how a day is closed."""
        working = {d: t for d, t in self.WORKING.items() if d != "saturday"}
        form = self.form(working)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn("sat", form.cleaned_data["week_days"])

    def test_a_half_filled_only_day_does_not_also_ask_for_a_weekday(self):
        """One clear message, not the generic "at least one weekday" as well."""
        form = self.form({"monday": ("09:00", "")})
        self.assertFalse(form.is_valid())
        self.assertIn("monday_end", form.errors)
        self.assertNotIn("__all__", form.errors)

    def test_every_half_filled_day_is_reported_at_once(self):
        """The user is not sent back once per day."""
        working = {**self.WORKING, "monday": ("09:00", ""), "friday": ("", "13:30")}
        form = self.form(working)
        self.assertFalse(form.is_valid())
        self.assertIn("monday_end", form.errors)
        self.assertIn("friday_start", form.errors)

    # -- per-day breaks ----------------------------------------------------------

    def test_a_break_day_with_only_a_start_is_reported(self):
        """Monday's break has a start and no end, while Saturday's is complete."""
        form = self.form(
            break1_mode="different",
            break1_diff_monday_start="12:30",
            break1_diff_saturday_start="12:30",
            break1_diff_saturday_end="13:30",
        )
        self.assertFalse(form.is_valid())
        messages = self.messages(form, "break1_diff_monday_end")
        self.assertEqual(len(messages), 1)
        self.assertIn("Monday", messages[0])

    def test_a_break_day_with_only_an_end_is_reported(self):
        """The message is on the start field when that is the empty one."""
        form = self.form(
            break1_mode="different",
            break1_diff_monday_end="13:30",
            break1_diff_saturday_start="12:30",
            break1_diff_saturday_end="13:30",
        )
        self.assertFalse(form.is_valid())
        self.assertIn("Monday", self.messages(form, "break1_diff_monday_start")[0])

    def test_the_second_break_is_checked_too(self):
        """Break 2 follows the same rule as Break 1."""
        form = self.form(
            **self.diff("break1", saturday=("12:30", "13:30")),
            break2_mode="different",
            break2_diff_monday_start="15:00",
        )
        self.assertFalse(form.is_valid())
        self.assertIn("break2_diff_monday_end", form.errors)
        self.assertNotIn("break1_diff_saturday_start", form.errors)

    def test_a_break_day_left_empty_is_just_no_break(self):
        """Both empty means no break that day."""
        form = self.form(
            break1_mode="different",
            break1_diff_saturday_start="12:30",
            break1_diff_saturday_end="13:30",
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["break1_week_days"], ["sat"])

    def test_a_half_filled_break_day_gets_no_second_message(self):
        """Only the half-filled day is reported, not "enter at least one break day"."""
        form = self.form(break1_mode="different", break1_diff_monday_start="12:30")
        self.assertFalse(form.is_valid())
        self.assertIn("break1_diff_monday_end", form.errors)
        self.assertNotIn("__all__", form.errors)


class ShiftHourSameHoursRequiredTests(ShiftHourFormTestCase):
    """With the same hours every day, the error is on the time that is missing."""

    def same(self, **extra):
        """Same hours on Monday; ``extra`` overrides the default times and breaks."""
        data = {"timing_type": "same", "week_days": ["mon"]}
        data.update(extra)
        return self.form(**data)

    def test_a_missing_end_is_reported_on_the_end_field(self):
        """Only the start is filled, so the error is under the end time."""
        form = self.same(default_start_time="08:30")
        self.assertFalse(form.is_valid())
        self.assertEqual(
            self.messages(form, "default_end_time"),
            ["End time is required when using the same hours every day."],
        )
        self.assertNotIn("default_start_time", form.errors)

    def test_a_missing_start_is_reported_on_the_start_field(self):
        """Only the end is filled, so the error is under the start time."""
        form = self.same(default_end_time="17:30")
        self.assertFalse(form.is_valid())
        self.assertEqual(
            self.messages(form, "default_start_time"),
            ["Start time is required when using the same hours every day."],
        )
        self.assertNotIn("default_end_time", form.errors)

    def test_both_missing_are_reported_each_on_its_own_field(self):
        """Nothing filled: each field says what it needs."""
        form = self.same()
        self.assertFalse(form.is_valid())
        self.assertIn("Start time", self.messages(form, "default_start_time")[0])
        self.assertIn("End time", self.messages(form, "default_end_time")[0])

    def test_an_end_before_the_start_is_still_reported_on_the_end_field(self):
        """The existing order check is unchanged."""
        form = self.same(default_start_time="17:30", default_end_time="08:30")
        self.assertFalse(form.is_valid())
        self.assertIn(
            "End time must be after start", form.errors["default_end_time"][0]
        )

    def test_a_missing_break_end_is_reported_on_the_break_end_field(self):
        """The same rule for a break that is the same every day."""
        form = self.same(
            default_start_time="08:30",
            default_end_time="17:30",
            break1_mode="same",
            break1_week_days=["mon"],
            break1_default_start="12:30",
        )
        self.assertFalse(form.is_valid())
        self.assertEqual(
            self.messages(form, "break1_default_end"),
            ["Break end is required for this mode."],
        )
        self.assertNotIn("break1_default_start", form.errors)

    def test_a_missing_break_start_is_reported_on_the_break_start_field(self):
        """And on the start field when that is the empty one."""
        form = self.same(
            default_start_time="08:30",
            default_end_time="17:30",
            break1_mode="same",
            break1_week_days=["mon"],
            break1_default_end="13:30",
        )
        self.assertFalse(form.is_valid())
        self.assertEqual(
            self.messages(form, "break1_default_start"),
            ["Break start is required for this mode."],
        )

    def test_complete_same_hours_with_a_break_are_valid(self):
        """The happy path still saves."""
        form = self.same(
            default_start_time="08:30",
            default_end_time="17:30",
            break1_mode="same",
            break1_week_days=["mon"],
            break1_default_start="12:30",
            break1_default_end="13:30",
        )
        self.assertTrue(form.is_valid(), form.errors)


class ShiftHourListColumnWidthTests(SimpleTestCase):
    """The Shift Hours column must be wide enough for "Different Hour Per Day"."""

    @staticmethod
    def views():
        """Both shift lists: Settings and My Settings."""
        from horilla.contrib.core.views.shift_hour import ShiftHourListView
        from horilla.contrib.core.views.user_shift_hours import UserShiftHourListView

        return (ShiftHourListView, UserShiftHourListView)

    def test_the_timing_column_has_a_fixed_width_in_both_lists(self):
        """Without a width the column shares the table equally and the text is cut."""
        for view in self.views():
            widths = {
                name: attrs["style"]
                for item in view.header_attrs
                for name, attrs in item.items()
            }
            self.assertIn(
                "width: 240px", widths["get_timing_type_display"], view.__name__
            )

    def test_every_width_belongs_to_a_real_column(self):
        """A renamed column would silently lose its width, so each key must exist."""
        for view in self.views():
            columns = {
                col[1] if isinstance(col, (tuple, list)) else col
                for col in view.columns
            }
            for item in view.header_attrs:
                for name in item:
                    self.assertIn(name, columns, f"{view.__name__}: {name}")


class HolidayFormTestCase(TestCase):
    """Builders for holiday forms, shared by the holiday tests."""

    def form(self, instance=None, **extra):
        """A holiday for all users, from 26 to 27 November 2026, with ``extra`` overrides."""
        data = {
            "name": "Founders Day",
            "start_date": "2026-11-26T09:00",
            "end_date": "2026-11-27T09:00",
            "all_users": "on",
        }
        data.update(extra)
        post = QueryDict(mutable=True)
        for key, value in data.items():
            if value is not None:
                post.setlist(key, value if isinstance(value, list) else [value])
        return HolidayForm(post, instance=instance)

    def recurring(self, frequency, **extra):
        """A recurring holiday of the given frequency."""
        return self.form(is_recurring="on", frequency=frequency, **extra)

    def monthly(self, **extra):
        """Monthly on a day of the month: the 5th, every month, unless overridden."""
        data = {"monthly_repeat_type": "day_of_month", "monthly_day_of_month": "5"}
        data.update(extra)
        return self.recurring("monthly", **data)

    def weekday_monthly(self, **extra):
        """Monthly on the 2nd Monday, unless overridden."""
        data = {
            "monthly_repeat_type": "weekday_of_month",
            "monthly_day_of_week": "mon",
            "monthly_week_of_month": "2",
        }
        data.update(extra)
        return self.recurring("monthly", **data)

    def yearly(self, **extra):
        """Yearly on 14 July, unless overridden."""
        data = {
            "yearly_repeat_type": "day_of_month",
            "yearly_month": "july",
            "yearly_day_of_month": "14",
        }
        data.update(extra)
        return self.recurring("yearly", **data)


class HolidayValidationTests(HolidayFormTestCase):
    """Every number, date and choice of the holiday form is checked, on its own field."""

    def assertRefused(self, form, field, text=None):
        """The form is invalid and ``field`` carries the message (containing ``text``)."""
        self.assertFalse(form.is_valid(), "the form was accepted")
        self.assertIn(field, form.errors, form.errors)
        if text:
            self.assertIn(text, " ".join(str(m) for m in form.errors[field]))

    # -- name and dates ------------------------------------------------------------

    def test_a_plain_holiday_is_valid(self):
        """The base case used by every test below."""
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)

    def test_the_end_cannot_be_before_the_start(self):
        """Shown under End Date, not as a general message at the top."""
        self.assertRefused(
            self.form(start_date="2026-11-28T09:00", end_date="2026-11-27T09:00"),
            "end_date",
            "before the start",
        )

    def test_a_holiday_may_start_and_end_at_the_same_moment(self):
        """Equal is allowed."""
        self.assertTrue(
            self.form(
                start_date="2026-11-26T09:00", end_date="2026-11-26T09:00"
            ).is_valid()
        )

    def test_a_holiday_cannot_last_more_than_a_year(self):
        """A holiday from 2026 to 2027-06 is a mistake."""
        self.assertRefused(
            self.form(start_date="2026-01-01T00:00", end_date="2027-06-01T00:00"),
            "end_date",
            "366 days",
        )

    def test_a_full_year_is_allowed(self):
        """The limit is 366 days, so a whole year still passes."""
        form = self.form(start_date="2026-01-01T00:00", end_date="2026-12-31T00:00")
        self.assertTrue(form.is_valid(), form.errors)

    def test_years_outside_1900_to_2100_are_refused(self):
        """Years such as 0001 and 9999 are typing mistakes."""
        form = self.form(start_date="0001-01-01T00:00", end_date="9999-12-31T00:00")
        self.assertRefused(form, "start_date", "1900 to 2100")
        self.assertIn("end_date", form.errors)

    def test_a_blank_name_is_refused(self):
        """Spaces only is blank."""
        self.assertRefused(self.form(name="   "), "name")

    # -- weekly --------------------------------------------------------------------

    def test_weekly_needs_at_least_one_day(self):
        """Weekly with no day ticked is refused on the days field."""
        self.assertRefused(
            self.recurring("weekly", recurs_every_weeks="1"), "weekly_days"
        )

    def test_weekly_interval_must_be_1_to_52(self):
        """0 and 53 are refused, 1 and 52 are fine."""
        for bad in ("0", "53", "9999"):
            self.assertRefused(
                self.recurring("weekly", weekly_days=["mon"], recurs_every_weeks=bad),
                "recurs_every_weeks",
                "between 1 and 52",
            )
        for good in ("1", "52"):
            form = self.recurring(
                "weekly", weekly_days=["mon"], recurs_every_weeks=good
            )
            self.assertTrue(form.is_valid(), form.errors)

    def test_a_blank_weekly_interval_is_a_message_and_not_a_crash(self):
        """It used to raise a TypeError (None < 1)."""
        self.assertRefused(
            self.recurring("weekly", weekly_days=["mon"], recurs_every_weeks=""),
            "recurs_every_weeks",
            "required",
        )

    # -- monthly -------------------------------------------------------------------

    def test_a_day_of_month_must_be_1_to_31(self):
        """0, 32 and 45 are refused."""
        for bad in ("0", "32", "45"):
            self.assertRefused(
                self.monthly(monthly_day_of_month=bad),
                "monthly_day_of_month",
                "between 1 and 31",
            )

    def test_the_31st_is_allowed_every_month(self):
        """Shorter months are the user's choice; the number itself is valid."""
        for good in ("1", "31"):
            form = self.monthly(monthly_day_of_month=good)
            self.assertTrue(form.is_valid(), form.errors)

    def test_monthly_interval_must_be_1_to_12_or_blank(self):
        """Blank means every month; 0 and 13 are refused."""
        for bad in ("0", "13", "9999"):
            self.assertRefused(
                self.monthly(monthly_interval=bad),
                "monthly_interval",
                "between 1 and 12",
            )
        for good in ("", "1", "12"):
            form = self.monthly(monthly_interval=good)
            self.assertTrue(form.is_valid(), form.errors)

    def test_the_week_of_the_month_must_be_1_to_5(self):
        """ "The 9th Monday" is refused."""
        for bad in ("0", "6", "9"):
            self.assertRefused(
                self.weekday_monthly(monthly_week_of_month=bad),
                "monthly_week_of_month",
                "between 1 and 5",
            )
        self.assertTrue(self.weekday_monthly().is_valid())
        self.assertTrue(self.weekday_monthly(monthly_week_of_month="5").is_valid())

    def test_monthly_on_the_nth_weekday_needs_the_weekday(self):
        """Weekday missing: refused on that field."""
        self.assertRefused(
            self.weekday_monthly(monthly_day_of_week=""), "monthly_day_of_week"
        )

    def test_monthly_needs_a_repeat_type(self):
        """No repeat type chosen: refused on that field."""
        self.assertRefused(self.recurring("monthly"), "monthly_repeat_type")

    # -- yearly --------------------------------------------------------------------

    def test_yearly_day_must_exist_in_the_month(self):
        """30 February and 31 April are not dates; 29 February and 30 April are."""
        self.assertRefused(
            self.yearly(yearly_month="february", yearly_day_of_month="30"),
            "yearly_day_of_month",
            "at most 29 days",
        )
        self.assertRefused(
            self.yearly(yearly_month="april", yearly_day_of_month="31"),
            "yearly_day_of_month",
            "at most 30 days",
        )
        self.assertTrue(
            self.yearly(yearly_month="february", yearly_day_of_month="29").is_valid()
        )
        self.assertTrue(
            self.yearly(yearly_month="april", yearly_day_of_month="30").is_valid()
        )

    def test_a_yearly_day_outside_1_to_31_is_refused(self):
        """99 and 0 are refused on the number itself."""
        for bad in ("0", "32", "99"):
            self.assertRefused(
                self.yearly(yearly_day_of_month=bad),
                "yearly_day_of_month",
                "between 1 and 31",
            )

    def test_yearly_needs_a_month(self):
        """Month missing: refused on that field."""
        self.assertRefused(self.yearly(yearly_month=""), "yearly_month")

    def test_the_yearly_week_of_the_month_must_be_1_to_5(self):
        """The same limit as the monthly rule."""
        data = {
            "yearly_repeat_type": "weekday_of_month",
            "yearly_month": "july",
            "yearly_day_of_week": "mon",
        }
        self.assertRefused(
            self.recurring("yearly", yearly_week_of_month="8", **data),
            "yearly_week_of_month",
            "between 1 and 5",
        )
        self.assertTrue(
            self.recurring("yearly", yearly_week_of_month="2", **data).is_valid()
        )

    def test_yearly_needs_a_repeat_type(self):
        """No repeat type chosen: refused on that field."""
        self.assertRefused(
            self.recurring("yearly", yearly_month="july"), "yearly_repeat_type"
        )

    def test_a_recurring_holiday_needs_a_frequency(self):
        """Recurring without a frequency is refused on the frequency field."""
        self.assertRefused(self.form(is_recurring="on"), "frequency")

    def test_a_valid_recurring_holiday_of_each_kind(self):
        """The three happy paths."""
        weekly = self.recurring(
            "weekly", weekly_days=["mon", "fri"], recurs_every_weeks="2"
        )
        for form in (weekly, self.monthly(), self.weekday_monthly(), self.yearly()):
            self.assertTrue(form.is_valid(), form.errors)

    # -- the form inputs and the model itself ---------------------------------------

    def test_inputs_carry_no_native_limits_so_errors_look_like_the_rest_of_the_app(
        self,
    ):
        """
        min / max / step make the browser show its own bubble, which looks unlike the
        app's red message under the field and covers the Save button.
        """
        form = self.monthly(monthly_interval="1")
        for name in HolidayForm.NUMBER_LIMITS:
            attrs = form.fields[name].widget.attrs
            # Django itself adds min=0 to a positive integer; the limits are ours to add.
            self.assertIn(attrs.get("min"), (None, 0), name)
            self.assertNotIn("max", attrs, name)
            self.assertNotIn("step", attrs, name)
        for name in ("start_date", "end_date"):
            attrs = form.fields[name].widget.attrs
            self.assertNotIn("min", attrs, name)
            self.assertNotIn("max", attrs, name)

    def test_an_out_of_range_number_is_answered_on_the_field_by_the_server(self):
        """The message the user sees is the app's own, under the field."""
        form = self.monthly(monthly_interval="65")
        self.assertRefused(form, "monthly_interval", "between 1 and 12")

    def test_the_model_reports_every_problem_on_its_field(self):
        """The same rules apply outside the form (API, admin, import)."""
        holiday = Holiday(
            name="X",
            start_date=timezone.make_aware(datetime(2026, 11, 26, 9)),
            end_date=timezone.make_aware(datetime(2026, 11, 25, 9)),
            is_recurring=True,
            frequency="weekly",
            weekly_days=[],
            recurs_every_weeks=None,
        )
        with self.assertRaises(ValidationError) as caught:
            holiday.clean()
        self.assertEqual(
            set(caught.exception.error_dict),
            {"end_date", "weekly_days", "recurs_every_weeks"},
        )


class HolidayFieldHelpTests(HolidayFormTestCase):
    """Each field says what it is: a clear label, a range placeholder and a real tooltip."""

    def every_kind(self):
        """One form for each way a holiday can repeat, plus a one-time holiday."""
        return {
            "one time": self.form(),
            "weekly": self.recurring(
                "weekly", weekly_days=["mon"], recurs_every_weeks="1"
            ),
            "monthly date": self.monthly(),
            "monthly weekday": self.weekday_monthly(),
            "yearly date": self.yearly(),
            "yearly weekday": self.recurring(
                "yearly",
                yearly_repeat_type="weekday_of_month",
                yearly_month="july",
                yearly_day_of_week="mon",
                yearly_week_of_month="2",
            ),
        }

    def test_every_visible_field_has_an_explanation(self):
        """No field is left with an empty tooltip, whichever way the holiday repeats."""
        for kind, form in self.every_kind().items():
            for name, field in form.fields.items():
                if field.widget.is_hidden:
                    continue
                self.assertTrue(
                    str(field.help_text).strip(), f"{kind}: {name} has no help"
                )

    def test_help_is_plain_text(self):
        """It is shown in a tooltip (a title attribute), so markup would print as text."""
        for name, text in HolidayForm.field_help_texts().items():
            self.assertNotIn("<", str(text), name)

    def test_help_states_the_limits_that_are_checked(self):
        """The numbers in the text are the ones Holiday.clean() enforces."""
        texts = {
            name: str(text) for name, text in HolidayForm.field_help_texts().items()
        }
        for name, (low, high) in HolidayForm.NUMBER_LIMITS.items():
            self.assertIn(f"from {low} to {high}", texts[name], name)
        self.assertIn(str(Holiday.MAX_DURATION_DAYS), texts["end_date"])
        for year in Holiday.YEAR_RANGE:
            self.assertIn(str(year), texts["start_date"])

    def test_help_explains_the_two_repeat_choices(self):
        """ "On Day" and "On the" are not self-explanatory, so the help gives an example."""
        help_texts = HolidayForm.field_help_texts()
        self.assertIn("5th", str(help_texts["monthly_repeat_type"]))
        self.assertIn("2nd Monday", str(help_texts["monthly_repeat_type"]))
        self.assertIn("14 July", str(help_texts["yearly_repeat_type"]))

    def test_the_repeat_counts_say_what_they_count(self):
        """ "Monthly Interval" did not say whether it counts days, weeks or months."""
        weekly = self.every_kind()["weekly"]
        self.assertEqual(
            str(weekly.fields["recurs_every_weeks"].label), "Repeat Every (Weeks)"
        )
        monthly = self.monthly(monthly_interval="1")
        self.assertEqual(
            str(monthly.fields["monthly_interval"].label), "Repeat Every (Months)"
        )

    def test_number_inputs_show_their_range_as_the_placeholder(self):
        """An empty box shows what is allowed, for example "1 to 31"."""
        form = self.monthly(monthly_interval="1")
        self.assertEqual(
            form.fields["monthly_day_of_month"].widget.attrs["placeholder"], "1 to 31"
        )
        self.assertEqual(
            form.fields["monthly_interval"].widget.attrs["placeholder"], "1 to 12"
        )


class HolidayRecurrenceTextTests(SimpleTestCase):
    """The recurrence line of the detail page reads as a sentence and never crashes."""

    def holiday(self, **extra):
        """An unsaved recurring holiday."""
        return Holiday(name="H", is_recurring=True, all_users=True, **extra)

    def test_one_time_holiday(self):
        """Not recurring says so."""
        self.assertEqual(
            str(Holiday(name="H").get_recurrence_description()),
            "Not a recurring holiday",
        )

    def test_weekly(self):
        """A weekly holiday used to crash (a lazy day name inside join) and show nothing."""
        cases = {
            (("sat", "sun"), 1): "Every week on Saturday and Sunday",
            (("sat",), 2): "Every 2 weeks on Saturday",
            (("mon", "wed", "fri"), None): "Every week on Monday, Wednesday and Friday",
        }
        for (days, weeks), expected in cases.items():
            holiday = self.holiday(
                frequency="weekly", weekly_days=list(days), recurs_every_weeks=weeks
            )
            self.assertEqual(str(holiday.get_recurrence_description()), expected)

    def test_monthly_on_a_date(self):
        """The 22nd, not "22th", and "every month", not "every 1 month"."""
        base = {"frequency": "monthly", "monthly_repeat_type": "day_of_month"}
        for day, interval, expected in (
            (5, 1, "On the 5th of every month"),
            (22, None, "On the 22nd of every month"),
            (31, 3, "On the 31st of every 3 months"),
        ):
            holiday = self.holiday(
                monthly_day_of_month=day, monthly_interval=interval, **base
            )
            self.assertEqual(str(holiday.get_recurrence_description()), expected)

    def test_monthly_on_a_weekday(self):
        """The weekday is spelled out ("Monday", not "Mon")."""
        holiday = self.holiday(
            frequency="monthly",
            monthly_repeat_type="weekday_of_month",
            monthly_day_of_week="mon",
            monthly_week_of_month=2,
        )
        self.assertEqual(
            str(holiday.get_recurrence_description()),
            "On the 2nd Monday of every month",
        )

    def test_yearly(self):
        """Both yearly forms."""
        by_date = self.holiday(
            frequency="yearly",
            yearly_repeat_type="day_of_month",
            yearly_month="july",
            yearly_day_of_month=14,
        )
        self.assertEqual(
            str(by_date.get_recurrence_description()), "Every year on 14 July"
        )
        by_weekday = self.holiday(
            frequency="yearly",
            yearly_repeat_type="weekday_of_month",
            yearly_month="july",
            yearly_day_of_week="mon",
            yearly_week_of_month=2,
        )
        self.assertEqual(
            str(by_weekday.get_recurrence_description()),
            "On the 2nd Monday of July every year",
        )

    def test_incomplete_data_gives_a_generic_line_and_no_crash(self):
        """A recurring holiday missing its details still shows something."""
        for extra in (
            {"frequency": "monthly"},
            {"frequency": "yearly"},
            {"frequency": "weekly", "weekly_days": []},
        ):
            self.assertEqual(
                str(self.holiday(**extra).get_recurrence_description()),
                "Recurring holiday",
                extra,
            )

    def test_ordinals(self):
        """1st 2nd 3rd 4th, 11th to 13th, then 21st 22nd 23rd and 31st."""
        holiday = Holiday()
        expected = {
            1: "1st",
            2: "2nd",
            3: "3rd",
            4: "4th",
            11: "11th",
            12: "12th",
            13: "13th",
            21: "21st",
            22: "22nd",
            23: "23rd",
            24: "24th",
            31: "31st",
        }
        for number, text in expected.items():
            self.assertEqual(holiday.get_ordinal_number(number), text)

    def test_both_detail_pages_use_the_one_description(self):
        """The Settings and My Settings details show the same line."""
        for view in (HolidayDetailView, UserHolidayDetailView):
            self.assertIn(("is_recurring", "get_recurrence_description"), view.body)

    def test_the_unused_helpers_are_gone(self):
        """Nothing called these, and two of them crashed."""
        for name in (
            "is_recurring_holiday",
            "get_eligible_users",
            "is_user_eligible",
            "duration_days",
        ):
            self.assertFalse(hasattr(Holiday, name), name)


class HolidayDateClashTests(HolidayFormTestCase):
    """Holidays are unique per dates (the name does not matter) for the same people."""

    def setUp(self):
        """A company, another company, and two users."""
        self.company = Company.objects.create(
            name="Acme", email="a@example.com", country="US"
        )
        self.other_company = Company.objects.create(
            name="Beta", email="b@example.com", country="US"
        )
        self.admin = User.objects.create_user(
            username="adm", email="adm@example.com", password="x"
        )
        self.ann = User.objects.create_user(
            username="ann", email="ann@example.com", password="x", first_name="Ann"
        )
        self.bob = User.objects.create_user(
            username="bob", email="bob@example.com", password="x", first_name="Bob"
        )

    @staticmethod
    def when(day, hour=0):
        """A moment in November 2026."""
        return timezone.make_aware(datetime(2026, 11, day, hour))

    def make(self, name="H", day=26, company=None, users=(), **extra):
        """Save a one-day holiday on ``day`` November; for all users unless ``users`` are given."""
        holiday = Holiday(
            name=name,
            start_date=self.when(day, 9),
            end_date=self.when(day, 18),
            all_users=not users,
            company=company or self.company,
            created_by=self.admin,
            updated_by=self.admin,
            **extra,
        )
        holiday.save()
        if users:
            holiday.specific_users.set(users)
        return holiday

    def personal_form(self, users, day=26, instance=None, **extra):
        """A form for a holiday of specific users on ``day`` November."""
        return self.form(
            instance=instance or Holiday(company=self.company),
            all_users=None,
            specific_users=[str(user.pk) for user in users],
            start_date=f"2026-11-{day:02d}T09:00",
            end_date=f"2026-11-{day:02d}T18:00",
            **extra,
        )

    # -- company holidays ----------------------------------------------------------

    def test_a_second_company_holiday_on_the_same_dates_is_refused_whatever_its_name(
        self,
    ):
        """The name is not part of the rule."""
        self.make("Founders Day")
        with self.assertRaises(ValidationError) as caught:
            self.make("A completely different name")
        self.assertEqual(list(caught.exception.error_dict), ["start_date"])
        self.assertIn("Founders Day is already a holiday", str(caught.exception))

    def test_the_same_name_on_other_dates_is_fine(self):
        """Only the dates matter."""
        self.make("Founders Day", day=26)
        self.make("Founders Day", day=27)

    def test_the_same_dates_in_another_company_is_fine(self):
        """Each company has its own holidays."""
        self.make("H", day=26)
        self.make("H", day=26, company=self.other_company)

    def test_saving_a_holiday_again_does_not_clash_with_itself(self):
        """Editing keeps working."""
        holiday = self.make("H")
        holiday.name = "Renamed"
        holiday.save()

    def test_the_form_refuses_a_company_holiday_on_taken_dates(self):
        """The message is under Start Date."""
        self.make("Founders Day", day=26)
        form = self.form(
            instance=Holiday(company=self.company),
            name="Another",
            start_date="2026-11-26T09:00",
            end_date="2026-11-26T18:00",
        )
        self.assertFalse(form.is_valid())
        self.assertIn("start_date", form.errors)
        self.assertIn("already a holiday for all users", str(form.errors["start_date"]))

    def test_a_different_day_is_accepted_by_the_form(self):
        """The base case."""
        self.make("Founders Day", day=20)
        form = self.form(
            instance=Holiday(company=self.company),
            start_date="2026-11-26T09:00",
            end_date="2026-11-26T18:00",
        )
        self.assertTrue(form.is_valid(), form.errors)

    # -- holidays of specific users --------------------------------------------------

    def test_a_company_holiday_and_a_personal_one_may_share_dates(self):
        """They are different kinds of holiday, in either order."""
        self.make("Company day", day=26)
        self.assertTrue(self.personal_form([self.ann]).is_valid())
        self.make("Ann day", day=24, users=[self.ann])
        self.make("Company day 2", day=24)

    def test_two_users_may_have_the_same_day_off(self):
        """Different people, same dates, is normal."""
        self.make("Ann day", day=26, users=[self.ann])
        form = self.personal_form([self.bob])
        self.assertTrue(form.is_valid(), form.errors)

    def test_a_user_cannot_get_the_same_dates_twice(self):
        """The message names the user who already has them."""
        self.make("Ann day", day=26, users=[self.ann])
        form = self.personal_form([self.ann, self.bob])
        self.assertFalse(form.is_valid())
        message = " ".join(str(m) for m in form.errors["start_date"])
        self.assertIn("Ann day is already a holiday", message)
        self.assertIn("Ann", message)
        self.assertNotIn("Bob", message)

    def test_editing_a_personal_holiday_does_not_clash_with_itself(self):
        """Its own row is left out of the comparison."""
        holiday = self.make("Ann day", day=26, users=[self.ann])
        form = self.personal_form([self.ann], instance=holiday)
        self.assertTrue(form.is_valid(), form.errors)

    # -- the API -----------------------------------------------------------------

    def payload(self, **extra):
        """A valid one-time holiday for the API."""
        data = {
            "name": "API holiday",
            "company": self.company.pk,
            "start_date": "2026-11-26T09:00:00Z",
            "end_date": "2026-11-26T18:00:00Z",
            "all_users": True,
        }
        data.update(extra)
        return data

    def test_the_api_accepts_a_valid_holiday(self):
        """The base case."""
        serializer = HolidaySerializer(data=self.payload())
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_the_api_answers_bad_data_with_field_errors_and_not_a_crash(self):
        """It used to pass here and fail with a server error on save."""
        serializer = HolidaySerializer(
            data=self.payload(
                is_recurring=True,
                frequency="monthly",
                monthly_repeat_type="day_of_month",
                monthly_day_of_month=45,
            )
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("monthly_day_of_month", serializer.errors)

    def test_the_api_refuses_taken_dates(self):
        """The same rule as the form."""
        self.make("Founders Day", day=26)
        serializer = HolidaySerializer(data=self.payload())
        self.assertFalse(serializer.is_valid())
        self.assertIn("start_date", serializer.errors)

    def test_the_api_checks_a_partial_update_against_the_stored_holiday(self):
        """Changing only the day of month still runs the rules on the whole holiday."""
        holiday = self.make(
            "Payday",
            day=10,
            is_recurring=True,
            frequency="monthly",
            monthly_repeat_type="day_of_month",
            monthly_day_of_month=5,
        )
        serializer = HolidaySerializer(
            holiday, data={"monthly_day_of_month": 45}, partial=True
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("monthly_day_of_month", serializer.errors)
        ok = HolidaySerializer(holiday, data={"monthly_day_of_month": 6}, partial=True)
        self.assertTrue(ok.is_valid(), ok.errors)

    def test_the_api_refuses_a_user_who_already_has_the_dates(self):
        """Specific users are compared too."""
        self.make("Ann day", day=26, users=[self.ann])
        serializer = HolidaySerializer(
            data=self.payload(all_users=False, specific_users=[self.ann.pk])
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("start_date", serializer.errors)

    # -- business hours ------------------------------------------------------------

    def business_hour(self):
        """A business hour of the company."""
        return BusinessHour.objects.create(
            name="Office",
            company=self.company,
            created_by=self.admin,
            updated_by=self.admin,
            time_zone="Asia/Kolkata",
            timing_type="same",
            week_days=["mon"],
            default_start_time="09:00",
            default_end_time="17:00",
        )

    def test_a_holiday_changed_to_specific_users_leaves_the_business_hours(self):
        """Business hours only take holidays for all users."""
        holiday = self.make("Founders Day")
        hours = self.business_hour()
        hours.holidays.add(holiday)
        holiday.all_users = False
        holiday.save()
        self.assertFalse(hours.holidays.filter(pk=holiday.pk).exists())

    def test_a_company_holiday_stays_in_the_business_hours(self):
        """Saving it again changes nothing."""
        holiday = self.make("Founders Day")
        hours = self.business_hour()
        hours.holidays.add(holiday)
        holiday.name = "Renamed"
        holiday.save()
        self.assertTrue(hours.holidays.filter(pk=holiday.pk).exists())

    def test_the_all_users_help_warns_about_the_business_hours(self):
        """So the unlinking is not a surprise."""
        self.assertIn(
            "business hours", str(HolidayForm.field_help_texts()["all_users"])
        )


class HolidayDemoDataTests(TestCase):
    """holiday.json: the fixed-date holidays of the country of each demo company."""

    LOAD_DATA = Path(__file__).resolve().parent / "load_data"

    # The country of each demo company in company.json, and what it is given. Holidays
    # that move every year (Easter, Eid, ...) cannot repeat on one date, so they are not here.
    EXPECTED = {
        "AT": {
            ("New Year's Day", 1, 1),
            ("Epiphany", 1, 6),
            ("Labour Day", 5, 1),
            ("Assumption Day", 8, 15),
            ("National Day", 10, 26),
            ("All Saints' Day", 11, 1),
            ("Immaculate Conception", 12, 8),
            ("Christmas Day", 12, 25),
            ("St. Stephen's Day", 12, 26),
        },
        "CM": {
            ("New Year's Day", 1, 1),
            ("Youth Day", 2, 11),
            ("Labour Day", 5, 1),
            ("National Day", 5, 20),
            ("Assumption Day", 8, 15),
            ("Christmas Day", 12, 25),
        },
    }

    @classmethod
    def setUpTestData(cls):
        """Load the demo companies and their holidays the way the demo loader does."""
        call_command("loaddata", str(cls.LOAD_DATA / "company.json"), verbosity=0)
        call_command("loaddata", str(cls.LOAD_DATA / "holiday.json"), verbosity=0)

    def test_the_demo_loader_loads_the_holidays_after_the_companies(self):
        """holiday.json is in the demo data list, ordered after company.json."""
        order = {name: number for number, name in CoreConfig.demo_data["files"]}
        self.assertGreater(
            order["load_data/holiday.json"], order["load_data/company.json"]
        )

    def test_every_demo_company_country_has_its_holidays(self):
        """If a company's country changes in company.json, its holidays must change too."""
        for company in Company.objects.all():
            expected = self.EXPECTED.get(company.country)
            self.assertIsNotNone(
                expected, f"no holidays for {company.name} ({company.country})"
            )
            found = {
                (h.name, h.yearly_month, h.yearly_day_of_month)
                for h in Holiday.all_objects.filter(company=company)
            }
            months = [
                "january",
                "february",
                "march",
                "april",
                "may",
                "june",
                "july",
                "august",
                "september",
                "october",
                "november",
                "december",
            ]
            wanted = {(name, months[month - 1], day) for name, month, day in expected}
            self.assertEqual(found, wanted, company.country)

    def test_only_these_companies_have_holidays(self):
        """Nothing is attached to a company that does not exist."""
        self.assertEqual(
            Holiday.all_objects.count(), sum(len(v) for v in self.EXPECTED.values())
        )

    def test_every_holiday_repeats_every_year_for_all_users(self):
        """Recurring, yearly, on a date, for everyone."""
        for holiday in Holiday.all_objects.all():
            self.assertTrue(holiday.all_users, holiday.name)
            self.assertTrue(holiday.is_recurring, holiday.name)
            self.assertEqual(holiday.frequency, "yearly", holiday.name)
            self.assertEqual(holiday.yearly_repeat_type, "day_of_month", holiday.name)

    def test_every_holiday_passes_the_holiday_rules(self):
        """The same clean() that checks the form and the API accepts the fixture."""
        for holiday in Holiday.all_objects.all():
            holiday.clean()

    def test_every_holiday_is_one_whole_day_on_its_own_date(self):
        """
        Starts at midnight and ends at 23:59 of the same day in the company's time zone,
        and that day is the month and date the rule repeats on.
        """
        for holiday in Holiday.all_objects.select_related("company"):
            zone = ZoneInfo(holiday.company.time_zone)
            start = holiday.start_date.astimezone(zone)
            end = holiday.end_date.astimezone(zone)
            self.assertEqual(start.date(), end.date(), holiday.name)
            self.assertEqual((start.hour, start.minute), (0, 0), holiday.name)
            self.assertEqual((end.hour, end.minute), (23, 59), holiday.name)
            self.assertEqual(start.day, holiday.yearly_day_of_month, holiday.name)
            self.assertEqual(
                start.strftime("%B").lower(), holiday.yearly_month, holiday.name
            )

    def test_no_company_has_two_holidays_on_one_date(self):
        """The date rule of the form applies to the demo data as well."""
        for company in Company.objects.all():
            dates = [
                (h.start_date, h.end_date)
                for h in Holiday.all_objects.filter(company=company)
            ]
            self.assertEqual(len(dates), len(set(dates)), company.name)

    def test_the_detail_page_reads_naturally(self):
        """An example: Austria's national day."""
        holiday = Holiday.all_objects.get(name="National Day", company__country="AT")
        self.assertEqual(
            str(holiday.get_recurrence_description()), "Every year on 26 October"
        )


class HolidayImportActionTests(SimpleTestCase):
    """The Holiday list has a gear menu with an Import action, like the other lists."""

    class User:
        """A user holding the given permissions."""

        def __init__(self, *perms):
            self.perms = set(perms)

        def has_perm(self, perm):
            """Has perm."""
            return perm in self.perms

    def actions(self, *perms):
        """The gear menu actions for a user with ``perms``."""
        navbar = HolidayNavbar()
        navbar.request = SimpleNamespace(user=self.User(*perms))
        return navbar.actions

    def test_the_gear_menu_is_switched_on(self):
        """Without this the navbar draws no gear icon."""
        self.assertTrue(HolidayNavbar.enable_actions)

    def test_the_import_action_opens_the_single_import_for_holidays(self):
        """The same URL and target as the Import action of Leads or Campaigns."""
        actions = self.actions("core.add_holiday", "core.can_view_horilla_import")
        self.assertEqual([str(a["action"]) for a in actions], ["Import"])
        attrs = actions[0]["attrs"]
        self.assertIn(
            f'hx-get="{reverse("core:import_data")}?single_import=true'
            '&model_name=Holiday&app_label=core"',
            attrs,
        )
        self.assertIn('hx-target="#modalBox"', attrs)
        self.assertIn("openModal()", attrs)

    def test_only_import_is_offered(self):
        """The generic column and quick-filter actions do not apply here."""
        actions = self.actions("core.add_holiday", "core.can_view_horilla_import")
        self.assertEqual(len(actions), 1)

    def test_a_user_who_cannot_add_holidays_has_no_import(self):
        """No gear for them."""
        self.assertEqual(self.actions("core.can_view_horilla_import"), [])

    def test_a_user_who_cannot_open_the_import_page_has_no_import(self):
        """It would only open an access-denied window."""
        self.assertEqual(self.actions("core.add_holiday"), [])


class HolidayImportWindowTests(TestCase):
    """Holiday is on the Import page and in the gear import of the Holidays list."""

    def setUp(self):
        """An admin who may add anything."""
        company = Company.objects.create(
            name="Acme", email="a@example.com", country="US"
        )
        self.admin = User.objects.create_superuser(
            username="root", email="root@example.com", password="x", company=company
        )

    def modules(self, query=""):
        """Names of the modules the import window offers the admin."""
        request = RequestFactory().get("/import-data/" + query)
        request.user = self.admin
        request.session = SessionStore()
        view = ImportDataView()
        view.request = request
        return [module["name"] for module in view.get_available_models()]

    def test_holiday_is_registered_for_the_import_feature(self):
        """The single import finds its model in the registry; without it the box is empty."""
        self.assertIn(Holiday, FEATURE_REGISTRY["import_models"])

    def test_the_gear_import_offers_holiday_as_the_only_module(self):
        """The same single import as Leads: one module, ready to be chosen."""
        self.assertEqual(
            self.modules("?single_import=true&model_name=Holiday&app_label=core"),
            ["Holiday"],
        )

    def test_the_main_import_page_lists_holiday(self):
        """Like every other registered model."""
        names = self.modules()
        self.assertIn("Holiday", names)
        self.assertIn("Company", names)
