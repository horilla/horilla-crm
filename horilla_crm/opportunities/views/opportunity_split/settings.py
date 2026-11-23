"""Views for opportunity split settings and split-type configuration."""

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import HorillaListView, HorillaNavView
from horilla.contrib.utils.middlewares import get_active_company
from horilla.shortcuts import render
from horilla.urls import reverse, reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView, View
from horilla.web import HttpResponse, ScriptResponse

# Local imports
from horilla_crm.opportunities.models import (
    OpportunitySettings,
    OpportunitySplit,
    OpportunitySplitType,
)


class TeamSellingRequiredMixin:
    """
    Blocks access to views when Team Selling is disabled.
    Mirrors the Google Calendar Sync access-control pattern:
      - HTMX requests: 204 + HX-Redirect (navigates the full page away cleanly).
      - Normal requests: 403 render.
    """

    def dispatch(self, request, *args, **kwargs):
        """Guard team-selling pages when team selling is disabled."""
        if not OpportunitySettings.is_team_selling_enabled(request.user.company):
            if request.headers.get("HX-Request") == "true":
                messages.error(request, _("Team Selling is not enabled."))
                response = HttpResponse(status=204)
                response["HX-Redirect"] = reverse("opportunities:opportunities_view")
                return response
            return render(
                request,
                "403.html",
                {
                    "message": _(
                        "Team Selling has not been enabled by your administrator."
                    )
                },
                status=403,
            )
        return super().dispatch(request, *args, **kwargs)


class SplitEnabledRequiredMixin:
    """
    Blocks access to views when Opportunity Splits are disabled.
    Mirrors the Google Calendar Sync access-control pattern:
      - HTMX requests: 204 + HX-Redirect (navigates the full page away cleanly).
      - Normal requests: 403 render.
    """

    def dispatch(self, request, *args, **kwargs):
        """Guard split pages when the split feature is disabled."""
        if not OpportunitySettings.is_split_enabled(request.user.company):
            if request.headers.get("HX-Request") == "true":
                messages.error(request, _("Opportunity Splits are not enabled."))
                response = HttpResponse(status=204)
                response["HX-Redirect"] = reverse("opportunities:opportunities_view")
                return response
            return render(
                request,
                "403.html",
                {
                    "message": _(
                        "Opportunity Splits have not been enabled by your administrator."
                    )
                },
                status=403,
            )
        return super().dispatch(request, *args, **kwargs)


class SplitTypeView(LoginRequiredMixin, TeamSellingRequiredMixin, TemplateView):
    """
    View to display and manage Team Selling setup
    """

    template_name = "opportunity_split/opportunity_split_view.html"

    def get_context_data(self, **kwargs):
        """Provide team-selling and split toggle state for settings page."""
        context = super().get_context_data(**kwargs)
        company = get_active_company(self.request)
        settings = OpportunitySettings.get_settings(company)
        context["settings"] = settings
        context["team_selling_enabled"] = settings.team_selling_enabled
        context["split_enabled"] = settings.split_enabled
        context["allow_all_users_in_splits"] = settings.allow_all_users_in_splits
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required("opportunities.view_opportunitysplittype"), name="dispatch"
)
class OpportunitySplitNavbar(
    LoginRequiredMixin, TeamSellingRequiredMixin, HorillaNavView
):
    """Navigation bar view for opportunity split settings."""

    nav_title = _("Opportunity Split Settings")
    nav_description = _(
        "Configure how revenue is split between team members on an opportunity."
    )
    search_url = reverse_lazy("opportunities:opportunity_split_list")
    main_url = reverse_lazy("opportunities:opportunity_split_view")
    nav_width = False
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False
    search_option = False


