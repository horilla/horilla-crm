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
from unittest import mock

# Third-party imports (Django)
from auditlog.models import LogEntry
from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.contrib.contenttypes.models import ContentType
from django.template import Context, Template
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
    History tab offers a "Show Full Text" toggle to switch between them."""

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
        self.assertIn("Show Full Text", html)
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


class EditDetailsAccessTests(TestCase):
    """Edit Details on the Details tab follows the record page's own rule,
    ``HorillaDetailView.check_update_permission``, which already decides
    whether its button shows: an owner with ``change_own_<model>``, or anyone
    with ``change_<model>``, and never a locked record.

    Holiday stands in for any owned model: its ``OWNER_FIELDS`` is
    ``specific_users``.
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
        self.owner = self.make_user("owner", "change_own_holiday")
        self.other = self.make_user("other", "change_own_holiday")
        self.editor = self.make_user("editor", "change_holiday")
        # Created by someone else, so the created_by fallback owner field
        # doesn't make anyone an owner.
        hr = User.objects.create_user(
            username="hr", email="hr@example.com", password="pass", company=self.company
        )
        now = timezone.now()
        self.holiday = Holiday.objects.create(
            name="Day off",
            start_date=now,
            end_date=now,
            company=self.company,
            created_by=hr,
            updated_by=hr,
        )
        self.holiday.specific_users.add(self.owner)
        self.url_kwargs = {
            "pk": self.holiday.pk,
            "app_label": "core",
            "model_name": "holiday",
        }

    def make_user(self, username, codename):
        """Create a user whose only edit right on holidays is ``codename``."""
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="pass",
            company=self.company,
        )
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label="core", codename=codename)
        )
        return user

    def open_form(self, user):
        """The response ``user`` gets from the Edit Details button."""
        self.client.force_login(user)
        return self.client.get(
            reverse("generics:edit_all_fields", kwargs=self.url_kwargs),
            HTTP_HX_REQUEST="true",
        )

    def save_name(self, user, name):
        """Post a new name through Edit Details as ``user``."""
        self.client.force_login(user)
        response = self.client.post(
            reverse("generics:update_all_fields", kwargs=self.url_kwargs),
            {"name": name},
            HTTP_HX_REQUEST="true",
        )
        self.holiday.refresh_from_db()
        return response

    def test_owner_with_change_own_gets_the_form(self):
        """Clicking Edit Details opens the form instead of a permission error."""
        self.assertContains(self.open_form(self.owner), 'id="details-bulk-edit-form"')

    def test_owner_with_change_own_saves(self):
        """The owner's change is saved."""
        response = self.save_name(self.owner, "Long weekend")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.holiday.name, "Long weekend")

    def test_change_own_on_someone_elses_record_is_refused(self):
        """change_own doesn't reach a record the user doesn't own."""
        self.assertNotContains(self.open_form(self.other), "details-bulk-edit-form")
        self.assertEqual(self.save_name(self.other, "Long weekend").status_code, 403)
        self.assertEqual(self.holiday.name, "Day off")

    def test_change_permission_edits_any_record(self):
        """change_<model> still edits records the user doesn't own."""
        self.assertContains(self.open_form(self.editor), 'id="details-bulk-edit-form"')
        self.save_name(self.editor, "Long weekend")
        self.assertEqual(self.holiday.name, "Long weekend")

    def test_locked_record_is_refused(self):
        """A read-only record opens no form and keeps its values."""
        with mock.patch.object(Holiday, "is_record_locked", True, create=True):
            self.assertNotContains(
                self.open_form(self.editor), "details-bulk-edit-form"
            )
            self.assertEqual(
                self.save_name(self.editor, "Long weekend").status_code, 403
            )
        self.assertEqual(self.holiday.name, "Day off")


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
        """Render the History tab for one Holiday edit with ``changes``."""
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
        """Return, per edit row, whether the actor sits inside a field row."""
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


