"""Tests for horilla_jalali's History tab formatting hook."""

# Standard library imports
import importlib
import sys
from datetime import date, datetime
from datetime import timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

# Third-party imports (Django)
from django.test import SimpleTestCase
from django.utils import formats, timezone

# First party imports (Horilla)
from horilla.contrib.generics.templatetags.horilla_tags.history_i18n import (
    history_datetime,
)
from horilla.registry.history_registry import (
    HISTORY_DATETIME_FORMATTERS,
    get_history_datetime_formatters,
    register_history_datetime_formatter,
)
from horilla.utils.translation import override
from horilla_jalali.history import format_history_datetime_as_jalali, format_shamsi


class IsolatedHistoryRegistryMixin:
    """Run each test against an empty History datetime formatter registry and
    restore the original one afterwards."""

    def setUp(self):
        """Clear the History datetime formatter registry for an isolated test."""
        super().setUp()
        saved = list(HISTORY_DATETIME_FORMATTERS)
        HISTORY_DATETIME_FORMATTERS.clear()
        self.addCleanup(HISTORY_DATETIME_FORMATTERS.extend, saved)
        self.addCleanup(HISTORY_DATETIME_FORMATTERS.clear)


class JalaliHistoryRegistrationTests(IsolatedHistoryRegistryMixin, SimpleTestCase):
    """The app plugs its formatter into the generics History tab itself."""

    def test_registration_registers_the_history_formatter(self):
        """Loading horilla_jalali.registration registers the Shamsi formatter."""
        with patch("horilla.registry.asset_registry.register_html"):
            module = sys.modules.get("horilla_jalali.registration")
            if module is None:
                importlib.import_module("horilla_jalali.registration")
            else:
                importlib.reload(module)
        self.assertEqual(
            get_history_datetime_formatters(), [format_history_datetime_as_jalali]
        )


class HistoryDatetimeShamsiTests(IsolatedHistoryRegistryMixin, SimpleTestCase):
    """Persian UI history timestamps render as Jalali once registered."""

    def setUp(self):
        super().setUp()
        register_history_datetime_formatter(format_history_datetime_as_jalali)

    def test_persian_history_datetime_uses_shamsi_year(self):
        """fa history_datetime uses Shamsi year digits without Gregorian/AM-PM."""
        with override("fa"):
            text = str(history_datetime(datetime(2026, 8, 19, 15, 7, 13)))
        self.assertIn("۱۴۰۵", text)
        self.assertNotIn("1405", text)
        self.assertNotIn("2026", text)
        self.assertNotIn("بعد از ظهر", text)
        self.assertNotIn("قبل از ظهر", text)
        self.assertNotIn("PM", text)
        self.assertNotIn("AM", text)
        self.assertNotRegex(text, r"[0-9]:[0-9]")

    def test_twelve_hour_format_renders_as_24_hour_without_ampm(self):
        """12-hour user format still renders 24-hour Shamsi without AM/PM."""
        user = SimpleNamespace(
            date_time_format="%Y-%m-%d %I:%M:%S %p",
            time_zone=None,
        )
        with override("fa"):
            text = str(
                format_shamsi(datetime(2026, 8, 19, 20, 1, 59), user=user, company=None)
            )
        self.assertIn("۱۴۰۵", text)
        self.assertIn("۲۰:۰۱", text)
        self.assertNotIn("20:01", text)
        self.assertNotIn("۲۰:۰۱:۵۹", text)
        self.assertNotIn("20:01:59", text)
        self.assertNotIn("08:01:59", text)
        self.assertNotIn("بعد از ظهر", text)
        self.assertNotIn("PM", text)

    def test_date_only_uses_persian_digits(self):
        """Date-only values render Shamsi with Persian digits."""
        with override("fa"):
            text = str(history_datetime(date(2026, 8, 19)))
        self.assertIn("۱۴۰۵", text)
        self.assertNotIn("1405", text)

    def test_localized_persian_gregorian_converts_to_shamsi(self):
        """Localized Persian Gregorian strings convert to Shamsi display."""
        with override("fa"):
            text = str(history_datetime("19 اوت 2026، ساعت 8:27"))
        self.assertIn("۱۴۰۵", text)
        self.assertNotIn("اوت", text)
        self.assertNotIn("2026", text)
        self.assertNotIn("ساعت", text)
        self.assertIn("۰۸:۲۷", text)
        self.assertNotIn("08:27", text)
        self.assertNotIn("۰۸:۲۷:۰۰", text)

    def test_other_languages_keep_the_default_format(self):
        """Outside Persian the formatter defers and the Gregorian format stays."""
        value = datetime(2026, 8, 19, 15, 7, 13)
        with override("en"):
            self.assertIsNone(format_history_datetime_as_jalali(value))
            self.assertIn("2026", str(history_datetime(value)))

    def test_gregorian_opt_out_keeps_the_default_format(self):
        """A Persian user who chose the Gregorian calendar is left alone."""
        user = SimpleNamespace(calendar_system="gregorian")
        with override("fa"):
            self.assertIsNone(
                format_history_datetime_as_jalali(date(2026, 8, 19), user=user)
            )

    def test_datetime_diff_values_shift_into_the_viewer_time_zone(self):
        """auditlog writes DateTimeField diff values in settings.TIME_ZONE, so
        they are shifted into the viewer's timezone like the entry times."""
        user = SimpleNamespace(time_zone="Asia/Tehran")
        value = datetime(2026, 9, 29, 23, 29, tzinfo=dt_timezone.utc)
        with override("fa"):
            # The diff string auditlog stores for this value.
            stored = formats.localize(
                timezone.localtime(value, timezone.get_default_timezone())
            )
            text = str(format_history_datetime_as_jalali(stored, user=user))
            self.assertEqual(text, str(format_shamsi(value, user=user)))
        self.assertIn("۱۴۰۵-۰۷-۰۸", text)
        self.assertIn("۰۲:۵۹", text)

    def test_date_diff_values_are_not_shifted(self):
        """A date has no time to shift, so a viewer west of UTC still sees the
        same day."""
        user = SimpleNamespace(time_zone="America/New_York")
        value = date(2026, 8, 19)
        with override("fa"):
            expected = format_shamsi(value, user=user)
            for stored in (formats.localize(value), "2026-08-19"):
                with self.subTest(stored=stored):
                    self.assertEqual(
                        format_history_datetime_as_jalali(stored, user=user),
                        expected,
                    )

    def test_unparseable_text_is_left_to_the_default(self):
        """Non-date diff text is not something the formatter claims."""
        with override("fa"):
            self.assertIsNone(format_history_datetime_as_jalali("--"))
            self.assertIsNone(format_history_datetime_as_jalali("Open"))
