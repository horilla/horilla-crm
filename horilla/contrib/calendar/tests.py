"""
Tests for the calendar app.

This module contains unit and integration tests for calendar functionality.
"""

# Standard library imports
import datetime
import json
from unittest import mock

# Third-party imports (Django)
from django.contrib.auth.models import Permission
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.test import TestCase
from login_history.models import post_login, post_logout

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.activity.models import Activity
from horilla.contrib.core.models import Company, Holiday, HorillaContentType
from horilla.urls import reverse
from horilla.utils import timezone

# Local imports
from . import views
from .models import CustomCalendar, UserAvailability, UserCalendarPreference


class CalendarRelatedRecordLinkTests(TestCase):
    """
    Calendar events carry ``relatedUrl`` for the popup's Open Related Record
    action, only when the user may open the activity's related record.

    Uses a core model (Holiday) as the related record: the calendar only knows
    the generic ``Activity.related_object``, not any particular related model.
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
        self.user = User.objects.create_user(
            username="salesperson",
            email="salesperson@example.com",
            password="pass",
            company=self.company,
        )
        now = timezone.now()
        self.record = Holiday.objects.create(
            name="Launch Day",
            start_date=now,
            end_date=now,
            company=self.company,
            created_by=self.user,
            updated_by=self.user,
        )
        self.activity = self._make_activity("Call about the launch", self.record)
        self.record_url = str(self.record.get_detail_url())

    def _make_activity(self, subject, related=None):
        activity = Activity.objects.create(
            subject=subject,
            activity_type="task",
            status="not_started",
            due_datetime=timezone.now(),
            owner=self.user,
            content_type=(
                HorillaContentType.objects.get_for_model(related) if related else None
            ),
            object_id=related.pk if related else None,
            company=self.company,
        )
        activity.assigned_to.add(self.user)
        return activity

    def _grant(self, *perms):
        for perm in perms:
            app_label, codename = perm.split(".")
            self.user.user_permissions.add(
                Permission.objects.get(
                    content_type__app_label=app_label, codename=codename
                )
            )

    def _events(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("calendar:get_calendar_events"),
            {"calendar_types[]": ["task"]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success", data)
        return {event["id"]: event for event in data["events"]}

    def test_link_when_user_can_view_the_related_record(self):
        """With view access to the record, the event links to its detail page."""
        self._grant("core.view_holiday")
        related_url = self._events()[self.activity.pk]["relatedUrl"]
        self.assertTrue(related_url.startswith(self.record_url), related_url)

    def test_no_link_without_access_to_the_related_record(self):
        """Seeing the activity on the calendar doesn't open its related record."""
        self.assertEqual(self._events()[self.activity.pk]["relatedUrl"], "")

    def test_no_link_when_there_is_no_related_record(self):
        """An activity that isn't related to any record gets no link."""
        activity = self._make_activity("Plan the week")
        self._grant("core.view_holiday")
        self.assertEqual(self._events()[activity.pk]["relatedUrl"], "")

    def test_no_link_to_a_record_outside_the_active_company(self):
        """A record in another company 404s on its own page, so it isn't linked."""
        other_company = Company.objects.create(
            name="Other", email="other@example.com", country="US"
        )
        Holiday.all_objects.filter(pk=self.record.pk).update(company=other_company)
        self._grant("core.view_holiday")
        self.assertEqual(self._events()[self.activity.pk]["relatedUrl"], "")

    def test_access_is_checked_once_per_related_record(self):
        """Activities on the same record share one access check."""
        second = self._make_activity("Follow up on the launch", self.record)
        self._grant("core.view_holiday")
        with mock.patch.object(
            views,
            "get_related_record_url",
            wraps=views.get_related_record_url,
        ) as helper:
            events = self._events()
        self.assertEqual(helper.call_count, 1)
        self.assertEqual(
            events[self.activity.pk]["relatedUrl"], events[second.pk]["relatedUrl"]
        )


ALL_TYPES = ["task", "event", "meeting", "unavailability"]


