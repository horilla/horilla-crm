"""Views for managing dashboard actions like toggling default/favorite status, creating, and deleting dashboards."""

# Standard library imports
import logging

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaSingleDeleteView,
    HorillaSingleFormView,
)
from horilla.contrib.utils.middlewares import _thread_local
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.functional import cached_property
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import HxTriggerResponse, JsonResponse, ScriptResponse

# Local imports
from ..forms import DashboardForm
from ..models import Dashboard, DefaultHomeLayoutOrder

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
class DashboardDefaultToggleView(LoginRequiredMixin, View):
    """Toggle default dashboard for the current user via HTMX"""

    def post(self, request, *args, **kwargs):
        """Handle HTMX POST to toggle the `is_default` flag for a dashboard."""
        try:
            dashboard = Dashboard.objects.get(pk=kwargs["pk"])
        except Exception as e:
            messages.error(request, str(e))
            return ScriptResponse(reload=True)
        user = request.user
        if user.has_perm("dashboard.change_dashboard") or (
            user.has_perm("dashboard.change_own_dashboard")
            and dashboard.dashboard_owner == user
        ):
            if not dashboard.is_default:
                Dashboard.objects.filter(
                    dashboard_owner=request.user,
                    company=request.user.company,
                    is_default=True,
                ).update(is_default=False)
                dashboard.is_default = True
                messages.success(request, f"{dashboard.name} set as default.")
            else:
                dashboard.is_default = False
                messages.success(request, f"{dashboard.name} removed from default.")
            dashboard.save()
            return ScriptResponse(reload=True)
        messages.error(
            request, _("You don't have permission to change this dashboard.")
        )
        return ScriptResponse(reload=True)

    def get(self, request, *args, **kwargs):
        """Handle GET request to return the 403 page for non-POST requests."""
        return render(request, "403.html")


@method_decorator(htmx_required, name="dispatch")
class DashboardFavoriteToggleView(LoginRequiredMixin, View):
    """Toggle favorite status of a dashboard for the logged-in user."""

    def post(self, request, *args, **kwargs):
        """Handle POST requests to toggle favorite status of a dashboard folder."""
        try:
            dashboard = Dashboard.objects.get(pk=kwargs["pk"])
        except Exception as e:
            messages.error(request, str(e))
            return ScriptResponse(reload=True)

        user = request.user
        if user.has_perm("dashboard.change_dashboard") or (
            user.has_perm("dashboard.change_own_dashboard")
            and dashboard.dashboard_owner == user
        ):
            if user in dashboard.favourited_by.all():
                dashboard.favourited_by.remove(user)
            else:
                dashboard.favourited_by.add(user)
        return ScriptResponse(reload=True)

    def get(self, request, *args, **kwargs):
        """Handle GET request to return 403 error for non-POST requests."""
        return render(request, "403.html")


@method_decorator(htmx_required, name="dispatch")
class DashboardCreateFormView(LoginRequiredMixin, HorillaSingleFormView):
    """View to handle creation and updating of dashboard."""

    model = Dashboard
    form_class = DashboardForm
    modal_height = False
    full_width_fields = ["name", "description", "folder", "dashboard_owner"]
    hidden_fields = ["dashboard_owner"]
    save_and_new = False

    @cached_property
    def form_url(self):
        """Determine the form URL based on whether it's a create or update operation."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("dashboard:dashboard_update", kwargs={"pk": pk})
        return reverse_lazy("dashboard:dashboard_create")

    def get_initial(self):
        """Set initial company and dashboard_owner; merge GET params into initial."""
        initial = super().get_initial()

        company = (
            getattr(_thread_local, "request", None).active_company
            if hasattr(_thread_local, "request")
            else self.request.user.company
        )
        initial["company"] = company
        initial["dashboard_owner"] = self.request.user

        initial.update(self.request.GET.dict())
        return initial


@method_decorator(htmx_required, name="dispatch")
class DashboardDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View to handle deletion of dashboard."""

    model = Dashboard

    def get_post_delete_response(self):
        """Return HTMX trigger script to reload after delete."""
        return HxTriggerResponse()


@method_decorator(
    permission_required_or_denied("dashboard.change_dashboard"), name="dispatch"
)
@method_decorator(
    permission_required_or_denied(
        ["dashboard.change_dashboard", "dashboard.change_own_dashboard"]
    ),
    name="dispatch",
)
class ResetDashboardLayoutOrderView(LoginRequiredMixin, View):
    """Remove the current user's saved layout order for this dashboard so default order is used."""

    def post(self, request, *args, **kwargs):
        """Delete user's layout order for the given dashboard and return JSON response."""
        dashboard_id = kwargs.get("dashboard_id")
        try:
            dashboard = get_object_or_404(Dashboard, id=dashboard_id)
            DefaultHomeLayoutOrder.objects.filter(
                user=request.user, dashboard=dashboard
            ).delete()
            messages.success(request, _("Dashboard layout reset to default order."))
            return JsonResponse(
                {"success": True, "message": _("Dashboard layout reset to default.")}
            )
        except Exception as e:
            messages.error(self.request, e)
            return JsonResponse({"success": False, "message": str(e)})
