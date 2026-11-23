"""
Shift hour form: main schedule, two optional breaks, optional users.

"""

# Standard library imports
from collections import OrderedDict
from datetime import datetime

# Third-party imports (Django)
from django import forms

# First-party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.generics.forms import (
    CheckboxGridSelectMultiple,
    DayQuickFillWidget,
    HorillaModelForm,
)
from horilla.utils.choices import DAY_LABELS, SHORT_TO_DAY_PREFIX, WEEK_ORDER
from horilla.utils.translation import gettext_lazy as _

# Local imports
from ..models import ShiftHour
from .day_time_cards import style_day_time_cards

DAY_ORDER_FULL = tuple(SHORT_TO_DAY_PREFIX[c] for c in WEEK_ORDER)

DAY_ABBR = {
    "mon": _("Mon"),
    "tue": _("Tue"),
    "wed": _("Wed"),
    "thu": _("Thu"),
    "fri": _("Fri"),
    "sat": _("Sat"),
    "sun": _("Sun"),
}

_BREAK_SLOT_ABBR = {"break1": _("B1"), "break2": _("B2")}

_TIME_24H_HELP = _(
    "Uses 24-hour time: morning stays 01:00–12:59; "
    "5:30 PM is 17:30 (not 05:30, which is 5:30 AM)."
)

_MSG_INTERVAL_END_AFTER_START = _(
    "End time must be after start on the same day. "
    "Use 24-hour time (for example 5:30 PM as 17:30, not 05:30)."
)


def _time_tuple(t):
    if t is None:
        return None
    return (t.hour, t.minute, t.second)


def _ordered_interval(start, end):
    if start is None or end is None:
        return False
    return _time_tuple(start) < _time_tuple(end)


def _interval_within_shift(shift_bounds, b_start, b_end):
    if shift_bounds is None or not _ordered_interval(b_start, b_end):
        return False
    open_s, open_e = shift_bounds
    return _time_tuple(open_s) <= _time_tuple(b_start) and _time_tuple(
        b_end
    ) <= _time_tuple(open_e)


def _normalize_multiselect(cleaned_data, field_name, form):
    """Fix multiselect POST when the browser sends choice labels instead of values."""
    if field_name not in form.errors:
        return
    field = form.fields.get(field_name)
    if not field or not hasattr(field, "choices"):
        return
    choices = field.choices
    valid = [c[0] for c in choices]
    label_to_value = {str(c[1]): c[0] for c in choices}
    values = cleaned_data.get(field_name)
    if not isinstance(values, list):
        values = form.data.getlist(field_name) if form.data else []
    values = [label_to_value.get(v, v) for v in values]
    if values and all(v in valid for v in values):
        del form.errors[field_name]
        cleaned_data[field_name] = values


def _parse_time_value(value):
    if value is None:
        return None
    if hasattr(value, "hour"):
        return value
    if isinstance(value, str):
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(value, fmt).time()
            except ValueError:
                continue
    return None


def resolve_toggle_params(instance, initial):
    """Effective timing_type / break modes for this request (HTMX or first paint)."""
    data = initial or {}
    params = {
        "timing_type": (data.get("timing_type") or "").strip(),
        "break1_mode": (data.get("break1_mode") or "").strip(),
        "break2_mode": (data.get("break2_mode") or "").strip(),
    }
    if instance and instance.pk:
        if not params["timing_type"]:
            params["timing_type"] = (
                getattr(instance, "timing_type", None) or ""
            ).strip()
        if not params["break1_mode"]:
            params["break1_mode"] = getattr(instance, "break1_mode", "none") or "none"
        if not params["break2_mode"]:
            params["break2_mode"] = getattr(instance, "break2_mode", "none") or "none"
    params["timing_type"] = params["timing_type"] or "same"
    params["break1_mode"] = params["break1_mode"] or "none"
    params["break2_mode"] = params["break2_mode"] or "none"
    return params


def _per_weekday_start_end_field_names():
    return [f"{day}_start" for day in DAY_ORDER_FULL] + [
        f"{day}_end" for day in DAY_ORDER_FULL
    ]


def _break_diff_field_names(slot):
    names = []
    for _short, full in SHORT_TO_DAY_PREFIX.items():
        names.extend([f"{slot}_diff_{full}_start", f"{slot}_diff_{full}_end"])
    return names


