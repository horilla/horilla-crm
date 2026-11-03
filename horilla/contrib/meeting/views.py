"""Views for the Horilla Meeting Integration app."""

# Standard library imports
import time as _time
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

# Third-party imports (Django)
from django.contrib import messages
from django.template.loader import render_to_string

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.auth.models import User
from horilla.contrib.generics.templatetags.horilla_tags.display_tags import (
    render_user_chip,
)
from horilla.contrib.generics.views.single_form import HorillaSingleFormView
from horilla.shortcuts import redirect, render
from horilla.urls import reverse, reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import HttpResponse, HttpResponseRedirect, RefreshResponse

# Local imports
from .forms import (
    MeetingAccessRolesForm,
    MeetingAccessUsersForm,
    MeetingIntegrationSettingForm,
)
from .models import (
    MeetingIntegrationSetting,
    MicrosoftTeamsOAuthConfig,
    UserMeetingConfig,
    ZoomOAuthConfig,
)

_ADMIN_SETTINGS_TEMPLATE = "meeting/meeting_integration_settings.html"
_USER_SETTINGS_TEMPLATE = "meeting/meeting_user_settings.html"


def _get_active_company(request):
    return getattr(request, "active_company", None) or request.user.company


def _clear_meeting_credentials(users_qs):
    """Delete all meeting OAuth data for the given user queryset."""

    ZoomOAuthConfig.objects.filter(user__in=users_qs).delete()
    MicrosoftTeamsOAuthConfig.objects.filter(user__in=users_qs).delete()
    UserMeetingConfig.objects.filter(user__in=users_qs).delete()


# ─────────────────────────────────────────────────────────────
# Admin Views  (Settings → Integrations)
# ─────────────────────────────────────────────────────────────


class MeetingIntegrationSettingsView(LoginRequiredMixin, View):
    """
    Admin view: single enable/disable toggle for meeting integration
    plus access-control configuration.

    GET  — renders the settings page.
    POST — enables or disables the integration (via hx-vals),
           or saves access-type/allowed fields.
    """

    @method_decorator(
        permission_required_or_denied("meeting.change_meetingintegrationsetting")
    )
    def dispatch(self, *args, **kwargs):
        """Require meeting integration settings change permission before dispatch."""
        return super().dispatch(*args, **kwargs)

    def _render(self, request, form=None):
        from horilla.contrib.core.models import Role

        company = _get_active_company(request)
        setting = MeetingIntegrationSetting.get_for_company(company)
        if form is None:
            form = MeetingIntegrationSettingForm(instance=setting)

        all_roles = Role.objects.filter(company=company)
        all_users = User.objects.filter(company=company, is_active=True)
        selected_role_ids = (
            list(setting.allowed_roles.values_list("pk", flat=True)) if setting else []
        )
        selected_user_ids = (
            list(setting.allowed_users.values_list("pk", flat=True)) if setting else []
        )

        context = {
            "integration_setting": setting,
            "form": form,
            "all_roles": all_roles,
            "all_users": all_users,
            "selected_role_ids": selected_role_ids,
            "selected_user_ids": selected_user_ids,
        }
        return render(request, _ADMIN_SETTINGS_TEMPLATE, context)

    def get(self, request, *args, **kwargs):
        """Render admin meeting integration settings."""
        if request.GET.get("check"):
            # Pre-check before an access change confirmation on a stale page.
            setting = MeetingIntegrationSetting.get_for_company(
                _get_active_company(request)
            )
            if setting and setting.is_enabled:
                return HttpResponse(status=204)
            messages.warning(
                request,
                _("Meeting integration is disabled. Enable it to continue."),
            )
        return self._render(request)

    def post(self, request, *args, **kwargs):
        """Toggle integration, update access type, or persist related admin actions."""
        company = _get_active_company(request)
        setting = MeetingIntegrationSetting.get_for_company(company)
        if setting is None:
            messages.error(request, _("No active company found.Cannot save settings."))
            return self._render(request)

        # Toggle enable/disable (sent via hx-vals from the toggle buttons)
        if "is_meeting_enabled" in request.POST:
            value = request.POST.get("is_meeting_enabled") == "true"
            if value == setting.is_enabled:
                # Another tab/user already changed it; the page is stale.
                if value:
                    messages.warning(
                        request, _("Meeting integration is already enabled.")
                    )
                else:
                    messages.warning(
                        request, _("Meeting integration is already disabled.")
                    )
                return self._render(request)
            setting.is_enabled = value
            setting.save(update_fields=["is_enabled"])

            if value:
                messages.success(request, _("Meeting integration enabled."))
            else:
                company_users = User.objects.filter(company=company)
                _clear_meeting_credentials(company_users)
                messages.success(
                    request,
                    _("Meeting integration disabled and all credentials cleared."),
                )
            return self._render(request)

        # Every other action needs the integration to be enabled
        if not setting.is_enabled:
            messages.warning(
                request,
                _("Meeting integration is disabled. Enable it to change access."),
            )
            return self._render(request)

        # "All Users" — no credentials to clear, everyone gets access
        if request.POST.get("access_type") == "all":
            setting.access_type = "all"
            setting.save(update_fields=["access_type"])
            messages.success(request, _("Access set to All Users."))
            return self._render(request)

        return self._render(request)


