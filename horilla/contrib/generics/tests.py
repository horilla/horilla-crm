"""
Tests for horilla.contrib.generics.

Unit tests and integration tests for the horilla.contrib.generics app.
"""

# Standard library imports
from datetime import date, datetime
from datetime import timezone as dt_timezone
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

# Third-party imports (Django)
from auditlog.models import LogEntry
from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.contrib.contenttypes.models import ContentType
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase
from login_history.models import post_login, post_logout

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.models import Company, Holiday, ListColumnVisibility
from horilla.contrib.generics.templatetags.horilla_tags import (
    history_i18n as history_i18n_module,
)
from horilla.contrib.generics.templatetags.horilla_tags._shared import (
    format_datetime_value,
)
from horilla.contrib.generics.templatetags.horilla_tags.history_display import (
    DIFF_VALUE_PREVIEW_LENGTH,
    collapse_redundant_history,
    has_long_diff_value,
    history_changes_display,
    html_to_paragraphs,
    is_long_diff_value,
)
from horilla.contrib.generics.templatetags.horilla_tags.history_i18n import (
    history_datetime,
)
from horilla.contrib.generics.views.core import HorillaHistorySectionView
from horilla.contrib.generics.views.helpers.list_column import get_view_columns
from horilla.registry.history_registry import (
    HISTORY_DATETIME_FORMATTERS,
    get_history_datetime_formatters,
    register_history_datetime_formatter,
    unregister_history_datetime_formatter,
)
from horilla.urls import reverse
from horilla.utils.translation import override


class GetViewColumnsVerboseNameTests(SimpleTestCase):
    """get_view_columns() must resolve a string column's real verbose_name.

    Regression test for a mislabeling bug introduced by f759bfa8a: string
    columns were humanized (`col.replace("_", " ").title()`) instead of
    looking up the model field's actual `verbose_name`.
    """

    def test_string_column_uses_the_field_verbose_name(self):
        """`LeadListView.columns` has `lead_status`, whose verbose_name
        ("Lead Stage") deliberately differs from its humanized name
        ("Lead Status").

        `url_name` is passed bare (no namespace prefix) here, matching how
        `HorillaListView` actually populates it for the page's own column
        selector -- see `list_view_url_name` in
        `horilla/contrib/generics/views/list.py`, built from
        `resolver_match.url_name`, not the namespaced `view_name`.
        """
        columns = get_view_columns("leads_list", "leads", "Lead")
        by_field_name = {field_name: label for label, field_name in columns}
        self.assertEqual(by_field_name["lead_status"], "Lead Stage")

    def test_method_based_column_falls_back_to_a_humanized_name(self):
        """`CallProviderListView.columns` has `status_col`, a model method
        with no corresponding `_meta` field, so it can't resolve a
        verbose_name and must keep the humanized fallback."""
        columns = get_view_columns("provider_list", "calls", "CallProvider")
        by_field_name = {field_name: label for label, field_name in columns}
        self.assertEqual(by_field_name["status_col"], "Status Col")


