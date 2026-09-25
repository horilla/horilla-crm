"""Helpers for custom-field names, widgets, labels, and stored values."""

import re
from calendar import monthrange
from datetime import timedelta

from django import forms

from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.forms.form_class_mixin import WIDGET_INPUT_CSS_CLASS_NO_PR
from horilla.contrib.utils.middlewares import get_current_request
from horilla.utils import timezone
from horilla.utils.html import strip_tags
from horilla.utils.translation import gettext as _

from .models import (
    CustomFieldDefinition,
    CustomFieldValue,
    format_choice_display,
    parse_choice_values,
    to_date_value,
    to_datetime_value,
)

SELECT2_MULTI_CLASS = "js-example-basic-multiple headselect w-full"

CUSTOM_FIELD_PREFIX = "cf_"

_UNSAFE_LABEL_CHARS = re.compile(r"[^\w\s.-]", re.UNICODE)

INLINE_FIELD_TYPES = {
    "small_text": "text",
    "large_text": "textarea",
    "number": "number",
    "choice": "select",
    "single_choice": "select",
    "date": "date",
    "datetime": "datetime-local",
}

DATE_FIELD_TYPES = ("date", "datetime")

RELATIVE_DATE_OPERATORS = ("today", "yesterday", "this_week", "this_month")

# Wire formats of ``<input type="date">`` / ``<input type="datetime-local">``.
# The Jalali picker (horilla_jalali) submits these same Gregorian formats.
DATE_INPUT_FORMAT = "%Y-%m-%d"
DATETIME_INPUT_FORMAT = "%Y-%m-%dT%H:%M"


def is_custom_field_name(name):
    """Return True if ``name`` is a custom-field form/detail key (``cf_<id>``)."""
    return str(name).startswith(CUSTOM_FIELD_PREFIX)


def custom_field_form_name(definition):
    """Return the form/detail key for a ``CustomFieldDefinition``."""
    return f"{CUSTOM_FIELD_PREFIX}{definition.pk}"


def parse_custom_field_pk(name):
    """Return the definition pk from ``cf_<id>``, or None if the name is invalid."""
    if not is_custom_field_name(name):
        return None
    try:
        return int(str(name)[len(CUSTOM_FIELD_PREFIX) :])
    except (TypeError, ValueError):
        return None


def assign_custom_field_attr(obj, key, value):
    """Store a ``cf_*`` value on the instance without going through Django fields."""
    obj.__dict__[key] = "" if value is None else value


def safe_custom_field_label(definition):
    """
    Label safe for Horilla's Details-tab input ids (``{{ col.0 }}-details-tab``).

    HTML in the field name is stripped so HTMX ``querySelector`` does not
    receive ``<``, quotes, or other selector-breaking characters.
    """
    raw = str(getattr(definition, "name", "") or "")
    text = strip_tags(raw)
    text = _UNSAFE_LABEL_CHARS.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" .-")
    if not text:
        return f"{_('Custom Field')} {definition.pk}"
    return text


def get_definition_by_form_name(model, field_name):
    """
    Return the active ``CustomFieldDefinition`` for ``field_name`` on ``model``.

    ``field_name`` must be ``cf_<id>`` and belong to this model's content type.
    """
    pk = parse_custom_field_pk(field_name)
    if pk is None:
        return None
    ct = HorillaContentType.objects.get_for_model(model)
    try:
        return CustomFieldDefinition.objects.get(pk=pk, content_type=ct, is_active=True)
    except CustomFieldDefinition.DoesNotExist:
        return None


def get_custom_field_definitions(model):
    """Return all active custom field definitions for a given model class.

    Several independent hooks (detail, list, filter, integration) each call
    this per request for the same model; cache the result on the current
    request object so it's fetched at most once per request instead of once
    per caller. Caching on the request (rather than a thread-local) avoids
    leaking stale results into a later request handled by the same worker.
    """
    ct = HorillaContentType.objects.get_for_model(model)
    request = get_current_request()
    cache = (
        getattr(request, "_custom_field_definitions_cache", None) if request else None
    )
    if cache is None:
        cache = {}
        if request is not None:
            request._custom_field_definitions_cache = cache
    if ct.pk not in cache:
        cache[ct.pk] = list(
            CustomFieldDefinition.objects.filter(content_type=ct, is_active=True)
        )
    return cache[ct.pk]


