"""Views for the calendar app in Horilla"""

# Standard library imports
import datetime
import json

# Third-party imports (Django)
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin

# First party imports (Horilla)
from horilla.apps import apps
from horilla.contrib.activity.methods import get_related_record_url
from horilla.contrib.activity.models import Activity
from horilla.contrib.core.utils import get_user_field_permission
from horilla.contrib.generics.templatetags.horilla_tags._shared import (
    format_datetime_value,
)
from horilla.contrib.generics.views import (
    HorillaSingleDeleteView,
    HorillaSingleFormView,
)
from horilla.contrib.generics.views.helpers.queryset_utils import (
    apply_conditions,
    get_queryset_for_module,
)
from horilla.contrib.utils.middlewares import _thread_local
from horilla.shortcuts import render
from horilla.urls import reverse_lazy
from horilla.utils import timezone
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.functional import cached_property  # type: ignore
from horilla.utils.translation import gettext as _
from horilla.views.generic import TemplateView, View
from horilla.web import HxTriggerResponse, JsonResponse, ScriptResponse

# Local imports
from .forms import CustomCalendarForm
from .models import (
    CustomCalendar,
    CustomCalendarCondition,
    UserAvailability,
    UserCalendarPreference,
)

# Default sidebar/checkbox colors per calendar type (keep in sync with calendar UI).
DEFAULT_CALENDAR_TYPE_COLORS = {
    "task": "#3B82F6",
    "event": "#10B981",
    "meeting": "#F50CCE",
    "unavailability": "#F5E614",
}

# Default "Color by: Status" colors; user overrides are UserCalendarPreference rows.
DEFAULT_STATUS_COLORS = {
    "status_completed": "#10B981",
    "status_pending": "#F97316",
}


def _calendar_display_value(obj, field_name):
    try:
        val = getattr(obj, field_name)
    except Exception:
        return str(obj.pk)
    if val is None:
        return str(obj.pk)
    return str(val)


def _related_record_url(activity, user, cache):
    """
    Return the detail URL of the activity's related record if the user may
    open it, else "". ``cache`` is keyed by the related record so activities
    sharing one record are checked once.
    """
    key = (activity.content_type_id, activity.object_id)
    if not all(key):
        return ""
    if key not in cache:
        related = activity.related_object
        cache[key] = get_related_record_url(related, user) if related else ""
    return cache[key]


def _combine_for_calendar(start_val, end_val, user):
    """Build ISO start/end and display strings for FullCalendar from model values."""
    if start_val is None:
        return None, None, None, None

    if isinstance(start_val, datetime.datetime):
        start_dt = start_val
        if timezone.is_naive(start_dt):
            start_dt = timezone.make_aware(start_dt)
        start_iso = start_dt.isoformat()
        start_disp = format_datetime_value(start_dt, user=user)
    else:
        start_d = start_val
        start_dt = timezone.make_aware(
            datetime.datetime.combine(start_d, datetime.time.min)
        )
        start_iso = start_dt.isoformat()
        start_disp = format_datetime_value(start_dt, user=user)

    if end_val is None:
        if isinstance(start_val, datetime.datetime):
            end_dt = start_dt + datetime.timedelta(hours=1)
        else:
            end_dt = timezone.make_aware(
                datetime.datetime.combine(
                    start_val + datetime.timedelta(days=1), datetime.time.min
                )
            )
    elif isinstance(end_val, datetime.datetime):
        end_dt = end_val
        if timezone.is_naive(end_dt):
            end_dt = timezone.make_aware(end_dt)
    else:
        end_dt = timezone.make_aware(
            datetime.datetime.combine(end_val, datetime.time.max)
        )

    end_iso = end_dt.isoformat()
    end_disp = format_datetime_value(end_dt, user=user)
    return start_iso, end_iso, start_disp, end_disp