class ColumnSelectorSavesVerboseNameTests(TestCase):
    """The column-selector POST flow must persist the real verbose_name."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # django-login-history reads request.META['HTTP_USER_AGENT'] on
        # login/logout. Django's test client builds a bare HttpRequest, so
        # this KeyErrors unless the signal is disconnected here.
        user_logged_in.disconnect(post_login)
        user_logged_out.disconnect(post_logout)

    @classmethod
    def tearDownClass(cls):
        user_logged_in.connect(post_login)
        user_logged_out.connect(post_logout)
        super().tearDownClass()

    def setUp(self):
        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        self.user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
            company=self.company,
        )
        self.client.force_login(self.user)

    def test_saved_visible_fields_use_the_real_verbose_name(self):
        """Column selector saves the field's actual verbose name, not the raw label."""
        response = self.client.post(
            reverse("generics:column_selector"),
            data={
                "app_label": "leads",
                "model_name": "Lead",
                "url_name": "leads_list",
                "visible_fields": ["title", "lead_status"],
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200, response.content[:2000])

        visibility = ListColumnVisibility.all_objects.get(
            user=self.user,
            app_label="leads",
            model_name="Lead",
            url_name="leads_list",
        )
        saved = {field_name: label for label, field_name in visibility.visible_fields}
        self.assertEqual(saved["lead_status"], "Lead Stage")

    def test_removed_view_column_is_listed_once_in_available_fields(self):
        """A method column removed from the list (e.g. `status_col`) is kept in
        both the view's columns and `removed_custom_fields`; Available Fields
        must still offer it only once."""
        url = reverse("generics:column_selector")
        params = {
            "app_label": "activity",
            "model_name": "Activity",
            "url_name": "global_task_list",
        }
        headers = {
            "HTTP_HX_REQUEST": "true",
            "HTTP_HX_CURRENT_URL": "http://testserver/activity/activity-view/",
        }
        self.client.post(
            url,
            {**params, "visible_fields": ["subject", "due_datetime", "status_col"]},
            **headers,
        )
        self.client.post(
            url, {**params, "visible_fields": ["subject", "due_datetime"]}, **headers
        )

        context = self.client.get(url, params, **headers).context
        available = [f[1] for f in context["available_fields"]]
        self.assertEqual(available.count("status_col"), 1)


class HistoryDiffValueFullTextTests(SimpleTestCase):
    """Long History diff values render a preview plus their full text, and the
    History tab offers a "Show full text" toggle to switch between them."""

    def render_value(self, value):
        """Render the History diff value partial for a raw diff `value`."""
        return render_to_string(
            "partials/history_diff_value.html", {"value": value}
        ).strip()

    def test_is_long_diff_value_matches_the_preview_length(self):
        """Only values longer than the preview length count as long."""
        self.assertFalse(is_long_diff_value("x" * DIFF_VALUE_PREVIEW_LENGTH))
        self.assertTrue(is_long_diff_value("x" * (DIFF_VALUE_PREVIEW_LENGTH + 1)))

    def test_has_long_diff_value_checks_old_and_new_text(self):
        """A diff counts as long when either side's text would be shortened,
        measured without markup; M2M markers never count."""
        long_text = "x" * (DIFF_VALUE_PREVIEW_LENGTH + 1)
        self.assertTrue(has_long_diff_value(["short", long_text]))
        self.assertTrue(has_long_diff_value([long_text, "short"]))
        self.assertFalse(
            has_long_diff_value(["short", "<p>" + "<b></b>" * 50 + "</p>"])
        )
        self.assertFalse(has_long_diff_value(["__m2m__", "add", "Added", long_text]))
        self.assertFalse(has_long_diff_value(None))

    def test_html_to_paragraphs_keeps_one_line_per_block(self):
        """Paragraphs, list items and line breaks each get their own line."""
        value = (
            "<p>Key requirements:</p><ol><li>Barcode scanning</li>"
            '<li class="x">Daily report</li></ol><p>Line one<br>line two</p>'
        )
        self.assertEqual(
            html_to_paragraphs(value),
            "Key requirements:\n• Barcode scanning\n• Daily report\nLine one\nline two",
        )

    def test_short_value_renders_as_plain_text(self):
        """A short value renders as plain text, with no preview/full wrappers."""
        html = self.render_value("<p>Called the customer</p>")
        self.assertEqual(html, "Called the customer")

    def test_long_value_renders_preview_and_full_paragraphs(self):
        """A long value keeps its tail preview and also carries the full text,
        one line per paragraph."""
        first = "Start of the call summary."
        second = "x" * DIFF_VALUE_PREVIEW_LENGTH
        html = self.render_value(f"<p>{first}</p><p>{second}</p>")
        self.assertIn(
            '<span class="history-value-preview" dir="auto">…'
            + f"{first}, {second}"[-DIFF_VALUE_PREVIEW_LENGTH:]
            + "</span>",
            html,
        )
        self.assertIn(
            f'<span class="history-value-full" dir="auto">{first}\n{second}</span>',
            html,
        )

    def test_long_value_is_escaped_in_both_spans(self):
        """Text that looks like markup is escaped in the preview and full text."""
        value = "x" * DIFF_VALUE_PREVIEW_LENGTH + " if a < b & c"
        html = self.render_value(value)
        self.assertNotIn("a < b", html)
        self.assertEqual(html.count("a &lt; b &amp; c"), 2)

    def test_history_tab_renders_the_full_text_toggle(self):
        """The History tab toolbar has the switch, hidden until JS finds a
        shortened value on the page."""
        request = RequestFactory().get("/history/")
        html = render_to_string(
            "history_tab.html", {"page_obj": None, "request": request}
        )
        self.assertIn('class="history-full-text-toggle', html)
        self.assertIn('role="switch"', html)
        self.assertIn('onclick="toggleHistoryFullText()"', html)
        self.assertIn("Show full text", html)
        self.assertIn('"historyShowFullText"', html)


class AuditlogDisplayTruncationTests(SimpleTestCase):
    """The History tab needs auditlog's full display values."""

    def test_auditlog_display_values_are_not_truncated(self):
        """Auditlog's own 140-character cut is disabled; the History tab
        shortens values itself and can show them in full."""
        self.assertLess(settings.AUDITLOG_CHANGE_DISPLAY_TRUNCATE_LENGTH, 0)


class HistoryDatetimeFormatterRegistryTests(SimpleTestCase):
    """`history_datetime` has no calendar-specific code: apps plug their own
    display in through the History datetime formatter registry."""

    def setUp(self):
        # Start from an empty registry (an installed extension app may have
        # registered a formatter) and put it back afterwards.
        saved = list(HISTORY_DATETIME_FORMATTERS)
        HISTORY_DATETIME_FORMATTERS.clear()
        self.addCleanup(HISTORY_DATETIME_FORMATTERS.extend, saved)
        self.addCleanup(HISTORY_DATETIME_FORMATTERS.clear)

    def test_without_formatters_the_default_format_is_used(self):
        """With nothing registered, history_datetime shows exactly what the
        shared datetime formatter gives for the value."""
        value = datetime(2026, 8, 19, 15, 7, 13)
        with override("fa"):
            self.assertEqual(
                history_datetime(value),
                format_datetime_value(value, convert_timezone=True),
            )
            self.assertEqual(
                history_datetime("2026-08-19 15:07"),
                format_datetime_value(
                    datetime(2026, 8, 19, 15, 7), convert_timezone=True
                ),
            )
            self.assertEqual(history_datetime("--"), "--")

    def test_core_filter_has_no_calendar_extension_imports(self):
        """Calendar systems plug in through the registry, not core imports."""
        source = Path(history_i18n_module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("horilla_jalali", source)
        self.assertNotIn("jdatetime", source)

    def test_registered_formatter_gets_the_raw_value(self):
        """A registered formatter's result is used, and it receives the value
        as passed to the filter plus the user and company."""
        calls = []

        def formatter(value, *, user=None, company=None):
            calls.append((value, user, company))
            return "formatted"

        register_history_datetime_formatter(formatter)
        value = date(2026, 8, 19)
        self.assertEqual(history_datetime(value), "formatted")
        self.assertEqual(calls, [(value, None, None)])

    def test_none_falls_through_in_priority_order(self):
        """Formatters run by ascending priority; None defers to the next one,
        and to the default format when every formatter defers."""
        order = []

        def deferring(value, **kwargs):
            order.append("deferring")
            return None

        def late(value, **kwargs):
            order.append("late")
            return "late"

        register_history_datetime_formatter(late, priority=90)
        register_history_datetime_formatter(deferring, priority=10)
        self.assertEqual(history_datetime("2026-08-19"), "late")
        self.assertEqual(order, ["deferring", "late"])

        unregister_history_datetime_formatter(late)
        self.assertIn("2026", str(history_datetime("2026-08-19")))

    def test_failing_formatter_is_skipped(self):
        """A formatter that raises is logged and skipped, not rendered as an
        error on the History tab."""

        def broken(value, **kwargs):
            raise ValueError("boom")

        register_history_datetime_formatter(broken)
        with self.assertLogs(
            "horilla.contrib.generics.templatetags.horilla_tags.history_i18n",
            level="ERROR",
        ):
            text = str(history_datetime(date(2026, 8, 19)))
        self.assertIn("2026", text)

    def test_registering_twice_is_a_no_op(self):
        """The same formatter is only registered once."""

        def formatter(value, **kwargs):
            return None

        register_history_datetime_formatter(formatter)
        register_history_datetime_formatter(formatter, priority=10)
        self.assertEqual(get_history_datetime_formatters(), [formatter])
        unregister_history_datetime_formatter(formatter)
        self.assertEqual(get_history_datetime_formatters(), [])


class HistoryDayGroupingTests(SimpleTestCase):
    """History entries are grouped under the day their shown time falls on,
    not the stored UTC day."""

    def _view(self, user_time_zone=None, company_time_zone=None):
        view = HorillaHistorySectionView()
        company = None
        if company_time_zone:
            company = SimpleNamespace(time_zone=company_time_zone)
        user = SimpleNamespace(time_zone=user_time_zone, company=company)
        view.request = SimpleNamespace(user=user, active_company=None)
        return view

    def test_entry_after_midnight_local_time_groups_under_the_local_day(self):
        """23:29 UTC is 02:59 the next day in Tehran, which is the day the
        entry shows, so it is grouped there."""
        view = self._view(user_time_zone="Asia/Tehran")
        timestamp = datetime(2026, 9, 29, 23, 29, tzinfo=dt_timezone.utc)
        self.assertEqual(view.get_history_date(timestamp), date(2026, 9, 30))

    def test_company_time_zone_is_used_when_the_user_has_none(self):
        """Grouping falls back to the company's timezone, like the entry
        times do."""
        view = self._view(company_time_zone="Asia/Tehran")
        timestamp = datetime(2026, 9, 29, 23, 29, tzinfo=dt_timezone.utc)
        self.assertEqual(view.get_history_date(timestamp), date(2026, 9, 30))

    def test_without_a_time_zone_the_utc_day_is_kept(self):
        """With no user or company timezone the stored day is unchanged."""
        view = self._view()
        timestamp = datetime(2026, 9, 29, 23, 29, tzinfo=dt_timezone.utc)
        self.assertEqual(view.get_history_date(timestamp), date(2026, 9, 29))


class HistoryChangesDisplayTests(TestCase):
    """history_changes_display turns auditlog's raw diff into what the
    History tab shows."""

    def _entry(self, changes):
        return LogEntry(
            content_type=ContentType.objects.get_for_model(Holiday),
            object_pk="1",
            action=LogEntry.Action.UPDATE,
            changes=changes,
        )

    @staticmethod
    def _label(field_name):
        return str(Holiday._meta.get_field(field_name).verbose_name)

    def test_last_saved_fields_are_hidden_in_every_language(self):
        """Updated At / Updated By are hidden whatever language their labels
        are in, leaving only the real edit."""
        entry = self._entry(
            {
                "name": ["Nowruz", "Nowruz holiday"],
                "updated_at": ["2026-09-29 14:25:00", "2026-09-29 23:29:00"],
                "updated_by": ["None", "99"],
            }
        )
        for language in ("en", "fa"):
            with self.subTest(language=language), override(language):
                changes = history_changes_display(entry)
                self.assertEqual([str(key) for key in changes], [self._label("name")])

    def test_empty_values_are_blank_not_none(self):
        """auditlog's "None" for an empty value shows as blank (the template's
        "--"), and None -> blank is not reported as a change."""
        entry = self._entry(
            {
                "monthly_day_of_month": ["None", "15"],
                "name": ["None", ""],
            }
        )
        changes = {
            str(key): value for key, value in history_changes_display(entry).items()
        }
        self.assertEqual(changes, {self._label("monthly_day_of_month"): ["", "15"]})

    def test_update_with_nothing_to_show_is_dropped(self):
        """A save that only touched hidden fields is not listed as an empty
        "X updated" row, even with no creation entry next to it."""
        hidden_only = self._entry(
            {"updated_at": ["2026-09-29 14:25:00", "2026-09-29 23:29:00"]}
        )
        real_edit = self._entry({"name": ["Nowruz", "Nowruz holiday"]})
        self.assertEqual(
            collapse_redundant_history([hidden_only, real_edit]), [real_edit]
        )


class HistoryTabViewTests(TestCase):
    """The History tab view lists each day's entries as the tab shows them."""

    def test_day_with_nothing_to_show_is_not_listed(self):
        """A day whose only entry has nothing to show is left out instead of
        rendering as an empty group."""
        user = User.objects.create_user(
            username="planner", email="planner@example.com", password="pass"
        )
        holiday = Holiday.objects.create(
            name="Nowruz",
            start_date=datetime(2026, 3, 20, tzinfo=dt_timezone.utc),
            end_date=datetime(2026, 3, 24, tzinfo=dt_timezone.utc),
            created_by=user,
            updated_by=user,
        )
        holiday.save()  # Changes nothing but Updated At.
        resave = LogEntry.objects.get_for_object(holiday).get(
            action=LogEntry.Action.UPDATE
        )
        resave.timestamp = datetime(2026, 9, 29, 12, 0, tzinfo=dt_timezone.utc)
        resave.save()

        view = HorillaHistorySectionView()
        view.model = Holiday
        request = RequestFactory().get("/history/")
        request.user = SimpleNamespace(time_zone="UTC", company=None)
        view.setup(request, pk=holiday.pk)
        view.object = holiday
        days = list(view.get_context_data()["page_obj"])

        self.assertEqual(len(days), 1)
        self.assertNotEqual(days[0][0], date(2026, 9, 29))
        self.assertEqual(
            [entry.action for entry in days[0][1]], [LogEntry.Action.CREATE]
        )


class _ActorPlacementParser(HTMLParser):
    """Record, for each "by {actor}" span, whether it sits inside a field row."""

    def __init__(self):
        super().__init__()
        self.open_spans = []
        self.actor_in_field_row = []

    def handle_starttag(self, tag, attrs):
        if tag != "span":
            return
        classes = (dict(attrs).get("class") or "").split()
        if "history-actor" in classes:
            self.actor_in_field_row.append(
                any("history-kv" in span for span in self.open_spans)
            )
        self.open_spans.append(classes)

    def handle_endtag(self, tag):
        if tag == "span" and self.open_spans:
            self.open_spans.pop()


class HistoryTabRenderingTests(TestCase):
    """How the History tab lays out an edit row."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="editor", email="editor@example.com", password="pass"
        )

    def render_edit(self, changes):
        entry = LogEntry(
            content_type=ContentType.objects.get_for_model(Holiday),
            object_pk="1",
            action=LogEntry.Action.UPDATE,
            changes=changes,
            actor=self.user,
            timestamp=datetime(2026, 9, 29, 12, 0, tzinfo=dt_timezone.utc),
        )
        request = RequestFactory().get("/history/")
        with override("en"):
            return render_to_string(
                "history_tab.html",
                {
                    "page_obj": [(date(2026, 9, 29), [entry])],
                    "model_name": "holiday",
                    "request": request,
                },
            )

    def actor_in_field_row(self, html):
        parser = _ActorPlacementParser()
        parser.feed(html)
        return parser.actor_in_field_row

    def test_actor_follows_a_single_field_inline(self):
        """With one changed field, "by {actor}" stays on that field's row."""
        html = self.render_edit({"name": ["Nowruz", "Nowruz holiday"]})
        self.assertEqual(self.actor_in_field_row(html), [True])

    def test_actor_gets_its_own_row_after_several_fields(self):
        """With several changed fields, "by {actor}" is not part of the last
        field's row."""
        html = self.render_edit(
            {
                "name": ["Nowruz", "Nowruz holiday"],
                "monthly_day_of_month": ["1", "15"],
            }
        )
        self.assertEqual(self.actor_in_field_row(html), [False])

    def test_diff_values_have_no_surrounding_whitespace(self):
        """No whitespace inside a value's span: in a right-to-left UI it would
        land on the far side of a left-to-right value, gluing it to the
        arrow."""
        html = self.render_edit({"monthly_day_of_month": ["None", "15"]})
        self.assertRegex(html, r'class="history-kv-value"\s+dir="auto"\s*>--</span>')
        self.assertRegex(html, r'class="history-diff-chip"\s+dir="auto"\s*>15</span>')
