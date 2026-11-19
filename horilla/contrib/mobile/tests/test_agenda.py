"""
Tests for the Agenda (the user's days, week strip, unavailability and type
filter) and for adding and editing meetings, events and tasks there and on
a record page.
"""

# Standard library imports
import json
from datetime import datetime, time, timedelta
from unittest import mock, skipUnless

# Third-party imports (Django)
from django.test import override_settings
from django.utils import translation

from .base import MOBILE_INSTALLED
from .test_log_activity import LogActivityTestBase, log_url, record_url

if MOBILE_INSTALLED:
    from horilla.contrib.activity.models import Activity
    from horilla.contrib.calendar.models import UserAvailability, UserCalendarPreference
    from horilla.contrib.mobile.agenda import week_start
    from horilla.contrib.mobile.dates import user_now

URL = "/m/agenda/"
# Where the desktop meeting view sends the invitations.
INVITES = "horilla.contrib.activity.views.create_view.meeting.send_meeting_invites"


def agenda_url(day):
    """Agenda url."""
    return f"{URL}?date={day.isoformat()}"


def new_url(kind, day):
    """New url."""
    return f"/m/agenda/new/{kind}/?date={day.isoformat()}"


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
@override_settings(ROOT_URLCONF="horilla.contrib.mobile.tests.urls")
class AgendaTestBase(LogActivityTestBase):
    """A seller who may view, change and add their own activities, and a day two weeks ahead."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.grant(self.seller, Activity, "view_own", "change_own", "add_own")
        now = user_now(self.seller)
        self.day = now.date() + timedelta(days=14)
        self.midnight = datetime.combine(self.day, time.min, tzinfo=now.tzinfo)

    def at(self, hours, days=0):
        """A time on the test day (or ``days`` from it)."""
        return self.midnight + timedelta(days=days, hours=hours)

    def activity(self, subject, kind, start, end=None, owner=None, **extra):
        """Activity."""
        fields = {
            "subject": subject,
            "activity_type": kind,
            "owner": owner or self.seller,
            "company": self.company,
            "status": "not_started" if kind == "task" else "scheduled",
        }
        if kind == "task":
            fields["due_datetime"] = start
        else:
            fields["start_datetime"] = start
            fields["end_datetime"] = end
        fields.update(extra)
        return Activity.objects.create(**fields)

    def titles(self, items):
        """Titles."""
        return [item["row"].title for item in items if item["kind"] == "activity"]


class AgendaDayTests(AgendaTestBase):
    """What a day shows."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.activity("Call the bank", "task", self.at(10))
        self.activity("Demo", "meeting", self.at(9), self.at(10))
        self.activity(
            "Trade fair", "event", self.at(0), self.at(23.98), is_all_day=True
        )
        self.activity("Conference", "event", self.at(10, days=-1), self.at(12, days=1))
        self.activity("Late dinner", "meeting", self.at(22, days=-1), self.at(8))
        # Not listed: cancelled, someone else's, and a logged call.
        self.activity(
            "Cancelled", "meeting", self.at(11), self.at(12), status="cancelled"
        )
        self.activity("Theirs", "task", self.at(11), owner=self.other_seller)
        self.activity("A call", "log_call", self.at(11), status="completed")
        self.client.force_login(self.seller)

    def test_all_day_and_running_over_first_then_by_time(self):
        """All day and running over first then by time."""
        response = self.client.get(agenda_url(self.day))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(self.titles(response.context["all_day_items"])),
            {"Trade fair", "Conference", "Late dinner"},
        )
        self.assertEqual(
            self.titles(response.context["timed_items"]), ["Demo", "Call the bank"]
        )

    def test_a_meeting_from_the_night_before_shows_until_when(self):
        """A meeting from the night before shows until when."""
        response = self.client.get(agenda_url(self.day))
        row = next(
            item["row"]
            for item in response.context["all_day_items"]
            if item["row"].title == "Late dinner"
        )
        self.assertTrue(row.when.startswith("Until "))

    def test_the_week_strip_marks_the_days_with_dots(self):
        """The week strip marks the days with dots."""
        response = self.client.get(agenda_url(self.day))
        week = response.context["week"]
        self.assertEqual(len(week), 7)
        picked = next(day for day in week if day["is_selected"])
        self.assertEqual(picked["date"], self.day)
        self.assertEqual(len(picked["colors"]), 3)  # meeting, event, task

    def test_unavailability_shows_in_grey_and_only_the_users_own(self):
        """Unavailability shows in grey and only the users own."""
        UserAvailability.objects.create(
            user=self.seller,
            from_datetime=self.at(13),
            to_datetime=self.at(14),
            reason="Dentist",
            company=self.company,
        )
        UserAvailability.objects.create(
            user=self.other_seller,
            from_datetime=self.at(15),
            to_datetime=self.at(16),
            reason="Theirs",
            company=self.company,
        )
        response = self.client.get(agenda_url(self.day))
        blocked = [
            item["row"].reason
            for item in response.context["timed_items"]
            if item["kind"] == "unavailable"
        ]
        self.assertEqual(blocked, ["Dentist"])
        self.assertContains(response, "Dentist")

    def test_the_desktop_type_filter_applies(self):
        """The desktop type filter applies."""
        UserCalendarPreference.objects.create(
            user=self.seller,
            calendar_type="task",
            color="#3B82F6",
            is_selected=False,
            company=self.company,
        )
        response = self.client.get(agenda_url(self.day))
        self.assertEqual(self.titles(response.context["timed_items"]), ["Demo"])
        self.assertTrue(response.context["filter_active"])
        self.assertContains(response, "data-calendar-filter")

    def test_moving_between_days_returns_only_the_content(self):
        """Moving between days returns only the content."""
        response = self.client.get(
            agenda_url(self.day + timedelta(days=1)), HTTP_HX_REQUEST="true"
        )
        self.assertTemplateUsed(response, "mobile/partials/agenda_content.html")
        self.assertTemplateNotUsed(response, "mobile/base.html")

    def test_a_date_that_isnt_one_shows_today(self):
        """A date that isnt one shows today."""
        response = self.client.get(URL, {"date": "soon"})
        self.assertEqual(response.context["day"], user_now(self.seller).date())
        # The top bar shows the date; the day's title just says so.
        self.assertEqual(response.context["day_title"], "Today")

    def test_mark_done_on_the_agenda_refreshes_the_agenda(self):
        """Mark done on the agenda refreshes the agenda."""
        demo = Activity.objects.get(subject="Demo")
        response = self.client.post(
            f"/m/activities/{demo.pk}/status/",
            {"status": "completed", "view": "agenda", "date": self.day.isoformat()},
        )
        self.assertTemplateUsed(response, "mobile/partials/agenda_content.html")
        undo = json.loads(response["HX-Trigger"])["mobileToast"]["undo"]
        self.assertEqual(
            undo["values"],
            {"view": "agenda", "date": self.day.isoformat(), "status": "scheduled"},
        )


