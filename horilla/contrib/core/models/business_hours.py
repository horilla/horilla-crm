"""
This module defines the BusinessHour for managing business hours in the Horilla platform.
"""

# Standard library imports
import logging

# Third-party imports
from datetime import datetime, time

# Django imports
from django.conf import settings
from django.utils.formats import time_format

# Third-party imports (Django)
from multiselectfield import MultiSelectField

# First party imports (Horilla)
from horilla.db import models
from horilla.urls import reverse_lazy
from horilla.utils.choices import (
    DAY_CHOICES,
    DAY_LABELS,
    SHORT_TO_DAY_PREFIX,
    TIMEZONE_CHOICES,
    TIMING_CHOICES,
    WEEK_ORDER,
)
from horilla.utils.html import format_html, format_html_join
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .base import HorillaCoreModel

logger = logging.getLogger(__name__)


def _format_card_time_range(start_label: str, end_label: str) -> str:
    """
    Join formatted times with a spaced en dash.
    Uses NBSP so HTML does not collapse the gaps (normal spaces render as one).
    """
    nbsp = "\u00a0"
    sep = f"{nbsp}{nbsp}{nbsp}\u2013{nbsp}{nbsp}{nbsp}"
    return f"{start_label}{sep}{end_label}"


class BusinessHourDayMixin(models.Model):
    """
    Model to add start and end time fields for each day of the week.
    """

    monday_start = models.TimeField(
        null=True, blank=True, verbose_name=_("Monday Start Time")
    )
    monday_end = models.TimeField(
        null=True, blank=True, verbose_name=_("Monday End Time")
    )

    tuesday_start = models.TimeField(
        null=True, blank=True, verbose_name=_("Tuesday Start Time")
    )
    tuesday_end = models.TimeField(
        null=True, blank=True, verbose_name=_("Tuesday End Time")
    )

    wednesday_start = models.TimeField(
        null=True, blank=True, verbose_name=_("Wednesday Start Time")
    )
    wednesday_end = models.TimeField(
        null=True, blank=True, verbose_name=_("Wednesday End Time")
    )

    thursday_start = models.TimeField(
        null=True, blank=True, verbose_name=_("Thursday Start Time")
    )
    thursday_end = models.TimeField(
        null=True, blank=True, verbose_name=_("Thursday End Time")
    )

    friday_start = models.TimeField(
        null=True, blank=True, verbose_name=_("Friday Start Time")
    )
    friday_end = models.TimeField(
        null=True, blank=True, verbose_name=_("Friday End Time")
    )

    saturday_start = models.TimeField(
        null=True, blank=True, verbose_name=_("Saturday Start Time")
    )
    saturday_end = models.TimeField(
        null=True, blank=True, verbose_name=_("Saturday End Time")
    )

    sunday_start = models.TimeField(
        null=True, blank=True, verbose_name=_("Sunday Start Time")
    )
    sunday_end = models.TimeField(
        null=True, blank=True, verbose_name=_("Sunday End Time")
    )

    class Meta:
        """
        Abstract model for business hour day model.
        """

        abstract = True