def events_for_custom_calendar(request, cc):
    """Turn a CustomCalendar config into FullCalendar event dicts."""
    module_name = cc.module.model
    model = None
    for app_config in apps.get_app_configs():
        try:
            model = apps.get_model(
                app_label=app_config.label, model_name=module_name.lower()
            )
            break
        except LookupError:
            continue
    if not model:
        return []

    queryset = get_queryset_for_module(request.user, model)
    conditions = cc.conditions.all().order_by("sequence")
    queryset = apply_conditions(queryset, conditions)

    out = []
    title_field = cc.display_name_field
    start_field = cc.start_date_field
    end_field = cc.end_date_field or ""

    for obj in queryset.iterator():
        try:
            start_raw = getattr(obj, start_field)
        except Exception:
            continue
        if start_raw is None:
            continue
        end_raw = None
        if end_field:
            try:
                end_raw = getattr(obj, end_field)
            except Exception:
                end_raw = None

        title = _calendar_display_value(obj, title_field)
        start_iso, end_iso, start_disp, end_disp = _combine_for_calendar(
            start_raw, end_raw, request.user
        )
        if not start_iso:
            continue
        if isinstance(start_raw, datetime.datetime):
            start_day = timezone.localtime(start_raw).date()
        else:
            start_day = start_raw
        if isinstance(end_raw, datetime.datetime):
            end_day = timezone.localtime(end_raw).date()
        elif end_raw:
            end_day = end_raw
        else:
            end_day = start_day
        if end_day and start_day and end_day < start_day:
            end_day = start_day
        start_iso = start_day.isoformat()
        # FullCalendar all-day end is exclusive; add one day so the end date is inclusive.
        end_iso = (end_day + datetime.timedelta(days=1)).isoformat()

        detail_url = None
        if hasattr(obj, "get_detail_url"):
            try:
                detail_url = str(obj.get_detail_url())
            except Exception:
                detail_url = None

        cal_type = f"custom_{cc.pk}"
        out.append(
            {
                "title": title,
                "start": start_iso,
                "end": end_iso,
                "start_display": start_disp,
                "end_display": end_disp,
                "allDay": True,
                "calendarType": cal_type,
                "description": "",
                "id": f"{cal_type}_{obj.pk}",
                "url": detail_url,
                "deleteUrl": None,
                "detailUrl": detail_url,
                "backgroundColor": cc.color,
                "borderColor": cc.color,
                "textColor": "#FFFFFF",
            }
        )
    return out


def _save_unchecked_calendar_types(user, company, checked_types):
    """
    Give each standard calendar type not in ``checked_types`` an unselected
    preference row if it has none. The sidebar shows a type without a row as
    checked, so otherwise unchecking it doesn't stick. Callers unselect the
    user's existing rows first.
    """
    saved_types = set(
        UserCalendarPreference.objects.filter(user=user, company=company).values_list(
            "calendar_type", flat=True
        )
    )
    for calendar_type, color in DEFAULT_CALENDAR_TYPE_COLORS.items():
        if calendar_type in checked_types or calendar_type in saved_types:
            continue
        # Not create(): a quick double click can post the same change twice.
        UserCalendarPreference.objects.get_or_create(
            user=user,
            calendar_type=calendar_type,
            company=company,
            defaults={"color": color, "is_selected": False},
        )