class _MeetingAllowedAccessModalView(LoginRequiredMixin, View):
    """Read-only modal listing who can use meeting integration, as pills in a grid."""

    title = ""
    show_search = True
    list_class = "grid grid-cols-3"
    # Below this many people the search box and grid only add empty space
    compact_threshold = 9

    @method_decorator(
        permission_required_or_denied("meeting.change_meetingintegrationsetting")
    )
    def dispatch(self, request, *args, **kwargs):
        """Require meeting integration settings change permission before dispatch."""
        if request.user.is_authenticated:
            setting = MeetingIntegrationSetting.get_for_company(
                _get_active_company(request)
            )
            if setting and not setting.is_enabled:
                messages.warning(
                    request,
                    _("Meeting integration is disabled. Enable it to change access."),
                )
                return RefreshResponse(request=request)
        return super().dispatch(request, *args, **kwargs)

    def get_items(self, request, setting, company):
        """Return a list of ``{"name", "chip"}`` dicts for everyone with access."""
        raise NotImplementedError

    def get(self, request, *args, **kwargs):
        """Render the modal, or only the pill list when the search box asks for it."""
        company = _get_active_company(request)
        setting = MeetingIntegrationSetting.get_for_company(company)
        items = self.get_items(request, setting, company) if setting else []
        total = len(items)
        query = request.GET.get("q", "").strip().lower()
        items = [item for item in items if query in item["name"].lower()]
        compact = total <= self.compact_threshold
        context = {
            "title": self.title,
            "items": items,
            "total": total,
            "show_search": self.show_search and not compact,
            "list_class": "flex flex-wrap" if compact else self.list_class,
            "empty_msg": (
                _("No Matching Results") if total else _("Nothing Selected Yet")
            ),
        }
        # The search box swaps only the pill list; the first load gets the whole modal
        template = (
            "partials/chip_list.html"
            if request.headers.get("HX-Target") == "accessList"
            else "meeting/allowed_access_modal.html"
        )
        return render(request, template, context)


@method_decorator(htmx_required, name="dispatch")
class MeetingAllowedUsersListView(_MeetingAllowedAccessModalView):
    """Read-only modal of the users allowed to use meeting integration."""

    title = _("Users With Access")

    def get_items(self, request, setting, company):
        users = (
            User.objects.filter(
                company=company,
                is_active=True,
                pk__in=setting.allowed_users.values_list("pk", flat=True),
            )
            .select_related("role")
            .order_by("first_name", "last_name")
        )
        return [
            {
                "name": user.get_full_name() or user.username,
                "chip": render_user_chip(user, request.user),
            }
            for user in users
        ]


