"""
Tests for the Today page: whose activities show in which tab, the rows, and
mark as done with undo.
"""

# Standard library imports
import json
from datetime import datetime, time, timedelta
from unittest import skipUnless

# Third-party imports (Django)
from django.conf import settings
from django.test import override_settings
from django.utils import translation

from .base import MOBILE_INSTALLED, MobileTestBase

if MOBILE_INSTALLED:
    from horilla.contrib.activity.models import Activity
    from horilla.contrib.core.models import HorillaContentType
    from horilla.contrib.mobile.dates import user_now
    from horilla.contrib.mobile.utils import local_digits

    from .models import MobileTestRecord

URL = "/m/today/"


def status_url(activity):
    """Status url."""
    return f"/m/activities/{activity.pk}/status/"


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
@override_settings(ROOT_URLCONF="horilla.contrib.mobile.tests.urls")
class TodayTestBase(MobileTestBase):
    """The seller may view and change their own activities."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.grant(self.seller, Activity, "view_own", "change_own")
        self.record = self.make_record("Lead", owner=self.seller, phone="0912 345 6789")
        self.content_type = HorillaContentType.objects.get_for_model(MobileTestRecord)
        now = user_now(self.seller)
        self.now = now
        self.day = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)

    def activity(
        self, subject, kind="task", when=None, owner=None, record=None, **extra
    ):
        """Activity."""
        fields = {
            "subject": subject,
            "activity_type": kind,
            "owner": owner or self.seller,
            "company": self.company,
            "status": "not_started" if kind == "task" else "scheduled",
        }
        if record is not None:
            fields.update(content_type=self.content_type, object_id=record.pk)
        if kind == "task":
            fields["due_datetime"] = when
        else:
            fields["start_datetime"] = when
            fields["end_datetime"] = when + timedelta(hours=1) if when else None
        fields.update(extra)
        return Activity.objects.create(**fields)

    def titles(self, rows):
        """Titles."""
        return [row.title for row in rows]


class TodayTabsTests(TodayTestBase):
    """Which of the user's activities each tab lists."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.late = self.activity("Late task", when=self.day - timedelta(days=2))
        self.late_meeting = self.activity(
            "Missed meeting", "meeting", when=self.day - timedelta(days=1, hours=-10)
        )
        self.today = self.activity("Today's task", when=self.day + timedelta(hours=23))
        self.soon = self.activity(
            "Demo", "meeting", when=self.day + timedelta(days=2, hours=10)
        )
        self.far = self.activity("Far away", when=self.day + timedelta(days=20))
        # Not listed: closed, someone else's, a logged call.
        self.activity(
            "Cancelled", when=self.day - timedelta(days=1), status="cancelled"
        )
        self.activity(
            "Theirs", when=self.day + timedelta(hours=22), owner=self.other_seller
        )
        self.activity(
            "A call", "log_call", when=self.day + timedelta(hours=1), status="completed"
        )
        self.client.force_login(self.seller)

    def test_home_opens_today_as_the_first_tab(self):
        """Home opens today as the first tab."""
        self.assertRedirects(self.client.get("/m/"), URL, fetch_redirect_response=False)
        response = self.client.get(URL)
        labels = [str(item["label"]) for item in response.context["mobile_nav_items"]]
        self.assertEqual(labels, ["My work", "Agenda", "Records"])
        # The account page is behind the photo in the top bar, not a tab.
        self.assertContains(response, 'href="/m/more/"')
        self.assertContains(response, 'aria-label="Account"')
        # Today's date sits on the other side of the top bar.
        self.assertContains(response, f'<time datetime="{self.now.date().isoformat()}"')

    def test_today_lists_todays_open_activities(self):
        """Today lists todays open activities."""
        response = self.client.get(URL)
        self.assertEqual(self.titles(response.context["rows"]), ["Today's task"])
        self.assertEqual(response.context["counts"], {"overdue": 2, "today": 1})

    def test_overdue_includes_meetings_oldest_first(self):
        """Overdue includes meetings oldest first."""
        response = self.client.get(URL, {"tab": "overdue"})
        self.assertEqual(
            self.titles(response.context["rows"]), ["Late task", "Missed meeting"]
        )

    def test_upcoming_is_the_next_seven_days_grouped_by_day(self):
        """Upcoming is the next seven days grouped by day."""
        response = self.client.get(URL, {"tab": "upcoming"})
        days = response.context["days"]
        self.assertEqual(len(days), 1)
        self.assertEqual(self.titles(days[0]["rows"]), ["Demo"])

    def test_activities_the_user_is_assigned_to_are_their_own(self):
        """Activities the user is assigned to are their own."""
        theirs = self.activity(
            "Shared", when=self.day + timedelta(hours=21), owner=self.other_seller
        )
        theirs.assigned_to.add(self.seller)
        response = self.client.get(URL)
        self.assertIn("Shared", self.titles(response.context["rows"]))

    def test_tab_switch_returns_only_the_content(self):
        """Tab switch returns only the content."""
        response = self.client.get(URL, {"tab": "overdue"}, HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(response, "mobile/partials/today_content.html")
        self.assertTemplateNotUsed(response, "mobile/base.html")


class TodayRowTests(TodayTestBase):
    """What a row shows."""

    def test_row_shows_the_record_and_its_call_button(self):
        """Row shows the record and its call button."""
        self.activity(
            "Call back", when=self.day + timedelta(hours=23), record=self.record
        )
        self.client.force_login(self.seller)
        response = self.client.get(URL)
        row = response.context["rows"][0]
        self.assertEqual(row.record_name, "Lead")
        self.assertContains(response, 'href="tel:09123456789"')

    def test_a_record_the_user_cannot_open_is_not_shown(self):
        """A record the user cannot open is not shown."""
        theirs = self.make_record(
            "Theirs", owner=self.other_seller, phone="0912 000 0000"
        )
        self.activity(
            "About theirs", when=self.day + timedelta(hours=23), record=theirs
        )
        self.client.force_login(self.seller)
        response = self.client.get(URL)
        row = response.context["rows"][0]
        self.assertEqual((row.record_name, row.phone_href), ("", ""))

    def test_rows_open_the_details_sheet_with_a_link_to_the_record(self):
        """Rows open the details sheet with a link to the record."""
        task = self.activity(
            "Call back", when=self.day + timedelta(hours=23), record=self.record
        )
        self.client.force_login(self.seller)
        response = self.client.get(URL)
        self.assertContains(
            response, f'hx-get="/m/activities/{task.pk}/?from=today&amp;tab=today"'
        )
        sheet = self.client.get(
            f"/m/activities/{task.pk}/?from=today", HTTP_HX_REQUEST="true"
        )
        self.assertContains(sheet, "Open the record")


class MarkDoneTests(TodayTestBase):
    """Mark as done and undo, with the desktop's permission rules."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.task = self.activity(
            "Send the quote", when=self.day + timedelta(hours=23), status="in_progress"
        )

    def post(self, activity, status, tab="today"):
        """Post."""
        return self.client.post(status_url(activity), {"status": status, "tab": tab})

    def test_marking_done_moves_it_to_done_today_with_an_undo(self):
        """Marking done moves it to done today with an undo."""
        self.client.force_login(self.seller)
        response = self.post(self.task, "completed")
        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "completed")
        self.assertEqual(response.context["rows"], [])
        self.assertEqual(self.titles(response.context["done_rows"]), ["Send the quote"])
        toast = json.loads(response["HX-Trigger"])["mobileToast"]
        self.assertEqual(toast["undo"]["values"]["status"], "in_progress")
        self.assertEqual(toast["undo"]["values"]["tab"], "today")

    def test_undo_restores_the_previous_status(self):
        """Undo restores the previous status."""
        self.client.force_login(self.seller)
        self.post(self.task, "completed")
        response = self.post(self.task, "in_progress")
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "in_progress")
        self.assertNotIn("undo", json.loads(response["HX-Trigger"])["mobileToast"])

    def test_someone_elses_activity_cannot_be_changed(self):
        """Someone elses activity cannot be changed."""
        theirs = self.activity(
            "Theirs", when=self.day + timedelta(hours=23), owner=self.other_seller
        )
        self.client.force_login(self.seller)
        self.assertEqual(self.post(theirs, "completed").status_code, 404)
        theirs.refresh_from_db()
        self.assertEqual(theirs.status, "not_started")

    def test_user_without_change_permission_cannot_mark_done(self):
        """User without change permission cannot mark done."""
        viewer = self.make_user("viewer")
        self.grant(viewer, Activity, "view_own")
        task = self.activity("Mine", when=self.day + timedelta(hours=23), owner=viewer)
        self.client.force_login(viewer)
        self.assertEqual(self.post(task, "completed").status_code, 403)
        task.refresh_from_db()
        self.assertEqual(task.status, "not_started")

    def test_unknown_status_is_refused(self):
        """Unknown status is refused."""
        self.client.force_login(self.seller)
        self.assertEqual(self.post(self.task, "finished").status_code, 400)


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
class LocalDigitsTests(TodayTestBase):
    """Counts are written in the language's own digits, like the dates."""

    def test_persian_arabic_and_latin_digits(self):
        """Persian arabic and latin digits."""
        with translation.override("fa"):
            self.assertEqual(local_digits(1405), "۱۴۰۵")
        with translation.override("ar"):
            self.assertEqual(local_digits(12), "١٢")
        with translation.override("en"):
            self.assertEqual(local_digits(12), "12")

    def test_the_tab_counts_in_persian(self):
        """The tab counts in persian."""
        self.activity("Late task", when=self.day - timedelta(days=2))
        self.activity("Another", when=self.day - timedelta(days=3))
        self.client.force_login(self.seller)
        self.client.cookies.load({settings.LANGUAGE_COOKIE_NAME: "fa"})
        response = self.client.get(URL)
        self.assertEqual(response.context["counts"]["overdue"], 2)
        self.assertContains(response, ">۲</span>")