def build_custom_form_fields(model):
    """
    Build a dict of Django form fields for all custom field definitions
    attached to the given model. Keys are prefixed with CUSTOM_FIELD_PREFIX.
    """
    fields = {}
    for defn in get_custom_field_definitions(model):
        key = f"{CUSTOM_FIELD_PREFIX}{defn.pk}"
        if defn.field_type == "small_text":
            field = forms.CharField(
                max_length=255,
                required=defn.is_required,
                label=safe_custom_field_label(defn),
                widget=forms.TextInput(
                    attrs={
                        "class": "text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm transition duration-300 focus:border-primary-600",
                        "placeholder": _("Enter %(name)s")
                        % {"name": safe_custom_field_label(defn)},
                    }
                ),
            )
        elif defn.field_type == "large_text":
            field = forms.CharField(
                required=defn.is_required,
                label=safe_custom_field_label(defn),
                widget=forms.Textarea(
                    attrs={
                        "class": "text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm transition duration-300 focus:border-primary-600",
                        "rows": 3,
                        "placeholder": _("Enter %(name)s")
                        % {"name": safe_custom_field_label(defn)},
                    }
                ),
            )
        elif defn.field_type == "number":
            field = forms.DecimalField(
                max_digits=20,
                decimal_places=4,
                required=defn.is_required,
                label=safe_custom_field_label(defn),
                widget=forms.NumberInput(
                    attrs={
                        "class": "text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm transition duration-300 focus:border-primary-600",
                        "placeholder": _("Enter %(name)s")
                        % {"name": safe_custom_field_label(defn)},
                    }
                ),
            )
        elif defn.field_type == "choice":
            choices_list = [(c, c) for c in defn.get_choices_list()]
            field = forms.MultipleChoiceField(
                choices=choices_list,
                required=defn.is_required,
                label=safe_custom_field_label(defn),
                widget=forms.SelectMultiple(
                    attrs={
                        "class": SELECT2_MULTI_CLASS,
                        "data-placeholder": "Select options...",
                    }
                ),
            )
        elif defn.field_type == "single_choice":
            choices_list = [(c, c) for c in defn.get_choices_list()]
            field = forms.ChoiceField(
                choices=[("", "---------")] + choices_list,
                required=defn.is_required,
                label=safe_custom_field_label(defn),
                widget=forms.Select(
                    attrs={
                        "class": "js-example-basic-single headselect w-full",
                        "data-placeholder": "Select an option...",
                    }
                ),
            )
        elif defn.field_type == "date":
            field = forms.DateField(
                required=defn.is_required,
                label=safe_custom_field_label(defn),
                widget=forms.DateInput(
                    attrs={"type": "date", "class": WIDGET_INPUT_CSS_CLASS_NO_PR},
                    format=DATE_INPUT_FORMAT,
                ),
            )
        elif defn.field_type == "datetime":
            field = forms.DateTimeField(
                required=defn.is_required,
                label=safe_custom_field_label(defn),
                widget=forms.DateTimeInput(
                    attrs={
                        "type": "datetime-local",
                        "class": WIDGET_INPUT_CSS_CLASS_NO_PR,
                    },
                    format=DATETIME_INPUT_FORMAT,
                ),
            )
        else:
            continue
        fields[key] = field
    return fields


def load_custom_field_values(model_class, instance_pk):
    """Return a dict of {cf_<defn_pk>: value} for a saved instance."""
    ct = HorillaContentType.objects.get_for_model(model_class)
    values = {}
    for cfv in CustomFieldValue.objects.filter(
        content_type=ct, object_id=instance_pk
    ).select_related("field_definition"):
        key = f"{CUSTOM_FIELD_PREFIX}{cfv.field_definition_id}"
        values[key] = cfv.get_value()
    return values


