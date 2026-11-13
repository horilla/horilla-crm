"""
Timeline (Gantt-style) view for Horilla.
Records are plotted by start and end date fields. Reuses HorillaListView.
"""

# Standard library imports
import ast
import logging
from datetime import date, datetime, timedelta

from horilla.db.models import CharField, DateField, DateTimeField, ForeignKey
from horilla.shortcuts import redirect

# First party imports (Horilla)
from horilla.utils import timezone as django_tz
from horilla.utils.translation import gettext_lazy as _
from horilla.web import QueryDict

# Local imports
from .list import HorillaListView

logger = logging.getLogger(__name__)


class HorillaTimelineView(HorillaListView):
    """
    View for displaying data in a timeline (Gantt-style) layout.
    Records are plotted by start and end date fields. Reuses HorillaListView.
    """

    template_name = "timeline_view.html"
    supports_quick_filters = False

    def _normalize_redirect_param_value(self, value):
        """Return a scalar string for redirect URL; unwrap list literals like "['x']" -> "x"."""
        if value is None:
            return None
        s = str(value).strip()
        if not s or s in ("[]", "['']", '[""]'):
            return None
        if len(s) >= 2 and s.startswith("[") and s.endswith("]"):
            try:
                parsed = ast.literal_eval(s)
                if (
                    isinstance(parsed, list)
                    and len(parsed) > 0
                    and parsed[0] is not None
                ):
                    return str(parsed[0]).strip() or None
                return None
            except (ValueError, SyntaxError):
                pass
        return s

    def dispatch(self, request, *args, **kwargs):
        """Redirect non-HTMX GET requests to main_url with timeline layout params."""
        if request.method == "GET" and request.headers.get("HX-Request") != "true":
            main_url = getattr(self, "main_url", None)
            if main_url:
                clean = QueryDict(mutable=True)
                clean.setlist("layout", ["timeline"])
                for key in request.GET:
                    if key == "layout":
                        clean.setlist(key, ["timeline"])
                        continue
                    if key == "search":
                        val = self._normalize_redirect_param_value(request.GET.get(key))
                        if val is not None:
                            clean.setlist(key, [val])
                        continue
                    val = self._normalize_redirect_param_value(request.GET.get(key))
                    if val is not None:
                        clean.setlist(key, [val])
                base = str(main_url)
                qs = clean.urlencode()
                url = f"{base}?{qs}" if qs else base
                return redirect(url)
        return super().dispatch(request, *args, **kwargs)

    bulk_select_option = False
    table_class = False
    table_width = False
    paginate_by = 200

    timeline_start_field = None  # e.g. "created_at", "close_date"
    timeline_end_field = None  # e.g. "close_date"; if None, use start as single date
    timeline_title_field = None  # e.g. "name", "title"; fallback to first column
    timeline_group_by_field = None
    # When end (e.g. close_date) < start (e.g. created_at), use end as start and this as end (e.g. "updated_at")
    timeline_fallback_end_field = None

    def get_allowed_timeline_date_fields(self):
        """
        Return list of (field_name, verbose_name) for DateField/DateTimeField
        suitable as timeline start/end. Used for dropdown overrides via GET.
        """
        model = self.model
        if not model:
            return []
        choices = []
        for field in model._meta.get_fields():
            if not getattr(field, "concrete", True):
                continue
            if isinstance(field, (DateField, DateTimeField)):
                choices.append(
                    (field.name, getattr(field, "verbose_name", None) or field.name)
                )
        if self.request and choices:
            from horilla.contrib.core.utils import filter_hidden_fields

            field_names = [c[0] for c in choices]
            allowed = filter_hidden_fields(self.request.user, model, field_names)
            choices = [c for c in choices if c[0] in allowed]
        return choices

    def get_timeline_start_field(self):
        """Return timeline start field: GET override, then saved user preference, then class default."""
        base = getattr(self, "timeline_start_field", None)
        if not self.request:
            return base
        allowed = [c[0] for c in self.get_allowed_timeline_date_fields()]
        param = self.request.GET.get("timeline_start")
        if param and param in allowed:
            return param
        # Persisted per user (TimelineSpanBy)
        if self.model and getattr(self.model, "_meta", None):
            from .helpers.timeline_settings import get_saved_timeline_fields

            saved_start, _ = get_saved_timeline_fields(
                self.request.user,
                self.model._meta.app_label,
                self.model._meta.model_name,
            )
            if saved_start and saved_start in allowed:
                return saved_start
        return base

    def get_timeline_end_field(self):
        """
        Return timeline end field: GET override, then saved user preference, then class default.
        """
        base_start = getattr(self, "timeline_start_field", None)
        base_end = getattr(self, "timeline_end_field", None) or base_start
        if not self.request:
            return base_end
        allowed = [c[0] for c in self.get_allowed_timeline_date_fields()]
        param = self.request.GET.get("timeline_end")
        if param and param in allowed:
            return param
        if self.model and getattr(self.model, "_meta", None):
            from .helpers.timeline_settings import get_saved_timeline_fields

            _, saved_end = get_saved_timeline_fields(
                self.request.user,
                self.model._meta.app_label,
                self.model._meta.model_name,
            )
            if saved_end and saved_end in allowed:
                return saved_end
        # Fall back to class default relative to resolved start
        start = self.get_timeline_start_field()
        return getattr(self, "timeline_end_field", None) or start

    def get_timeline_fallback_end_field(self):
        """Return the model field name used as end date when end < start (e.g. updated_at)."""
        return getattr(self, "timeline_fallback_end_field", None)

    def get_timeline_title_field(self):
        """Return the field name used as the bar title on the timeline."""
        if self.timeline_title_field:
            return self.timeline_title_field
        columns = getattr(self, "columns", [])
        if columns:
            col = columns[0]
            return col[1] if isinstance(col, (list, tuple)) and len(col) >= 2 else col
        return "pk"

    def _get_timeline_exclude_include_fields(self):
        """Return (exclude_fields, include_fields) for timeline group-by options."""
        exclude_str = getattr(self, "exclude_kanban_fields", "") or ""
        exclude_fields = [f.strip() for f in exclude_str.split(",") if f.strip()]
        include_fields = getattr(self, "include_kanban_fields", None)
        return exclude_fields, include_fields

    def get_allowed_timeline_group_by_fields(self):
        """
        Return list of (field_name, verbose_name) for the Group by dropdown.
        Includes ChoiceField, ForeignKey (including created_by, updated_by for timeline).
        """
        model = self.model
        if not model:
            return []
        exclude_fields, include_fields = self._get_timeline_exclude_include_fields()
        exclude_fields = list(exclude_fields) + ["country"]
        if not self.request.session.get("show_all_companies", False):
            exclude_fields.append("company")
        choices = []
        for field in model._meta.get_fields():
            if field.name in exclude_fields:
                continue
            if include_fields is not None and field.name not in include_fields:
                continue
            if isinstance(field, CharField) and getattr(field, "choices", None):
                choices.append(
                    (field.name, getattr(field, "verbose_name", None) or field.name)
                )
            elif isinstance(field, ForeignKey):
                choices.append(
                    (field.name, getattr(field, "verbose_name", None) or field.name)
                )
        if self.request and choices:
            from horilla.contrib.core.utils import filter_hidden_fields

            field_names = [c[0] for c in choices]
            allowed = filter_hidden_fields(self.request.user, model, field_names)
            choices = [c for c in choices if c[0] in allowed]
        return choices

    def get_timeline_group_by_field(self):
        """
        Return the field name used to group and colour timeline bars.
        Uses request GET param timeline_group_by (or group_by) if valid, else class default.
        """
        default = getattr(self, "timeline_group_by_field", None)
        param = self.request.GET.get("timeline_group_by") or self.request.GET.get(
            "group_by"
        )
        if not param:
            return default
        allowed = [c[0] for c in self.get_allowed_timeline_group_by_fields()]
        if param in allowed:
            return param
        return default

    def _get_group_key_label(self, obj, group_by_field):
        """Return (group_key, group_label) for this object based on group_by field."""
        model = self.model
        try:
            field = model._meta.get_field(group_by_field)
        except Exception:
            return None, ""

        raw = getattr(obj, group_by_field, None)
        if isinstance(field, ForeignKey):
            if raw is None:
                return "none", _("None")
            related = raw
            key = str(related.pk)
            label = str(related)
            return key, label
        if hasattr(field, "choices") and field.choices:
            key = str(raw) if raw is not None else "none"
            label = self._get_display_value(obj, group_by_field) or _("None")
            return key, label
        return None, ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not hasattr(self, "object_list"):
            self.object_list = self.get_queryset()

        start_field = self.get_timeline_start_field()
        end_field = self.get_timeline_end_field()
        title_field = self.get_timeline_title_field()

        if not start_field:
            context["timeline_error"] = _(
                "Timeline view requires timeline_start_field to be set."
            )
            context["timeline_items"] = []
            context["timeline_range_start"] = None
            context["timeline_range_end"] = None
            return context

        model = self.model
        try:
            model._meta.get_field(start_field)
        except Exception:
            context["timeline_error"] = _(
                "Invalid timeline_start_field: %(field)s."
            ) % {"field": start_field}
            context["timeline_items"] = []
            context["timeline_range_start"] = None
            context["timeline_range_end"] = None
            return context

        # End field must exist on model (GET override may point to invalid field)
        try:
            model._meta.get_field(end_field)
        except Exception:
            end_field = start_field

        group_by_field = self.get_timeline_group_by_field()
        queryset = self.object_list
        if group_by_field:
            try:
                f = model._meta.get_field(group_by_field)
                if isinstance(f, ForeignKey):
                    queryset = queryset.select_related(group_by_field)
            except Exception:
                group_by_field = None

        items = []
        range_start = None
        range_end = None
        groups_seen = {}  # key -> label for ordered timeline_groups

        for obj in queryset:
            start_val = getattr(obj, start_field, None)
            end_val = getattr(obj, end_field, None) if end_field else start_val

            if start_val is None:
                continue

            # Always interpret as calendar dates: start_field = bar start, end_field = bar end.
            # Do not swap or replace with fallback — that produced wrong spans (e.g. close_date
            # replaced by updated_at). If end < start, show a single-day bar at start.
            start_dt = self._to_date(start_val)
            if not start_dt:
                continue
            end_dt = self._to_date(end_val) if end_val is not None else None
            end_dt = max(start_dt, end_dt or start_dt)

            title = self._get_display_value(obj, title_field)
            if range_start is None:
                range_start = start_dt
                range_end = end_dt
            else:
                range_start = min(range_start, start_dt)
                range_end = max(range_end, end_dt)

            detail_url = ""
            if hasattr(obj, "get_detail_url") and callable(
                getattr(obj, "get_detail_url")
            ):
                try:
                    detail_url = obj.get_detail_url()
                except Exception:
                    pass

            group_key, group_label = None, ""
            if group_by_field:
                group_key, group_label = self._get_group_key_label(obj, group_by_field)
                if group_key not in groups_seen:
                    groups_seen[group_key] = group_label

            # Date-only strings for JS (YYYY-MM-DD). JS must parse as local calendar
            # dates — never ISO datetime without timezone or bars shift (UTC midnight).
            def _ymd(d):
                return d.isoformat() if d else ""

            items.append(
                {
                    "obj": obj,
                    "start": start_dt,
                    "end": end_dt,
                    "title": title,
                    "start_iso": _ymd(start_dt),
                    "end_iso": _ymd(end_dt),
                    "detail_url": detail_url,
                    "group_key": group_key,
                    "group_label": group_label,
                }
            )

        if range_start is not None and range_end is not None:
            margin = (range_end - range_start).days or 1
            margin = min(max(margin, 7), 90)
            range_start = range_start - timedelta(days=margin // 2)
            range_end = range_end + timedelta(days=margin // 2)
        else:
            today = date.today()
            range_start = today - timedelta(days=90)
            range_end = today + timedelta(days=30)

        # Timeline scale (days/weeks/months/quarters)
        raw_scale = (
            self.request.GET.get("timeline_scale", "months")
            if self.request
            else "months"
        )
        if raw_scale not in {"days", "weeks", "months", "quarters"}:
            raw_scale = "months"
        timeline_scale = raw_scale

        timeline_groups = []
        if group_by_field and groups_seen:
            try:
                field = model._meta.get_field(group_by_field)
                if isinstance(field, ForeignKey):
                    related_model = field.related_model
                    if hasattr(related_model, "_meta") and "order" in [
                        f.name for f in related_model._meta.fields
                    ]:
                        related_qs = related_model.objects.all().order_by("order")
                    else:
                        related_qs = related_model.objects.all().order_by("pk")
                    for rel in related_qs:
                        key = str(rel.pk)
                        if key in groups_seen:
                            label = groups_seen[key]
                            timeline_groups.append({"key": key, "label": label})
                    if "none" in groups_seen:
                        label = groups_seen["none"]
                        timeline_groups.append({"key": "none", "label": label})
                else:
                    for key, label in groups_seen.items():
                        timeline_groups.append({"key": key, "label": label})
            except Exception:
                for key, label in groups_seen.items():
                    timeline_groups.append({"key": key, "label": label})

        timeline_group_rows = []
        if timeline_groups:
            for grp in timeline_groups:
                group_items = [it for it in items if it.get("group_key") == grp["key"]]
                timeline_group_rows.append(
                    {"group": {**grp, "count": len(group_items)}, "items": group_items}
                )
        else:
            timeline_group_rows.append(
                {
                    "group": {"key": "all", "label": _("All"), "count": len(items)},
                    "items": items,
                }
            )

        group_by_choices = self.get_allowed_timeline_group_by_fields()
        current_group_by = group_by_field
        current_group_by_label = ""
        if current_group_by and group_by_choices:
            for fn, label in group_by_choices:
                if fn == current_group_by:
                    current_group_by_label = str(label)
                    break

        app_label = getattr(model._meta, "app_label", "")
        context["timeline_items"] = items
        context["timeline_groups"] = timeline_groups
        context["timeline_group_rows"] = timeline_group_rows
        context["timeline_group_by_field"] = group_by_field
        context["timeline_group_by_choices"] = group_by_choices
        context["current_timeline_group_by"] = current_group_by
        context["current_timeline_group_by_label"] = (
            current_group_by_label or current_group_by
        )
        context["timeline_range_start"] = range_start
        context["timeline_range_end"] = range_end
        context["timeline_scale"] = timeline_scale
        context["timeline_scale_choices"] = [
            ("days", _("Days")),
            ("weeks", _("Weeks")),
            ("months", _("Months")),
            ("quarters", _("Quarters")),
        ]
        context["timeline_start_field"] = start_field
        context["timeline_end_field"] = end_field
        context["timeline_date_field_choices"] = self.get_allowed_timeline_date_fields()
        context["show_timeline_field_selectors"] = (
            len(context["timeline_date_field_choices"]) > 0 and start_field
        )
        context["timeline_span_caption"] = self.get_timeline_span_caption(
            model, start_field, end_field
        )
        context["timeline_title_field"] = title_field
        context["app_label"] = getattr(
            self, "app_label", model._meta.app_label if model else ""
        )
        context["apps_label"] = app_label
        context["model_name"] = model.__name__ if model else ""
        return context

    def _to_date(self, value):
        """Convert value to date for timeline positioning (in request timezone)."""
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            if getattr(value, "date", None) is None:
                return None
            if django_tz.is_naive(value):
                return value.date()
            return django_tz.localtime(value).date()
        if hasattr(value, "date"):
            return value.date()
        return None

    def _timeline_field_verbose(self, model, field_name):
        """Human-readable label for a timeline date field (verbose_name from model)."""
        if not model or not field_name:
            return field_name or ""
        try:
            f = model._meta.get_field(field_name)
            return str(getattr(f, "verbose_name", None) or field_name)
        except Exception:
            return field_name

    def get_timeline_span_caption(self, model, start_field, end_field):
        """
        Short caption for the UI so users know which fields define bar start/end.
        """
        start_c = self._timeline_field_verbose(model, start_field)
        end_c = self._timeline_field_verbose(model, end_field)
        if not start_field:
            return ""
        if start_field == end_field:
            return _("Bars use: %(field)s") % {"field": start_c}
        return _("From %(start)s → %(end)s") % {"start": start_c, "end": end_c}

    def _get_display_value(self, obj, field_name):
        """Get display value for a field (supports get_FOO_display for choices)."""
        if not field_name:
            return str(obj)
        raw = getattr(obj, field_name, None)
        if raw is None:
            return ""
        display_method = f"get_{field_name}_display"
        if hasattr(obj, display_method):
            try:
                return getattr(obj, display_method)() or str(raw)
            except Exception:
                pass
        return str(raw)
