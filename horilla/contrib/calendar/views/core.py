"""Calendar page and calendar preference views."""

# Standard library imports
import json

# Third-party imports (Django)
from django.contrib import messages

from horilla.auth.mixins import LoginRequiredMixin

# First party imports (Horilla)
from horilla.contrib.activity.models import Activity
from horilla.contrib.core.utils import get_user_field_permission
from horilla.contrib.generics.templatetags.horilla_tags.display_tags import (
    render_user_chip,
)
from horilla.contrib.utils.middlewares import get_active_company
from horilla.shortcuts import render
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext as _
from horilla.views.generic import TemplateView, View
from horilla.web import JsonResponse, ScriptResponse

# Local imports
from ..models import CustomCalendar, UserCalendarPreference
from .helpers import (
    DEFAULT_CALENDAR_TYPE_COLORS,
    DEFAULT_STATUS_COLORS,
    DEFAULT_TEXT_COLOR,
    HEX_COLOR_RE,
    TEXT_COLOR_PREFIX,
    _calendar_activities,
    _save_unchecked_calendar_types,
    _team_scope_available,
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
        # Text colors keyed by plain calendar id ("task", "custom_5", ...).
        context["text_preferences"] = {
            pref.calendar_type[len(TEXT_COLOR_PREFIX) :]: pref.color
            for pref in preferences
            if pref.calendar_type.startswith(TEXT_COLOR_PREFIX)
        }
        context["default_text_color"] = DEFAULT_TEXT_COLOR
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
        company = get_active_company(self.request)
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
        context["team_scope_available"] = _team_scope_available(self.request.user)

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
            company = get_active_company(request)

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

            text_color = data.get("text_color")
            if calendar_type and text_color and HEX_COLOR_RE.match(str(text_color)):
                is_custom = isinstance(calendar_type, str) and calendar_type.startswith(
                    "custom_"
                )
                text_key_ok = (
                    calendar_type in valid_types
                    or calendar_type in DEFAULT_STATUS_COLORS
                )
                if is_custom:
                    try:
                        custom_pk = int(calendar_type.replace("custom_", "", 1))
                    except ValueError:
                        custom_pk = None
                    text_key_ok = (
                        custom_pk is not None
                        and CustomCalendar.objects.filter(
                            user=request.user, pk=custom_pk
                        ).exists()
                    )
                if text_key_ok:
                    # Color-only row: never selected, so it is not fetched as a calendar.
                    UserCalendarPreference.objects.update_or_create(
                        user=request.user,
                        calendar_type=f"{TEXT_COLOR_PREFIX}{calendar_type}",
                        company=company,
                        defaults={"color": text_color, "is_selected": False},
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


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["activity.view_activity", "activity.view_own_activity"]
    ),
    name="dispatch",
)
class ActivityAssigneesView(LoginRequiredMixin, View):
    """Read-only modal listing everyone an activity is assigned to."""

    def get(self, request, *args, **kwargs):
        """Render the assignees of an activity the user can see on the calendar."""
        activity_types = [choice[0] for choice in Activity.ACTIVITY_TYPES]
        activity = (
            _calendar_activities(request.user, activity_types, team=True)
            .filter(pk=kwargs["pk"])
            .prefetch_related("assigned_to")
            .first()
        )
        if activity is None:
            messages.error(request, _("The requested record does not exist."))
            return ScriptResponse(msgs=True, close=True, reload=True)
        users = activity.assigned_to.all()
        total = len(users)
        query = request.GET.get("q", "").strip().lower()
        items = [
            {
                "name": user.get_full_name() or user.username,
                "chip": render_user_chip(user, request.user),
            }
            for user in users
            if query in (user.get_full_name() or user.username).lower()
        ]
        context = {
            "title": _("Assigned to"),
            "items": items,
            "total": total,
            # A short list does not need the search box or the 3-column grid
            "compact": total <= 9,
            "empty_msg": (
                _("No matching users.") if total else _("No users assigned yet.")
            ),
        }
        # The search box swaps only the chip list; the first load gets the whole modal
        template = (
            "activity_assignees_list.html"
            if request.headers.get("HX-Target") == "assigneesList"
            else "activity_assignees_modal.html"
        )
        return render(request, template, context)
