"""
Choice constants for various form fields and configuration options.

This module contains predefined choice tuples for languages, date/time formats,
currency formats, number grouping, months, days, and operators used throughout
the Horilla application.
"""

# Standard library imports
from zoneinfo import available_timezones

# Third-party imports
import pycountry
import pytz

# Third-party imports (Django)
from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

# Legacy prefixes that pytz still lists: each name is an alias of a Region/City name
# (US/Pacific is America/Los_Angeles) and "GMT" is the old name of UTC.
_LEGACY_TIMEZONE_PREFIXES = ("US/", "Canada/")


def _timezone_choices():
    """
    The time zones a user can pick: ``UTC`` and the ``Region/City`` names.

    ``zoneinfo.available_timezones()`` also holds the server's ``localtime``,
    duplicate aliases of UTC (``Universal``, ``Zulu``, ``UCT``, ``Greenwich``),
    old abbreviations (``CET``, ``EST``, ``W-SU``), the ``Etc/GMT+n`` offsets and
    renamed cities (``Asia/Calcutta``). ``pytz.common_timezones`` leaves those out,
    so only its names that the system also knows are kept, minus the legacy
    ``US/`` and ``Canada/`` aliases.
    """
    known = available_timezones()
    return sorted(
        (tz, tz)
        for tz in pytz.common_timezones
        if tz in known and tz != "GMT" and not tz.startswith(_LEGACY_TIMEZONE_PREFIXES)
    )


TIMEZONE_CHOICES = _timezone_choices()


LANGUAGE_CHOICES = [
    ("en", _("English")),
    ("fr", _("French")),
    ("de", _("German")),
    ("es", _("Spanish")),
    ("it", _("Italian")),
    ("pt", _("Portuguese")),
]

CURRENCY_FORMAT_CHOICES = [
    ("western_format", "1,234,567"),
    ("european_format", "1.234.567"),
    ("scientific_format", "1 234 567"),
    ("indian_format", "12,34,567"),
]

DATE_FORMAT_CHOICES = [
    ("%Y-%m-%d", "YYYY-MM-DD (2006-10-25)"),
    ("%m/%d/%Y", "MM/DD/YYYY (10/25/2006)"),
    ("%m/%d/%y", "MM/DD/YY (10/25/06)"),
    ("%b %d %Y", "Mon DD YYYY (Oct 25 2006)"),
    ("%b %d, %Y", "Mon DD, YYYY (Oct 25, 2006)"),
    ("%d %b %Y", "DD Mon YYYY (25 Oct 2006)"),
    ("%d %b, %Y", "DD Mon, YYYY (25 Oct, 2006)"),
    ("%B %d %Y", "Full Month DD YYYY (October 25 2006)"),
    ("%B %d, %Y", "Full Month DD, YYYY (October 25, 2006)"),
    ("%d %B %Y", "DD Full Month YYYY (25 October 2006)"),
    ("%d %B, %Y", "DD Full Month, YYYY (25 October, 2006)"),
]

DATETIME_FORMAT_CHOICES = [
    ("%Y-%m-%d %H:%M:%S", "YYYY-MM-DD HH:MM:SS (2006-10-25 13:45:00)"),
    ("%Y-%m-%d %I:%M:%S %p", "YYYY-MM-DD HH:MM:SS AM/PM (2006-10-25 01:45:00 PM)"),
    ("%m/%d/%Y %H:%M", "MM/DD/YYYY HH:MM (10/25/2006 13:45)"),
    ("%d %b %Y %H:%M:%S", "DD Mon YYYY HH:MM:SS (25 Oct 2006 13:45:00)"),
    ("%d %B %Y %I:%M %p", "DD Full Month YYYY HH:MM AM/PM (25 October 2006 01:45 PM)"),
    ("%b %d, %Y %I:%M:%S %p", "Mon DD, YYYY HH:MM:SS AM/PM (Oct 25, 2006 01:45:00 PM)"),
    ("%d-%m-%Y %H:%M:%S", "DD-MM-YYYY HH:MM:SS (25-10-2006 13:45:00)"),
    ("%Y/%m/%d %H:%M:%S", "YYYY/MM/DD HH:MM:SS (2006/10/25 13:45:00)"),
    ("%Y-%m-%dT%H:%M:%S", "ISO 8601 (2006-10-25T13:45:00)"),
    ("%Y-%m-%d %H:%M:%S.%f", "YYYY-MM-DD HH:MM:SS.mmmmmm (2006-10-25 13:45:00.123456)"),
    (
        "%A, %d %B %Y %I:%M %p",
        "Full Weekday, DD Full Month YYYY HH:MM AM/PM (Wednesday, 25 October 2006 01:45 PM)",
    ),
]