def save_custom_field_values(model_class, instance_pk, cleaned_data, company=None):
    """
    Persist custom field values from cleaned_data for the given instance.
    Only processes keys that start with CUSTOM_FIELD_PREFIX.

    Skips the write entirely for a field whose submitted value matches what's
    already stored (and whose company doesn't need updating) — callers like
    the "Edit Details" bulk-edit form and the full edit form resubmit every
    custom field on each save regardless of whether the user changed it, so
    without this a no-op save would still rewrite every CustomFieldValue row.

    Returns the set of ``cf_*`` keys that were actually written (i.e. whose
    value differed from what was stored), so callers can tell a real change
    from a no-op resubmission.
    """
    ct = HorillaContentType.objects.get_for_model(model_class)
    changed_keys = set()
    for key, value in cleaned_data.items():
        if not key.startswith(CUSTOM_FIELD_PREFIX):
            continue
        defn_pk = int(key[len(CUSTOM_FIELD_PREFIX) :])
        try:
            defn = CustomFieldDefinition.objects.get(pk=defn_pk)
        except CustomFieldDefinition.DoesNotExist:
            continue
        value = coerce_custom_field_value(defn, value)

        cfv, created = CustomFieldValue.objects.update_or_create(
            field_definition=defn,
            content_type=ct,
            object_id=instance_pk,
            defaults={"company": company} if company else {},
        )
        current_value = cfv.get_value() if not created else None
        if isinstance(current_value, list) or isinstance(value, list):
            unchanged = set(current_value or []) == set(value or [])
        else:
            unchanged = current_value == value
        if not created and unchanged and (not company or cfv.company == company):
            continue
        cfv.set_value(value)
        if company and cfv.company != company:
            cfv.company = company
        cfv.save()
        changed_keys.add(key)
    return changed_keys


def coerce_custom_field_value(definition, value):
    """
    Return ``value`` as the Python type stored for ``definition``.

    Form ``cleaned_data`` is already typed, but the "Edit Details" bulk form
    posts raw strings; coercing both keeps the no-op-save comparison in
    ``save_custom_field_values`` accurate for date and datetime fields.
    """
    if definition.field_type == "date":
        return to_date_value(value)
    if definition.field_type == "datetime":
        return to_datetime_value(value)
    return value


def format_custom_field_display(definition, value):
    """Plain-text value for detail, list, export, and inline display."""
    if definition.field_type == "choice":
        return format_choice_display(value)
    if definition.field_type in DATE_FIELD_TYPES:
        return format_custom_field_date_display(definition, value)
    if value is None:
        return ""
    return str(value)


def format_custom_field_date_display(definition, value):
    """
    Format a date/datetime value with the viewer's date format and calendar.

    Goes through Horilla's composed ``DateTimeFormatter``, so the Jalali
    extension (when installed and enabled for the user) shows Shamsi dates
    while the stored value stays Gregorian.
    """
    from horilla.contrib.generics.templatetags.horilla_tags._shared import (
        _get_request_user_company,
        format_datetime_value,
    )

    value = coerce_custom_field_value(definition, value)
    if value is None:
        return ""
    _request, user, company = _get_request_user_company()
    return format_datetime_value(value, user=user, company=company) or ""


def custom_field_input_value(definition, value):
    """
    Return ``value`` in the wire format of the field's HTML input.

    Datetimes are shown in the active (user) timezone, like Horilla's own
    ``datetime-local`` inputs.
    """
    if definition.field_type == "date":
        parsed = to_date_value(value)
        return parsed.strftime(DATE_INPUT_FORMAT) if parsed else ""
    if definition.field_type == "datetime":
        parsed = to_datetime_value(value)
        if parsed is None:
            return ""
        return timezone.localtime(parsed).strftime(DATETIME_INPUT_FORMAT)
    return value


def choice_values_from_data(value):
    """Normalize POST/session/form data into a list of selected choices."""
    return parse_choice_values(value)


def relative_date_bounds(operator):
    """
    Return inclusive ``(start, end)`` dates for today/yesterday/this_week/this_month.

    Same semantics as ``HorillaFilterSet._get_relative_date_bounds`` (week
    starts on Monday, "today" is the active timezone's local date), so custom
    fields filter exactly like model date fields.
    """
    today = timezone.localdate()
    if operator == "today":
        return today, today
    if operator == "yesterday":
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    if operator == "this_week":
        week_start = today - timedelta(days=today.weekday())
        return week_start, week_start + timedelta(days=6)
    if operator == "this_month":
        last_day = monthrange(today.year, today.month)[1]
        return today.replace(day=1), today.replace(day=last_day)
    return None, None