class BusinessHour(BusinessHourDayMixin, HorillaCoreModel):
    """
    Model to handle business hours with support for:
    - 24/7 operations
    - Weekdays only (Mon-Fri)
    - Custom hours with different times per day
    """

    BUSINESS_HOUR_TYPES = [
        ("24_7", _("24 Hours x 7 days")),
        ("24_5", _("24 Hours x 5 days")),
        ("custom", _("Custom Hours")),
    ]

    TIMING_CHOICES = TIMING_CHOICES
    DAY_LABELS = DAY_LABELS
    WEEK_ORDER = WEEK_ORDER
    SHORT_TO_DAY_PREFIX = SHORT_TO_DAY_PREFIX

    # Basic Information
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    time_zone = models.CharField(
        max_length=100,
        choices=TIMEZONE_CHOICES,
        default="UTC",
        verbose_name=_("Time Zone"),
    )

    # Business Hour Type
    business_hour_type = models.CharField(
        max_length=10,
        choices=BUSINESS_HOUR_TYPES,
        default="24_7",
        help_text=_("Type of business hours"),
        verbose_name=_("Business Hour Type"),
    )

    # Week Configuration
    week_days = MultiSelectField(
        choices=DAY_CHOICES, blank=True, verbose_name=_("Week Days")
    )

    # Timing Configuration (for custom hours)
    timing_type = models.CharField(
        max_length=10,
        choices=TIMING_CHOICES,
        default="same",
        blank=True,
        null=True,
        help_text=_("Same hours every day or different hours per day"),
        verbose_name=_("Timing Type"),
    )

    # For "Same Hour Every Day"
    default_start_time = models.TimeField(
        null=True,
        blank=True,
        help_text=_("Default start time"),
        verbose_name=_("Default Start Time"),
    )
    default_end_time = models.TimeField(
        null=True,
        blank=True,
        help_text=_("Default end time"),
        verbose_name=_("Default End Time"),
    )

    # Status
    is_default = models.BooleanField(
        default=False,
        help_text=_("Default Business Hour"),
        verbose_name=_("Is Default"),
    )

    holidays = models.ManyToManyField(
        "Holiday",
        blank=True,
        related_name="business_hours",
        verbose_name=_("Holidays"),
        help_text=_("Company holidays associated with this business hour schedule."),
    )

    class Meta:
        """
        Meta options for the BusinessHour model.
        """

        verbose_name = _("Business Hour")
        verbose_name_plural = _("Business Hours")
        ordering = ["name"]

    #: At most one row per company in the UI (enforced in :class:`BusinessHourForm`).
    BUSINESS_HOUR_PER_COMPANY_LIMIT = 1

    def __str__(self):
        return f"{self.name} ({self.get_business_hour_type_display()})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    def get_edit_url(self):
        """
        Get the URL for editing the business hour
        """
        return reverse_lazy("core:business_hour_update_form", kwargs={"pk": self.pk})

    def get_card_active_day_codes(self):
        """Weekday short codes (mon..sun) when the business is open."""
        if self.business_hour_type == "24_7":
            return list(self.WEEK_ORDER)
        if self.business_hour_type == "24_5":
            sel = self.normalized_week_day_codes()
            return sel if sel else list(self.WEEK_ORDER[:5])
        if self.business_hour_type == "custom":
            return self.normalized_week_day_codes()
        return []

    def get_card_business_days_label(self):
        """Comma-separated open days for the summary card."""
        active = set(self.get_card_active_day_codes())
        labels = [str(self.DAY_LABELS[d]) for d in self.WEEK_ORDER if d in active]
        return ", ".join(labels) if labels else "—"

    def get_card_business_days_compact(self):
        """
        Compact label for open days: \"Monday – Sunday\", \"Monday – Friday\",
        or a comma list when days are not one contiguous block.
        """
        active_ordered = [
            d for d in self.WEEK_ORDER if d in set(self.get_card_active_day_codes())
        ]
        if not active_ordered:
            return "—"
        if len(active_ordered) == 7:
            return _format_card_time_range(
                str(self.DAY_LABELS[active_ordered[0]]),
                str(self.DAY_LABELS[active_ordered[-1]]),
            )
        idxs = [self.WEEK_ORDER.index(d) for d in active_ordered]
        consecutive = all(idxs[i + 1] - idxs[i] == 1 for i in range(len(idxs) - 1))
        if consecutive and len(active_ordered) > 1:
            return _format_card_time_range(
                str(self.DAY_LABELS[active_ordered[0]]),
                str(self.DAY_LABELS[active_ordered[-1]]),
            )
        return ", ".join(str(self.DAY_LABELS[d]) for d in active_ordered)

    def get_card_different_hours_week_rows(self):
        """
        For custom + different timing: one row per weekday (Mon→Sun) with hours
        or \"Closed\" (Zoho-style business days block).
        """
        if (
            self.business_hour_type != "custom"
            or (self.timing_type or "") != "different"
        ):
            return None

        def fmt(t):
            if not t:
                return "—"
            return time_format(t, "P")

        selected = set(self.normalized_week_day_codes())
        # One entry per weekday: [first_code, last_code, hours_text]
        groups = []
        for day_code in self.WEEK_ORDER:
            if day_code not in selected:
                hours = str(_("Closed"))
            else:
                prefix = self.SHORT_TO_DAY_PREFIX[day_code]
                start_val = getattr(self, f"{prefix}_start", None)
                end_val = getattr(self, f"{prefix}_end", None)
                if self._is_midnight(start_val) and self._is_midnight(end_val):
                    hours = str(_("Closed"))
                else:
                    hours = _format_card_time_range(fmt(start_val), fmt(end_val))
            # Merge consecutive days that share the same hours (e.g. Mon – Fri)
            if groups and groups[-1][2] == hours:
                groups[-1][1] = day_code
            else:
                groups.append([day_code, day_code, hours])

        nbsp = "\u00a0"
        rows = []
        for first, last, hours in groups:
            first_label = str(self.DAY_LABELS[first])
            if first == last:
                day = first_label
            else:
                day = f"{first_label}{nbsp}\u2013{nbsp}{str(self.DAY_LABELS[last])}"
            rows.append({"day": day, "hours": hours})
        return rows

    def get_card_closed_days_label(self):
        """Comma-separated closed days (or none)."""
        if self.business_hour_type == "24_7":
            return str(_("None"))
        active = set(self.get_card_active_day_codes())
        closed = [str(self.DAY_LABELS[d]) for d in self.WEEK_ORDER if d not in active]
        if not closed:
            return str(_("None"))
        return ", ".join(closed)

    def get_card_hours_lines(self):
        """
        Lines for the “Business hours” block on the summary card (one string per row).
        """

        def fmt(t):
            if not t:
                return "—"
            return time_format(t, "P")

        if self.business_hour_type in ("24_7", "24_5"):
            return [str(_("24 hours"))]
        if self.business_hour_type == "custom" and (self.timing_type or "") == "same":
            if not self.default_start_time or not self.default_end_time:
                return ["—"]
            return [
                _format_card_time_range(
                    fmt(self.default_start_time),
                    fmt(self.default_end_time),
                )
            ]
        if (
            self.business_hour_type == "custom"
            and (self.timing_type or "") == "different"
        ):
            # Per-day lines are rendered via get_card_different_hours_week_rows().
            return []
        return ["—"]

    def normalized_week_day_codes(self):
        """
        Return weekday short codes (mon, tue, ...) stored on week_days / multiselect.
        """
        raw = self.week_days
        if isinstance(raw, (list, tuple)):
            selected = list(raw)
        elif isinstance(raw, str) and raw.strip():
            selected = [p.strip() for p in raw.replace(",", " ").split() if p.strip()]
        else:
            selected = []
        return selected

    def get_card_holidays_label(self):
        """Comma-separated holiday names for the summary card (by start date)."""
        all_h = list(self.holidays.order_by("start_date", "name"))
        if not all_h:
            return ""
        if len(all_h) > 50:
            return ", ".join(str(h.name) for h in all_h[:50]) + " (+{})".format(
                len(all_h) - 50
            )
        return ", ".join(str(h.name) for h in all_h)

    @staticmethod
    def _is_midnight(t):
        return t is None or t == time(0, 0)