class ReloadButtonTagTests(SimpleTestCase):
    """``{% reload_button %}`` renders the hidden HTMX refresh button."""

    def render(self, tag_args, path="/roles/", query="page=2", **extra_context):
        """Render the tag with ``tag_args`` against a GET request to ``path``."""
        request = RequestFactory().get(path + ("?" + query if query else ""))
        template = Template(
            "{% load horilla_tags %}{% reload_button " + tag_args + " %}"
        )
        context = Context({"request": request, **extra_context})
        return " ".join(template.render(context).split())

    def test_defaults(self):
        """Trigger and label default to click; url comes from the request;
        hx-select falls back to the target."""
        html = self.render('"#role-container"')
        self.assertEqual(
            html,
            '<button id="reloadButton" hidden hx-get="/roles/?page=2" '
            'hx-target="#role-container" hx-trigger="click" hx-swap="outerHTML" '
            'hx-select="#role-container"> click </button>',
        )

    def test_url_without_query_string(self):
        """With no query string, hx-get is just the request path."""
        html = self.render('"#x"', query="")
        self.assertIn('hx-get="/roles/"', html)

    def test_dynamic_target_from_context(self):
        """The target can be built from context and also sets hx-select."""
        html = self.render(
            '"#"|add:view_id indicator="#loading-indicator"', view_id="lead-list"
        )
        self.assertIn('hx-target="#lead-list"', html)
        self.assertIn('hx-select="#lead-list"', html)
        self.assertIn('hx-indicator="#loading-indicator"', html)

    def test_hx_select_can_differ_or_be_omitted(self):
        """The container is both target and select; hx_select overrides it."""
        html = self.render('"#a" hx_select="#b"')
        self.assertIn('hx-target="#a"', html)
        self.assertIn('hx-select="#b"', html)
        self.assertEqual(html.count("hx-select"), 1)
        html = self.render('"#tab" swap="innerHTML" hx_select=""')
        self.assertNotIn("hx-select", html)
        self.assertIn('hx-swap="innerHTML"', html)

    def test_explicit_trigger_and_label(self):
        """An explicit trigger and label replace the click defaults."""
        html = self.render('"#a" trigger="load" label="reload"')
        self.assertIn('hx-trigger="load"', html)
        self.assertTrue(html.endswith("> reload </button>"))

    def test_push_url_and_select_oob_via_attrs(self):
        """hx_push_url and hx_select_oob are rendered as hyphenated attrs."""
        html = self.render(
            '"#mainContent" hx_push_url="true" hx_select_oob="#dropdown-companies"'
        )
        self.assertIn('hx-push-url="true"', html)
        self.assertIn('hx-select-oob="#dropdown-companies"', html)

    def test_arbitrary_attrs_use_hyphens(self):
        """Any other keyword (e.g. hx-swap-oob) is rendered as an attribute."""
        html = self.render('"#x" hx_swap_oob="true" class="mb-4" hx_vals="{}"')
        self.assertIn('hx-swap-oob="true"', html)
        self.assertIn('class="mb-4"', html)
        self.assertIn('hx-vals="{}"', html)

    def test_hx_keyword_overrides_generated_attribute(self):
        """An explicit hx_target replaces the generated one, not duplicates it."""
        html = self.render('"#x" hx_target=".card"')
        self.assertIn('hx-target=".card"', html)
        self.assertEqual(html.count("hx-target"), 1)

    def test_boolean_and_none_attrs(self):
        """True renders a bare attribute; False and None omit it."""
        html = self.render('"#x" data_flag=True data_off=False data_none=None')
        self.assertIn(" data-flag>", html)
        self.assertNotIn("data-off", html)
        self.assertNotIn("data-none", html)

    def test_visible_and_custom_id(self):
        """hidden=False drops the hidden attribute; button_id sets the id."""
        html = self.render('"#x" hidden=False button_id="other"')
        self.assertIn('id="other"', html)
        self.assertNotIn(" hidden ", html)

    def test_custom_url_overrides_request(self):
        """An explicit url is used instead of the request's path and query."""
        html = self.render('"#x" url="/custom/?a=1"')
        self.assertIn('hx-get="/custom/?a=1"', html)

    def test_values_are_escaped(self):
        """Context values are autoescaped (template literals are trusted)."""
        html = self.render("evil", evil='"><script>')
        self.assertNotIn("<script>", html)
        self.assertIn("&quot;&gt;&lt;script&gt;", html)