@method_decorator(htmx_required, name="dispatch")
class MeetingAllowedRolesListView(_MeetingAllowedAccessModalView):
    """Read-only modal of the roles allowed to use meeting integration."""

    title = _("Roles With Access")
    show_search = False
    list_class = "flex flex-wrap"

    def get_items(self, request, setting, company):
        from horilla.contrib.core.models import Role

        roles = Role.objects.filter(
            company=company, pk__in=setting.allowed_roles.values_list("pk", flat=True)
        ).order_by("role_name")
        return [
            {
                "name": role.role_name,
                "chip": render_to_string(
                    "partials/role_pill.html", {"role_name": role.role_name}
                ),
            }
            for role in roles
        ]


@method_decorator(htmx_required, name="dispatch")
class MeetingAccessRolesView(LoginRequiredMixin, HorillaSingleFormView):
    """Modal form: select which roles can access meeting integration."""

    model = MeetingIntegrationSetting
    form_class = MeetingAccessRolesForm
    form_title = _("Select Roles")
    form_url = reverse_lazy("meeting:meeting_access_roles")
    full_width_fields = ["allowed_roles"]
    modal_height = False
    save_and_new = False

    @method_decorator(
        permission_required_or_denied("meeting.change_meetingintegrationsetting")
    )
    def dispatch(self, request, *args, **kwargs):
        """Require meeting integration settings change permission before dispatch."""
        if request.user.is_authenticated:
            setting = MeetingIntegrationSetting.get_for_company(
                _get_active_company(request)
            )
            if setting and not setting.is_enabled:
                messages.warning(
                    request,
                    _("Meeting integration is disabled. Enable it to change access."),
                )
                return RefreshResponse(request=request)
        return super().dispatch(request, *args, **kwargs)

    def _get_m2m_picker_info(self):
        return {}

    def get_form(self, form_class=None):
        """Scope allowed_roles queryset and initial values to the active company."""
        form = super().get_form(form_class)
        company = _get_active_company(self.request)
        setting = MeetingIntegrationSetting.get_for_company(company)
        from horilla.contrib.core.models import Role

        form.fields["allowed_roles"].queryset = Role.objects.filter(company=company)
        form.fields["allowed_roles"].initial = setting.allowed_roles.all()
        return form

    def form_valid(self, form):
        company = _get_active_company(self.request)
        setting = MeetingIntegrationSetting.get_for_company(company)
        if not setting.is_enabled:
            messages.warning(
                self.request,
                _("Meeting integration is disabled. Enable it to change access."),
            )
            return RefreshResponse(request=self.request)
        new_roles = form.cleaned_data["allowed_roles"]

        # Find users whose roles are being removed
        removed_roles = setting.allowed_roles.exclude(
            pk__in=new_roles.values_list("pk", flat=True)
        )
        users_losing_access = User.objects.filter(
            company=company, role__in=removed_roles
        )

        setting.access_type = "roles"
        setting.save(update_fields=["access_type"])
        setting.allowed_roles.set(new_roles)

        if users_losing_access.exists():
            _clear_meeting_credentials(users_losing_access)

        messages.success(self.request, _("Allowed roles updated."))
        return RefreshResponse(request=self.request)