class CalendarView(LoginRequiredMixin, TemplateView):
    """View to display the calendar with user preferences."""

    template_name = "calendar.html"

    def get_context_data(self, **kwargs):
        """Build context with calendar types and user color preferences for display."""
        context = super().get_context_data(**kwargs)
        context["calendars"] = [
            {
                "id": "task",
                "name": _("Tasks"),
                "default_color": DEFAULT_CALENDAR_TYPE_COLORS["task"],
            },
            {
                "id": "event",
                "name": _("Events"),
                "default_color": DEFAULT_CALENDAR_TYPE_COLORS["event"],
            },
            {
                "id": "meeting",
                "name": _("Meetings"),
                "default_color": DEFAULT_CALENDAR_TYPE_COLORS["meeting"],
            },
            {
                "id": "unavailability",
                "name": _("Unavailability"),
                "default_color": DEFAULT_CALENDAR_TYPE_COLORS["unavailability"],
            },
        ]
        preferences = UserCalendarPreference.objects.filter(user=self.request.user)
        preferences_by_type = {pref.calendar_type: pref for pref in preferences}
        context["user_preferences"] = {
            pref.calendar_type: pref.color for pref in preferences
        }
        context["status_colors"] = [
            {
                "id": "status_completed",
                "name": _("Completed"),
                "default_color": DEFAULT_STATUS_COLORS["status_completed"],
            },
            {
                "id": "status_pending",
                "name": _("Not completed"),
                "default_color": DEFAULT_STATUS_COLORS["status_pending"],
            },
        ]

        display_only = self.request.GET.get("display_only")
        company = (
            getattr(self.request, "active_company", None) or self.request.user.company
        )
        custom_calendars = CustomCalendar.objects.filter(
            user=self.request.user, is_active=True
        ).order_by("name")

        if display_only and display_only in [cal["id"] for cal in context["calendars"]]:
            UserCalendarPreference.objects.filter(user=self.request.user).update(
                is_selected=False
            )
            UserCalendarPreference.objects.filter(
                user=self.request.user, calendar_type=display_only
            ).update(is_selected=True)
            _save_unchecked_calendar_types(self.request.user, company, [display_only])
            for calendar in context["calendars"]:
                calendar["selected"] = calendar["id"] == display_only
            CustomCalendar.objects.filter(user=self.request.user).update(
                is_selected=False
            )
        elif (
            display_only
            and isinstance(display_only, str)
            and display_only.startswith("custom_")
        ):
            try:
                custom_pk = int(display_only.replace("custom_", "", 1))
            except ValueError:
                custom_pk = None
            if custom_pk is not None and custom_calendars.filter(pk=custom_pk).exists():
                UserCalendarPreference.objects.filter(user=self.request.user).update(
                    is_selected=False
                )
                _save_unchecked_calendar_types(self.request.user, company, [])
                for calendar in context["calendars"]:
                    calendar["selected"] = False
                CustomCalendar.objects.filter(user=self.request.user).update(
                    is_selected=False
                )
                CustomCalendar.objects.filter(
                    user=self.request.user, pk=custom_pk
                ).update(is_selected=True)
        else:
            for calendar in context["calendars"]:
                pref = preferences_by_type.get(calendar["id"])
                calendar["selected"] = pref.is_selected if pref else True

        status_field_permission = get_user_field_permission(
            self.request.user, Activity, "status"
        )
        context["status_field_permission"] = status_field_permission

        context["custom_calendars"] = CustomCalendar.objects.filter(
            user=self.request.user, is_active=True
        ).order_by("name")

        return context


class SaveCalendarPreferencesView(LoginRequiredMixin, View):
    """View to save user calendar preferences via AJAX."""

    def post(self, request, *args, **kwargs):
        """Handle AJAX POST request to save calendar preferences."""
        try:
            data = json.loads(request.body)
            calendar_types = data.get("calendar_types", [])
            calendar_type = data.get("calendar_type")
            color = data.get("color")
            valid_types = {"task", "event", "meeting", "unavailability"}
            company = getattr(request, "active_company", None) or request.user.company

            if calendar_type and color:
                if calendar_type in valid_types:
                    preference, created = (
                        UserCalendarPreference.objects.update_or_create(
                            user=request.user,
                            calendar_type=calendar_type,
                            company=company,
                            defaults={
                                "color": color,
                                "is_selected": True,
                            },
                        )
                    )
                    if not created:
                        preference.color = color
                        preference.save()
                elif calendar_type in DEFAULT_STATUS_COLORS:
                    # Color-only rows: never selected, so they are not fetched as a calendar.
                    UserCalendarPreference.objects.update_or_create(
                        user=request.user,
                        calendar_type=calendar_type,
                        company=company,
                        defaults={"color": color, "is_selected": False},
                    )
                elif isinstance(calendar_type, str) and calendar_type.startswith(
                    "custom_"
                ):
                    try:
                        pk = int(calendar_type.replace("custom_", "", 1))
                    except ValueError:
                        pk = None
                    if pk is not None:
                        CustomCalendar.objects.filter(user=request.user, pk=pk).update(
                            color=color, is_selected=True
                        )

            if "calendar_types" in data:
                UserCalendarPreference.objects.filter(user=request.user).update(
                    is_selected=False
                )
                CustomCalendar.objects.filter(user=request.user).update(
                    is_selected=False
                )
                calendar_types = data.get("calendar_types") or []
                standard_types = [ct for ct in calendar_types if ct in valid_types]
                custom_pks = []
                for ct in calendar_types:
                    if isinstance(ct, str) and ct.startswith("custom_"):
                        try:
                            custom_pks.append(int(ct.replace("custom_", "", 1)))
                        except ValueError:
                            continue

                for ct in standard_types:
                    defaults = {
                        "is_selected": True,
                        "company": company,
                    }
                    if not UserCalendarPreference.objects.filter(
                        user=request.user, calendar_type=ct
                    ).exists():
                        defaults["color"] = DEFAULT_CALENDAR_TYPE_COLORS[ct]
                    preference, created = (
                        UserCalendarPreference.objects.update_or_create(
                            user=request.user,
                            calendar_type=ct,
                            company=company,
                            defaults=defaults,
                        )
                    )

                    if not created:
                        preference.is_selected = True
                        if not preference.company:
                            preference.company = company
                        preference.save(update_fields=["is_selected", "company"])

                _save_unchecked_calendar_types(request.user, company, standard_types)

                if custom_pks:
                    CustomCalendar.objects.filter(
                        user=request.user, pk__in=custom_pks
                    ).update(is_selected=True)

            messages.success(request, _("Preferences saved successfully"))

            return JsonResponse(
                {"status": "success", "message": "Preferences saved successfully"}
            )
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)


