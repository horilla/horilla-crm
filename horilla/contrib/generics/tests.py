"""
Tests for horilla.contrib.generics.

Unit tests and integration tests for the horilla.contrib.generics app.
"""

# Standard library imports
from datetime import date, datetime
from pathlib import Path
from unittest import mock

# Third-party imports (Django)
from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase
from login_history.models import post_login, post_logout

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.models import Company, Holiday, ListColumnVisibility, Role
from horilla.contrib.generics.templatetags.horilla_tags import (
    history_i18n as history_i18n_module,
)
from horilla.contrib.generics.templatetags.horilla_tags._shared import (
    format_datetime_value,
)
from horilla.contrib.generics.templatetags.horilla_tags.history_display import (
    DIFF_VALUE_PREVIEW_LENGTH,
    has_long_diff_value,
    html_to_paragraphs,
    is_long_diff_value,
)
from horilla.contrib.generics.templatetags.horilla_tags.history_i18n import (
    history_datetime,
)
from horilla.contrib.generics.views.helpers.list_column import get_view_columns
from horilla.registry.history_registry import (
    HISTORY_DATETIME_FORMATTERS,
    get_history_datetime_formatters,
    register_history_datetime_formatter,
    unregister_history_datetime_formatter,
)
from horilla.urls import reverse
from horilla.utils import timezone
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


class ChangeOwnEditFormAccessTests(TestCase):
    """With only ``change_own_<model>``, a generic edit form opens for the
    same records the list and detail views offer Edit on: an ``OWNER_FIELDS``
    entry, ForeignKey or ManyToMany, names the user or someone in a role
    below theirs.

    Holiday stands in for any owned model: its ``OWNER_FIELDS`` is the
    ManyToMany ``specific_users``, and its edit form is a plain
    ``HorillaSingleFormView``.
    """

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
        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        director_role = Role.objects.create(role_name="Director", company=self.company)
        manager_role = Role.objects.create(
            role_name="Sales Manager", parent_role=director_role, company=self.company
        )
        rep_role = Role.objects.create(
            role_name="Sales Rep", parent_role=manager_role, company=self.company
        )
        support_role = Role.objects.create(role_name="Support", company=self.company)
        self.director = self.make_user("director", director_role)
        self.manager = self.make_user("manager", manager_role)
        self.rep = self.make_user("rep", rep_role)
        self.peer = self.make_user("peer", support_role)
        # Holidays are created by someone else, so the created_by fallback
        # owner field doesn't grant anyone access.
        self.hr = User.objects.create_user(
            username="hr", email="hr@example.com", password="pass", company=self.company
        )
        self.rep_holiday = self.make_holiday("Rep's day off", self.rep)
        self.manager_holiday = self.make_holiday("Manager's day off", self.manager)

    def make_user(self, username, role):
        """Create a user in ``role`` whose only edit right is change_own_holiday."""
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="pass",
            company=self.company,
            role=role,
        )
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="core", codename="change_own_holiday"
            )
        )
        return user

    def make_holiday(self, name, owner):
        """Create a holiday that ``owner`` holds through ``specific_users``."""
        now = timezone.now()
        holiday = Holiday.objects.create(
            name=name,
            start_date=now,
            end_date=now,
            company=self.company,
            created_by=self.hr,
            updated_by=self.hr,
        )
        holiday.specific_users.add(owner)
        return holiday

    def can_open_edit_form(self, user, holiday):
        """Whether ``user`` gets the edit form rather than the 403 page."""
        self.client.force_login(user)
        response = self.client.get(
            reverse("core:holiday_update_form", kwargs={"pk": holiday.pk}),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        return "403.html" not in [template.name for template in response.templates]

    def test_owner_through_a_many_to_many_owner_field(self):
        """A user listed in a ManyToMany owner field can edit the record."""
        self.assertTrue(self.can_open_edit_form(self.rep, self.rep_holiday))

    def test_users_in_parent_roles_can_edit_a_subordinate_record(self):
        """The rep's manager, and the director above them, can edit it too."""
        self.assertTrue(self.can_open_edit_form(self.manager, self.rep_holiday))
        self.assertTrue(self.can_open_edit_form(self.director, self.rep_holiday))

    def test_no_access_up_or_across_the_role_tree(self):
        """Neither a subordinate nor a user in an unrelated role gets access."""
        self.assertFalse(self.can_open_edit_form(self.rep, self.manager_holiday))
        self.assertFalse(self.can_open_edit_form(self.peer, self.rep_holiday))

    def test_change_own_permission_is_still_required(self):
        """Owning the record isn't enough without change_own_<model>."""
        self.rep.user_permissions.clear()
        self.assertFalse(self.can_open_edit_form(self.rep, self.rep_holiday))

    def test_is_owned_by_still_decides_alone(self):
        """A model's own is_owned_by() replaces the OWNER_FIELDS rule."""
        with mock.patch.object(Holiday, "is_owned_by", create=True) as is_owned_by:
            is_owned_by.return_value = False
            self.assertFalse(self.can_open_edit_form(self.manager, self.rep_holiday))
            is_owned_by.return_value = True
            self.assertTrue(self.can_open_edit_form(self.peer, self.rep_holiday))

    def test_granted_access_still_opens_the_form(self):
        """has_granted_access(user, "change") grants edit without ownership."""

        def has_granted_access(holiday, user, action):
            return user == self.peer and action == "change"

        with mock.patch.object(
            Holiday, "has_granted_access", has_granted_access, create=True
        ):
            self.assertTrue(self.can_open_edit_form(self.peer, self.rep_holiday))

    def test_fallback_owner_fields_still_open_the_form(self):
        """The record's creator can edit it without being in OWNER_FIELDS."""
        Holiday.objects.filter(pk=self.rep_holiday.pk).update(created_by=self.peer)
        self.assertTrue(self.can_open_edit_form(self.peer, self.rep_holiday))