class SpinnerTagTests(SimpleTestCase):
    """``{% spinner %}`` renders the animated loading ring."""

    def render(self, tag_args="", **context):
        template = Template("{% load horilla_tags %}{% spinner " + tag_args + " %}")
        return template.render(Context(context)).strip()

    def test_default_size(self):
        self.assertHTMLEqual(
            self.render(),
            '<div class="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 '
            'border-primary-600"></div>',
        )

    def test_every_size(self):
        sizes = {"xs": "h-3 w-3", "sm": "h-5 w-5", "md": "h-6 w-6", "lg": "h-8 w-8"}
        for name, classes in sizes.items():
            with self.subTest(size=name):
                self.assertIn(f"{classes} ", self.render(f'"{name}"'))

    def test_size_from_context_and_keyword(self):
        self.assertIn("h-5 w-5", self.render("size", size="sm"))
        self.assertIn("h-6 w-6", self.render('size="md"'))

    def test_unknown_size_raises(self):
        with self.assertRaises(ValueError):
            self.render('"huge"')

    def test_centered_wraps_in_flex_block(self):
        self.assertHTMLEqual(
            self.render("centered=True"),
            '<div class="flex justify-center items-center p-4">'
            '<div class="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 '
            'border-primary-600"></div></div>',
        )

    def test_centered_with_size_and_wrapper_class(self):
        html = self.render('"sm" centered=True wrapper_class="w-full"')
        self.assertIn('class="flex justify-center items-center p-4 w-full"', html)
        self.assertIn("h-5 w-5", html)

    def test_wrapper_class_ignored_unless_centered(self):
        self.assertNotIn("w-full", self.render('wrapper_class="w-full"'))

    def test_uses_theme_primary_not_hex(self):
        html = self.render()
        self.assertIn("border-primary-600", html)
        self.assertNotIn("#", html)


class BtnTagTests(SimpleTestCase):
    """``{% btn %}`` is a single tag. ``body`` is what opens ``{% endbtn %}``."""

    def render(self, source, **context):
        template = Template("{% load horilla_tags %}" + source)
        return template.render(Context(context))

    def test_submit_without_label_says_save(self):
        html = self.render('{% btn type="submit" %}')
        self.assertIn("Save", html)
        self.assertIn('type="submit"', html)
        self.assertIn("bg-primary-600", html)
        self.assertIn("text-sm px-4 py-2", html)

    def test_loading_id_draws_the_spinner_before_the_label(self):
        html = self.render(
            '{% btn type="submit" hx_indicator="#single-form-save-spinner" '
            'loading_id="single-form-save-spinner" %}'
        )
        self.assertIn('id="single-form-save-spinner"', html)
        self.assertIn("htmx-indicator", html)
        self.assertIn('hx-indicator="#single-form-save-spinner"', html)
        self.assertIn("Save", html)
        self.assertLess(html.index("htmx-indicator"), html.index("Save"))

    def test_body_uses_inner_markup_and_needs_endbtn(self):
        html = self.render(
            '{% btn body type="submit" sizing="p-3 w-full" '
            'extra_class="flex gap-3 justify-center" %}'
            '<img src="/static/assets/icons/sign.svg" alt="Arrow">'
            "Sign In"
            "{% endbtn %}"
        )
        self.assertIn("Sign In", html)
        self.assertIn("sign.svg", html)
        self.assertIn("p-3 w-full", html)
        self.assertIn("flex gap-3 justify-center", html)
        self.assertNotIn("text-sm px-4 py-2", html)
        self.assertNotIn("Save", html)

    def test_body_without_a_label_is_allowed(self):
        html = self.render(
            '{% btn body variant="outline" tag="label" for="provider-help-toggle" %}'
            "Setup Guide"
            "{% endbtn %}"
        )
        self.assertIn("<label ", html)
        self.assertIn('for="provider-help-toggle"', html)
        self.assertIn("Setup Guide", html)
        self.assertIn("text-primary-600", html)

    def test_endbtn_without_body_is_an_error(self):
        from django.template.exceptions import TemplateSyntaxError

        with self.assertRaises(TemplateSyntaxError):
            self.render('{% btn type="submit" %}{% endbtn %}')

    def test_non_submit_without_label_raises(self):
        with self.assertRaises(ValueError):
            self.render("{% btn %}")


