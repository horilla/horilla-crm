"""
Tests for the phone search: digits and letters as people type them on a phone.
"""

# Standard library imports
from unittest import skipUnless

# Third-party imports (Django)
from django.test import SimpleTestCase

from .base import MOBILE_INSTALLED, TEST_MOBILE_SETTINGS, MobileTestBase

if MOBILE_INSTALLED:
    from horilla.contrib.mobile.registry import build_config
    from horilla.contrib.mobile.search import (
        apply_search,
        phone_digits,
        tel_href,
        text_variants,
    )

    from .models import MobileTestRecord


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
class NormalizationTests(SimpleTestCase):
    """Digits, separators and letter variants."""

    def test_phone_digits_accept_persian_and_arabic_digits_and_separators(self):
        """Phone digits accept persian and arabic digits and separators."""
        self.assertEqual(phone_digits("۰۹۱۲ ۳۴۵-۶۷۸۹"), "09123456789")
        self.assertEqual(phone_digits("٠٩١٢٣٤٥"), "0912345")
        self.assertEqual(phone_digits("+98 (912) 345.6789"), "989123456789")

    def test_text_is_not_a_phone_number(self):
        """Text is not a phone number."""
        self.assertEqual(phone_digits("Sara 0912"), "")
        self.assertEqual(phone_digits("Acme"), "")

    def test_tel_href_keeps_a_leading_plus_and_digits_only(self):
        """Tel href keeps a leading plus and digits only."""
        self.assertEqual(tel_href("‎+98 912-345 6789"), "+989123456789")
        self.assertEqual(tel_href("۰۲۱ ۸۸۷۶ ۵۴۳۲"), "02188765432")
        self.assertEqual(tel_href(""), "")
        self.assertEqual(tel_href(None), "")

    def test_text_variants_cover_both_forms_of_ye_and_kaf(self):
        """Text variants cover both forms of ye and kaf."""
        variants = text_variants("كريمي")
        self.assertIn("کریمی", variants)
        self.assertIn("كريمي", variants)


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
class ApplySearchTests(MobileTestBase):
    """Matching against the database."""

    def setUp(self):
        """Create the records these tests share."""
        super().setUp()
        self.config = build_config(MobileTestRecord, TEST_MOBILE_SETTINGS)
        self.sara = self.make_record("سارا کریمی", phone="0912-345 6789", city="Tehran")
        self.nima = self.make_record(
            "Nima Salehi", mobile_phone="۰۹۳۵۱۱۱۲۲۳۳", email="nima@example.com"
        )
        self.acme = self.make_record("Acme Trading", city="Isfahan")

    def search(self, query):
        """Search."""
        return set(apply_search(MobileTestRecord.objects.all(), self.config, query))

    def test_persian_digits_find_a_number_stored_with_latin_digits_and_spaces(self):
        """Persian digits find a number stored with latin digits and spaces."""
        self.assertEqual(self.search("۰۹۱۲۳۴۵"), {self.sara})

    def test_latin_digits_find_a_number_stored_with_persian_digits(self):
        """Latin digits find a number stored with persian digits."""
        self.assertEqual(self.search("0935 111"), {self.nima})

    def test_arabic_letters_find_the_persian_spelling(self):
        """Arabic letters find the persian spelling."""
        self.assertEqual(self.search("كريمي"), {self.sara})

    def test_title_email_and_search_fields_match_case_insensitively(self):
        """Title email and search fields match case insensitively."""
        self.assertEqual(self.search("acme"), {self.acme})
        self.assertEqual(self.search("NIMA@"), {self.nima})
        self.assertEqual(self.search("isfahan"), {self.acme})

    def test_one_character_does_not_filter(self):
        """One character does not filter."""
        self.assertEqual(self.search("a"), {self.sara, self.nima, self.acme})