class GetCalendarEventsView(LoginRequiredMixin, View):
    """View to fetch calendar events based on user preferences."""

    def get(self, request, *args, **kwargs):
        """Handle AJAX GET request to fetch calendar events."""

        if not request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return render(request, "405.html", status=405)

        try:
            selected_types = request.GET.getlist("calendar_types[]")
            if not selected_types and "calendar_types[]" in request.GET:
                return JsonResponse({"status": "success", "events": []})

            if not selected_types:
                # Same rule as the sidebar: a type without a row is checked.
                unchecked = set(
                    UserCalendarPreference.objects.filter(
                        user=request.user, is_selected=False
                    ).values_list("calendar_type", flat=True)
                )
                selected_types = [
                    ct for ct in DEFAULT_CALENDAR_TYPE_COLORS if ct not in unchecked
                ]
                selected_types += [
                    f"custom_{pk}"
                    for pk in CustomCalendar.objects.filter(
                        user=request.user, is_selected=True, is_active=True
                    ).values_list("id", flat=True)
                ]

            events = []
            if selected_types:
                # Fetch Activity events (exclude unavailability and custom calendars)
                activity_types = [
                    t
                    for t in selected_types
                    if t != "unavailability"
                    and not (isinstance(t, str) and t.startswith("custom_"))
                ]
                if activity_types:
                    activities = (
                        Activity.objects.filter(
                            activity_type__in=activity_types,
                            assigned_to=request.user,
                        )
                        | Activity.objects.filter(
                            activity_type__in=activity_types, participants=request.user
                        )
                        | Activity.objects.filter(
                            activity_type__in=activity_types, owner=request.user
                        )
                        | Activity.objects.filter(
                            activity_type__in=activity_types, meeting_host=request.user
                        )
                    ).prefetch_related("assigned_to", "related_object")

                    related_urls = {}
                    for activity in activities.distinct():
                        start_dt = activity.get_start_date()
                        end_dt = activity.get_end_date()
                        start_display = (
                            format_datetime_value(start_dt, user=request.user)
                            if not isinstance(start_dt, str)
                            else start_dt
                        )
                        end_display = (
                            format_datetime_value(end_dt, user=request.user)
                            if not isinstance(end_dt, str) and end_dt
                            else None
                        )
                        due_date_display = None
                        if activity.activity_type == "task" and activity.due_datetime:
                            due_date_display = format_datetime_value(
                                activity.due_datetime, user=request.user
                            )
                        # get_start_date()/get_end_date() return a translated
                        # "All Day Event" label (not a datetime) for all-day
                        # events/meetings, so the actual ISO timestamps for
                        # FullCalendar must come from the raw datetime fields.
                        start_raw = (
                            activity.start_datetime
                            or activity.due_datetime
                            or activity.created_at
                        )
                        end_raw = (
                            activity.end_datetime
                            or activity.due_datetime
                            or activity.created_at
                        )
                        event = {
                            "title": activity.title or activity.subject,
                            "start": start_raw.isoformat(),
                            "end": end_raw.isoformat() if end_raw else None,
                            "calendarType": activity.activity_type,
                            "activity_type_display": activity.get_activity_type_display(),
                            "description": activity.description or "",
                            "subject": activity.subject or "",
                            "assignedTo": [
                                {
                                    "id": user.id,
                                    "first_name": user.first_name,
                                    "last_name": user.last_name,
                                    "email": user.email,
                                }
                                for user in activity.assigned_to.all()
                            ],
                            "status": activity.status,
                            "status_display": activity.get_status_display(),
                            "start_display": start_display,
                            "end_display": end_display,
                            "due_date_display": due_date_display,
                            "id": activity.id,
                            "url": (
                                activity.get_activity_edit_url()
                                if activity.activity_type != "email"
                                else None
                            ),
                            "deleteUrl": (
                                activity.get_delete_url()
                                if activity.activity_type != "email"
                                else None
                            ),
                            "detailUrl": (
                                activity.get_detail_url()
                                if activity.activity_type != "email"
                                else None
                            ),
                            "relatedUrl": _related_record_url(
                                activity, request.user, related_urls
                            ),
                            "dueDate": (
                                activity.due_datetime.isoformat()
                                if activity.activity_type == "task"
                                and activity.due_datetime
                                else None
                            ),
                            "textColor": "#FFFFFF",
                        }
                        if (
                            activity.activity_type in ["event", "meeting"]
                            and activity.is_all_day
                        ):
                            event["allDay"] = True
                        events.append(event)

                # Fetch UserAvailability events if selected
                if "unavailability" in selected_types:
                    unavailabilities = UserAvailability.objects.filter(
                        user=self.request.user
                    )
                    for unavailability in unavailabilities:
                        start_display = format_datetime_value(
                            unavailability.from_datetime, user=request.user
                        )
                        end_display = (
                            format_datetime_value(
                                unavailability.to_datetime, user=request.user
                            )
                            if unavailability.to_datetime
                            else None
                        )
                        # Use the event title for Google-sourced events; fall back to "User Unavailable"
                        if unavailability.reason and unavailability.reason.startswith(
                            "[Google]"
                        ):
                            event_title = unavailability.reason[len("[Google] ") :]
                        else:
                            event_title = _("User Unavailable")
                        event = {
                            "title": event_title,
                            "start": unavailability.from_datetime.isoformat(),
                            "end": (
                                unavailability.to_datetime.isoformat()
                                if unavailability.to_datetime
                                else None
                            ),
                            "start_display": start_display,
                            "end_display": end_display,
                            "calendarType": "unavailability",
                            "description": unavailability.reason
                            or "No reason provided",
                            "id": f"unavailability_{unavailability.id}",
                            "url": (
                                unavailability.update_mark_unavailability_url()
                                if unavailability.pk
                                else None
                            ),
                            "deleteUrl": (
                                unavailability.delete_mark_unavailability_url()
                                if unavailability.pk
                                else None
                            ),
                            "backgroundColor": "#F51414",
                            "borderColor": "#F51414",
                            "textColor": "#FFFFFF",
                        }
                        events.append(event)

                custom_ids = []
                for t in selected_types:
                    if isinstance(t, str) and t.startswith("custom_"):
                        try:
                            custom_ids.append(int(t.replace("custom_", "", 1)))
                        except ValueError:
                            continue
                if custom_ids:
                    for cc in CustomCalendar.objects.filter(
                        user=request.user, pk__in=custom_ids, is_active=True
                    ):
                        events.extend(events_for_custom_calendar(request, cc))

            return JsonResponse({"status": "success", "events": events})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)


