"""Tests for the Date and Date and Time custom field types."""

# Standard library imports
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

# Third-party imports (Django)
from django import forms
from django.test import TestCase

from custom_fields.condition_field_extensions import CustomFieldConditionExtension
from custom_fields.detail_hooks import _validate_inline_value, build_custom_field_info
from custom_fields.filter_hooks import matching_object_ids
from custom_fields.models import CustomFieldDefinition, CustomFieldValue
from custom_fields.utils import (
    build_custom_form_fields,
    format_custom_field_display,
    save_custom_field_values,
)

# First party imports (Horilla)
from horilla.contrib.core.models import Company, HorillaContentType
from horilla.contrib.generics.views.helpers.condition_widget import (
    GetFieldValueWidgetView,
)
from horilla.extension.bootstrap import bootstrap_extensions
from horilla.utils import timezone
from horilla_crm.leads import signals as lead_signals
from horilla_crm.leads.models import Lead

TEHRAN = ZoneInfo("Asia/Tehran")


class CustomDateFieldTestBase(TestCase):
    """Creates one Date and one Date and Time definition on Lead."""

    def setUp(self):
        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        self.lead_ct = HorillaContentType.objects.get_for_model(Lead)
        self.date_field = CustomFieldDefinition.objects.create(
            content_type=self.lead_ct,
            name="Contract Date",
            field_type="date",
            company=self.company,
        )
        self.datetime_field = CustomFieldDefinition.objects.create(
            content_type=self.lead_ct,
            name="Callback At",
            field_type="datetime",
            company=self.company,
        )

    def _store(self, definition, object_id, value):
        cfv = CustomFieldValue(
            field_definition=definition,
            content_type=self.lead_ct,
            object_id=object_id,
            company=self.company,
        )
        cfv.set_value(value)
        cfv.save()
        return cfv


class CustomDateFieldStorageTests(CustomDateFieldTestBase):
    """Values land in typed Gregorian columns."""

    def test_date_value_is_stored_in_date_column(self):
        cfv = self._store(self.date_field, 1, "2026-03-21")
        cfv.refresh_from_db()
        self.assertEqual(cfv.value_date, date(2026, 3, 21))
        self.assertEqual(cfv.get_value(), date(2026, 3, 21))
        self.assertEqual(cfv.value_text, "")
        self.assertIsNone(cfv.value_datetime)

    def test_naive_datetime_input_is_read_in_active_timezone(self):
        with timezone.override(TEHRAN):
            cfv = self._store(self.datetime_field, 1, "2026-03-21T10:30")
        cfv.refresh_from_db()
        self.assertEqual(
            cfv.value_datetime, datetime(2026, 3, 21, 7, 0, tzinfo=dt_timezone.utc)
        )
        self.assertIsNone(cfv.value_date)

    def test_empty_or_invalid_input_clears_value(self):
        cfv = self._store(self.date_field, 1, "2026-03-21")
        cfv.set_value("")
        self.assertIsNone(cfv.value_date)
        cfv.set_value("2026-02-31")
        self.assertIsNone(cfv.value_date)

    def test_resubmitting_same_date_string_is_a_no_op(self):
        self._store(self.date_field, 7, "2026-03-21")
        key = f"cf_{self.date_field.pk}"
        changed = save_custom_field_values(Lead, 7, {key: "2026-03-21"})
        self.assertEqual(changed, set())
        changed = save_custom_field_values(Lead, 7, {key: "2026-03-22"})
        self.assertEqual(changed, {key})


class CustomDateFieldFormTests(CustomDateFieldTestBase):
    """Form widgets are the standard inputs the Jalali picker attaches to."""

    def test_form_fields_use_native_date_inputs(self):
        fields = build_custom_form_fields(Lead)
        date_field = fields[f"cf_{self.date_field.pk}"]
        datetime_field = fields[f"cf_{self.datetime_field.pk}"]
        self.assertIsInstance(date_field, forms.DateField)
        self.assertEqual(date_field.widget.input_type, "date")
        self.assertIsInstance(datetime_field, forms.DateTimeField)
        self.assertEqual(datetime_field.widget.input_type, "datetime-local")

    def test_form_cleans_iso_values_submitted_by_the_pickers(self):
        fields = build_custom_form_fields(Lead)
        self.assertEqual(
            fields[f"cf_{self.date_field.pk}"].clean("2026-03-21"), date(2026, 3, 21)
        )
        cleaned = fields[f"cf_{self.datetime_field.pk}"].clean("2026-03-21T10:30")
        self.assertEqual((cleaned.hour, cleaned.minute), (10, 30))

    def test_edit_details_info_uses_input_wire_format(self):
        lead = Lead(pk=3)
        self._store(self.datetime_field, 3, "2026-03-21T10:30")
        info = build_custom_field_info(self.datetime_field, lead)
        self.assertEqual(info["field_type"], "datetime-local")
        self.assertEqual(info["value"], "2026-03-21T10:30")

    def test_edit_details_rejects_invalid_dates(self):
        self.assertIsNotNone(_validate_inline_value(self.date_field, "not-a-date"))
        self.assertIsNone(_validate_inline_value(self.date_field, "2026-03-21"))
        self.assertIsNotNone(_validate_inline_value(self.datetime_field, "2026-13-01"))

    def test_display_uses_horilla_date_formatter(self):
        self.assertEqual(
            format_custom_field_display(self.date_field, date(2026, 3, 21)),
            "2026-03-21",
        )
        self.assertEqual(format_custom_field_display(self.date_field, None), "")


