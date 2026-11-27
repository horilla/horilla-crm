"""
Jalali (Shamsi) calendar helpers.

Gregorian values stay in the database. These utilities convert for display
and parse user-facing Jalali input when the Shamsi calendar is active.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any

import jdatetime

from horilla.utils.translation import get_language
from horilla.utils.translation import gettext_lazy as _

CALENDAR_SYSTEM_CHOICES = [
    ("jalali", _("Shamsi (Jalali)")),
    ("gregorian", _("Gregorian")),
]

JALALI_DATE_FORMATS = (
    "%Y/%m/%d",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
)

JALALI_DATETIME_FORMATS = (
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
)


def normalize_language_code(language: str | None) -> str:
    """Return the primary language subtag (e.g. ``fa`` from ``fa-ir``)."""
    if not language:
        return ""
    return language.replace("_", "-").split("-")[0].lower()


def get_active_language(user: Any = None) -> str:
    """Return the active UI language."""
    return normalize_language_code(get_language())


def uses_jalali_calendar(user: Any = None, language: str | None = None) -> bool:
    """
    Return True when the UI should use the Shamsi calendar.

    Applies to Persian (``fa``) unless the user opted into Gregorian
    via ``calendar_system``.
    """
    lang = language or get_active_language(user)
    if lang != "fa":
        return False
    if user is None:
        return True
    system = getattr(user, "calendar_system", None) or "jalali"
    return system == "jalali"


def shamsi_period_bounds(period: str, day: date) -> tuple[date, date] | None:
    """
    Gregorian ``(start, end)`` of the Shamsi ``"week"`` or ``"month"`` holding ``day``.

    The week runs Saturday to Friday, as in Iran. Returns ``None`` for any
    other ``period``.
    """
    if period == "week":
        # weekday(): Monday is 0, so Saturday is 5.
        start = day - timedelta(days=(day.weekday() + 2) % 7)
        return start, start + timedelta(days=6)
    if period == "month":
        shamsi = jdatetime.date.fromgregorian(date=day)
        if shamsi.month == 12:
            next_month = jdatetime.date(shamsi.year + 1, 1, 1)
        else:
            next_month = jdatetime.date(shamsi.year, shamsi.month + 1, 1)
        start = jdatetime.date(shamsi.year, shamsi.month, 1).togregorian()
        return start, next_month.togregorian() - timedelta(days=1)
    return None


def _is_plausible_jalali_year(year: int) -> bool:
    return 1200 <= year <= 1600


def _first_directive_index(fmt: str, chars: str) -> int | None:
    for match in re.finditer(r"%-?[A-Za-z]", fmt):
        if match.group(0)[-1] in chars:
            return match.start()
    return None


_AMPM_TEXT = re.compile(
    r"\s*(?:قبل از ظهر|بعد از ظهر|ق\.?\s*ظ|ب\.?\s*ظ|A\.?M\.?|P\.?M\.?)\s*$",
    re.IGNORECASE,
)

_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_ASCII_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def to_persian_digits(text: str) -> str:
    """Map ASCII digits to Persian (fa) digits."""
    if not text:
        return text
    return text.translate(_PERSIAN_DIGITS)


def to_ascii_digits(text: str) -> str:
    """Map Persian / Arabic-Indic digits to ASCII so parsers still work."""
    if not text:
        return text
    return text.translate(_ASCII_DIGITS)


def to_persian_date_digits(text: str) -> str:
    """Map every digit in a Shamsi date/time string to Persian digits."""
    return to_persian_digits(text)


_SECONDS_TAIL = re.compile(r"(\d{1,2}:\d{2}):\d{2}(?:\.\d+)?")


def drop_seconds_strftime(fmt: str) -> str:
    """``%H:%M:%S`` → ``%H:%M`` (History Shamsi times have no seconds)."""
    if not fmt:
        return fmt
    out = re.sub(r"%[-]?[Sf]", "", fmt)
    out = re.sub(r"[:.]+(?=\s|$)", "", out)
    return re.sub(r"\s+", " ", out).strip()


def to_persian_datetime_digits(text: str) -> str:
    """Persian digits for the whole datetime; drop seconds from HH:MM:SS."""
    if not text:
        return text
    prefix = suffix = ""
    inner = text
    if inner.startswith("\u2066") and inner.endswith("\u2069"):
        prefix, suffix = "\u2066", "\u2069"
        inner = inner[1:-1]
    inner = strip_ampm_suffix(to_ascii_digits(inner))
    inner = _SECONDS_TAIL.sub(r"\1", inner)
    return f"{prefix}{to_persian_digits(inner)}{suffix}"


def to_24h_strftime(fmt: str) -> str:
    """Use 24-hour time and drop AM/PM (``%p`` → بعد از ظهر / قبل از ظهر)."""
    if not fmt:
        return fmt
    out = fmt.replace("%-I", "%-H").replace("%I", "%H")
    out = re.sub(r"\s*%-?[pP]", "", out)
    return drop_seconds_strftime(out.strip())


def strip_ampm_suffix(text: str) -> str:
    """Remove trailing AM/PM labels from an already-formatted datetime."""
    if not text:
        return text
    return _AMPM_TEXT.sub("", text).rstrip()


def jalali_strftime_format(fmt: str) -> str:
    """
    Adapt a Gregorian ``strftime`` pattern for Persian Jalali display.

    Named-month formats such as ``%b %d %Y`` become ``%d %B %Y`` so the
    result is ``23 مرداد 1405`` instead of ``Mor 23 1405``.
    Datetime patterns with time before date are reordered to date-first.
    12-hour ``%I`` / ``%p`` becomes 24-hour (no بعد از ظهر / قبل از ظهر).
    """
    if not fmt:
        return fmt
    out = to_24h_strftime(fmt.replace("%b", "%B").replace("%a", "%A"))
    out = re.sub(r"%B(\s*),?\s*%d", r"%d\1%B", out)
    out = re.sub(r"%d\s*,\s*%B", "%d %B", out)
    out = re.sub(r"%B\s*,\s*%Y", "%B %Y", out)

    date_idx = _first_directive_index(out, "YymdbBAUWwxX")
    time_idx = _first_directive_index(out, "HIMSf")
    if date_idx is not None and time_idx is not None and time_idx < date_idx:
        parts = out.split()
        if len(parts) == 2:
            return f"{parts[1]} {parts[0]}"
    return out


def preserve_rtl_datetime_order(text: str) -> str:
    """
    Keep date-before-time visual order on RTL pages.

    Numeric datetimes such as ``1405-05-12 19:52:00`` are two LTR runs; in
    RTL layout the browser often shows ``19:52:00 1405-05-12``. Wrapping in
    LRI/PDI keeps the formatted order.
    """
    if not text:
        return text
    return f"\u2066{text}\u2069"


def format_gregorian_as_jalali(value: date | datetime | time, fmt: str) -> str:
    """Format a Gregorian value using Jalali calendar parts and Persian names."""
    if isinstance(value, time) and not isinstance(value, datetime):
        return value.strftime(fmt)

    jalali_fmt = jalali_strftime_format(fmt)
    if isinstance(value, datetime):
        jalali_value = jdatetime.datetime.fromgregorian(
            datetime=value, locale=jdatetime.FA_LOCALE
        )
        formatted = to_persian_datetime_digits(
            strip_ampm_suffix(jalali_value.strftime(jalali_fmt))
        )
        return preserve_rtl_datetime_order(formatted)
    jalali_value = jdatetime.date.fromgregorian(date=value, locale=jdatetime.FA_LOCALE)
    return to_persian_digits(jalali_value.strftime(jalali_fmt))


_BIDI_MARKS = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_LOCALIZED_GREGORIAN = re.compile(
    r"(?P<day>\d{1,2})\s+(?P<month>\S+)\s+(?P<year>\d{4})"
    r"(?:[،,]?\s*(?:ساعت\s*)?(?P<hour>\d{1,2}):(?P<minute>\d{2})"
    r"(?::(?P<second>\d{2}))?)?",
    re.UNICODE,
)

# Django fa locale uses «اوت» for August; keep extra spellings too.
_GREGORIAN_MONTHS = {
    "january": 1,
    "jan": 1,
    "ژانویه": 1,
    "february": 2,
    "feb": 2,
    "فوریه": 2,
    "march": 3,
    "mar": 3,
    "مارس": 3,
    "april": 4,
    "apr": 4,
    "آوریل": 4,
    "may": 5,
    "مه": 5,
    "می": 5,
    "june": 6,
    "jun": 6,
    "ژوئن": 6,
    "july": 7,
    "jul": 7,
    "ژوئیه": 7,
    "جولای": 7,
    "august": 8,
    "aug": 8,
    "اوت": 8,
    "آگوست": 8,
    "اگست": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "سپتامبر": 9,
    "october": 10,
    "oct": 10,
    "اکتبر": 10,
    "november": 11,
    "nov": 11,
    "نوامبر": 11,
    "december": 12,
    "dec": 12,
    "دسامبر": 12,
}


def _gregorian_month_number(token: str) -> int | None:
    key = (token or "").strip().strip("،,").lower()
    if key in _GREGORIAN_MONTHS:
        return _GREGORIAN_MONTHS[key]
    try:
        from django.utils import dates

        for mapping in (dates.MONTHS, dates.MONTHS_3, dates.MONTHS_ALT):
            for number, name in mapping.items():
                if str(name).strip().lower() == key:
                    return int(number)
    except Exception:
        pass
    return None


def parse_localized_gregorian_display(value: str) -> date | datetime | None:
    """
    Parse Django-localized Gregorian strings such as
    ``19 اوت 2026، ساعت 8:27`` (fa DATETIME_FORMAT ``j F Y، ساعت G:i``).
    """
    if not value or not str(value).strip():
        return None
    raw = _BIDI_MARKS.sub("", to_ascii_digits(str(value))).strip()
    match = _LOCALIZED_GREGORIAN.search(raw)
    if not match:
        return None
    year = int(match.group("year"))
    if _is_plausible_jalali_year(year) or year < 1700:
        return None
    month = _gregorian_month_number(match.group("month"))
    if not month:
        return None
    day = int(match.group("day"))
    try:
        if match.group("hour") is None:
            return date(year, month, day)
        return datetime(
            year,
            month,
            day,
            int(match.group("hour")),
            int(match.group("minute")),
            int(match.group("second") or 0),
        )
    except ValueError:
        return None


def parse_jalali_date(value: str) -> date | None:
    """Parse a Jalali date string into a Gregorian ``date``."""
    if not value or not str(value).strip():
        return None
    raw = to_ascii_digits(str(value).strip())
    for fmt in JALALI_DATE_FORMATS:
        try:
            jalali_value = jdatetime.datetime.strptime(raw, fmt)
        except ValueError:
            continue
        if _is_plausible_jalali_year(jalali_value.year):
            return jalali_value.togregorian().date()
    return None


def parse_jalali_datetime(value: str) -> datetime | None:
    """Parse a Jalali datetime string into a Gregorian ``datetime``."""
    if not value or not str(value).strip():
        return None
    raw = to_ascii_digits(str(value).strip())
    candidates = (raw, raw.replace("T", " "))
    for candidate in candidates:
        for fmt in JALALI_DATETIME_FORMATS:
            try:
                jalali_value = jdatetime.datetime.strptime(candidate, fmt)
            except ValueError:
                continue
            if _is_plausible_jalali_year(jalali_value.year):
                return jalali_value.togregorian()
    return None
