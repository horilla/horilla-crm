"""
Tests for logging a call, adding a task and adding a note from a record's
phone page, with the desktop forms.
"""

# Standard library imports
from datetime import timedelta
from unittest import skipUnless

# Third-party imports (Django)
from django.test import override_settings

# First party imports (Horilla)
from horilla.registry.feature import FEATURE_REGISTRY, register_model_for_feature
from horilla.utils import timezone

from .base import MOBILE_INSTALLED, MobileTestBase

if MOBILE_INSTALLED:
    from horilla.contrib.activity.models import Activity
    from horilla.contrib.core.models import HorillaAttachment, HorillaContentType

    from .models import MobileTestRecord

ACTIVITY_FEATURE_KEY = "activity_related_models"


def log_url(record, kind):
    """Log url."""
    return f"/m/records/mobile/mobiletestrecord/{record.pk}/log/{kind}/"


def note_url(record):
    """Note url."""
    return f"/m/records/mobile/mobiletestrecord/{record.pk}/note/"


def record_url(record):
    """Record url."""
    return f"/m/records/mobile/mobiletestrecord/{record.pk}/"


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
@override_settings(ROOT_URLCONF="horilla.contrib.mobile.tests.urls")
class LogActivityTestBase(MobileTestBase):
    """The test model accepts activities, like a CRM record does."""

    @classmethod
    def setUpClass(cls):
        """SetUpClass."""
        super().setUpClass()
        register_model_for_feature(
            model_class=MobileTestRecord, features=[ACTIVITY_FEATURE_KEY]
        )

    @classmethod
    def tearDownClass(cls):
        """TearDownClass."""
        registered = FEATURE_REGISTRY[ACTIVITY_FEATURE_KEY]
        if MobileTestRecord in registered:
            registered.remove(MobileTestRecord)
        super().tearDownClass()

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.record = self.make_record("Lead", owner=self.seller)
        self.content_type = HorillaContentType.objects.get_for_model(MobileTestRecord)


