"""History tab RTL / Farsi support, kept off rtl.css."""

from pathlib import Path

from django.conf import settings
from django.template.loader import get_template, render_to_string
from django.test import SimpleTestCase


class HistoryTabRtlOverlayTests(SimpleTestCase):
    """History tab RTL template, history-rtl.css, and project overlays, kept off rtl.css."""

    def test_rtl_css_is_unchanged_by_history_rules(self):
        """rtl.css must not contain history-specific selectors or imports."""
        css = (
            Path(settings.BASE_DIR) / "static" / "assets" / "css" / "rtl.css"
        ).read_text(encoding="utf-8")
        self.assertNotIn("#history-main", css)
        self.assertNotIn("history-rtl.css", css)
        self.assertNotIn("history-filter-bar", css)

    def test_history_rtl_css_covers_bidi_not_filter_bar(self):
        """Filter-bar alignment is Tailwind on the template; CSS keeps bidi isolates."""
        css = (
            Path(settings.BASE_DIR) / "static" / "assets" / "css" / "history-rtl.css"
        ).read_text(encoding="utf-8")
        self.assertNotIn("history-filter-bar", css)
        self.assertNotIn("flex-direction: row-reverse", css)
        self.assertIn("unicode-bidi: isolate", css)

    def test_history_rtl_css_points_the_diff_arrow_at_the_new_value(self):
        """In RTL the new value sits left of the old one, so the arrow is flipped."""
        css = (
            Path(settings.BASE_DIR) / "static" / "assets" / "css" / "history-rtl.css"
        ).read_text(encoding="utf-8")
        rule = css.split('[dir="rtl"] #history-main .history-diff-arrow {', 1)[1]
        self.assertIn("transform: scaleX(-1);", rule.split("}", 1)[0])

    def test_detail_tab_view_css_expands_detail_pane(self):
        """tab_view.html still defines detail-pane expand styles."""
        css = (
            Path(settings.BASE_DIR)
            / "horilla"
            / "contrib"
            / "generics"
            / "templates"
            / "tab_view.html"
        ).read_text(encoding="utf-8")
        self.assertIn("detail-tab-expanded", css)
        self.assertIn("#detailHeaderCard", css)

    def test_rtl_assets_overlay_loads_history_stylesheet(self):
        """rtl_assets.html loads both rtl.css and history-rtl.css when BIDI."""
        html = render_to_string("inject_html/rtl_assets.html", {"LANGUAGE_BIDI": True})
        self.assertIn("assets/css/rtl.css", html)
        self.assertIn("assets/css/history-rtl.css", html)

    def test_history_tab_uses_localizable_phrases(self):
        """Generics history_tab.html uses translatable phrases and filters."""
        text = (
            Path(settings.BASE_DIR)
            / "horilla"
            / "contrib"
            / "generics"
            / "templates"
            / "history_tab.html"
        ).read_text(encoding="utf-8")
        self.assertIn("New {{ model }} created", text)
        self.assertIn("{% trans field %}", text)
        self.assertIn("LANGUAGE_BIDI", text)
        self.assertIn("history-filter-bar", text)
        self.assertIn("justify-end rtl:justify-start", text)
        self.assertIn("history-kv", text)
        self.assertIn("history_datetime", text)
        self.assertIn("history_is_date_field", text)
        self.assertNotIn("sticky top-4", text)
        self.assertNotIn("Jalali", text)
        actor = (
            Path(settings.BASE_DIR)
            / "horilla"
            / "contrib"
            / "generics"
            / "templates"
            / "partials"
            / "history_entry_actor.html"
        ).read_text(encoding="utf-8")
        self.assertIn('{% trans "by" %}', actor)

    def test_project_history_tab_duplicate_is_removed(self):
        """history_tab.html lives only in generics, with no project-level copy."""
        base = Path(settings.BASE_DIR) / "templates"
        self.assertFalse((base / "history_tab.html").exists())
        self.assertFalse((base / "partials" / "history_entry_actor.html").exists())

    def test_persian_history_strings_exist(self):
        """leads/fa django.po includes Persian strings used by history UI."""
        po = (
            Path(settings.BASE_DIR)
            / "horilla_crm"
            / "leads"
            / "locale"
            / "fa"
            / "LC_MESSAGES"
            / "django.po"
        ).read_text(encoding="utf-8")
        self.assertIn('msgid "by"', po)
        self.assertIn('msgstr "توسط"', po)
        self.assertIn('msgid "New %(model)s created"', po)
        self.assertIn('msgstr "%(model)s جدید ایجاد شد"', po)
        self.assertIn('msgid "Sender"', po)
        self.assertIn('msgstr "فرستنده"', po)
        self.assertIn('msgid "Expand"', po)
        self.assertIn('msgstr "بزرگ‌نمایی"', po)
        self.assertIn('msgid "Select date to filter"', po)
        self.assertIn('msgstr "تاریخ را برای فیلتر انتخاب کنید"', po)
        self.assertIn('msgid "Apply"', po)
        self.assertIn('msgstr "اعمال"', po)

    def test_history_date_range_dropdown_is_translated(self):
        """The history date-range dropdown uses {% trans %} for its labels and
        the shared primary button for Apply."""
        text = (
            Path(settings.BASE_DIR)
            / "horilla"
            / "contrib"
            / "generics"
            / "templates"
            / "components"
            / "date_range_filter.html"
        ).read_text(encoding="utf-8")
        self.assertIn('{% trans "Start Date" %}', text)
        self.assertIn('{% trans "End Date" %}', text)
        self.assertIn('{% trans "All Time" %}', text)
        self.assertIn('{% trans "Custom Range" %}', text)
        self.assertIn('{% btn _("Apply")', text)
        self.assertNotIn("form.filter_date.label_tag", text)
        self.assertNotIn("Jalali", text)

    def test_history_tab_resolves_to_generics_template(self):
        """Template loader resolves history_tab.html from generics."""
        template = get_template("history_tab.html")
        parts = Path(template.origin.name).parts
        self.assertIn("contrib", parts)
        self.assertIn("generics", parts)


class HistoryIsDateFieldTests(SimpleTestCase):
    """History date-field detection for translated labels."""

    def test_history_is_date_field_matches_persian_start_date_label(self):
        """history_is_date_field recognizes Persian date-related labels."""
        from horilla.contrib.generics.templatetags.horilla_tags.history_i18n import (
            history_is_date_field,
        )

        self.assertTrue(history_is_date_field(None, "تاریخ شروع"))
        self.assertTrue(history_is_date_field(None, "به‌روزرسانی شده در"))
        self.assertFalse(history_is_date_field(None, "وضعیت"))