class MarkCompletedView(LoginRequiredMixin, View):
    """View to mark an activity as completed via AJAX."""

    def post(self, request, *args, **kwargs):
        """Handle AJAX POST request to mark activity as completed."""
        try:
            data = json.loads(request.body)
            event_id = data.get("event_id")
            new_status = data.get("status")

            if not event_id or not new_status:
                return JsonResponse(
                    {"status": "error", "message": "Missing event_id or status"},
                    status=400,
                )

            activity = Activity.objects.get(pk=event_id)

            if not request.user.has_perm("activity.change_own_activity"):
                return JsonResponse(
                    {
                        "status": "error",
                        "message": "Permission denied: You don't have permission to change activities",
                    },
                    status=403,
                )

            status_permission = get_user_field_permission(
                request.user, Activity, "status"
            )
            if status_permission != "readwrite":
                return JsonResponse(
                    {
                        "status": "error",
                        "message": "Permission denied: You don't have permission to change status",
                    },
                    status=403,
                )

            if new_status not in dict(Activity.STATUS_CHOICES):
                return JsonResponse(
                    {"status": "error", "message": "Invalid status"}, status=400
                )

            activity.status = new_status
            activity.save()

            messages.success(request, _("Marked as completed successfully."))
            return JsonResponse(
                {
                    "status": "success",
                }
            )

        except Activity.DoesNotExist as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=404)
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)


