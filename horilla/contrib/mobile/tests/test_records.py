"""
Tests for the Records tab: browsing, filters, search, pagination, recently
viewed, and what each user may see.
"""

# Standard library imports
from unittest import skipUnless

# Third-party imports (Django)
from django.test import override_settings

# First party imports (Horilla)
from horilla.web import QueryDict

from .base import MOBILE_INSTALLED, TEST_MOBILE_SETTINGS, MobileTestBase

if MOBILE_INSTALLED:
    from horilla.contrib.core.models import RecentlyViewed
    from horilla.contrib.mobile.records import PAGE_SIZE, FilterSet
    from horilla.contrib.mobile.registry import build_config, register_config

    from .models import MobileTestRecord

URL = "/m/records/"
MODEL = "mobile.mobiletestrecord"


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
class RecordsAccessTests(MobileTestBase):
    """Each user sees the records the desktop list would show them."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.mine = self.make_record("Mine", owner=self.seller, phone="0912 345 6789")
        self.theirs = self.make_record("Theirs", owner=self.other_seller)

    def test_admin_sees_every_record(self):
        """Admin sees every record."""
        self.client.force_login(self.admin)
        response = self.client.get(URL, {"model": MODEL})
        self.assertContains(response, "Mine")
        self.assertContains(response, "Theirs")

    def test_own_records_only_with_view_own(self):
        """Own records only with view own."""
        self.client.force_login(self.seller)
        response = self.client.get(URL, {"model": MODEL})
        self.assertContains(response, "Mine")
        self.assertNotContains(response, "Theirs")

    def test_search_respects_the_same_scope(self):
        """Search respects the same scope."""
        self.client.force_login(self.seller)
        response = self.client.get(URL, {"q": "Theirs"})
        self.assertNotContains(
            response, f"/m/records/mobile/mobiletestrecord/{self.theirs.pk}/"
        )

    def test_user_without_permission_sees_no_record_types(self):
        """User without permission sees no record types."""
        stranger = self.make_user("stranger")
        self.client.force_login(stranger)
        response = self.client.get(URL)
        self.assertContains(response, "No records are available on the phone yet.")
        self.assertNotContains(response, "Mine")

    def test_rows_link_the_record_and_call_its_phone(self):
        """Rows link the record and call its phone."""
        self.client.force_login(self.seller)
        response = self.client.get(URL, {"model": MODEL})
        self.assertContains(
            response, f'href="/m/records/mobile/mobiletestrecord/{self.mine.pk}/"'
        )
        self.assertContains(response, 'href="tel:09123456789"')

    def test_rows_show_the_row_fields_with_their_labels(self):
        """Rows show the row fields with their labels."""
        self.mine.city = "Tehran"
        self.mine.save()
        self.client.force_login(self.seller)
        response = self.client.get(URL, {"model": MODEL})
        self.assertContains(response, "<dt", count=2)  # City and Owner of the one row
        self.assertContains(response, "Tehran")

    @override_settings(ROOT_URLCONF="horilla.contrib.mobile.tests.urls")
    def test_subtitle_fields_show_on_one_line_under_the_title(self):
        """Subtitle fields show on one line under the title."""
        register_config(
            MobileTestRecord,
            {**TEST_MOBILE_SETTINGS, "subtitle_fields": ["city", "email"]},
        )
        self.addCleanup(register_config, MobileTestRecord, TEST_MOBILE_SETTINGS)
        self.mine.city = "Tehran"
        self.mine.email = "ali@example.com"
        self.mine.save()
        self.client.force_login(self.seller)
        response = self.client.get(URL, {"model": MODEL})
        self.assertContains(response, "<bdi>Tehran ali@example.com</bdi>")
        response = self.client.get(
            f"/m/records/mobile/mobiletestrecord/{self.mine.pk}/"
        )
        self.assertContains(response, "<bdi>Tehran ali@example.com</bdi>")

    def test_user_fields_are_plain_names_not_nested_links(self):
        # The desktop renders users as a link chip; inside the row's own link
        # that would be a nested <a> and break the row.
        """User fields are plain names not nested links."""
        self.client.force_login(self.seller)
        response = self.client.get(URL, {"model": MODEL})
        self.assertContains(response, "<bdi>seller</bdi>")
        self.assertNotContains(response, "/user-detail-view/")


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
class RecordsBrowseTests(MobileTestBase):
    """Filters, pagination and recently viewed."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.client.force_login(self.admin)

    def test_status_filter(self):
        """Status filter."""
        self.make_record("New one", status="new")
        self.make_record("Won one", status="won")
        response = self.client.get(URL, {"model": MODEL, "f_status": "won"})
        self.assertContains(response, "Won one")
        self.assertNotContains(response, "New one")
        self.assertContains(response, 'aria-label="Remove filter Status: Won"')

    def test_user_filter_options_show_names_even_without_a_full_name(self):
        """User filter options show names even without a full name."""
        config = build_config(
            MobileTestRecord, {**TEST_MOBILE_SETTINGS, "filter_fields": ["owner"]}
        )
        filters = FilterSet(config, self.admin, QueryDict())
        owner = next(field for field in filters.fields if field["name"] == "owner")
        labels = {option["label"] for option in owner["options"]}
        self.assertIn("seller", labels)
        self.assertNotIn(" ", labels)

    def test_unknown_filter_values_are_ignored(self):
        """Unknown filter values are ignored."""
        self.make_record("Anyone", status="new")
        response = self.client.get(URL, {"model": MODEL, "f_status": "bogus"})
        self.assertContains(response, "Anyone")

    def test_count_partial_returns_the_filtered_total(self):
        """Count partial returns the filtered total."""
        self.make_record("A", status="won")
        self.make_record("B", status="won")
        self.make_record("C", status="new")
        response = self.client.get(
            URL, {"model": MODEL, "f_status": "won", "partial": "count"}
        )
        self.assertEqual(response.content, b"2")

    def test_long_lists_load_the_next_page_when_reached(self):
        """Long lists load the next page when reached."""
        for index in range(PAGE_SIZE + 5):
            self.make_record(f"Record {index:02d}")
        first = self.client.get(URL, {"model": MODEL})
        self.assertContains(first, 'hx-trigger="revealed"')
        self.assertContains(first, "Record 19")
        self.assertNotContains(first, "Record 20")
        second = self.client.get(URL, {"model": MODEL, "partial": "rows", "page": 2})
        self.assertContains(second, "Record 24")
        self.assertNotContains(second, "Record 19")
        self.assertNotContains(second, 'hx-trigger="revealed"')

    def test_recently_viewed_lists_records_the_user_can_still_open(self):
        """Recently viewed lists records the user can still open."""
        seen = self.make_record("Seen before", owner=self.seller)
        gone = self.make_record("Reassigned", owner=self.seller)
        RecentlyViewed.objects.add_viewed_item(self.seller, seen)
        RecentlyViewed.objects.add_viewed_item(self.seller, gone)
        gone.owner = self.other_seller
        gone.save()
        self.client.force_login(self.seller)
        response = self.client.get(URL, {"model": MODEL})
        self.assertContains(response, "Recently viewed")
        recent = response.context["recent"]
        self.assertEqual([item["obj"] for item in recent], [seen])


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
class RecordsSearchTests(MobileTestBase):
    """Searching every record type at once."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.client.force_login(self.admin)
        self.make_record("Sara Ahmadi", phone="09123456789")

    def test_search_results_are_grouped_by_record_type(self):
        """Search results are grouped by record type."""
        response = self.client.get(URL, {"q": "۰۹۱۲"})
        self.assertContains(response, "Sara Ahmadi")
        self.assertContains(response, "All (1)")

    def test_results_partial_is_just_the_results(self):
        """Results partial is just the results."""
        response = self.client.get(URL, {"q": "sara", "partial": "results"})
        self.assertContains(response, "Sara Ahmadi")
        self.assertNotContains(response, "<html")

    def test_no_match_says_so(self):
        """No match says so."""
        response = self.client.get(URL, {"q": "nobody"})
        self.assertContains(response, "Every record type was searched.")