class CustomDateFieldFilterTests(CustomDateFieldTestBase):
    """Filter Records operators compare real dates, not text."""

    def setUp(self):
        super().setUp()
        self._store(self.date_field, 1, "2026-01-10")
        self._store(self.date_field, 2, "2026-02-10")
        self._store(self.date_field, 3, "")

    def _ids(self, definition, operator, value=None, start=None, end=None):
        include, ids = matching_object_ids(
            Lead, definition, operator, value, start, end
        )
        return include, sorted(ids)

    def test_exact_and_comparisons(self):
        self.assertEqual(self._ids(self.date_field, "exact", "2026-01-10"), (True, [1]))
        self.assertEqual(self._ids(self.date_field, "gt", "2026-01-10"), (True, [2]))
        self.assertEqual(self._ids(self.date_field, "lt", "2026-02-10"), (True, [1]))
        self.assertEqual(self._ids(self.date_field, "ne", "2026-01-10"), (False, [1]))

    def test_between_and_empty(self):
        self.assertEqual(
            self._ids(self.date_field, "between", start="2026-02-01", end="2026-02-28"),
            (True, [2]),
        )
        self.assertEqual(self._ids(self.date_field, "isnull"), (False, [1, 2]))

    def test_relative_operator(self):
        self._store(self.date_field, 4, timezone.localdate())
        self.assertEqual(self._ids(self.date_field, "today"), (True, [4]))

    def test_datetime_between_bare_dates_covers_whole_end_day(self):
        self._store(self.datetime_field, 5, "2026-01-31T23:00")
        self._store(self.datetime_field, 6, "2026-02-01T00:30")
        self.assertEqual(
            self._ids(
                self.datetime_field, "between", start="2026-01-01", end="2026-01-31"
            ),
            (True, [5]),
        )
        self.assertEqual(
            self._ids(self.datetime_field, "exact", "2026-01-31T23:00"), (True, [5])
        )


class CustomDateFieldAssignmentRuleTests(CustomDateFieldTestBase):
    """Lead assignment rules evaluate custom date criteria by value."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # MixinExtensions are applied when the URLconf loads; unit tests that
        # never make a request must apply them explicitly.
        bootstrap_extensions()

    def _matches(self, definition, operator, value):
        criteria = SimpleNamespace(
            field=f"cf_{definition.pk}", operator=operator, value=value
        )
        # Module attribute lookup: the MixinExtension patches the function on
        # its module, which is how the rule engine itself calls it.
        return lead_signals._eval_single_criterion(criteria, Lead(pk=9))

    def test_condition_widget_metadata(self):
        info = CustomFieldConditionExtension().get_widget_info(
            f"cf_{self.datetime_field.pk}"
        )
        self.assertEqual(info, {"widget": "datetime", "operator_type": "datetime"})

    def test_condition_value_widget_renders_date_pickers(self):
        view = GetFieldValueWidgetView()
        html = view._get_value_widget_html(
            f"cf_{self.date_field.pk}", "lead", "0", "2026-01-01,2026-01-31", "between"
        )
        self.assertEqual(str(html).count('type="date"'), 2)
        html = view._get_value_widget_html(
            f"cf_{self.datetime_field.pk}", "lead", "0", "", "gt"
        )
        self.assertIn('type="datetime-local"', str(html))
        html = view._get_value_widget_html(
            f"cf_{self.date_field.pk}", "lead", "0", "", "today"
        )
        self.assertNotIn('type="date"', str(html))

    def test_text_criteria_still_use_horilla_evaluator(self):
        text_field = CustomFieldDefinition.objects.create(
            content_type=self.lead_ct,
            name="Note",
            field_type="small_text",
            company=self.company,
        )
        self._store(text_field, 9, "Widget Pro")
        self.assertTrue(self._matches(text_field, "icontains", "widget"))

    def test_date_criteria(self):
        self._store(self.date_field, 9, "2026-03-21")
        self.assertTrue(self._matches(self.date_field, "exact", "2026-03-21"))
        self.assertTrue(self._matches(self.date_field, "gt", "2026-03-20"))
        self.assertFalse(self._matches(self.date_field, "lt", "2026-03-21"))
        self.assertTrue(
            self._matches(self.date_field, "between", "2026-03-01,2026-03-31")
        )
        self.assertTrue(self._matches(self.date_field, "isnotnull", ""))

    def test_datetime_criteria(self):
        self._store(self.datetime_field, 9, "2026-03-21T10:30")
        self.assertTrue(self._matches(self.datetime_field, "exact", "2026-03-21T10:30"))
        self.assertTrue(self._matches(self.datetime_field, "exact", "2026-03-21"))
        self.assertTrue(self._matches(self.datetime_field, "lt", "2026-03-21T11:00"))
        self.assertFalse(self._matches(self.datetime_field, "gt", "2026-03-21T10:30"))

    def test_relative_and_empty_criteria(self):
        self.assertTrue(self._matches(self.date_field, "isnull", ""))
        self.assertFalse(self._matches(self.date_field, "today", ""))
        self._store(self.date_field, 9, timezone.localdate() - timedelta(days=1))
        self.assertTrue(self._matches(self.date_field, "yesterday", ""))
