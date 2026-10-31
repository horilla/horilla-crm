"""
Tests for editing a record's fields on the phone: who may edit (the desktop
Edit Details rule), which fields the form offers, and the save through the
desktop's own Edit Details save.
"""

# Standard library imports
from unittest import mock, skipUnless

# Third-party imports (Django)
from django.contrib import messages
from django.test import override_settings

# First party imports (Horilla)
from horilla.core.exceptions import ValidationError
from horilla.web import HttpResponse

from .base import MOBILE_INSTALLED, MobileTestBase

if MOBILE_INSTALLED:
    from horilla.contrib.core.models import (
        Company,
        FieldPermission,
        HorillaContentType,
    )
    from horilla.contrib.generics.forms.generics import PhoneWidget

    from .models import MobileTestRecord

TEST_URLCONF = "horilla.contrib.mobile.tests.urls"


def record_url(record):
    return f"/m/records/mobile/mobiletestrecord/{record.pk}/"


def edit_url(record):
    return f"{record_url(record)}edit/"


class StoppingHooks:
    """Edit Details hooks whose pre-save check stops the save, as a duplicate check would."""

    def get_allowed_fields(self, request, obj):
        return None

    def check_before_save(self, request, obj, changed_fields):
        messages.warning(request, "A record like this one already exists.")
        return HttpResponse("desktop warning markup")

    def handle_save_error(self, request, obj, error, app_label, model_name):
        return None