@method_decorator(htmx_required, name="dispatch")
class OpportunitySplitListView(
    LoginRequiredMixin, TeamSellingRequiredMixin, HorillaListView
):
    """
    opportunity List view
    """

    model = OpportunitySplitType
    view_id = "opportunity-split-list"
    search_url = reverse_lazy("opportunities:opportunity_split_list")
    main_url = reverse_lazy("opportunities:opportunity_split_view")
    save_to_list_option = False
    bulk_select_option = False
    table_width = False
    enable_sorting = False
    table_height_as_class = "h-[500px]"

    columns = [
        "split_label",
        "split_field",
        "totals_100_percent",
        ("is_active", "is_active_col"),
    ]


@method_decorator(
    permission_required_or_denied("opportunities.change_opportunitysettings"),
    name="dispatch",
)
class ToggleOpportunitySplitView(LoginRequiredMixin, TeamSellingRequiredMixin, View):
    """
    HTMX view to toggle opportunity split feature on/off
    """

    def post(self, request, *args, **kwargs):
        """Handle POST request to toggle opportunity split feature."""
        company = get_active_company(self.request)
        settings = OpportunitySettings.get_settings(company)
        action = request.POST.get("action")

        if action == "enable":
            settings.split_enabled = True
            settings.save()
            messages.success(
                request,
                _(
                    "Opportunity Splits has been enabled successfully."
                    "Users can now split opportunities and assign percentages to team members."
                ),
            )
        elif action == "disable":
            settings.split_enabled = False
            settings.save()
            messages.success(
                request,
                _(
                    "Opportunity Splits has been disabled. "
                    "Existing splits will no longer be visible or accessible."
                ),
            )

        OpportunitySplit.objects.all().delete()
        return ScriptResponse(reload=True, msgs=True)


@method_decorator(
    permission_required_or_denied("opportunities.change_opportunitysettings"),
    name="dispatch",
)
class ToggleAllowAllUsersSplitView(LoginRequiredMixin, TeamSellingRequiredMixin, View):
    """
    HTMX view to toggle whether all users can be added to opportunity splits
    """

    def post(self, request, *args, **kwargs):
        """Handle POST request to toggle allow all users in splits."""
        company = get_active_company(self.request)
        settings = OpportunitySettings.get_settings(company)
        action = request.POST.get("action")

        if action == "enable_all_users":
            settings.allow_all_users_in_splits = True
            settings.save()
            messages.success(
                request,
                _(
                    "All users can now be added to opportunity splits. "
                    "Users can assign splits to any active user in the company."
                ),
            )

        elif action == "disable_all_users":
            settings.allow_all_users_in_splits = False
            settings.save()
            messages.success(
                request,
                _(
                    "Only opportunity team members can now be added to splits. "
                    "Adding other users has been restricted."
                ),
            )

        return ScriptResponse(reload=True, msgs=True)


@method_decorator(htmx_required, name="dispatch")
class OpportunitySplitTypeActiveToggleView(
    LoginRequiredMixin, TeamSellingRequiredMixin, View
):
    """
    Toggle active/inactive status for Opportunity Split Types via HTMX.
    """

    def post(self, request, *args, **kwargs):
        """Handle POST request to toggle split type active status."""
        try:
            split_type = OpportunitySplitType.objects.get(pk=kwargs["pk"])
            user = request.user

            if user.has_perm("opportunity.change_opportunitysplittype"):
                # Toggle is_active
                split_type.is_active = not getattr(split_type, "is_active", False)
                split_type.save()

                if split_type.is_active:
                    messages.success(
                        request, f"{split_type.split_label} activated successfully."
                    )
                else:
                    messages.success(
                        request, f"{split_type.split_label} deactivated successfully."
                    )

                # Trigger HTMX reload (for list/table refresh)
                return ScriptResponse(reload=True)

            messages.error(
                request, _("You don’t have permission to change split types.")
            )
            return ScriptResponse(reload=True)

        except OpportunitySplitType.DoesNotExist:
            messages.error(request, _("Split Type not found."))
            return ScriptResponse(reload=True)
        except Exception as e:
            messages.error(request, f"Error: {e}")
            return ScriptResponse(reload=True)