@method_decorator(htmx_required, name="dispatch")
class MeetingAccessUsersView(LoginRequiredMixin, HorillaSingleFormView):
    """Modal form: select which users can access meeting integration."""

    model = MeetingIntegrationSetting
    form_class = MeetingAccessUsersForm
    form_title = _("Select Users")
    form_url = reverse_lazy("meeting:meeting_access_users")
    full_width_fields = ["allowed_users"]
    modal_height = False
    save_and_new = False

    @method_decorator(
        permission_required_or_denied("meeting.change_meetingintegrationsetting")
    )
    def dispatch(self, request, *args, **kwargs):
        """Require meeting integration settings change permission before dispatch."""
        if request.user.is_authenticated:
            setting = MeetingIntegrationSetting.get_for_company(
                _get_active_company(request)
            )
            if setting and not setting.is_enabled:
                messages.warning(
                    request,
                    _("Meeting integration is disabled. Enable it to change access."),
                )
                return RefreshResponse(request=request)
        return super().dispatch(request, *args, **kwargs)

    def get_form(self, form_class=None):
        """Scope allowed_users queryset and initial values to the active company."""
        form = super().get_form(form_class)
        company = _get_active_company(self.request)
        setting = MeetingIntegrationSetting.get_for_company(company)

        form.fields["allowed_users"].queryset = User.objects.filter(
            company=company, is_active=True
        )
        form.fields["allowed_users"].initial = setting.allowed_users.all()
        return form

    def form_valid(self, form):
        company = _get_active_company(self.request)
        setting = MeetingIntegrationSetting.get_for_company(company)
        if not setting.is_enabled:
            messages.warning(
                self.request,
                _("Meeting integration is disabled. Enable it to change access."),
            )
            return RefreshResponse(request=self.request)
        new_users = form.cleaned_data["allowed_users"]

        # Find users being removed from the allowed list
        removed_users = setting.allowed_users.exclude(
            pk__in=new_users.values_list("pk", flat=True)
        )

        setting.access_type = "users"
        setting.save(update_fields=["access_type"])
        setting.allowed_users.set(new_users)

        if removed_users.exists():
            _clear_meeting_credentials(removed_users)

        messages.success(self.request, _("Allowed users updated."))
        return RefreshResponse(request=self.request)


# ─────────────────────────────────────────────────────────────
# User / My-Settings Views
# ─────────────────────────────────────────────────────────────


def _build_provider_cards(request, company, open_provider=None):
    """Build context cards for each meeting provider."""
    from horilla.contrib.calendar.models import GoogleCalendarConfig

    cards = {}

    zoom = ZoomOAuthConfig.objects.filter(user=request.user).first()
    cards["zoom"] = {
        "label": _("Zoom"),
        "oauth": True,
        "has_credentials": zoom.has_credentials() if zoom else False,
        "is_connected": zoom.is_connected() if zoom else False,
        "connected_email": zoom.connected_email if zoom else "",
        "client_id": zoom.client_id if zoom else "",
        "client_secret": zoom.client_secret if zoom else "",
        "show_panel": open_provider == "zoom",
    }

    # ── Google Meet (reuses Google Calendar OAuth) ──
    from horilla.contrib.calendar.models import GoogleIntegrationSetting

    # Enabled for the company AND this user is allowed by the Google access setting
    gcal_admin_enabled = GoogleIntegrationSetting.user_can_access(
        request.user, company, request=request
    )
    gcal = GoogleCalendarConfig.all_objects.filter(user=request.user).first()
    gcal_connected = gcal.is_connected() if gcal else False
    meet_cfg = UserMeetingConfig.objects.filter(
        user=request.user, provider="google_meet", company=company
    ).first()
    meet_enabled = bool(meet_cfg)
    cards["google_meet"] = {
        "label": _("Google Meet"),
        "oauth": True,
        "gcal_admin_enabled": gcal_admin_enabled,
        "has_credentials": gcal.is_configured() if gcal else False,
        "gcal_connected": gcal_connected,
        "is_connected": gcal_connected and meet_enabled,
        "meet_enabled": meet_enabled,
        "connected_email": gcal.google_email if gcal else "",
        "gcal_settings_url": reverse_lazy("calendar:google_calendar_settings"),
        "show_panel": open_provider == "google_meet",
    }

    # ── Microsoft Teams ──
    teams = MicrosoftTeamsOAuthConfig.objects.filter(user=request.user).first()
    cards["ms_teams"] = {
        "label": _("Microsoft Teams"),
        "oauth": True,
        "has_credentials": teams.has_credentials() if teams else False,
        "is_connected": teams.is_connected() if teams else False,
        "connected_email": teams.connected_email if teams else "",
        "client_id": teams.client_id if teams else "",
        "client_secret": teams.client_secret if teams else "",
        "tenant_id": teams.tenant_id if teams else "",
        "show_panel": open_provider == "ms_teams",
    }

    return cards