NUMBER_FORMAT_CHOICES = [
    ("western_format", _("Western - 1,234,567.89")),
    ("european_format", _("European - 1.234.567,89")),
    ("space_format", _("Space Separated - 1 234 567,89")),
    ("indian_format", _("Indian - 12,34,567.89")),
]

TIME_FORMAT_CHOICES = [
    ("%H:%M:%S", "HH:MM:SS (13:45:00)"),
    ("%I:%M:%S %p", "HH:MM:SS AM/PM (01:45:00 PM)"),
    ("%H:%M", "HH:MM (13:45)"),
    ("%I:%M %p", "HH:MM AM/PM (01:45 PM)"),
    ("%H", "HH (13)"),
    ("%I", "HH (01)"),
    ("%M:%S", "MM:SS (45:00)"),
    ("%S", "SS (00)"),
    ("%p", "AM/PM (PM)"),
    ("%H:%M:%S.%f", "HH:MM:SS.mmmmmm (13:45:00.123456)"),
]

MONTH_CHOICES = [
    ("january", _("January")),
    ("february", _("February")),
    ("march", _("March")),
    ("april", _("April")),
    ("may", _("May")),
    ("june", _("June")),
    ("july", _("July")),
    ("august", _("August")),
    ("september", _("September")),
    ("october", _("October")),
    ("november", _("November")),
    ("december", _("December")),
]

DAY_LABELS = {
    "mon": _("Monday"),
    "tue": _("Tuesday"),
    "wed": _("Wednesday"),
    "thu": _("Thursday"),
    "fri": _("Friday"),
    "sat": _("Saturday"),
    "sun": _("Sunday"),
}

# Sunday-first for legacy pickers (``WEEK_ORDER`` is Mon→Sun — keep these separate).
DAY_CHOICES = [
    (code, DAY_LABELS[code])
    for code in ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
]

# Mon→Sun order for business hours, shifts, and per-day TimeField prefixes.
WEEK_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# BusinessHour.timing_type and ShiftHour.timing_type
TIMING_CHOICES = [
    ("same", _("Same Hour Every Day")),
    ("different", _("Different Hour Per Day")),
]

# Short weekday code → TimeField name prefix (``mon`` → ``monday`` for ``monday_start``)
SHORT_TO_DAY_PREFIX = {
    "mon": "monday",
    "tue": "tuesday",
    "wed": "wednesday",
    "thu": "thursday",
    "fri": "friday",
    "sat": "saturday",
    "sun": "sunday",
}

OPERATOR_CHOICES = [
    ("exact", _("Equals")),
    ("ne", _("Not Equals")),
    ("icontains", _("Contains")),
    ("not_contains", _("Does Not Contain")),
    ("istartswith", _("Starts With")),
    ("iendswith", _("Ends With")),
    ("gt", _("Greater Than")),
    ("gte", _("Greater Than or Equal")),
    ("lt", _("Less Than")),
    ("lte", _("Less Than or Equal")),
    ("isnull", _("Is Empty")),
    ("isnotnull", _("Is Not Empty")),
    ("between", _("Between")),
]

# IMPORTANT: Order matters — do not change the order of these lists
DISPLAYABLE_FIELD_TYPES = [
    "CharField",
    "TextField",
    "BooleanField",
    "DateField",
    "DateTimeField",
    "TimeField",
    "EmailField",
    "URLField",
]

