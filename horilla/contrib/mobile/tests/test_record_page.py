"""
Tests for the record page: access, the desktop's field choice, Call and Email,
status changes through the desktop stage update, activities and notes.
"""

# Standard library imports
from unittest import skipUnless

# Third-party imports (Django)
from django.test import override_settings

# First party imports (Horilla)
from horilla.utils import timezone

from .base import MOBILE_INSTALLED, MobileTestBase

if MOBILE_INSTALLED:
    from horilla.contrib.activity.models import Activity
    from horilla.contrib.core.models import (
        DetailFieldVisibility,
        HorillaAttachment,
        HorillaContentType,
        RecentlyViewed,
    )

    from .models import MobileTestRecord

TEST_URLCONF = "horilla.contrib.mobile.tests.urls"


def record_url(record):
    """Record url."""
    return f"/m/records/mobile/mobiletestrecord/{record.pk}/"


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
@override_settings(ROOT_URLCONF=TEST_URLCONF)
class RecordAccessTests(MobileTestBase):
    """Who can open a record."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.mine = self.make_record("Mine", owner=self.seller)
        self.theirs = self.make_record("Theirs", owner=self.other_seller)

    def test_owner_opens_their_record_and_it_is_remembered(self):
        """Owner opens their record and it is remembered."""
        self.client.force_login(self.seller)
        response = self.client.get(record_url(self.mine))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "mobile/record.html")
        self.assertEqual(
            RecentlyViewed.objects.get_recently_viewed(self.seller, MobileTestRecord),
            [self.mine],
        )

    def test_owner_without_a_full_name_shows_the_username(self):
        # Matches the owner field in the key fields below it.
        """Owner without a full name shows the username."""
        self.client.force_login(self.seller)
        response = self.client.get(record_url(self.mine))
        self.assertEqual(response.context["owner_name"], "seller")
        self.assertContains(response, "Owner: seller")

    def test_someone_elses_record_is_refused(self):
        """Someone elses record is refused."""
        self.client.force_login(self.seller)
        response = self.client.get(record_url(self.theirs))
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "mobile/unavailable.html")
        self.assertFalse(RecentlyViewed.objects.filter(user=self.seller).exists())

    def test_missing_record_and_unknown_model_are_not_found(self):
        """Missing record and unknown model are not found."""
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get("/m/records/mobile/mobiletestrecord/999999/").status_code,
            404,
        )
        self.assertEqual(
            self.client.get(f"/m/records/core/company/{self.company.pk}/").status_code,
            404,
        )

    def test_signed_out_users_go_to_the_mobile_login(self):
        """Signed out users go to the mobile login."""
        response = self.client.get(record_url(self.mine))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/m/login/"))


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
@override_settings(ROOT_URLCONF=TEST_URLCONF)
class RecordFieldsTests(MobileTestBase):
    """Key fields and All fields follow the user's desktop detail-page choice."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.record = self.make_record(
            "Sara",
            owner=self.seller,
            phone="0912",
            email="sara@example.com",
            city="Tehran",
        )
        self.client.force_login(self.seller)

    def names(self, fields):
        """Names."""
        return [name for _label, name in fields]

    def test_key_fields_default_to_the_desktop_header_without_the_title(self):
        """Key fields default to the desktop header without the title."""
        response = self.client.get(record_url(self.record))
        self.assertEqual(
            self.names(response.context["key_fields"]),
            ["phone", "email", "city", "owner"],
        )

    def test_key_fields_follow_the_users_desktop_choice(self):
        """Key fields follow the users desktop choice."""
        DetailFieldVisibility.all_objects.create(
            user=self.seller,
            app_label="mobile",
            model_name="mobiletestrecord",
            url_name="mobile_test_record_detail",
            header_fields=[["Name", "name"], ["City", "city"]],
            details_fields=[["Email", "email"], ["Phone", "phone"]],
        )
        response = self.client.get(record_url(self.record))
        self.assertEqual(self.names(response.context["key_fields"]), ["city"])
        self.assertEqual(self.names(response.context["all_fields"]), ["email", "phone"])

    def test_a_choice_saved_for_another_page_is_ignored(self):
        """A choice saved for another page is ignored."""
        DetailFieldVisibility.all_objects.create(
            user=self.seller,
            app_label="mobile",
            model_name="mobiletestrecord",
            url_name="record",
            header_fields=[["Name", "name"], ["City", "city"]],
        )
        response = self.client.get(record_url(self.record))
        self.assertIn("phone", self.names(response.context["key_fields"]))

    def test_visiting_never_saves_a_field_choice(self):
        """Visiting never saves a field choice."""
        self.client.get(record_url(self.record))
        self.assertFalse(DetailFieldVisibility.all_objects.exists())

    def test_all_fields_default_to_the_desktop_details_tab(self):
        """All fields default to the desktop details tab."""
        response = self.client.get(record_url(self.record))
        names = self.names(response.context["all_fields"])
        self.assertIn("mobile_phone", names)
        self.assertNotIn("status", names)  # the stage bar shows it
        self.assertNotIn("created_by", names)


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
@override_settings(ROOT_URLCONF=TEST_URLCONF)
class RecordActionsTests(MobileTestBase):
    """Call and Email."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.client.force_login(self.admin)

    def test_one_number_calls_directly(self):
        """One number calls directly."""
        record = self.make_record("One", phone="+98 912 345 6789")
        response = self.client.get(record_url(record))
        self.assertContains(response, 'href="tel:+989123456789"')
        self.assertNotContains(response, 'id="phone-sheet"')

    def test_two_numbers_ask_which_one(self):
        """Two numbers ask which one."""
        record = self.make_record(
            "Two", phone="021 8876 5432", mobile_phone="۰۹۱۲۳۴۵۶۷۸۹"
        )
        response = self.client.get(record_url(record))
        self.assertContains(response, 'id="phone-sheet"')
        self.assertContains(response, 'href="tel:02188765432"')
        self.assertContains(response, 'href="tel:09123456789"')

    def test_email_opens_the_mail_app(self):
        """Email opens the mail app."""
        record = self.make_record("Mail", email="mail@example.com")
        response = self.client.get(record_url(record))
        self.assertContains(response, 'href="mailto:mail@example.com"')

    def test_no_phone_or_email_means_no_buttons(self):
        """No phone or email means no buttons."""
        record = self.make_record("Nothing")
        response = self.client.get(record_url(record))
        self.assertNotContains(response, 'href="tel:')
        self.assertNotContains(response, 'href="mailto:')


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
@override_settings(ROOT_URLCONF=TEST_URLCONF)
class RecordStatusTests(MobileTestBase):
    """The status sheet posts the desktop stage update."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.record = self.make_record("Lead", owner=self.seller, status="new")

    def test_choices_come_from_the_desktop_stage_bar(self):
        """Choices come from the desktop stage bar."""
        self.client.force_login(self.seller)
        response = self.client.get(record_url(self.record))
        status = response.context["status"]
        self.assertTrue(status["can_update"])
        self.assertEqual(
            [c["value"] for c in status["choices"]], ["new", "contacted", "won"]
        )
        self.assertContains(response, 'action="/generics/update-pipeline/')
        self.assertContains(response, 'name="pipeline_field" value="status"')

    def post_status(self, value):
        """Post what the status sheet posts."""
        return self.client.post(
            f"/generics/update-pipeline/{self.record.pk}/",
            {
                "pipeline_update": "true",
                "app_label": "mobile",
                "model_name": "mobiletestrecord",
                "pipeline_field": "status",
                "pipeline_value": value,
            },
            HTTP_HX_REQUEST="true",
        )

    def test_stage_labels_are_shown_as_stored_not_translated(self):
        # A stage named like a catalog entry ("New") must not be replaced by
        # that entry's translation.
        """Stage labels are shown as stored not translated."""
        self.client.force_login(self.seller)
        response = self.client.get(record_url(self.record), HTTP_ACCEPT_LANGUAGE="fa")
        # The stage pill's own text, not the rest of the page.
        self.assertRegex(
            response.content.decode(), r'data-status-current="new"[^>]*>\s*New\s*<i'
        )

    def test_owner_with_change_own_changes_the_status(self):
        """Owner with change own changes the status."""
        self.client.force_login(self.seller)
        self.post_status("contacted")
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, "contacted")

    def test_read_only_user_gets_no_sheet_and_cannot_post(self):
        """Read only user gets no sheet and cannot post."""
        viewer = self.make_user("viewer")
        self.grant(viewer, MobileTestRecord, "view")
        self.client.force_login(viewer)
        response = self.client.get(record_url(self.record))
        self.assertFalse(response.context["status"]["can_update"])
        self.assertNotContains(response, 'id="status-sheet"')
        self.post_status("won")
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, "new")


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
@override_settings(ROOT_URLCONF=TEST_URLCONF)
class RecordTimelineTests(MobileTestBase):
    """Open activities and interactions."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.record = self.make_record("Lead", owner=self.seller)
        self.content_type = HorillaContentType.objects.get_for_model(MobileTestRecord)
        self.grant(self.seller, Activity, "view_own")

    def activity(self, subject, owner, **fields):
        """Activity."""
        return Activity.objects.create(
            subject=subject,
            owner=owner,
            content_type=self.content_type,
            object_id=self.record.pk,
            company=self.company,
            **fields,
        )

    def test_open_activities_and_interactions(self):
        """Open activities and interactions."""
        now = timezone.now()
        self.activity(
            "Send the quote",
            self.seller,
            activity_type="task",
            status="not_started",
            due_datetime=now,
        )
        self.activity(
            "Kick-off",
            self.seller,
            activity_type="meeting",
            status="completed",
            start_datetime=now,
        )
        self.activity(
            "Asked for a discount",
            self.seller,
            activity_type="log_call",
            status="completed",
        )
        HorillaAttachment.objects.create(
            title="Wants volume pricing",
            content_type=self.content_type,
            object_id=self.record.pk,
            company=self.company,
        )
        self.client.force_login(self.seller)
        response = self.client.get(record_url(self.record))
        open_titles = [row.title for row in response.context["open_activities"]]
        done_titles = {row.title for row in response.context["interactions"]}
        self.assertEqual(open_titles, ["Send the quote"])
        self.assertEqual(
            done_titles, {"Kick-off", "Asked for a discount", "Wants volume pricing"}
        )

    def test_activities_the_user_cannot_view_are_left_out(self):
        """Activities the user cannot view are left out."""
        self.activity(
            "Private task",
            self.other_seller,
            activity_type="task",
            status="not_started",
        )
        self.client.force_login(self.seller)
        response = self.client.get(record_url(self.record))
        self.assertEqual(response.context["open_activities"], [])
        self.assertContains(response, "No open activities.")


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
class NavigationTests(MobileTestBase):
    """Records has its tab in the bar."""

    def test_records_tab_is_marked_current(self):
        """Records tab is marked current."""
        self.client.force_login(self.admin)
        response = self.client.get("/m/records/")
        self.assertContains(response, 'aria-current="page"')
        self.assertContains(response, 'href="/m/more/"')
