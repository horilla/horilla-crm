"""Views for the Horilla Calls Integration app."""

# Standard library imports
import logging

# Third-party imports (Django)
from django.contrib import messages
from django.template.loader import render_to_string

from horilla.auth.mixins import LoginRequiredMixin

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.models import Role
from horilla.contrib.generics.templatetags.horilla_tags.display_tags import (
    render_user_chip,
)
from horilla.contrib.generics.views import HorillaSingleFormView
from horilla.contrib.generics.views.core import HorillaTabView
from horilla.shortcuts import render
from horilla.urls import reverse, reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import HttpResponse, RedirectResponse, RefreshResponse

# Local imports
from ..forms import CallAccessRolesForm, CallAccessUsersForm, CallIntegrationSettingForm
from ..models import AgentMapping, CallIntegrationSetting, CallProvider

logger = logging.getLogger(__name__)


@method_decorator(
    permission_required_or_denied("calls.view_callintegrationsetting"), name="dispatch"
)
class CallIntegrationSettingsView(LoginRequiredMixin, View):
    """
    Admin settings page — enable/disable call integration and manage providers.
    Renders under Settings → Integrations, extending settings/settings.html.
    """

    template_name = "calls/integration_settings.html"

    def _render(self, request):
        company = request.active_company
        setting = CallIntegrationSetting.get_for_company(company) if company else None
        all_roles = (
            Role.objects.filter(company=company) if company else Role.objects.none()
        )
        all_users = (
            User.objects.filter(company=company, is_active=True)
            if company
            else User.objects.none()
        )
        selected_role_ids = (
            list(setting.allowed_roles.values_list("pk", flat=True)) if setting else []
        )
        selected_user_ids = (
            list(setting.allowed_users.values_list("pk", flat=True)) if setting else []
        )
        access_type = setting.access_type if setting else "all"
        return render(
            request,
            self.template_name,
            {
                "setting": setting,
                "form": CallIntegrationSettingForm(instance=setting),
                "all_roles": all_roles,
                "all_users": all_users,
                "selected_role_ids": selected_role_ids,
                "selected_user_ids": selected_user_ids,
                "access_all": access_type == "all",
                "access_roles": access_type == "roles",
                "access_users": access_type == "users",
            },
        )

    def get(self, request, *args, **kwargs):
        """Render the main settings page with the current setting values."""
        if request.GET.get("check"):
            # Pre-check before an access change confirmation on a stale page.
            company = request.active_company
            setting = CallIntegrationSetting.get_for_company(company)
            if setting and setting.is_enabled:
                return HttpResponse(status=204)
            messages.warning(
                request,
                _("Call integration is disabled. Enable it to continue."),
            )
        return self._render(request)

    def post(self, request, *args, **kwargs):
        """Handle form submission to update the main Call Integration settings (enabled + access type)."""
        company = request.active_company
        setting = CallIntegrationSetting.get_for_company(company)
        if setting is None:
            return self._render(request)
        is_enabled = request.POST.get("is_enabled") == "true"
        is_toggle = bool(request.POST.get("toggle"))
        if is_toggle and setting.is_enabled == is_enabled:
            state = _("enabled") if is_enabled else _("disabled")
            messages.warning(
                request, _("Call integration is already %(state)s.") % {"state": state}
            )
            return self._render(request)
        if not is_toggle and not setting.is_enabled:
            messages.warning(
                request,
                _("Call integration is disabled. Enable it to change access."),
            )
            return self._render(request)
        access_type = request.POST.get("access_type", setting.access_type)
        setting.is_enabled = is_enabled
        setting.access_type = access_type
        setting.save(update_fields=["is_enabled", "access_type"])
        if not is_toggle and access_type == "all":
            messages.success(request, _("Access set to All Users."))
        return self._render(request)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("calls.view_callintegrationsetting"), name="dispatch"
)
class CallSettingsTabView(LoginRequiredMixin, HorillaTabView):
    """Tab bar for the Call Integration settings page (Access Control / Providers)."""

    view_id = "call-settings-tab"

    def setup(self, request, *args, **kwargs):
        """Define the tabs for the settings page."""
        super().setup(request, *args, **kwargs)
        self.tabs = [
            {
                "title": _("Access Control"),
                "url": reverse_lazy("calls:settings_access_control"),
                "id": "access-control",
            },
            {
                "title": _("Providers"),
                "url": reverse_lazy("calls:settings_providers"),
                "id": "providers",
            },
        ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("calls.view_callintegrationsetting"), name="dispatch"
)
class CallAccessControlTabContent(LoginRequiredMixin, View):
    """HTMX content for the Access Control tab inside Call Integration settings."""

    template_name = "calls/tab_access_control.html"

    def get(self, request, *args, **kwargs):
        """Render the Access Control tab with the current setting values."""
        company = request.active_company
        setting = CallIntegrationSetting.get_for_company(company) if company else None
        selected_role_ids = (
            list(setting.allowed_roles.values_list("pk", flat=True)) if setting else []
        )
        selected_user_ids = (
            list(setting.allowed_users.values_list("pk", flat=True)) if setting else []
        )
        access_type = setting.access_type if setting else "all"
        return render(
            request,
            self.template_name,
            {
                "setting": setting,
                "selected_role_ids": selected_role_ids,
                "selected_user_ids": selected_user_ids,
                "access_all": access_type == "all",
                "access_roles": access_type == "roles",
                "access_users": access_type == "users",
            },
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("calls.view_callprovider"), name="dispatch"
)
class CallProvidersTabContent(LoginRequiredMixin, View):
    """HTMX wrapper for the Providers tab — renders help guide + Add button + provider list."""

    template_name = "calls/tab_providers.html"

    def get(self, request, *args, **kwargs):
        """Render the Providers tab with the list of existing providers and the Add Provider button."""
        return render(request, self.template_name)