TABLE_FALLBACK_FIELD_TYPES = [
    "CharField",
    "TextField",
    "EmailField",
]

FIELD_TYPE_MAP = {
    "CharField": "text",
    "TextField": "text",
    "BooleanField": "boolean",
    "IntegerField": "number",
    "FloatField": "float",
    "DecimalField": "decimal",
    "ForeignKey": "foreignkey",
    "DateField": "date",
    "DateTimeField": "datetime",
}

BLOCKED_EXTENSIONS = {
    ".sqlite3",
    ".py",
    ".env",
    ".key",
    ".pem",
    ".ini",
    ".conf",
}


def get_subdivision_choices(country_code):
    """
    Return (code, name) subdivision choices for a given ISO country code,
    with a leading blank choice so the <select> doesn't default to the
    first real subdivision when no value (or an unmatched legacy value)
    is selected.
    """
    try:
        subdivisions = list(
            pycountry.subdivisions.get(country_code=country_code.upper())
        )
        return [("", "---------")] + [(sub.code, sub.name) for sub in subdivisions]
    except Exception:
        return [("", "---------")]


def resolve_subdivision_choice(choices, stored_value):
    """
    Match a stored state/subdivision value against (code, name) choices.

    Older records may hold a plain name (e.g. "Georgia") instead of the ISO
    subdivision code (e.g. "US-GA") that the dropdown now submits. Matching
    by code first, then falling back to a case-insensitive name match, keeps
    the correct option selected either way so the field is never silently
    reset to the first choice in the list.
    """
    if not stored_value:
        return stored_value
    for code, name in choices:
        if stored_value == code:
            return code
    for code, name in choices:
        if stored_value.casefold() == name.casefold():
            return code
    return stored_value


def get_allowed_language_choices():
    """
    Return ``settings.ALLOWED_LANGUAGES`` as ``[(code, label), ...]`` choices.
    """
    return [(code, _(name)) for code, name, _flag in settings.ALLOWED_LANGUAGES]


def get_company_language_choices(company):
    """
    Return the languages selected on ``company`` as ``[(code, label), ...]``.

    Falls back to ``settings.ALLOWED_LANGUAGES`` when there is no company or the
    company has no language selected yet.
    """
    codes = list(getattr(company, "language", None) or [])
    if not codes:
        return get_allowed_language_choices()
    labels = dict(settings.LANGUAGES)
    return [(code, _(labels.get(code, code))) for code in codes]


def limit_language_choices(form, company=None):
    """
    Restrict the options of the form's ``language`` field (single or multi-select).

    With a ``company`` the options are the languages selected on that company;
    without one they are ``settings.ALLOWED_LANGUAGES``. The model field still
    accepts every language in ``settings.LANGUAGES``. Languages already saved on
    the record that are not in the list stay as extra options, so opening and
    re-saving it does not blank out or reject them.
    """
    field = form.fields.get("language")
    if field is None:
        return

    choices = (
        get_company_language_choices(company)
        if company is not None
        else get_allowed_language_choices()
    )
    saved = form.instance.language if form.instance.pk else None
    saved = [saved] if isinstance(saved, str) else list(saved or [])
    labels = dict(settings.LANGUAGES)
    known = {code for code, _name in choices}
    choices += [
        (code, _(labels.get(code, code))) for code in saved if code not in known
    ]

    if isinstance(field, forms.MultipleChoiceField):
        # Same chips dropdown the rest of the CRM uses for multi-selects.
        field.widget = forms.SelectMultiple(
            attrs={
                "class": "js-example-basic-multiple headselect w-full",
                "data-placeholder": _("Select Language(s)"),
            }
        )
        field.choices = choices
    else:
        field.choices = [("", "---------")] + choices


def limit_language_choices_to_company(form):
    """
    Limit a user form's ``language`` dropdown to the languages selected on the
    user's company: the edited user's company, else the current user's.
    """
    company = getattr(form.instance, "company", None) if form.instance.pk else None
    if company is None:
        request = getattr(form, "request", None)
        company = getattr(getattr(request, "user", None), "company", None)
    limit_language_choices(form, company)