class WeekStartTests(AgendaTestBase):
    """The week starts on the language's first day."""

    def test_saturday_in_persian_and_sunday_in_english(self):
        """Saturday in persian and sunday in english."""
        with translation.override("fa"):
            self.assertEqual(week_start(self.day).weekday(), 5)
        with translation.override("en"):
            self.assertEqual(week_start(self.day).weekday(), 6)


class AgendaAddTests(AgendaTestBase):
    """Adding a task, an event or a meeting on the picked day."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.client.force_login(self.seller)

    def stamp(self, hours):
        """Stamp."""
        return self.at(hours).strftime("%Y-%m-%dT%H:%M")

    def test_adding_needs_the_add_permission(self):
        """Adding needs the add permission."""
        viewer = self.make_user("viewer")
        self.grant(viewer, Activity, "view_own", "change_own")
        self.client.force_login(viewer)
        response = self.client.get(agenda_url(self.day))
        self.assertNotContains(response, 'data-open-dialog="add-sheet"')
        self.assertEqual(self.client.get(new_url("task", self.day)).status_code, 403)

    def test_a_logged_call_is_not_added_from_the_agenda(self):
        """A logged call is not added from the agenda."""
        self.assertEqual(self.client.get(new_url("call", self.day)).status_code, 404)

    def test_new_forms_start_on_the_picked_day(self):
        """New forms start on the picked day."""
        response = self.client.get(new_url("meeting", self.day))
        self.assertEqual(
            response.context["form"].initial["start_datetime"], self.stamp(9)
        )
        self.assertEqual(
            response.context["form"].initial["end_datetime"], self.stamp(10)
        )

    def test_a_task_from_the_agenda_belongs_to_no_record(self):
        """A task from the agenda belongs to no record."""
        response = self.client.post(
            new_url("task", self.day),
            {
                "subject": "Send the quote",
                "due_datetime": self.stamp(16),
                "task_priority": "high",
                "status": "not_started",
            },
        )
        self.assertRedirects(
            response, agenda_url(self.day), fetch_redirect_response=False
        )
        task = Activity.objects.get(subject="Send the quote")
        self.assertEqual(task.activity_type, "task")
        self.assertIsNone(task.content_type)
        self.assertEqual(task.owner, self.seller)

    def test_an_event_from_the_agenda(self):
        """An event from the agenda."""
        self.client.post(
            new_url("event", self.day),
            {
                "subject": "Trade fair",
                "start_datetime": self.stamp(9),
                "end_datetime": self.stamp(17),
                "location": "Hall 3",
                "status": "scheduled",
            },
        )
        self.assertTrue(
            Activity.objects.filter(
                subject="Trade fair", activity_type="event"
            ).exists()
        )

    def test_a_meeting_goes_through_the_desktop_meeting_save(self):
        """A meeting goes through the desktop meeting save."""
        with mock.patch(INVITES) as invites:
            response = self.client.post(
                new_url("meeting", self.day),
                {
                    "subject": "Kick-off",
                    "start_datetime": self.stamp(10),
                    "end_datetime": self.stamp(11),
                    "location": "Office",
                    "status": "scheduled",
                    "participants": [self.other_seller.pk],
                    "external_participants_email": "guest@example.com",
                },
            )
        self.assertRedirects(
            response, agenda_url(self.day), fetch_redirect_response=False
        )
        meeting = Activity.objects.get(subject="Kick-off")
        self.assertEqual(meeting.activity_type, "meeting")
        self.assertEqual(list(meeting.participants.all()), [self.other_seller])
        self.assertEqual(meeting.external_participants, ["guest@example.com"])
        recipients = invites.call_args.args[2]
        self.assertIn("guest@example.com", recipients)
        self.assertIn(self.other_seller.email, recipients)

    def test_an_in_person_meeting_needs_a_location(self):
        """An in person meeting needs a location."""
        response = self.client.post(
            new_url("meeting", self.day),
            {
                "subject": "Nowhere",
                "start_datetime": self.stamp(10),
                "end_datetime": self.stamp(11),
                "status": "scheduled",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors.get("location"))
        self.assertFalse(Activity.objects.filter(subject="Nowhere").exists())

    def test_ticking_all_day_redraws_the_form_without_saving(self):
        """Ticking all day redraws the form without saving."""
        response = self.client.post(
            new_url("meeting", self.day),
            {
                "mobile_toggle": "1",
                "is_all_day": "on",
                "subject": "Kick-off",
                "start_datetime": self.stamp(10),
                "end_datetime": self.stamp(11),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Activity.objects.exists())
        form = response.context["form"]
        self.assertFalse(form.is_bound)
        self.assertEqual(form.fields["start_datetime"].widget.input_type, "date")
        self.assertContains(response, 'value="Kick-off"')

    def test_ticking_online_drops_the_location(self):
        """Ticking online drops the location."""
        response = self.client.post(
            new_url("meeting", self.day),
            {"mobile_toggle": "1", "is_online": "on", "subject": "Call"},
        )
        names = [field.name for field in response.context["shown_fields"]]
        self.assertNotIn("location", names)
        self.assertNotIn("is_all_day", names)

    def test_signed_out_visitors_go_to_the_mobile_login(self):
        """Signed out visitors go to the mobile login."""
        self.client.logout()
        response = self.client.get(new_url("meeting", self.day))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/m/login/", response["Location"])


class RecordMeetingTests(AgendaTestBase):
    """Meetings and events from a record page, and editing a meeting."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.client.force_login(self.seller)

    def test_the_log_activity_sheet_offers_meetings_and_events(self):
        """The log activity sheet offers meetings and events."""
        response = self.client.get(record_url(self.record))
        self.assertContains(response, f'href="{log_url(self.record, "meeting")}"')
        self.assertContains(response, f'href="{log_url(self.record, "event")}"')

    def test_a_meeting_on_a_record(self):
        """A meeting on a record."""
        stamp = self.at(10).strftime("%Y-%m-%dT%H:%M")
        with mock.patch(INVITES):
            response = self.client.post(
                log_url(self.record, "meeting"),
                {
                    "subject": "Site visit",
                    "start_datetime": stamp,
                    "end_datetime": self.at(11).strftime("%Y-%m-%dT%H:%M"),
                    "location": "Their office",
                    "status": "scheduled",
                },
            )
        self.assertRedirects(
            response, record_url(self.record), fetch_redirect_response=False
        )
        meeting = Activity.objects.get(subject="Site visit")
        self.assertEqual(meeting.object_id, self.record.pk)
        self.assertEqual(meeting.content_type_id, self.content_type.pk)

    def test_editing_a_meeting_keeps_what_the_phone_doesnt_show(self):
        """Editing a meeting keeps what the phone doesnt show."""
        meeting = self.activity(
            "Kick-off",
            "meeting",
            self.at(10),
            self.at(11),
            location="Office",
            meeting_host=self.other_seller,
            external_participants=["guest@example.com"],
            content_type=self.content_type,
            object_id=self.record.pk,
        )
        with mock.patch(INVITES):
            response = self.client.post(
                f"/m/activities/{meeting.pk}/edit/",
                {
                    "subject": "Kick-off, moved",
                    "start_datetime": self.at(12).strftime("%Y-%m-%dT%H:%M"),
                    "end_datetime": self.at(13).strftime("%Y-%m-%dT%H:%M"),
                    "location": "Office",
                    "status": "scheduled",
                    "external_participants_email": "guest@example.com",
                    "meeting_host": self.seller.pk,
                },
            )
        self.assertRedirects(
            response, record_url(self.record), fetch_redirect_response=False
        )
        meeting.refresh_from_db()
        self.assertEqual(meeting.subject, "Kick-off, moved")
        self.assertEqual(meeting.meeting_host, self.other_seller)
        self.assertEqual(meeting.external_participants, ["guest@example.com"])