def reorder_shift_hour_form_fields(form, toggle_params):
    """
    Dynamic break fields are appended after Meta fields; the list template uses a
    two-column grid. Put break1 diff right after break1 block, break2 after break2,
    then assigned_users and is_active.
    """
    meta = list(getattr(form.__class__, "field_order", None) or [])
    block1 = meta[: meta.index("break1_per_day") + 1]
    i2 = meta.index("break2_mode")
    block2 = meta[i2 : meta.index("break2_per_day") + 1]
    tail = meta[meta.index("assigned_users") :]

    def diff_keys(slot):
        key = "break1_mode" if slot == "break1" else "break2_mode"
        if toggle_params[key] != "different":
            return []
        return [f"{slot}_day_quick_fill"] + _break_diff_field_names(slot)

    ordered = []
    for k in block1:
        if k == "monday_start" and "day_quick_fill" in form.fields:
            ordered.append("day_quick_fill")
        if k in form.fields:
            ordered.append(k)
    ordered.extend(k for k in diff_keys("break1") if k in form.fields)
    for k in block2:
        if k in form.fields:
            ordered.append(k)
    ordered.extend(k for k in diff_keys("break2") if k in form.fields)
    for k in tail:
        if k in form.fields:
            ordered.append(k)

    new_fields = OrderedDict((k, form.fields[k]) for k in ordered)
    for k, v in form.fields.items():
        if k not in new_fields:
            new_fields[k] = v
    form.fields = new_fields


def load_break_diff_initial(form, instance, toggle_params):
    """When editing, fill per-day break time inputs from JSON on the instance."""
    if not instance or not instance.pk:
        return
    for slot in ("break1", "break2"):
        key = "break1_mode" if slot == "break1" else "break2_mode"
        if toggle_params[key] != "different":
            continue
        raw = getattr(instance, f"{slot}_per_day", None) or {}
        if not isinstance(raw, dict):
            continue
        for short, full in SHORT_TO_DAY_PREFIX.items():
            pair = raw.get(short) or raw.get(full)
            if not pair or not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            s = _parse_time_value(pair[0])
            e = _parse_time_value(pair[1])
            fs = form.fields.get(f"{slot}_diff_{full}_start")
            fe = form.fields.get(f"{slot}_diff_{full}_end")
            if fs and s:
                fs.initial = s
            if fe and e:
                fe.initial = e


def pack_break_per_day(slot, cleaned_data):
    """Build JSON dict mon..sun → [start_iso, end_iso] from posted diff fields."""
    out = {}
    for short, full in SHORT_TO_DAY_PREFIX.items():
        s = cleaned_data.get(f"{slot}_diff_{full}_start")
        e = cleaned_data.get(f"{slot}_diff_{full}_end")
        if s and e:
            out[short] = [s.isoformat(), e.isoformat()]
    return out