class CalendarTypeSelectionTests(TestCase):
    """
    Unchecking a calendar type in the sidebar sticks after the reload, also
    when the user has no ``UserCalendarPreference`` row for it yet (e.g. a new
    user who never changed its color). The sidebar shows a type without a row
    as checked.
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
        self.user = User.objects.create_user(
            username="planner",
            email="planner@example.com",
            password="pass",
            company=self.company,
        )
        start = timezone.now()
        end = start + datetime.timedelta(hours=1)
        for activity_type in ("task", "event", "meeting"):
            Activity.objects.create(
                subject=f"Weekly {activity_type}",
                activity_type=activity_type,
                status="not_started",
                start_datetime=start,
                end_datetime=end,
                owner=self.user,
                company=self.company,
            )
        UserAvailability.objects.create(
            user=self.user,
            from_datetime=start,
            to_datetime=end,
            reason="Dentist",
            company=self.company,
        )
        self.client.force_login(self.user)

    def _save(self, calendar_types):
        """Post the checked types, as a sidebar or My Calendars checkbox does."""
        response = self.client.post(
            reverse("calendar:save_calendar_preferences"),
            json.dumps({"calendar_types": calendar_types}),
            content_type="application/json",
        )
        self.assertEqual(response.json()["status"], "success", response.json())

    def _checked(self, **params):
        """Return the standard calendar types the sidebar renders checked."""
        response = self.client.get(
            reverse("calendar:calendar_view"), params, HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        return [cal["id"] for cal in response.context["calendars"] if cal["selected"]]

    def _event_types(self):
        """Return the event types fetched without ``calendar_types[]``."""
        response = self.client.get(
            reverse("calendar:get_calendar_events"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        data = response.json()
        self.assertEqual(data["status"], "success", data)
        return {event["calendarType"] for event in data["events"]}

    def _row(self, calendar_type):
        return UserCalendarPreference.objects.get(
            user=self.user, calendar_type=calendar_type
        )

    def test_unchecked_type_without_a_row_stays_unchecked(self):
        """Unchecking Tasks is saved as a row with the default color."""
        self._save(["event", "meeting", "unavailability"])

        self.assertEqual(self._checked(), ["event", "meeting", "unavailability"])
        task = self._row("task")
        self.assertFalse(task.is_selected)
        self.assertEqual(task.color, views.DEFAULT_CALENDAR_TYPE_COLORS["task"])
        self.assertEqual(task.company, self.company)

        self._save(ALL_TYPES)
        self.assertEqual(self._checked(), ALL_TYPES)

    def test_unchecking_keeps_the_saved_color(self):
        """A type that already has a row keeps its color when unchecked."""
        UserCalendarPreference.objects.create(
            user=self.user, calendar_type="task", color="#123456", company=self.company
        )
        self._save(["event", "meeting", "unavailability"])

        task = self._row("task")
        self.assertFalse(task.is_selected)
        self.assertEqual(task.color, "#123456")

    def test_status_color_rows_are_left_alone(self):
        """Status colors aren't calendar types: no row is added or changed."""
        UserCalendarPreference.objects.create(
            user=self.user,
            calendar_type="status_completed",
            color="#123456",
            is_selected=False,
            company=self.company,
        )
        self._save(["task"])

        self.assertEqual(
            list(
                UserCalendarPreference.objects.filter(
                    user=self.user, calendar_type__startswith="status_"
                ).values_list("calendar_type", "color", "is_selected")
            ),
            [("status_completed", "#123456", False)],
        )

    def test_unchecking_my_calendars_unchecks_every_type(self):
        """With nothing checked, no type comes back and no event is fetched."""
        self._save([])

        self.assertEqual(self._checked(), [])
        self.assertEqual(self._event_types(), set())

        self._save(ALL_TYPES)
        self.assertEqual(self._checked(), ALL_TYPES)
        self.assertEqual(self._event_types(), set(ALL_TYPES))

    def test_events_without_types_count_a_type_without_a_row_as_checked(self):
        """The events fallback matches the sidebar, not just the saved rows."""
        UserCalendarPreference.objects.create(
            user=self.user, calendar_type="task", color="#123456", company=self.company
        )

        self.assertEqual(self._checked(), ALL_TYPES)
        self.assertEqual(self._event_types(), set(ALL_TYPES))

    def test_selection_is_saved_for_the_active_company(self):
        """Rows go to the active company; another company keeps its own."""
        other = Company.objects.create(
            name="Other", email="other@example.com", country="US"
        )
        session = self.client.session
        session["active_company_id"] = other.pk
        session.save()
        self._save(["event", "meeting", "unavailability"])

        self.assertEqual(self._checked(), ["event", "meeting", "unavailability"])
        self.assertEqual(self._row("task").company, other)

        session["active_company_id"] = self.company.pk
        session.save()
        self.assertEqual(self._checked(), ALL_TYPES)

    def test_display_this_only_sticks(self):
        """Display This Only on a type is still applied on the next load."""
        self.assertEqual(self._checked(display_only="task"), ["task"])
        self.assertEqual(self._checked(), ["task"])
        self.assertEqual(self._event_types(), {"task"})

    def test_display_this_only_on_a_custom_calendar_sticks(self):
        """Display This Only on a custom calendar unchecks every standard type."""
        custom = CustomCalendar.objects.create(
            user=self.user,
            name="Holidays",
            module=HorillaContentType.objects.get_for_model(Holiday),
            start_date_field="start_date",
            display_name_field="name",
            company=self.company,
        )

        self.assertEqual(self._checked(display_only=f"custom_{custom.pk}"), [])
        self.assertEqual(self._checked(), [])
        custom.refresh_from_db()
        self.assertTrue(custom.is_selected)