# ── Access Control Modals ────────────────────────────────────────────────────


# @method_decorator(htmx_required, name="dispatch")
class CallAccessRolesView(LoginRequiredMixin, HorillaSingleFormView):
    """Modal: select which roles can access call integration."""

    model = CallIntegrationSetting
    form_class = CallAccessRolesForm
    form_title = _("Select Roles")
    form_url = reverse_lazy("calls:call_access_roles")
    full_width_fields = ["allowed_roles"]
    modal_height = False
    save_and_new = False

    def dispatch(self, request, *args, **kwargs):
        """Go back to the settings page when no company is active."""
        if request.user.is_authenticated:
            if not request.active_company:
                return RedirectResponse(
                    request, redirect_to=reverse("calls:integration_settings")
                )
        return super().dispatch(request, *args, **kwargs)

    def get_form(self, form_class=None):
        """Override to limit the allowed_roles queryset to roles from this company and set initial values."""
        company = self.request.active_company
        setting = CallIntegrationSetting.get_for_company(company)
        form = super().get_form(form_class)
        form.fields["allowed_roles"].queryset = Role.objects.filter(company=company)
        form.fields["allowed_roles"].initial = setting.allowed_roles.all()
        return form

    def form_valid(self, form):
        company = self.request.active_company
        setting = CallIntegrationSetting.get_for_company(company)
        setting.access_type = "roles"
        setting.save(update_fields=["access_type"])
        setting.allowed_roles.set(form.cleaned_data["allowed_roles"])
        messages.success(self.request, _("Allowed roles updated."))
        return RefreshResponse(request=self.request)


@method_decorator(htmx_required, name="dispatch")
class CallAccessUsersView(LoginRequiredMixin, HorillaSingleFormView):
    """Modal: select which users can access call integration."""

    model = CallIntegrationSetting
    form_class = CallAccessUsersForm
    form_title = _("Select Users")
    form_url = reverse_lazy("calls:call_access_users")
    full_width_fields = ["allowed_users"]
    modal_height = False
    save_and_new = False

    def dispatch(self, request, *args, **kwargs):
        """Go back to the settings page when no company is active."""
        if request.user.is_authenticated:
            if not request.active_company:
                return RedirectResponse(
                    request, redirect_to=reverse("calls:integration_settings")
                )
        return super().dispatch(request, *args, **kwargs)

    def get_form(self, form_class=None):
        """Override to limit the allowed_users queryset to active users from this company and set initial values."""
        company = self.request.active_company
        setting = CallIntegrationSetting.get_for_company(company)
        form = super().get_form(form_class)
        form.fields["allowed_users"].queryset = User.objects.filter(
            company=company, is_active=True
        )
        form.fields["allowed_users"].initial = setting.allowed_users.all()
        return form

    def form_valid(self, form):
        company = self.request.active_company
        setting = CallIntegrationSetting.get_for_company(company)
        setting.access_type = "users"
        setting.save(update_fields=["access_type"])
        setting.allowed_users.set(form.cleaned_data["allowed_users"])
        messages.success(self.request, _("Allowed users updated."))
        return RefreshResponse(request=self.request)