@method_decorator(htmx_required, name="dispatch")
class CustomCalendarFormView(LoginRequiredMixin, HorillaSingleFormView):
    """Create or update a user-defined module-backed calendar with filter conditions."""

    model = CustomCalendar
    form_class = CustomCalendarForm

    condition_fields = ["field", "operator", "value"]
    condition_model = CustomCalendarCondition
    condition_related_name = "conditions"

    condition_order_by = ["sequence"]
    content_type_field = "module"
    condition_hx_include = "#id_module"

    hidden_fields = ["is_selected"]
    full_width_fields = ["name", "color"]
    save_and_new = False
    view_id = "customcalendar-form-view"
    modal_height = False
    return_response = ScriptResponse(reload=True, close=True)

    @cached_property
    def form_url(self):
        """Return the create or update URL for the custom calendar form."""
        pk = self.kwargs.get("pk")
        if pk:
            return reverse_lazy("calendar:custom_calendar_update", kwargs={"pk": pk})
        return reverse_lazy("calendar:custom_calendar_create")

    def get_object_or_error_response(self, request):
        """Return calendar-aware reload script when the custom calendar pk is not found."""
        obj, error_response = super().get_object_or_error_response(request)
        if error_response is not None:
            error_response = ScriptResponse(reload=True, close=True)

        return obj, error_response

    def form_valid(self, form):
        if not form.instance.pk:
            form.instance.user = self.request.user
        return super().form_valid(form)


@method_decorator(htmx_required, name="dispatch")
class UserAvailabilityFormView(LoginRequiredMixin, HorillaSingleFormView):
    """View to handle marking user unavailability via a form."""

    model = UserAvailability
    form_title = _("Mark Unavailability")
    modal_height = False
    hidden_fields = ["user", "company", "is_active", "google_event_id"]
    full_width_fields = ["from_datetime", "to_datetime", "reason"]
    save_and_new = False

    @cached_property
    def form_url(self):
        """Generate the form URL based on whether it's an update or create action."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "calendar:update_mark_unavailability", kwargs={"pk": pk}
            )
        return reverse_lazy("calendar:mark_unavailability")

    def get_initial(self):
        """Set initial form data (company, user, optional start date/time from request)."""
        initial = super().get_initial()
        company = (
            getattr(_thread_local, "request", None).active_company
            if hasattr(_thread_local, "request")
            else self.request.user.company
        )
        initial["company"] = company
        initial["user"] = self.request.user
        initial["company"] = company
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if not pk:
            date_str = self.request.GET.get("start_date_time")
            if date_str:
                try:
                    clicked_datetime = datetime.datetime.fromisoformat(date_str)

                    clicked_date = clicked_datetime.date()
                    clicked_time = clicked_datetime.time()

                    start_datetime = timezone.make_aware(
                        datetime.datetime.combine(clicked_date, clicked_time)
                    )

                    end_datetime = start_datetime + datetime.timedelta(minutes=30)

                    initial["from_datetime"] = start_datetime
                    initial["to_datetime"] = end_datetime

                except ValueError:
                    initial["from_datetime"] = timezone.now()
                    initial["to_datetime"] = timezone.now()
            else:
                now = timezone.now()
                initial["from_datetime"] = now
                initial["to_datetime"] = now + datetime.timedelta(minutes=30)

        return initial

    def form_valid(self, form):
        """
        Handle form submission and save the meeting.
        """

        super().form_valid(form)
        return ScriptResponse(reload=True, close=True)

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("calendar.delete_userunavailability"),
    name="dispatch",
)
class UserAvailabilityDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View to handle deletion of user unavailability records."""

    model = UserAvailability

    def get_post_delete_response(self):
        return HxTriggerResponse()


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("calendar.delete_customcalendar"),
    name="dispatch",
)
class CustomCalendarDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View to handle deletion of custom calendar records."""

    model = CustomCalendar

    def get_post_delete_response(self):
        return HxTriggerResponse()

    def _calendar_not_found_response(self, request, exc):
        """Add error message and reload the calendar when the object is not found."""
        messages.error(request, _(str(exc)))
        return ScriptResponse(reload=True, extra="closeDeleteModeModal();")

    def get(self, request, *args, **kwargs):
        """Intercept missing-object early so we can return a calendar-aware reload."""
        try:
            self.object = self.get_object()
        except Exception as e:
            return self._calendar_not_found_response(request, e)
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        """Intercept missing-object early so we can return a calendar-aware reload."""
        try:
            self.object = self.get_object()
        except Exception as e:
            return self._calendar_not_found_response(request, e)
        return self.delete(request, *args, **kwargs)