class MeetingUserSettingsView(LoginRequiredMixin, View):
    """My Settings page — OAuth connect cards per provider."""

    def _render(self, request, open_provider=None):
        company = request.user.company
        has_access = MeetingIntegrationSetting.user_can_access(request.user, company)
        context = {
            "has_access": has_access,
            "provider_cards": (
                _build_provider_cards(request, company, open_provider)
                if has_access
                else {}
            ),
        }
        return render(request, _USER_SETTINGS_TEMPLATE, context)

    def get(self, request, *args, **kwargs):
        """Show the current user's meeting OAuth and provider configuration."""
        return self._render(request)

    def post(self, request, *args, **kwargs):
        """Save OAuth credentials, disconnect providers, or toggle Google Meet linking."""
        company = request.user.company
        if not MeetingIntegrationSetting.user_can_access(
            request.user, company, request=request
        ):
            messages.error(
                request,
                _("Meeting integration is disabled or you do not have access to it."),
            )
            return self._render(request)
        provider = request.POST.get("provider")
        action = request.POST.get("action", "save_credentials")

        # ── Zoom: save credentials ──
        if provider == "zoom" and action == "save_credentials":

            cfg, _created = ZoomOAuthConfig.all_objects.get_or_create(
                user=request.user, company=company
            )
            cfg.client_id = request.POST.get("client_id", "").strip()
            cfg.client_secret = request.POST.get("client_secret", "").strip()
            cfg.company = company
            cfg.save(update_fields=["client_id", "client_secret", "company"])
            messages.success(
                request, _("Zoom credentials saved. Click Connect to authorize.")
            )
            return self._render(request)

        if provider == "zoom" and action == "disconnect":

            ZoomOAuthConfig.objects.filter(user=request.user).update(
                token={}, connected_email=""
            )
            messages.success(request, _("Zoom account disconnected."))
            return self._render(request)

        # ── Google Meet: enable / disable ──
        if provider == "google_meet" and action == "enable":
            from horilla.contrib.calendar.models import GoogleCalendarConfig

            gcal = GoogleCalendarConfig.all_objects.filter(user=request.user).first()
            if not gcal or not gcal.is_connected():
                messages.error(
                    request, _("Connect Google Calendar first to enable Google Meet.")
                )
                return self._render(request)
            _cfg, created = UserMeetingConfig.objects.get_or_create(
                user=request.user,
                provider="google_meet",
                defaults={"company": company, "personal_meeting_url": ""},
            )
            if created:
                messages.success(
                    request, _("Google Meet enabled for meeting link generation.")
                )
            else:
                messages.warning(request, _("Google Meet is already enabled."))
            return self._render(request)

        if provider == "google_meet" and action == "disable":
            deleted, _count = UserMeetingConfig.objects.filter(
                user=request.user, provider="google_meet", company=company
            ).delete()
            if deleted:
                messages.success(request, _("Google Meet disabled."))
            else:
                messages.warning(request, _("Google Meet is already disabled."))
            return self._render(request)

        # ── Teams: save credentials ──
        if provider == "ms_teams" and action == "save_credentials":

            cfg, _created = MicrosoftTeamsOAuthConfig.all_objects.get_or_create(
                user=request.user, company=company
            )
            cfg.client_id = request.POST.get("client_id", "").strip()
            cfg.client_secret = request.POST.get("client_secret", "").strip()
            cfg.tenant_id = request.POST.get("tenant_id", "common").strip()
            cfg.company = company
            cfg.save(
                update_fields=["client_id", "client_secret", "tenant_id", "company"]
            )
            messages.success(
                request, _("Teams credentials saved. Click Connect to authorize.")
            )
            return self._render(request)

        if provider == "ms_teams" and action == "disconnect":

            MicrosoftTeamsOAuthConfig.objects.filter(user=request.user).update(
                token={}, connected_email=""
            )
            messages.success(request, _("Teams account disconnected."))
            return self._render(request)

        return self._render(request)