# ── Access Control Detail Modals (read-only lists) ───────────────────────────


class _CallAccessDetailView(LoginRequiredMixin, View):
    """Read-only modal listing who has call access, as pills."""

    title = ""
    show_search = True
    list_class = "grid grid-cols-3"
    # Below this many people the search box and grid only add empty space
    compact_threshold = 9

    def get_items(self, request, setting):
        """Return a list of ``{"name", "chip"}`` dicts for everyone with access."""
        raise NotImplementedError

    def get(self, request, *args, **kwargs):
        """Render the modal, or only the pill list when the search box asks for it."""
        setting = CallIntegrationSetting.get_for_company(request.active_company)
        items = self.get_items(request, setting) if setting else []
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
            else "calls/access_detail_modal.html"
        )
        return render(request, template, context)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("calls.view_callintegrationsetting"), name="dispatch"
)
class CallAccessRolesDetailView(_CallAccessDetailView):
    """Read-only modal listing all roles that currently have call access."""

    title = _("Roles With Call Access")
    show_search = False
    list_class = "flex flex-wrap"

    def get_items(self, request, setting):
        return [
            {
                "name": role.role_name,
                "chip": render_to_string(
                    "partials/role_pill.html", {"role_name": role.role_name}
                ),
            }
            for role in setting.allowed_roles.order_by("role_name")
        ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("calls.view_callintegrationsetting"), name="dispatch"
)
class CallAccessUsersDetailView(_CallAccessDetailView):
    """Read-only modal listing all users that currently have call access."""

    title = _("Users With Call Access")

    def get_items(self, request, setting):
        users = setting.allowed_users.order_by("first_name", "last_name")
        return [
            {
                "name": user.get_full_name() or user.username,
                "chip": render_user_chip(user, request.user),
            }
            for user in users
        ]


# ── User Settings (My Settings → Calls) ──────────────────────────────────────


class CallUserSettingsView(LoginRequiredMixin, View):
    """
    Per-user Calls settings — shown in My Settings → Calls.
    Each user sees one card per active provider and can save their own
    extension / agent ID for that provider.
    """

    template_name = "calls/calls_user_settings.html"

    def _get_user_cards(self, request):
        """Build a list of provider cards with this user's current AgentMapping for each."""
        providers = CallProvider.objects.filter(
            status=CallProvider.STATUS_ACTIVE
        ).exclude(provider_type=CallProvider.PROVIDER_MOCK)
        cards = []
        for provider in providers:
            mapping = AgentMapping.objects.filter(
                provider=provider, user=request.user
            ).first()
            cards.append(
                {
                    "provider": provider,
                    "mapping": mapping,
                    "extension": mapping.extension if mapping else "",
                    "agent_id": mapping.agent_id if mapping else "",
                }
            )
        return cards

    def get(self, request, *args, **kwargs):
        """Render the user's settings page with a card for each active provider, showing their current extension/agent ID if set."""
        company = request.active_company
        has_access = (
            CallIntegrationSetting.user_can_access(request.user, company)
            if company
            else False
        )
        return render(
            request,
            self.template_name,
            {
                "has_access": has_access,
                "provider_cards": self._get_user_cards(request) if has_access else [],
            },
        )

    def post(self, request, *args, **kwargs):
        """Handle saving/updating the user's AgentMapping for a given provider based on the submitted form data."""
        provider_id = request.POST.get("provider_id")
        action = request.POST.get("action", "save")
        provider = (
            CallProvider.objects.filter(
                pk=provider_id, status=CallProvider.STATUS_ACTIVE
            )
            .exclude(provider_type=CallProvider.PROVIDER_MOCK)
            .first()
        )

        if not provider:
            messages.error(
                request,
                _(
                    "This calling provider no longer exists or is inactive. "
                    "Your changes were not saved."
                ),
            )
            return self.get(request, *args, **kwargs)

        company = request.active_company
        if action == "save":
            mapping, _created = AgentMapping.all_objects.get_or_create(
                provider=provider,
                user=request.user,
                defaults={"company": company, "created_by": request.user},
            )
            mapping.agent_id = request.POST.get("agent_id", "")
            mapping.save(update_fields=["agent_id"])
        elif action == "remove":
            AgentMapping.objects.filter(provider=provider, user=request.user).delete()

        has_access = (
            CallIntegrationSetting.user_can_access(request.user, company)
            if company
            else False
        )
        return render(
            request,
            self.template_name,
            {
                "has_access": has_access,
                "provider_cards": self._get_user_cards(request) if has_access else [],
            },
        )