class CityOnlyHooks(StoppingHooks):
    """Edit Details hooks that only let the city be changed, and save."""

    def get_allowed_fields(self, request, obj):
        return {"city"}

    def check_before_save(self, request, obj, changed_fields):
        return None


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
@override_settings(ROOT_URLCONF=TEST_URLCONF)
class EditRecordAccessTests(MobileTestBase):
    """Who may edit: an owner with change_own, or change, never a locked record."""

    def setUp(self):
        super().setUp()
        self.mine = self.make_record("Mine", owner=self.seller, city="Tehran")
        self.viewer = self.make_user("viewer")
        self.grant(self.viewer, MobileTestRecord, "view_own")
        self.viewed = self.make_record("Viewed", owner=self.viewer)

    def test_the_owner_with_change_own_gets_the_form(self):
        self.client.force_login(self.seller)
        response = self.client.get(edit_url(self.mine))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "mobile/edit_record.html")

    def test_the_record_page_links_to_the_form_only_for_users_who_may_edit(self):
        self.client.force_login(self.seller)
        self.assertContains(self.client.get(record_url(self.mine)), edit_url(self.mine))
        self.client.force_login(self.viewer)
        self.assertNotContains(
            self.client.get(record_url(self.viewed)), edit_url(self.viewed)
        )

    def test_view_permission_alone_is_refused(self):
        self.client.force_login(self.viewer)
        response = self.client.post(edit_url(self.viewed), {"city": "Shiraz"})
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "mobile/unavailable.html")
        self.viewed.refresh_from_db()
        self.assertEqual(self.viewed.city, "")

    def test_someone_elses_record_is_refused(self):
        self.client.force_login(self.other_seller)
        response = self.client.post(edit_url(self.mine), {"city": "Shiraz"})
        self.assertEqual(response.status_code, 403)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.city, "Tehran")

    def test_change_permission_edits_any_record(self):
        self.client.force_login(self.admin)
        self.client.post(edit_url(self.mine), {"city": "Shiraz"})
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.city, "Shiraz")

    def test_a_locked_record_is_refused(self):
        self.client.force_login(self.admin)
        with mock.patch.object(MobileTestRecord, "is_record_locked", True, create=True):
            response = self.client.post(edit_url(self.mine), {"city": "Shiraz"})
            self.assertNotContains(
                self.client.get(record_url(self.mine)),
                edit_url(self.mine),
                status_code=200,
            )
        self.assertEqual(response.status_code, 403)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.city, "Tehran")

    def test_missing_record_is_not_found(self):
        self.client.force_login(self.admin)
        response = self.client.get("/m/records/mobile/mobiletestrecord/999999/edit/")
        self.assertEqual(response.status_code, 404)


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
@override_settings(ROOT_URLCONF=TEST_URLCONF)
class EditRecordFormTests(MobileTestBase):
    """The fields offered, and the save through the desktop Edit Details save."""

    def setUp(self):
        super().setUp()
        self.record = self.make_record(
            "Aria Trading", owner=self.seller, city="Tehran", phone="+98 9123456789"
        )
        self.client.force_login(self.seller)

    def field_names(self):
        response = self.client.get(edit_url(self.record))
        return [field["name"] for field in response.context["fields"]]

    def test_the_details_tab_fields_without_the_stage_and_non_editable_ones(self):
        names = self.field_names()
        for name in ("name", "phone", "city", "owner"):
            self.assertIn(name, names)
        # The stage bar's field, and the Details tab's non_editable_fields.
        self.assertNotIn("status", names)
        self.assertNotIn("email", names)

    def test_fields_the_user_may_not_change_are_left_out(self):
        content_type = HorillaContentType.objects.get_for_model(MobileTestRecord)
        for field_name, permission in (("city", "readonly"), ("phone", "hidden")):
            FieldPermission.objects.create(
                user=self.seller,
                content_type=content_type,
                field_name=field_name,
                permission_type=permission,
            )
        names = self.field_names()
        self.assertNotIn("city", names)
        self.assertNotIn("phone", names)
        # Posted anyway: the desktop save skips them too.
        self.client.post(edit_url(self.record), {"city": "Shiraz", "name": "Aria"})
        self.record.refresh_from_db()
        self.assertEqual(self.record.city, "Tehran")
        self.assertEqual(self.record.name, "Aria")

    def test_inputs_follow_the_desktop_field_types(self):
        response = self.client.get(edit_url(self.record))
        fields = {field["name"]: field for field in response.context["fields"]}
        self.assertEqual(fields["owner"]["kind"], "related")
        self.assertEqual(fields["owner"]["selected"][0]["value"], self.seller.pk)
        self.assertEqual(fields["phone"]["kind"], "phone")
        # Split as the desktop phone widget splits it ("+98", "9123456789"
        # with the stock widget), so a project's own widget is followed too.
        self.assertEqual(
            (fields["phone"]["code"], fields["phone"]["number"]),
            tuple(PhoneWidget().decompress(self.record.phone)),
        )
        self.assertEqual(fields["city"]["kind"], "input")
        self.assertEqual(fields["city"]["maxlength"], 50)

    def test_the_company_country_code_comes_first(self):
        # The phone's list has no search box: the likely code is on top.
        Company.objects.filter(pk=self.company.pk).update(country="IR")
        response = self.client.get(edit_url(self.record))
        codes = [code for code, _label in response.context["phone_codes"]]
        self.assertEqual(codes[:3], ["", "+98", "+1"])
        self.assertEqual(codes.count("+98"), 1)

    def test_saving_goes_back_to_the_record(self):
        response = self.client.post(
            edit_url(self.record), {"name": "Aria Trading Co", "city": "Shiraz"}
        )
        self.assertRedirects(
            response, record_url(self.record), fetch_redirect_response=False
        )
        self.record.refresh_from_db()
        self.assertEqual(self.record.name, "Aria Trading Co")
        self.assertEqual(self.record.city, "Shiraz")
        self.assertContains(self.client.get(record_url(self.record)), "Changes saved.")

    def test_only_posted_fields_change(self):
        self.client.post(edit_url(self.record), {"city": "Shiraz"})
        self.record.refresh_from_db()
        self.assertEqual(self.record.name, "Aria Trading")
        self.assertEqual(self.record.phone, "+98 9123456789")
        self.assertEqual(self.record.owner, self.seller)

    def test_a_value_that_cannot_be_applied_is_shown_under_its_field(self):
        response = self.client.post(
            edit_url(self.record), {"owner": "999999", "city": "Shiraz"}
        )
        self.assertEqual(response.status_code, 200)
        owner = next(f for f in response.context["fields"] if f["name"] == "owner")
        self.assertTrue(owner["error"])
        self.record.refresh_from_db()
        self.assertEqual(self.record.city, "Tehran")

    def test_an_invalid_phone_number_keeps_what_was_typed(self):
        response = self.client.post(
            edit_url(self.record), {"phone_0": "+98", "phone_1": "12"}
        )
        phone = next(f for f in response.context["fields"] if f["name"] == "phone")
        self.assertTrue(phone["error"])
        self.assertEqual((phone["code"], phone["number"]), ("+98", "12"))
        self.record.refresh_from_db()
        self.assertEqual(self.record.phone, "+98 9123456789")

    def test_only_the_fields_an_extension_allows_are_offered_and_saved(self):
        # As under a pending approval that lets the approver change one field.
        with mock.patch(
            "horilla.contrib.mobile.edit_record.get_update_all_fields_view",
            return_value=CityOnlyHooks(),
        ):
            response = self.client.get(edit_url(self.record))
            names = [field["name"] for field in response.context["fields"]]
            self.client.post(edit_url(self.record), {"city": "Shiraz", "name": "Aria"})
        self.assertEqual(names, ["city"])
        self.record.refresh_from_db()
        self.assertEqual(self.record.city, "Shiraz")
        self.assertEqual(self.record.name, "Aria Trading")

    def test_a_check_that_stops_the_save_is_explained(self):
        with mock.patch(
            "horilla.contrib.mobile.edit_record.get_update_all_fields_view",
            return_value=StoppingHooks(),
        ):
            response = self.client.post(edit_url(self.record), {"city": "Shiraz"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your changes weren't saved.")
        self.assertContains(response, "A record like this one already exists.")
        self.assertNotContains(response, "desktop warning markup")
        self.record.refresh_from_db()
        self.assertEqual(self.record.city, "Tehran")

    def test_a_save_error_is_shown(self):
        with mock.patch.object(
            MobileTestRecord,
            "save",
            side_effect=ValidationError("This record is waiting for approval."),
        ):
            response = self.client.post(edit_url(self.record), {"city": "Shiraz"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This record is waiting for approval.")