class ShiftHourForm(HorillaModelForm):
    """
    Model-backed fields + optional extra TimeFields for “different break per day”.

    HTMX reloads the whole form when timing_type / break*_mode change; visibility
    and field order are applied in ``__init__``.
    """

    # UI-only helpers (not model fields, never saved): bulk-fill the per-day
    # start/end inputs for the main hours and for each "different" break.
    day_quick_fill = forms.CharField(
        required=False,
        label=_("Quick fill"),
        widget=DayQuickFillWidget(),
    )
    break1_day_quick_fill = forms.CharField(
        required=False,
        label=_("Break 1 quick fill"),
        widget=DayQuickFillWidget(field_prefix="break1_diff_"),
    )
    break2_day_quick_fill = forms.CharField(
        required=False,
        label=_("Break 2 quick fill"),
        widget=DayQuickFillWidget(field_prefix="break2_diff_"),
    )

    field_order = [
        "company",
        "name",
        "time_zone",
        "timing_type",
        "week_days",
        "default_start_time",
        "default_end_time",
        "monday_start",
        "monday_end",
        "tuesday_start",
        "tuesday_end",
        "wednesday_start",
        "wednesday_end",
        "thursday_start",
        "thursday_end",
        "friday_start",
        "friday_end",
        "saturday_start",
        "saturday_end",
        "sunday_start",
        "sunday_end",
        "break1_mode",
        "break1_week_days",
        "break1_default_start",
        "break1_default_end",
        "break1_per_day",
        "break2_mode",
        "break2_week_days",
        "break2_default_start",
        "break2_default_end",
        "break2_per_day",
        "assigned_users",
    ]

    class Meta:
        """Meta for shift hour form: all model fields; core audit fields auto-excluded."""

        model = ShiftHour
        fields = "__all__"
        keep_on_form = ("company",)
        widgets = {
            "name": forms.TextInput(
                attrs={"placeholder": _("e.g. US Shift, APAC Support")}
            ),
            "timing_type": forms.Select(
                attrs={
                    "id": "id_shift_timing_type",
                    "hx-trigger": "change",
                    "hx-target": "#shift-hour-form-view-container",
                    "hx-swap": "outerHTML",
                    "hx-include": "#shift-hour-form-view",
                }
            ),
            "break1_mode": forms.Select(
                attrs={
                    "id": "id_break1_mode",
                    "hx-trigger": "change",
                    "hx-target": "#shift-hour-form-view-container",
                    "hx-swap": "outerHTML",
                    "hx-include": "#shift-hour-form-view",
                }
            ),
            "break2_mode": forms.Select(
                attrs={
                    "id": "id_break2_mode",
                    "hx-trigger": "change",
                    "hx-target": "#shift-hour-form-view-container",
                    "hx-swap": "outerHTML",
                    "hx-include": "#shift-hour-form-view",
                }
            ),
            "week_days": CheckboxGridSelectMultiple(),
            "break1_week_days": CheckboxGridSelectMultiple(),
            "break2_week_days": CheckboxGridSelectMultiple(),
            "break1_per_day": forms.HiddenInput(),
            "break2_per_day": forms.HiddenInput(),
            "assigned_users": forms.SelectMultiple(
                attrs={"class": "js-example-basic-multiple w-full"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = self.instance
        initial = self.data or self.initial
        toggle_params = resolve_toggle_params(instance, initial)

        self._shift_hx_reload_url(instance)
        self._shift_assigned_users_queryset(instance, initial)
        self._shift_add_break_per_day_fields(toggle_params)
        self._shift_hide_irrelevant_fields(toggle_params)

        load_break_diff_initial(self, instance, toggle_params)
        reorder_shift_hour_form_fields(self, toggle_params)

        # Day-card look (same as Business Hour). These fields are skipped by the
        # 24h help-text loop below so the hint isn't repeated on every day card.
        card_styled = style_day_time_cards(self.fields)
        for slot, abbr in (("break1", _("Break 1")), ("break2", _("Break 2"))):
            card_styled += style_day_time_cards(
                self.fields,
                field_prefix=f"{slot}_diff_",
                legend_prefix=f"{abbr} \u2013 ",
            )

        for _fname, field in self.fields.items():
            if (
                isinstance(field, forms.TimeField)
                and not isinstance(field.widget, forms.HiddenInput)
                and _fname not in card_styled
            ):
                field.help_text = _TIME_24H_HELP

    def _shift_hx_reload_url(self, instance):
        base = (
            f"/shift-hour-update-form/{instance.pk}"
            if instance and instance.pk
            else "/shift-hour-create-form/"
        )
        hx_get = f"{base}?toggle_data=true"
        for fname in ("timing_type", "break1_mode", "break2_mode"):
            if fname in self.fields:
                self.fields[fname].widget.attrs["hx-get"] = hx_get

    def _shift_assigned_users_queryset(self, instance, initial):
        company_id = None
        if instance and instance.pk:
            company_id = instance.company_id
        elif initial.get("company"):
            co = initial.get("company")
            company_id = getattr(co, "id", None) or co
        if company_id and "assigned_users" in self.fields:
            self.fields["assigned_users"].queryset = User.objects.filter(
                company_id=company_id, is_active=True
            ).order_by("first_name", "last_name", "username")

    def _shift_add_break_per_day_fields(self, toggle_params):
        ref_tf = ShiftHour._meta.get_field("break1_default_start")
        for slot in ("break1", "break2"):
            key = "break1_mode" if slot == "break1" else "break2_mode"
            if toggle_params[key] != "different":
                continue
            abbr = _BREAK_SLOT_ABBR[slot]
            for short, full in SHORT_TO_DAY_PREFIX.items():
                day_abbr = DAY_ABBR.get(short, short)
                for piece, tail in (("start", _("- start")), ("end", _("- end"))):
                    fname = f"{slot}_diff_{full}_{piece}"
                    self.fields[fname] = forms.TimeField(
                        required=False,
                        label=_("%(slot)s %(day)s%(tail)s")
                        % {"slot": abbr, "day": day_abbr, "tail": tail},
                        widget=forms.TimeInput(),
                    )
                    self._apply_datetime_like_widget(
                        self.fields[fname], fname, ref_tf, {"step": "60"}
                    )

    def _shift_hide_irrelevant_fields(self, toggle_params):
        def hide(names, nullify=False):
            for name in names:
                if name not in self.fields:
                    continue
                self.fields[name].widget = forms.HiddenInput(attrs={"required": False})
                if nullify and self.data is not None:
                    self.data = self.data.copy()
                    self.data[name] = ""

        day_fields = _per_weekday_start_end_field_names()
        defaults = ["default_start_time", "default_end_time"]
        tt = toggle_params["timing_type"]

        if tt != "same":
            hide(defaults, nullify=True)
        if tt != "different":
            hide(day_fields + ["day_quick_fill"], nullify=True)
        if tt == "different":
            hide(["week_days"], nullify=True)

        for slot in ("break1", "break2"):
            bm = toggle_params["break1_mode" if slot == "break1" else "break2_mode"]
            bwd = f"{slot}_week_days"
            bdef = [f"{slot}_default_start", f"{slot}_default_end"]
            diff_names = _break_diff_field_names(slot)
            qf = f"{slot}_day_quick_fill"
            if bm == "none":
                hide([bwd] + bdef + diff_names + [qf], nullify=True)
                hide([f"{slot}_per_day"], nullify=True)
            elif bm == "same":
                hide(diff_names + [qf], nullify=True)
                hide([f"{slot}_per_day"], nullify=True)
            else:
                hide(bdef, nullify=True)
                if bwd in self.fields:
                    self.fields[bwd].widget.attrs[
                        "container_style"
                    ] = "display:none;height:0;margin:0;padding:0;overflow:hidden;"

    def clean(self):
        cleaned = super().clean()

        for fname in ("week_days", "break1_week_days", "break2_week_days"):
            _normalize_multiselect(cleaned, fname, self)

        self._clean_shift_limit(cleaned)
        self._clean_apply_main_timing_to_data(cleaned)

        week_days = cleaned.get("week_days") or []
        fake_shift = self._clean_fake_shift_for_bounds(cleaned, week_days)

        self._clean_validate_main_hours(cleaned, week_days)
        self._clean_validate_break("break1", cleaned, week_days, fake_shift)
        self._clean_validate_break("break2", cleaned, week_days, fake_shift)
        self._clean_breaks_do_not_overlap(cleaned)

        return cleaned

    def _clean_shift_limit(self, cleaned):
        company = cleaned.get("company")
        if self.instance.pk or not company:
            return
        cid = getattr(company, "id", None) or company
        if (
            ShiftHour.objects.filter(company_id=cid).count()
            >= ShiftHour.SHIFT_HOUR_LIMIT
        ):
            self.add_error(
                None,
                _("You can define at most %(limit)s shift hours per company.")
                % {"limit": ShiftHour.SHIFT_HOUR_LIMIT},
            )

    def _clean_apply_main_timing_to_data(self, cleaned):
        """Same mode: copy default times to each selected weekday. Different: derive week_days."""
        if cleaned.get("timing_type") == "same":
            days = cleaned.get("week_days") or []
            ds, de = cleaned.get("default_start_time"), cleaned.get("default_end_time")
            for short in days:
                day = SHORT_TO_DAY_PREFIX.get(short)
                if day:
                    cleaned[f"{day}_start"] = ds
                    cleaned[f"{day}_end"] = de

        if cleaned.get("timing_type") == "different":
            selected = []
            for short, full in SHORT_TO_DAY_PREFIX.items():
                if cleaned.get(f"{full}_start") and cleaned.get(f"{full}_end"):
                    selected.append(short)
            cleaned["week_days"] = selected

    def _clean_fake_shift_for_bounds(self, cleaned, week_days):
        """In-memory row used only for get_shift_bounds_for_day() in break validation."""
        fake = ShiftHour(
            timing_type=cleaned.get("timing_type"),
            week_days=week_days,
            default_start_time=cleaned.get("default_start_time"),
            default_end_time=cleaned.get("default_end_time"),
        )
        for full in DAY_ORDER_FULL:
            setattr(fake, f"{full}_start", cleaned.get(f"{full}_start"))
            setattr(fake, f"{full}_end", cleaned.get(f"{full}_end"))
        return fake

    def _require_time_pair(self, start_name, end_name, cleaned, start_msg, end_msg):
        """
        Both times of a pair are needed. The error goes on the field that is empty (on
        both when both are), so the user sees what is missing. Returns True when the
        pair is complete.
        """
        complete = True
        for name, message in ((start_name, start_msg), (end_name, end_msg)):
            if cleaned.get(name) is None:
                complete = False
                if name not in self.errors:  # an invalid time already has its message
                    self.add_error(name, message)
        return complete

    def _flag_half_filled_day(self, short, start_name, end_name, cleaned):
        """
        Error on the empty one of a day's start/end pair when only the other is filled,
        so the day is not dropped without a word. Returns True when it flagged the day.
        """
        if start_name in self.errors or end_name in self.errors:
            return False  # one of them already has its own error
        has_start = cleaned.get(start_name) is not None
        has_end = cleaned.get(end_name) is not None
        if has_start == has_end:
            return False
        self.add_error(
            end_name if has_start else start_name,
            _("Enter both start and end for %(day)s, or leave both empty.")
            % {"day": str(DAY_LABELS.get(short, short))},
        )
        return True

    def _clean_validate_main_hours(self, cleaned, week_days):
        timing = cleaned.get("timing_type")
        if timing == "same":
            if not week_days:
                self.add_error(
                    "week_days", _("Select at least one weekday for the shift.")
                )
            if self._require_time_pair(
                "default_start_time",
                "default_end_time",
                cleaned,
                _("Start time is required when using the same hours every day."),
                _("End time is required when using the same hours every day."),
            ) and not _ordered_interval(
                cleaned.get("default_start_time"), cleaned.get("default_end_time")
            ):
                self.add_error("default_end_time", _MSG_INTERVAL_END_AFTER_START)

        if timing == "different":
            flagged = [
                self._flag_half_filled_day(
                    short, f"{full}_start", f"{full}_end", cleaned
                )
                for short, full in SHORT_TO_DAY_PREFIX.items()
            ]
            if not week_days and not any(flagged):
                self.add_error(
                    None,
                    _(
                        "Set start and end times for at least one weekday for the shift."
                    ),
                )
            # ``week_days`` holds only the days with both times, so each one is a full pair.
            for short in week_days:
                full = SHORT_TO_DAY_PREFIX[short]
                if not _ordered_interval(
                    cleaned.get(f"{full}_start"), cleaned.get(f"{full}_end")
                ):
                    self.add_error(f"{full}_end", _MSG_INTERVAL_END_AFTER_START)

    def _break_day_field(self, slot, short):
        """The field an error about ``short`` of break ``slot`` is shown on."""
        if (self.cleaned_data.get(f"{slot}_mode") or "none") == "different":
            return f"{slot}_diff_{SHORT_TO_DAY_PREFIX[short]}_start"
        return f"{slot}_default_start"

    def _clean_break_fits_day(self, slot, short, fake_shift, start, end):
        """A break must be inside the shift of its day and leave some working time."""
        bounds = fake_shift.get_shift_bounds_for_day(short)
        day = {"day": str(DAY_LABELS.get(short, short))}
        field = self._break_day_field(slot, short)
        if not _interval_within_shift(bounds, start, end):
            self.add_error(
                field,
                _("Break on %(day)s must fall within the shift hours for that day.")
                % day,
            )
        elif _time_tuple(start) <= _time_tuple(bounds[0]) and _time_tuple(
            end
        ) >= _time_tuple(bounds[1]):
            self.add_error(
                field,
                _(
                    "Break on %(day)s cannot cover the whole shift. "
                    "Leave some working time."
                )
                % day,
            )

    def _clean_validate_break(self, slot, cleaned, week_days, fake_shift):
        mode = cleaned.get(f"{slot}_mode") or "none"
        if mode == "none":
            cleaned[f"{slot}_per_day"] = {}
            return

        per_day = None
        if mode == "different":
            flagged = [
                self._flag_half_filled_day(
                    short,
                    f"{slot}_diff_{full}_start",
                    f"{slot}_diff_{full}_end",
                    cleaned,
                )
                for short, full in SHORT_TO_DAY_PREFIX.items()
            ]
            if any(flagged):
                return
            per_day = pack_break_per_day(slot, cleaned)
            cleaned[f"{slot}_week_days"] = list(per_day.keys()) if per_day else []

        bwd = cleaned.get(f"{slot}_week_days") or []
        if not bwd:
            if mode == "different":
                self.add_error(
                    None, _("Enter start and end for at least one break day.")
                )
            else:
                self.add_error(
                    f"{slot}_week_days",
                    _("Select at least one weekday for this break."),
                )
            return

        outside = [d for d in bwd if d not in week_days]
        if outside:
            if mode == "different":
                # The weekday picker is hidden in this mode, so say it on the day itself.
                for d in outside:
                    self.add_error(
                        self._break_day_field(slot, d),
                        _(
                            "%(day)s is not a working day of the shift, "
                            "so it cannot have a break."
                        )
                        % {"day": str(DAY_LABELS.get(d, d))},
                    )
            else:
                self.add_error(
                    f"{slot}_week_days",
                    _("Break days must be among the shift working days."),
                )
            return

        if mode == "same":
            bs, be = (
                cleaned.get(f"{slot}_default_start"),
                cleaned.get(f"{slot}_default_end"),
            )
            if not self._require_time_pair(
                f"{slot}_default_start",
                f"{slot}_default_end",
                cleaned,
                _("Break start is required for this mode."),
                _("Break end is required for this mode."),
            ):
                return
            if not _ordered_interval(bs, be):
                self.add_error(
                    f"{slot}_default_end",
                    _(
                        "Break end must be after break start. "
                        "Use 24-hour time (5:30 PM is 17:30, not 05:30)."
                    ),
                )
                return
            for d in bwd:
                self._clean_break_fits_day(slot, d, fake_shift, bs, be)
            cleaned[f"{slot}_per_day"] = {}
            return

        per_day = per_day or {}
        if not per_day:
            self.add_error(None, _("Enter start and end for at least one break day."))
            return

        for short, pair in per_day.items():
            start, end = _parse_time_value(pair[0]), _parse_time_value(pair[1])
            if start is None or end is None:
                self.add_error(None, _("Invalid break time format."))
                return
            self._clean_break_fits_day(slot, short, fake_shift, start, end)
        cleaned[f"{slot}_per_day"] = per_day

    @staticmethod
    def _break_intervals(slot, cleaned):
        """``{day: (start, end)}`` of a break, for the days where it is a valid interval."""
        mode = cleaned.get(f"{slot}_mode") or "none"
        if mode == "same":
            pair = (
                cleaned.get(f"{slot}_default_start"),
                cleaned.get(f"{slot}_default_end"),
            )
            pairs = {d: pair for d in cleaned.get(f"{slot}_week_days") or []}
        elif mode == "different":
            pairs = {
                d: (_parse_time_value(p[0]), _parse_time_value(p[1]))
                for d, p in (cleaned.get(f"{slot}_per_day") or {}).items()
            }
        else:
            return {}
        return {d: pair for d, pair in pairs.items() if _ordered_interval(*pair)}

    def _clean_breaks_do_not_overlap(self, cleaned):
        """Break 1 and Break 2 must not run at the same time on a day (touching is fine)."""
        if any(name.startswith(("break1", "break2")) for name in self.errors):
            return  # the breaks are not valid yet, so there is nothing to compare
        first = self._break_intervals("break1", cleaned)
        second = self._break_intervals("break2", cleaned)
        for short in WEEK_ORDER:
            if short not in first or short not in second:
                continue
            (start1, end1), (start2, end2) = first[short], second[short]
            if _time_tuple(start1) < _time_tuple(end2) and _time_tuple(
                start2
            ) < _time_tuple(end1):
                self.add_error(
                    self._break_day_field("break2", short),
                    _("Break 1 and Break 2 overlap on %(day)s.")
                    % {"day": str(DAY_LABELS.get(short, short))},
                )