class ShiftHour(BusinessHourDayMixin, HorillaCoreModel):
    """
    Stand-alone named shift ,main working hours, optional breaks, optional users.
    """

    SHIFT_HOUR_LIMIT = 50

    TIMING_CHOICES = TIMING_CHOICES
    DAY_LABELS = DAY_LABELS
    WEEK_ORDER = WEEK_ORDER
    SHORT_TO_DAY_PREFIX = SHORT_TO_DAY_PREFIX
    BREAK_MODE_CHOICES = [
        ("none", _("No break hours")),
        ("same", _("Same hours every day")),
        ("different", _("Different hours every day")),
    ]

    name = models.CharField(max_length=255, verbose_name=_("Name"))
    time_zone = models.CharField(
        max_length=100,
        choices=TIMEZONE_CHOICES,
        default="UTC",
        verbose_name=_("Time Zone"),
    )
    timing_type = models.CharField(
        max_length=10,
        choices=TIMING_CHOICES,
        default="same",
        help_text=_("Same hours every day or different hours per day"),
        verbose_name=_("Shift Hours"),
    )
    week_days = MultiSelectField(
        choices=DAY_CHOICES, blank=True, verbose_name=_("Week Days")
    )
    default_start_time = models.TimeField(
        null=True,
        blank=True,
        verbose_name=_("Default Start Time"),
    )
    default_end_time = models.TimeField(
        null=True,
        blank=True,
        verbose_name=_("Default End Time"),
    )

    break1_mode = models.CharField(
        max_length=12,
        choices=BREAK_MODE_CHOICES,
        default="none",
        verbose_name=_("Break Hours 1"),
    )
    break1_week_days = MultiSelectField(choices=DAY_CHOICES, blank=True)
    break1_default_start = models.TimeField(
        null=True,
        blank=True,
        verbose_name=_("Break 1 Default Start"),
    )
    break1_default_end = models.TimeField(
        null=True,
        blank=True,
        verbose_name=_("Break 1 Default End"),
    )
    break1_per_day = models.JSONField(
        default=dict,
        blank=True,
        help_text=_('Per-day break times when mode is "different" (mon..sun keys).'),
        verbose_name=_("Break 1 Per-Day Times"),
    )

    break2_mode = models.CharField(
        max_length=12,
        choices=BREAK_MODE_CHOICES,
        default="none",
        verbose_name=_("Break Hours 2"),
    )
    break2_week_days = MultiSelectField(choices=DAY_CHOICES, blank=True)
    break2_default_start = models.TimeField(
        null=True,
        blank=True,
        verbose_name=_("Break 2 Default Start"),
    )
    break2_default_end = models.TimeField(
        null=True,
        blank=True,
        verbose_name=_("Break 2 Default End"),
    )
    break2_per_day = models.JSONField(
        default=dict,
        blank=True,
        help_text=_('Per-day break times when mode is "different" (mon..sun keys).'),
        verbose_name=_("Break 2 Per-Day Times"),
    )

    assigned_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="shift_hours",
        verbose_name=_("Assigned Users"),
    )

    class Meta:
        """
        Meta options for the ShiftHour model.
        """

        verbose_name = _("Shift Hour")
        verbose_name_plural = _("Shift Hours")
        ordering = ["name"]

    def __str__(self):
        return str(self.name)

    @staticmethod
    def _is_midnight(t):
        return t is None or t == time(0, 0)

    def normalized_week_day_codes(self):
        """Weekday codes selected for this shift."""
        raw = self.week_days
        if isinstance(raw, (list, tuple)):
            selected = list(raw)
        elif isinstance(raw, str) and raw.strip():
            selected = [p.strip() for p in raw.replace(",", " ").split() if p.strip()]
        else:
            selected = []
        return selected

    def get_shift_bounds_for_day(self, short_code):
        """Return (start, end) for the main shift on a weekday code, or None if closed."""
        if short_code not in WEEK_ORDER:
            return None
        selected = set(self.normalized_week_day_codes())
        if short_code not in selected:
            return None
        if self.timing_type == "same":
            if not self.default_start_time or not self.default_end_time:
                return None
            return (self.default_start_time, self.default_end_time)
        if self.timing_type == "different":
            prefix = self.SHORT_TO_DAY_PREFIX[short_code]
            start_val = getattr(self, f"{prefix}_start", None)
            end_val = getattr(self, f"{prefix}_end", None)
            if self._is_midnight(start_val) and self._is_midnight(end_val):
                return None
            return (start_val, end_val)
        return None

    def get_avatar(self):
        """Method will return the API to the avatar or path to the profile image. For now, using ui-avatars.com with random background."""
        url = f"https://ui-avatars.com/api/?name={self.name}&background=random"
        return url

    def get_edit_url(self):
        """Get the URL for editing the shift hour."""
        return reverse_lazy("core:shift_hour_update_form", kwargs={"pk": self.pk})

    def get_delete_url(self):
        """Get the URL for deleting the shift hour."""
        return reverse_lazy("core:shift_hour_delete_view", kwargs={"pk": self.pk})

    def get_detail_url(self):
        """Get the URL for shift hour detail view."""
        return reverse_lazy("core:shift_hour_detail_view", kwargs={"pk": self.pk})

    def get_assigned_users_count_display(self):
        """Return the count of assigned users, or "No users assigned" if none."""
        n = self.assigned_users.count()
        return str(n) if n else _("No users assigned")

    @staticmethod
    def _render_day_groups(day_values, empty_label):
        """
        Table rows of consecutive days sharing the same value, e.g. "Mon - Fri".

        ``day_values`` maps weekday codes to a text (or ``None`` for ``empty_label``).
        Days missing from it are left out and never merged across.
        """
        groups = []
        for day_code in WEEK_ORDER:
            if day_code not in day_values:
                continue
            text = day_values[day_code] or empty_label
            if (
                groups
                and groups[-1][2] == text
                and WEEK_ORDER.index(day_code) == WEEK_ORDER.index(groups[-1][1]) + 1
            ):
                groups[-1][1] = day_code
            else:
                groups.append([day_code, day_code, text])

        rows = []
        for first, last, text in groups:
            first_label = str(DAY_LABELS[first])[:3]
            if first == last:
                label = first_label
            else:
                label = f"{first_label} - {str(DAY_LABELS[last])[:3]}"
            rows.append((label, text))

        return format_html(
            "<table class='text-start align-top'>{}</table>",
            format_html_join(
                "",
                "<tr class='text-xs'>"
                "<td class='pe-3 py-0.5 text-gray-600 whitespace-nowrap'>{}</td>"
                "<td class='py-0.5 font-semibold text-black whitespace-nowrap'>{}</td>"
                "</tr>",
                rows,
            ),
        )

    def get_formatted_week_days(self):
        """Compact HTML summary of the shift days and hours (list views)."""
        return self._format_week_days(detailed=False)

    def get_formatted_week_days_detail(self):
        """HTML summary of the shift days and hours, one row per day when they differ."""
        return self._format_week_days(detailed=True)

    def _format_week_days(self, detailed):
        """Build the days/hours HTML; ``detailed`` expands per-day hours into a table."""

        def format_time_value(value):
            if not value:
                return "--:--"
            return time_format(value, "P")

        def is_midnight(t):
            return t is None or t == time(0, 0)

        def day_range_label(codes):
            """'Monday - Saturday' for one consecutive run, else a comma list."""
            labels = [str(DAY_LABELS[d]) for d in codes]
            idxs = [WEEK_ORDER.index(d) for d in codes]
            if len(codes) > 1 and idxs[-1] - idxs[0] == len(idxs) - 1:
                return f"{labels[0]} - {labels[-1]}"
            return ", ".join(labels)

        selected = self.normalized_week_day_codes()
        ordered = [d for d in WEEK_ORDER if d in selected]

        if self.timing_type == "same":
            start = format_time_value(self.default_start_time)
            end = format_time_value(self.default_end_time)
            if ordered:
                return format_html(
                    "<div><div class='whitespace-nowrap'>{}</div>"
                    "<strong>({} – {})</strong></div>",
                    day_range_label(ordered),
                    start,
                    end,
                )
            return format_html("{} – {}", start, end)

        if self.timing_type == "different":
            hours = {}
            for day_code in ordered:
                prefix = DAY_LABELS[day_code].lower()
                start_val = getattr(self, f"{prefix}_start", None)
                end_val = getattr(self, f"{prefix}_end", None)
                if not (is_midnight(start_val) and is_midnight(end_val)):
                    hours[day_code] = (start_val, end_val)

            if not detailed:
                open_days = [d for d in ordered if d in hours]
                if not open_days:
                    return format_html("—")
                if len(set(hours.values())) == 1:
                    start_val, end_val = hours[open_days[0]]
                    summary = format_html(
                        "<strong>({} – {})</strong>",
                        format_time_value(start_val),
                        format_time_value(end_val),
                    )
                else:
                    summary = format_html(
                        "<span class='text-gray-600'>{}</span>",
                        _("Hours vary by day"),
                    )
                return format_html(
                    "<div><div class='whitespace-nowrap'>{}</div>{}</div>",
                    day_range_label(open_days),
                    summary,
                )

            return self._render_day_groups(
                {
                    day_code: (
                        "{} – {}".format(
                            format_time_value(hours[day_code][0]),
                            format_time_value(hours[day_code][1]),
                        )
                        if day_code in hours
                        else None
                    )
                    for day_code in WEEK_ORDER
                },
                str(_("Closed")),
            )

        return format_html("—")

    def get_assigned_users_label(self):
        """User pills for assigned users in detail views."""
        # Local imports: generics template tags import core models
        from horilla.contrib.generics.templatetags.horilla_tags._shared import (
            _get_request_user_company,
        )
        from horilla.contrib.generics.templatetags.horilla_tags.display_tags import (
            render_user_chip_list,
        )

        users = list(self.assigned_users.all())
        if not users:
            return _("No users assigned")
        _request, viewer, _company = _get_request_user_company()
        return render_user_chip_list(
            users,
            viewer,
            self,
            "detail",
            str(self._meta.get_field("assigned_users").verbose_name),
        )

    def get_break_slot_brief(self, slot):
        """Short text for break 1 or 2 (slot is 'break1' or 'break2')."""
        mode = getattr(self, f"{slot}_mode", "none")
        if mode == "none":
            return str(_("None"))
        if mode == "same":
            ds = getattr(self, f"{slot}_default_start")
            de = getattr(self, f"{slot}_default_end")
            if ds and de:
                return f"{time_format(ds, 'P')} – {time_format(de, 'P')}"
            return str(_("Same (incomplete)"))
        return str(_("Different per day"))

    def get_break_slot_detail(self, slot):
        """Days and times of break 1 or 2 (slot is 'break1' or 'break2'), grouped by day."""
        mode = getattr(self, f"{slot}_mode", "none")
        if mode == "none":
            return str(_("None"))

        def parse_time(value):
            if not isinstance(value, str):
                return value
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    return datetime.strptime(value, fmt).time()
                except ValueError:
                    continue
            return None

        def format_range(start, end):
            if not (start and end):
                return None
            return f"{time_format(start, 'P')} – {time_format(end, 'P')}"

        raw = getattr(self, f"{slot}_week_days", None)
        if isinstance(raw, str):
            raw = raw.replace(",", " ").split()
        selected = set(raw or [])

        # Only working days are listed; closed days have no break to show
        day_values = {}
        for day_code in WEEK_ORDER:
            if self.get_shift_bounds_for_day(day_code) is None:
                continue
            if day_code not in selected:
                day_values[day_code] = None
                continue
            if mode == "same":
                start = getattr(self, f"{slot}_default_start", None)
                end = getattr(self, f"{slot}_default_end", None)
            else:
                pair = (getattr(self, f"{slot}_per_day", None) or {}).get(day_code)
                if not pair or len(pair) != 2:
                    day_values[day_code] = None
                    continue
                start, end = parse_time(pair[0]), parse_time(pair[1])
            day_values[day_code] = format_range(start, end)

        if not any(day_values.values()):
            return str(_("None"))
        return self._render_day_groups(day_values, str(_("No break")))

    def get_break1_brief(self):
        """Short text for break 1 to show in detail view."""
        return self.get_break_slot_brief("break1")

    def get_break2_brief(self):
        """Short text for break 2 to show in detail view."""
        return self.get_break_slot_brief("break2")

    def get_break1_detail(self):
        """Break 1 days and times for the detail view."""
        return self.get_break_slot_detail("break1")

    def get_break2_detail(self):
        """Break 2 days and times for the detail view."""
        return self.get_break_slot_detail("break2")