class _SubmittedValues(HTMLParser):
    """The name -> value pairs a browser would submit for rendered inputs."""

    def __init__(self):
        super().__init__()
        self.data = {}
        self._select = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name"):
            self.data[attrs["name"]] = attrs.get("value") or ""
        elif tag == "select" and attrs.get("name"):
            self._select = attrs["name"]
            self.data.setdefault(self._select, "")
        elif tag == "option" and self._select and "selected" in attrs:
            self.data[self._select] = attrs.get("value") or ""

    def handle_endtag(self, tag):
        if tag == "select":
            self._select = None


def submitted_values(html):
    """Parse ``html`` into what submitting it would post."""
    parser = _SubmittedValues()
    parser.feed(str(html))
    return parser.data


class EditDetailsFieldErrorTests(TestCase):
    """When Edit Details can't apply a value, the form stays open with what
    was typed, the error under its field and a message named by the field's
    label, shown right away rather than on the next page load.

    Role stands in for any record: ``parent_role`` is a foreign key.
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
        self.admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
            company=self.company,
        )
        self.role = Role.objects.create(role_name="Sales", company=self.company)
        self.client.force_login(self.admin)

    def save(self, data):
        """Post ``data`` through Edit Details."""
        return self.client.post(
            reverse(
                "generics:update_all_fields",
                kwargs={"pk": self.role.pk, "app_label": "core", "model_name": "role"},
            ),
            data,
            HTTP_HX_REQUEST="true",
        )

    def test_the_form_stays_open_with_the_error_and_the_typed_values(self):
        response = self.save({"role_name": "Sales team", "parent_role": "999999"})
        self.assertTemplateUsed(response, "partials/edit_all_fields.html")
        fields = {
            entry["info"]["name"]: entry["info"] for entry in response.context["fields"]
        }
        self.assertTrue(fields["parent_role"]["error"])
        self.assertContains(response, 'value="Sales team"')
        self.role.refresh_from_db()
        self.assertEqual(self.role.role_name, "Sales")

    def test_the_message_names_the_field_by_its_label_and_shows_now(self):
        response = self.save({"parent_role": "999999"})
        self.assertContains(response, 'id="messages-container"')
        texts = [str(message) for message in response.context["messages"]]
        self.assertEqual(len(texts), 1)
        self.assertTrue(texts[0].startswith("Parent Role: "))

    def test_a_refused_phone_number_keeps_what_was_typed(self):
        from horilla.contrib.generics.views.helpers.edit_field import keep_posted_value

        request = RequestFactory().post(
            "/", {"contact_number_0": "+98", "contact_number_1": "12"}
        )
        field_info = {"name": "contact_number", "field_type": "phone"}
        keep_posted_value(field_info, request)
        # Checked as what the widget posts back, not its markup, so it holds
        # for a project that renders the dial code differently.
        self.assertEqual(
            submitted_values(field_info["phone_widget_html"]),
            {"contact_number_0": "+98", "contact_number_1": "12"},
        )