# ─────────────────────────────────────────────────────────────
# Generate meeting link (called from activity form)
# ─────────────────────────────────────────────────────────────


class GenerateMeetingLinkView(LoginRequiredMixin, View):
    """
    POST: generate a meeting link for the given provider and return JSON.
    Called via fetch() from the activity meeting form.
    """

    def post(self, request, *args, **kwargs):
        """Create a Zoom, Teams, Google Meet, or manual meeting URL and return JSON."""
        from horilla.web import JsonResponse

        if not MeetingIntegrationSetting.user_can_access(
            request.user, request.user.company, request=request
        ):
            return JsonResponse(
                {"error": str(_("Meeting integration is disabled or not accessible."))},
                status=403,
            )

        provider = request.POST.get("provider", "zoom")
        title = request.POST.get("title", "Meeting")
        start_dt = request.POST.get("start_datetime")
        end_dt = request.POST.get("end_datetime")

        def _parse(dt_str):
            if not dt_str:
                return None
            for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return datetime.strptime(dt_str, fmt)
                except ValueError:
                    continue
            return None

        start = _parse(start_dt)
        end = _parse(end_dt)

        if provider == "zoom":
            from horilla.contrib.meeting.oauth.zoom import create_meeting

            config = ZoomOAuthConfig.objects.filter(user=request.user).first()
            if not config or not config.is_connected():
                return JsonResponse(
                    {
                        "error": "Zoom account not connected. Go to My Settings → Meeting to connect."
                    },
                    status=400,
                )
            url, error = create_meeting(config, title, start, end)
            if error:
                return JsonResponse({"error": error}, status=400)
            return JsonResponse({"url": url})

        if provider == "ms_teams":
            from horilla.contrib.meeting.oauth.teams import create_meeting

            config = MicrosoftTeamsOAuthConfig.objects.filter(user=request.user).first()
            if not config or not config.is_connected():
                return JsonResponse(
                    {
                        "error": "Teams account not connected. Go to My Settings → Meeting to connect."
                    },
                    status=400,
                )
            url, error = create_meeting(config, title, start, end)
            if error:
                return JsonResponse({"error": error}, status=400)
            return JsonResponse({"url": url})

        if provider == "google_meet":
            from horilla.contrib.calendar.models import GoogleCalendarConfig

            config = GoogleCalendarConfig.all_objects.filter(user=request.user).first()
            if not config or not config.is_connected():
                return JsonResponse(
                    {
                        "error": "Google account not connected. Go to My Settings → Google Calendar to connect."
                    },
                    status=400,
                )
            try:
                from horilla.contrib.calendar.google_calendar.client_settings import (
                    GOOGLE_CALENDAR_API_BASE,
                    PRIMARY_CALENDAR_ID,
                )
                from horilla.contrib.calendar.google_calendar.service import (
                    GOOGLE_API_TIMEOUT,
                    _get_oauth_session,
                )

                session = _get_oauth_session(config)
                _start = start or datetime.now(dt_timezone.utc)
                if _start.tzinfo is None:
                    _start = _start.replace(tzinfo=dt_timezone.utc)
                _end = end or (_start + timedelta(hours=1))
                if _end.tzinfo is None:
                    _end = _end.replace(tzinfo=dt_timezone.utc)

                def _fmt(d):
                    return d.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:00")

                body = {
                    "summary": title,
                    "start": {"dateTime": _fmt(_start), "timeZone": "UTC"},
                    "end": {"dateTime": _fmt(_end), "timeZone": "UTC"},
                    "conferenceData": {
                        "createRequest": {
                            "requestId": f"horilla-meet-{request.user.pk}-{int(_time.time())}",
                            "conferenceSolutionKey": {"type": "hangoutsMeet"},
                        }
                    },
                }
                url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{PRIMARY_CALENDAR_ID}/events?conferenceDataVersion=1"
                resp = session.post(url, json=body, timeout=GOOGLE_API_TIMEOUT)
                resp.raise_for_status()
                result = resp.json()
                meet_url = result.get("hangoutLink") or ""
                if not meet_url:
                    for ep in result.get("conferenceData", {}).get("entryPoints", []):
                        if ep.get("entryPointType") == "video":
                            meet_url = ep.get("uri", "")
                            break
                google_event_id = result.get("id")
                if google_event_id:
                    del_url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{PRIMARY_CALENDAR_ID}/events/{google_event_id}"
                    session.delete(del_url, timeout=GOOGLE_API_TIMEOUT)
                if not meet_url:
                    return JsonResponse(
                        {"error": "Could not retrieve Meet link from Google."},
                        status=400,
                    )
                return JsonResponse({"url": meet_url})
            except Exception as e:
                return JsonResponse({"error": str(e)}, status=400)

        return JsonResponse(
            {
                "error": f"Provider '{provider}' does not support auto-generation. Please enter the URL manually."
            },
            status=400,
        )


