"""
Tests for the details of an activity or note, opened from a record page's
interactions as a bottom sheet (or as a page).
"""

# Standard library imports
from unittest import skipUnless

# Third-party imports (Django)
from django.test import override_settings

from .base import MOBILE_INSTALLED, MobileTestBase

if MOBILE_INSTALLED:
    from horilla.contrib.activity.models import Activity
    from horilla.contrib.core.models import HorillaAttachment, HorillaContentType

    from .models import MobileTestRecord

HTMX = {"HTTP_HX_REQUEST": "true"}


def record_url(record):
    """Record url."""
    return f"/m/records/mobile/mobiletestrecord/{record.pk}/"


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
@override_settings(ROOT_URLCONF="horilla.contrib.mobile.tests.urls")
class DetailTestBase(MobileTestBase):
    """A seller's record with a logged call and a note on it."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.grant(self.seller, Activity, "view_own")
        self.record = self.make_record("Lead", owner=self.seller)
        self.content_type = HorillaContentType.objects.get_for_model(MobileTestRecord)
        self.call = self.activity(
            "Asked for a discount",
            self.seller,
            activity_type="log_call",
            status="waiting",
            call_type="outbound",
            call_purpose="Pricing",
            notes="Call back next week.",
        )
        self.note = HorillaAttachment.objects.create(
            title="Decision maker",
            description="The CEO decides.",
            content_type=self.content_type,
            object_id=self.record.pk,
            company=self.company,
            created_by=self.seller,
        )

    def activity(self, subject, owner, record=None, **fields):
        """Activity."""
        return Activity.objects.create(
            subject=subject,
            owner=owner,
            content_type=self.content_type,
            object_id=(record or self.record).pk,
            company=self.company,
            **fields,
        )


class ActivityDetailTests(DetailTestBase):
    """An activity shows what was saved on it, to those who may view it."""

    def test_the_sheet_shows_everything_entered_and_skips_empty_fields(self):
        """The sheet shows everything entered and skips empty fields."""
        self.client.force_login(self.seller)
        response = self.client.get(f"/m/activities/{self.call.pk}/", **HTMX)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "mobile/partials/detail_sheet_body.html")
        self.assertTemplateNotUsed(response, "mobile/base.html")
        for value in ("Asked for a discount", "Waiting on Someone", "Outbound"):
            self.assertContains(response, value)
        self.assertContains(response, "Pricing")
        self.assertContains(response, "Call back next week.")
        # Left empty on the phone, so not listed.
        self.assertNotContains(response, "Call Duration")

    def test_yes_no_fields_read_yes_or_no(self):
        """Yes no fields read yes or no."""
        meeting = self.activity(
            "Kick-off",
            self.seller,
            activity_type="meeting",
            status="completed",
            is_all_day=False,
            is_online=True,
        )
        self.client.force_login(self.seller)
        response = self.client.get(f"/m/activities/{meeting.pk}/", **HTMX)
        self.assertContains(response, "<bdi>Yes</bdi>")
        self.assertContains(response, "<bdi>No</bdi>")
        self.assertNotContains(response, "False")
        self.assertNotContains(response, "True")

    def test_status_leads_and_the_header_fields_are_not_repeated(self):
        # The desktop shows the status as its stage bar, outside the field list.
        """Status leads and the header fields are not repeated."""
        self.client.force_login(self.seller)
        response = self.client.get(f"/m/activities/{self.call.pk}/", **HTMX)
        names = [name for _label, name in response.context["fields"]]
        self.assertEqual(names[0], "status")
        self.assertNotIn("subject", names)
        self.assertNotIn("activity_type", names)
        self.assertIn("call_type", names)
        self.assertIn("notes", names)

    def test_opened_directly_it_is_a_page_back_to_the_record(self):
        """Opened directly it is a page back to the record."""
        self.client.force_login(self.seller)
        response = self.client.get(f"/m/activities/{self.call.pk}/")
        self.assertTemplateUsed(response, "mobile/detail_page.html")
        self.assertEqual(response.context["back_url"], record_url(self.record))
        self.assertNotContains(response, "data-close-dialog")

    def test_someone_elses_activity_is_not_shown(self):
        """Someone elses activity is not shown."""
        theirs = self.activity(
            "Private call", self.other_seller, activity_type="log_call"
        )
        self.client.force_login(self.seller)
        response = self.client.get(f"/m/activities/{theirs.pk}/", **HTMX)
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "mobile/unavailable.html")
        self.assertNotContains(response, "Private call", status_code=404)

    def test_without_activity_permission_nothing_is_shown(self):
        """Without activity permission nothing is shown."""
        viewer = self.make_user("viewer")
        self.grant(viewer, MobileTestRecord, "view")
        self.client.force_login(viewer)
        response = self.client.get(f"/m/activities/{self.call.pk}/")
        self.assertEqual(response.status_code, 404)

    def test_missing_activity_is_not_found(self):
        """Missing activity is not found."""
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get("/m/activities/999999/").status_code, 404)


class NoteDetailTests(DetailTestBase):
    """A note shows its full text to those who may open its record."""

    def test_the_sheet_shows_the_text_and_who_added_it(self):
        """The sheet shows the text and who added it."""
        self.client.force_login(self.seller)
        response = self.client.get(f"/m/notes/{self.note.pk}/", **HTMX)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Decision maker")
        self.assertContains(response, "The CEO decides.")
        self.assertContains(response, "Added by")
        self.assertEqual(response.context["parent_url"], record_url(self.record))

    def test_note_on_a_record_the_user_cannot_open_is_not_shown(self):
        """Note on a record the user cannot open is not shown."""
        self.client.force_login(self.other_seller)
        response = self.client.get(f"/m/notes/{self.note.pk}/", **HTMX)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "The CEO decides.", status_code=404)

    def test_missing_note_is_not_found(self):
        """Missing note is not found."""
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get("/m/notes/999999/").status_code, 404)


class TimelineRowTests(DetailTestBase):
    """Rows show what was entered and open the details sheet."""

    def test_rows_open_the_details_sheet(self):
        """Rows open the details sheet."""
        self.client.force_login(self.seller)
        response = self.client.get(record_url(self.record))
        self.assertContains(response, 'id="detail-sheet"')
        self.assertContains(response, f'hx-get="/m/activities/{self.call.pk}/"')
        self.assertContains(response, f'hx-get="/m/notes/{self.note.pk}/"')

    def test_a_call_row_shows_its_status_and_notes_only(self):
        # Call type and purpose are in the details sheet.
        """A call row shows its status and notes only."""
        self.client.force_login(self.seller)
        response = self.client.get(record_url(self.record))
        row = next(
            row for row in response.context["interactions"] if row.obj == self.call
        )
        self.assertEqual(row.status, "Waiting on Someone")
        self.assertEqual(row.detail, "Call back next week.")

    def test_a_task_row_leaves_out_the_starting_status(self):
        """A task row leaves out the starting status."""
        task = self.activity(
            "Send the quote",
            self.seller,
            activity_type="task",
            status="not_started",
            task_priority="high",
        )
        self.client.force_login(self.seller)
        response = self.client.get(record_url(self.record))
        row = next(
            row for row in response.context["open_activities"] if row.obj == task
        )
        self.assertEqual(row.status, "")