class LogActivityAccessTests(LogActivityTestBase):
    """Who gets the Log activity button and the forms."""

    def test_owner_with_change_own_gets_the_button_and_the_forms(self):
        """Owner with change own gets the button and the forms."""
        self.client.force_login(self.seller)
        response = self.client.get(record_url(self.record))
        self.assertContains(response, 'data-open-dialog="log-sheet"')
        for url in (
            log_url(self.record, "call"),
            log_url(self.record, "task"),
            note_url(self.record),
        ):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_read_only_user_gets_neither(self):
        """Read only user gets neither."""
        viewer = self.make_user("viewer")
        self.grant(viewer, MobileTestRecord, "view")
        self.client.force_login(viewer)
        response = self.client.get(record_url(self.record))
        self.assertNotContains(response, 'data-open-dialog="log-sheet"')
        response = self.client.get(log_url(self.record, "call"))
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "mobile/unavailable.html")
        response = self.client.post(note_url(self.record), {"title": "Nope"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(HorillaAttachment.objects.exists())

    def test_someone_elses_record_is_refused(self):
        """Someone elses record is refused."""
        theirs = self.make_record("Theirs", owner=self.other_seller)
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get(log_url(theirs, "task")).status_code, 403)

    def test_unknown_kind_is_not_found(self):
        """Unknown kind is not found."""
        self.client.force_login(self.seller)
        self.assertEqual(
            self.client.get(log_url(self.record, "lunch")).status_code, 404
        )


class LogCallTests(LogActivityTestBase):
    """Log a call with LogCallForm."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.client.force_login(self.seller)

    def test_form_shows_the_short_field_list_and_hides_the_record_and_owner(self):
        """Form shows the short field list and hides the record and owner."""
        response = self.client.get(log_url(self.record, "call"))
        names = [field.name for field in response.context["shown_fields"]]
        self.assertIn("subject", names)
        self.assertIn("call_type", names)
        for hidden in ("object_id", "content_type", "activity_type", "owner"):
            self.assertNotIn(hidden, names)

    def test_valid_call_is_saved_on_the_record_and_returns_to_it(self):
        """Valid call is saved on the record and returns to it."""
        response = self.client.post(
            log_url(self.record, "call"),
            {
                "subject": "Asked for a discount",
                "call_type": "outbound",
                "status": "completed",
                "notes": "Call back next week.",
            },
        )
        self.assertRedirects(
            response, record_url(self.record), fetch_redirect_response=False
        )
        call = Activity.objects.get(subject="Asked for a discount")
        self.assertEqual(call.activity_type, "log_call")
        self.assertEqual(call.content_type_id, self.content_type.pk)
        self.assertEqual(call.object_id, self.record.pk)
        self.assertEqual(call.owner, self.seller)
        self.assertEqual(call.created_by, self.seller)
        self.assertEqual(call.company, self.company)

    def test_posted_record_fields_cannot_point_elsewhere(self):
        """Posted record fields cannot point elsewhere."""
        theirs = self.make_record("Theirs", owner=self.other_seller)
        self.client.post(
            log_url(self.record, "call"),
            {
                "subject": "Tampered",
                "call_type": "outbound",
                "status": "completed",
                "object_id": theirs.pk,
                "activity_type": "meeting",
            },
        )
        call = Activity.objects.get(subject="Tampered")
        self.assertEqual(call.object_id, self.record.pk)
        self.assertEqual(call.activity_type, "log_call")

    def test_missing_subject_shows_the_error_and_saves_nothing(self):
        """Missing subject shows the error and saves nothing."""
        response = self.client.post(
            log_url(self.record, "call"),
            {"call_type": "outbound", "status": "completed"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "mobile/log_activity.html")
        self.assertTrue(response.context["form"].errors.get("subject"))
        self.assertFalse(Activity.objects.exists())


class AddTaskTests(LogActivityTestBase):
    """Add a task with TaskForm, including its own rules."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.client.force_login(self.seller)

    def due(self, delta):
        """Due."""
        return (timezone.localtime() + delta).strftime("%Y-%m-%dT%H:%M")

    def test_task_with_a_future_due_date_is_saved(self):
        """Task with a future due date is saved."""
        self.client.post(
            log_url(self.record, "task"),
            {
                "subject": "Send the quote",
                "due_datetime": self.due(timedelta(days=1)),
                "task_priority": "high",
                "status": "not_started",
            },
        )
        task = Activity.objects.get(subject="Send the quote")
        self.assertEqual(task.activity_type, "task")
        self.assertEqual(task.object_id, self.record.pk)

    def test_the_forms_own_rules_apply(self):
        # TaskForm refuses a due date in the past; the phone doesn't skip it.
        """The forms own rules apply."""
        response = self.client.post(
            log_url(self.record, "task"),
            {
                "subject": "Too late",
                "due_datetime": self.due(-timedelta(days=2)),
                "task_priority": "high",
                "status": "not_started",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Activity.objects.filter(subject="Too late").exists())


class AddNoteTests(LogActivityTestBase):
    """Add a text note through the desktop notes form."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.client.force_login(self.seller)

    def test_note_is_saved_on_the_record(self):
        """Note is saved on the record."""
        response = self.client.post(
            note_url(self.record),
            {"title": "Decision maker", "description": "The CEO decides."},
        )
        self.assertRedirects(
            response, record_url(self.record), fetch_redirect_response=False
        )
        note = HorillaAttachment.objects.get(title="Decision maker")
        self.assertEqual(note.object_id, self.record.pk)
        self.assertEqual(note.content_type_id, self.content_type.pk)
        self.assertEqual(note.company, self.company)
        self.assertEqual(note.created_by, self.seller)
        self.assertEqual(note.description, "The CEO decides.")

    def test_note_form_has_no_file_field_and_a_plain_text_box(self):
        """Note form has no file field and a plain text box."""
        response = self.client.get(note_url(self.record))
        names = [field.name for field in response.context["shown_fields"]]
        self.assertEqual(names, ["title", "description"])
        self.assertContains(response, "<textarea")

    def test_missing_title_shows_the_error(self):
        """Missing title shows the error."""
        response = self.client.post(note_url(self.record), {"description": "No title"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors.get("title"))
        self.assertFalse(HorillaAttachment.objects.exists())


class EditActivityTests(LogActivityTestBase):
    """Edit a logged call or a task from its details sheet."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.grant(self.seller, Activity, "view_own", "change_own")
        self.call = Activity.objects.create(
            subject="First call",
            activity_type="log_call",
            status="completed",
            call_type="outbound",
            description="Kept as it was.",
            owner=self.seller,
            content_type=self.content_type,
            object_id=self.record.pk,
            company=self.company,
        )
        self.url = f"/m/activities/{self.call.pk}/edit/"

    def test_owner_gets_the_pencil_and_the_filled_in_form(self):
        """Owner gets the pencil and the filled in form."""
        self.client.force_login(self.seller)
        sheet = self.client.get(
            f"/m/activities/{self.call.pk}/", HTTP_HX_REQUEST="true"
        )
        self.assertContains(sheet, f'href="{self.url}"')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_title"], "Edit call")
        self.assertContains(response, 'value="First call"')

    def test_saving_changes_the_shown_fields_and_keeps_the_rest(self):
        """Saving changes the shown fields and keeps the rest."""
        theirs = self.make_record("Theirs", owner=self.other_seller)
        self.client.force_login(self.seller)
        response = self.client.post(
            self.url,
            {
                "subject": "Second try",
                "call_type": "inbound",
                "status": "completed",
                "notes": "They called back.",
                "object_id": theirs.pk,
                "activity_type": "meeting",
                "description": "Overwritten?",
                "owner": self.other_seller.pk,
            },
        )
        self.assertRedirects(
            response, record_url(self.record), fetch_redirect_response=False
        )
        self.call.refresh_from_db()
        self.assertEqual(self.call.subject, "Second try")
        self.assertEqual(self.call.call_type, "inbound")
        self.assertEqual(self.call.notes, "They called back.")
        # Not on the phone form: saved values stay, posted ones are ignored.
        self.assertEqual(self.call.description, "Kept as it was.")
        self.assertEqual(self.call.object_id, self.record.pk)
        self.assertEqual(self.call.activity_type, "log_call")
        self.assertEqual(self.call.owner, self.seller)

    def test_user_who_may_only_view_gets_no_pencil_and_cannot_post(self):
        """User who may only view gets no pencil and cannot post."""
        viewer = self.make_user("viewer")
        self.grant(viewer, Activity, "view")
        self.client.force_login(viewer)
        sheet = self.client.get(
            f"/m/activities/{self.call.pk}/", HTTP_HX_REQUEST="true"
        )
        self.assertNotContains(sheet, f'href="{self.url}"')
        response = self.client.post(self.url, {"subject": "Nope"})
        self.assertEqual(response.status_code, 403)
        self.call.refresh_from_db()
        self.assertEqual(self.call.subject, "First call")

    def test_someone_elses_activity_is_not_found(self):
        """Someone elses activity is not found."""
        self.client.force_login(self.other_seller)
        self.grant(self.other_seller, Activity, "view_own", "change_own")
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_meetings_get_the_pencil_too(self):
        """Meetings get the pencil too."""
        meeting = Activity.objects.create(
            subject="Kick-off",
            activity_type="meeting",
            owner=self.seller,
            content_type=self.content_type,
            object_id=self.record.pk,
            company=self.company,
        )
        self.client.force_login(self.seller)
        url = f"/m/activities/{meeting.pk}/edit/"
        self.assertEqual(self.client.get(url).status_code, 200)
        sheet = self.client.get(f"/m/activities/{meeting.pk}/", HTTP_HX_REQUEST="true")
        self.assertContains(sheet, f'href="{url}"')

    def test_edit_opened_from_my_work_returns_there(self):
        """Edit opened from my work returns there."""
        self.client.force_login(self.seller)
        sheet = self.client.get(
            f"/m/activities/{self.call.pk}/?from=today&tab=overdue",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(sheet, "next=%2Fm%2Ftoday%2F%3Ftab%3Doverdue")
        response = self.client.post(
            self.url,
            {
                "subject": "Second try",
                "call_type": "inbound",
                "status": "completed",
                "next": "/m/today/?tab=overdue",
            },
        )
        self.assertRedirects(
            response, "/m/today/?tab=overdue", fetch_redirect_response=False
        )

    def test_a_next_outside_the_phone_pages_is_ignored(self):
        """A next outside the phone pages is ignored."""
        self.client.force_login(self.seller)
        for next_url in ("https://example.com/", "/settings/"):
            response = self.client.post(
                self.url,
                {
                    "subject": "Second try",
                    "call_type": "inbound",
                    "status": "completed",
                    "next": next_url,
                },
            )
            self.assertRedirects(
                response, record_url(self.record), fetch_redirect_response=False
            )


class EditNoteTests(LogActivityTestBase):
    """Edit a note from its details sheet, with the desktop note rule."""

    def note(self, created_by):
        """Note."""
        return HorillaAttachment.objects.create(
            title="Decision maker",
            description="The CEO decides.",
            content_type=self.content_type,
            object_id=self.record.pk,
            company=self.company,
            created_by=created_by,
        )

    def test_author_edits_the_title_and_text(self):
        """Author edits the title and text."""
        note = self.note(self.seller)
        self.client.force_login(self.seller)
        response = self.client.post(
            f"/m/notes/{note.pk}/edit/",
            {"title": "Decision makers", "description": "The CEO and the CFO."},
        )
        self.assertRedirects(
            response, record_url(self.record), fetch_redirect_response=False
        )
        note.refresh_from_db()
        self.assertEqual(note.title, "Decision makers")
        self.assertEqual(note.description, "The CEO and the CFO.")
        self.assertEqual(note.object_id, self.record.pk)

    def test_change_own_user_cannot_edit_someone_elses_note(self):
        # The record is the seller's, the note another seller's.
        """Change own user cannot edit someone elses note."""
        note = self.note(self.other_seller)
        self.client.force_login(self.seller)
        sheet = self.client.get(f"/m/notes/{note.pk}/", HTTP_HX_REQUEST="true")
        self.assertNotContains(sheet, f"/m/notes/{note.pk}/edit/")
        response = self.client.post(
            f"/m/notes/{note.pk}/edit/", {"title": "Changed", "description": ""}
        )
        self.assertEqual(response.status_code, 403)
        note.refresh_from_db()
        self.assertEqual(note.title, "Decision maker")

    def test_note_on_a_record_the_user_cannot_open_is_not_found(self):
        """Note on a record the user cannot open is not found."""
        note = self.note(self.seller)
        self.client.force_login(self.other_seller)
        response = self.client.get(f"/m/notes/{note.pk}/edit/")
        self.assertEqual(response.status_code, 404)