# ─────────────────────────────────────────────────────────────
# Zoom OAuth views
# ─────────────────────────────────────────────────────────────


class ZoomAuthorizeView(LoginRequiredMixin, View):
    """Redirect user to Zoom OAuth consent screen."""

    def get(self, request, *args, **kwargs):
        """Send the browser to Zoom's authorization URL when credentials are configured."""
        from horilla.contrib.meeting.oauth.zoom import get_or_create_config, start_oauth

        config = get_or_create_config(request.user)
        if not config.has_credentials():
            messages.error(
                request, _("Please save your Zoom Client ID and Secret first.")
            )
            return redirect(reverse("meeting:meeting_user_settings"))
        auth_url = start_oauth(request)

        return HttpResponseRedirect(auth_url)


class ZoomCallbackView(View):
    """Handle Zoom OAuth callback."""

    def get(self, request, *args, **kwargs):
        """Exchange the callback for tokens, set flash messages, then return to settings."""
        from horilla.contrib.meeting.oauth.zoom import handle_callback

        _config, error = handle_callback(request)
        if error:
            messages.error(request, f"Zoom OAuth error: {error}")
        else:
            messages.success(request, _("Zoom account connected successfully."))
        return redirect(reverse("meeting:meeting_user_settings"))


# ─────────────────────────────────────────────────────────────
# Microsoft Teams OAuth views
# ─────────────────────────────────────────────────────────────


class TeamsAuthorizeView(LoginRequiredMixin, View):
    """Redirect user to Microsoft OAuth consent screen."""

    def get(self, request, *args, **kwargs):
        """Send the browser to Microsoft's authorization URL when credentials are configured."""
        from horilla.contrib.meeting.oauth.teams import (
            get_or_create_config,
            start_oauth,
        )

        config = get_or_create_config(request.user)
        if not config.has_credentials():
            messages.error(
                request,
                _("Please save your Teams Client ID, Secret and Tenant ID first."),
            )
            return redirect(reverse("meeting:meeting_user_settings"))
        auth_url = start_oauth(request)

        return HttpResponseRedirect(auth_url)


class TeamsCallbackView(View):
    """Handle Microsoft Teams OAuth callback."""

    def get(self, request, *args, **kwargs):
        """Complete the OAuth dance, set flash messages, then return to settings."""
        from horilla.contrib.meeting.oauth.teams import handle_callback

        _config, error = handle_callback(request)
        if error:
            messages.error(request, f"Teams OAuth error: {error}")
        else:
            messages.success(request, _("Teams account connected successfully."))
        return redirect(reverse("meeting:meeting_user_settings"))
