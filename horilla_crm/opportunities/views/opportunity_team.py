"""
Views for managing Opportunity Teams and their members.

This module provides list, detail, form, and delete views for opportunity teams
and their members, including HTMX-based navigation, filtering, and CRUD handling.
"""

# Standard library imports
import logging
from functools import cached_property
from urllib.parse import urlencode

# Third-party imports (Django)
from django.contrib import messages
from django.utils.encoding import force_str

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin, login_redirect
from horilla.auth.models import User
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla.contrib.generics.views.details import check_record_change_access
from horilla.contrib.utils.middlewares import _thread_local
from horilla.core.exceptions import PermissionDenied
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse, reverse_lazy
from horilla.utils import timezone
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.html import format_html
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import DetailView, TemplateView, View
from horilla.web import (
    HttpNotFound,
    HttpResponse,
    HxTriggerResponse,
    RefreshResponse,
    ScriptResponse,
)

# Local imports
from horilla_crm.opportunities.filters import (
    OpportunityTeamFilter,
    OpportunityTeamMembersFilter,
)
from horilla_crm.opportunities.forms import (
    AddDefaultTeamForm,
    OpportunityMemberForm,
    OpportunityTeamForm,
    OpportunityTeamMemberForm,
)
from horilla_crm.opportunities.models import (
    DefaultOpportunityMember,
    Opportunity,
    OpportunitySettings,
    OpportunitySplit,
    OpportunityTeam,
    OpportunityTeamMember,
)

logger = logging.getLogger(__name__)


class TeamSellingRequiredMixin:
    """
    Blocks access to views when Team Selling is disabled.
    Mirrors the Google Calendar Sync access-control pattern:
      - HTMX requests: 204 + HX-Redirect (navigates the full page away cleanly).
      - Normal requests: 403 render.
    """

    def dispatch(self, request, *args, **kwargs):
        """Block access when team selling is disabled for the user's company."""
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


class OpportunityTeamView(LoginRequiredMixin, TeamSellingRequiredMixin, HorillaView):
    """Displays the main opportunity team page."""

    template_name = "settings/my_settings_list_shell.html"
    view_id = "opportunity-team-view"
    nav_url = reverse_lazy("opportunities:opportunity_team_nav_view")
    list_url = reverse_lazy("opportunities:opportunity_team_list_view")


@method_decorator(htmx_required, name="dispatch")
class OpportunityTeamNavbar(
    LoginRequiredMixin, TeamSellingRequiredMixin, HorillaNavView
):
    """Navbar for opportunity team listing with filters and create option."""

    search_url = reverse_lazy("opportunities:opportunity_team_list_view")
    main_url = reverse_lazy("opportunities:opportunity_team_view")
    filterset_class = OpportunityTeamFilter
    model_name = "OpportunityTeam"
    model_app_label = "opportunities"
    nav_width = False
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False

    @cached_property
    def new_button(self):
        """Return 'New' button config if user has add permission."""
        return {
            "url": f"""{reverse_lazy("opportunities:create_opportunity_team")}?new=true""",
            "attrs": {"id": "opportunity-team-create"},
        }


@method_decorator(htmx_required, name="dispatch")
class OpportunityTeamListView(
    LoginRequiredMixin, TeamSellingRequiredMixin, HorillaListView
):
    """Lists opportunity teams owned by the logged-in user."""

    model = OpportunityTeam
    view_id = "opportunity-team-list"
    filterset_class = OpportunityTeamFilter
    search_url = reverse_lazy("opportunities:opportunity_team_list_view")
    main_url = reverse_lazy("opportunities:opportunity_team_view")
    save_to_list_option = False
    bulk_select_option = False
    table_width = False
    enable_sorting = False
    owner_filtration = False

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(owner=self.request.user.pk)
        return queryset

    @cached_property
    def col_attrs(self):
        """Defines HTMX attributes for clickable team name column."""
        htmx_attrs = {
            "hx-get": "{get_detail_view_url}",
            "hx-target": "#opportunity-team-view",
            "hx-swap": "outerHTML",
            "hx-push-url": "true",
            "hx-select": "#opportunity-team-view",
        }
        return [
            {
                "team_name": {
                    "style": "cursor:pointer",
                    "class": "hover:text-primary-600",
                    **htmx_attrs,
                }
            }
        ]

    def no_record_add_button(self):
        """Return 'Add' button config for no-record state."""
        return {
            "url": f"""{reverse_lazy("opportunities:create_opportunity_team")}?new=true""",
            "attrs": 'id="opportunity-team-create"',
        }

    columns = ["team_name", "description"]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "attrs": """
                      hx-get="{get_edit_url}?new=true"
                      hx-target="#modalBox"
                      hx-swap="innerHTML"
                      onclick="openModal()"
                     """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "attrs": """
                hx-post="{get_delete_url}"
                hx-target="#deleteModeBox"
                hx-swap="innerHTML"
                hx-trigger="click"
                hx-vals='{{"check_dependencies": "true"}}'
                onclick="openDeleteModeModal()"
            """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
class OpportunityTeamFormView(
    LoginRequiredMixin, TeamSellingRequiredMixin, HorillaSingleFormView
):
    """Handles creation and update of opportunity teams with members."""

    model = OpportunityTeam
    form_class = OpportunityTeamForm
    full_width_fields = ["team_name", "description"]
    condition_fields = ["user", "team_role", "opportunity_access_level"]
    modal_height = False
    condition_field_title = _("Add Members")
    save_and_new = False

    def has_permission(self):
        """
        Any authenticated user may create their own Opportunity Team, and may
        edit a team they own, without needing an admin-granted permission -
        mirrors Salesforce, where every user manages their own Opportunity Team.
        """
        if super().has_permission():
            return True
        pk = self.kwargs.get("pk")
        if not pk:
            return True
        team = OpportunityTeam.objects.filter(pk=pk).first()
        return bool(team and team.owner_id == self.request.user.pk)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["condition_model"] = DefaultOpportunityMember
        kwargs["request"] = self.request
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.object and self.object.pk:
            existing_members = DefaultOpportunityMember.objects.filter(
                team=self.object
            ).order_by("created_at")
            context["existing_conditions"] = existing_members
        form = context.get("form")
        if form and hasattr(form, "condition_field_choices"):
            context["condition_field_choices"] = form.condition_field_choices
        else:
            temp_form = self.get_form_class()(
                condition_model=DefaultOpportunityMember, request=self.request
            )
            if hasattr(temp_form, "condition_field_choices"):
                context["condition_field_choices"] = temp_form.condition_field_choices

        return context

    def form_valid(self, form):
        self.object = form.save(commit=False)

        if self.kwargs.get("pk"):
            self.object.updated_at = timezone.now()
            self.object.updated_by = self.request.user
        else:
            self.object.created_at = timezone.now()
            self.object.created_by = self.request.user
            self.object.updated_at = timezone.now()
            self.object.updated_by = self.request.user
        self.object.owner = self.request.user
        self.object.company = (
            getattr(_thread_local, "request", None).active_company
            if hasattr(_thread_local, "request")
            else self.request.user.company
        )
        self.object.save()
        form.save_m2m()

        condition_rows = form.cleaned_data.get("condition_rows", [])
        if self.kwargs.get("pk"):
            DefaultOpportunityMember.objects.filter(team=self.object).delete()

        for row in condition_rows:
            try:
                DefaultOpportunityMember.objects.create(
                    team=self.object,
                    user=row.get("user"),
                    team_role=row.get("team_role"),
                    opportunity_access_level=row.get("opportunity_access_level"),
                    created_at=timezone.now(),
                    created_by=self.request.user,
                    updated_at=timezone.now(),
                    updated_by=self.request.user,
                    company=(
                        getattr(_thread_local, "request", None).active_company
                        if hasattr(_thread_local, "request")
                        else self.request.user.company
                    ),
                )
            except Exception as e:
                messages.error(self.request, f"Failed to save team member: {str(e)}")
                return self.form_invalid(form)

        self.request.session["condition_row_count"] = 0
        self.request.session.modified = True
        messages.success(
            self.request,
            f"{self.model._meta.verbose_name} {'updated' if self.kwargs.get('pk') else 'created'} successfully.",
        )
        return ScriptResponse(reload=True, close=True)

    @cached_property
    def form_url(self):
        """Constructs the form URL for creating or editing an opportunity team."""
        model_name = self.request.GET.get("model_name")
        obj = self.request.GET.get("obj")
        pk = self.kwargs.get("pk")
        if pk:
            base_url = reverse_lazy(
                "opportunities:edit_opportunity_team", kwargs={"pk": pk} if pk else None
            )
        else:
            base_url = reverse_lazy("opportunities:create_opportunity_team")
        if model_name:
            return f"{base_url}?{urlencode({'model_name': model_name, 'obj': obj})}"
        return base_url


class OpportunityTeamDetailView(DetailView):
    """Shows details and members of a specific opportunity team."""

    template_name = "opportunity_team/opportunity_team_detail_view.html"
    model = OpportunityTeam

    def dispatch(self, request, *args, **kwargs):
        """Validate access and object existence before rendering detail view."""
        if not request.user.is_authenticated:
            return login_redirect(request)
        if not OpportunitySettings.is_team_selling_enabled(
            getattr(request, "active_company", None)
        ):
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
        try:
            self.object = self.get_object()
        except Exception as e:
            if request.headers.get("HX-Request") == "true":
                messages.error(self.request, e)
                return RefreshResponse(request)
            raise HttpNotFound(e) from e
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Provide selected team details and member list for detail template."""
        context = super().get_context_data(**kwargs)
        current_obj = self.get_object()
        members = DefaultOpportunityMember.objects.filter(team=current_obj)
        context["current_obj"] = current_obj
        context["members"] = members
        context["nav_url"] = reverse_lazy(
            "opportunities:opportunity_team_detail_nav_view"
        )
        context["list_url"] = reverse_lazy(
            "opportunities:opportunity_team_detail_list_view"
        )
        return context


@method_decorator(htmx_required, name="dispatch")
class OpportunityTeamDetailNavbar(
    LoginRequiredMixin, TeamSellingRequiredMixin, HorillaNavView
):
    """Navbar for navigating inside a single opportunity team detail view."""

    search_url = reverse_lazy("opportunities:opportunity_team_detail_list_view")
    filterset_class = OpportunityTeamFilter
    one_view_only = True
    all_view_types = False
    filter_option = False
    reload_option = False
    model_name = "OpportunityTeam"
    nav_width = False
    navbar_indication = True
    navbar_indication_attrs = {
        "hx-get": reverse_lazy("opportunities:opportunity_team_view"),
        "hx-target": "#opportunity-team-view",
        "hx-swap": "outerHTML",
        "hx-push-url": "true",
        "hx-select": "#opportunity-team-view",
    }

    @cached_property
    def new_button(self):
        """Return 'New' button config for adding team members."""
        obj = self.request.GET.get("obj")
        if obj:
            obj = str(obj).split("?")[0].strip()
        base = reverse_lazy("opportunities:create_opportunity_team_member")
        url = f"{base}?obj={obj}" if obj else str(base)
        return {
            "url": url,
            "attrs": {"id": "opportunity-team-member-create"},
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj_id = self.request.GET.get("obj")
        obj = OpportunityTeam.objects.filter(pk=obj_id).first()
        self.nav_title = obj.team_name if obj else ""
        context["nav_title"] = self.nav_title
        return context


@method_decorator(htmx_required, name="dispatch")
class OpportunityTeamDetailListView(
    LoginRequiredMixin, TeamSellingRequiredMixin, HorillaListView
):
    """Lists members of a specific opportunity team."""

    model = DefaultOpportunityMember
    view_id = "opportunity-team-members-list"
    filterset_class = OpportunityTeamMembersFilter
    search_url = reverse_lazy("opportunities:opportunity_team_detail_list_view")
    main_url = reverse_lazy("opportunities:opportunity_team_view")
    save_to_list_option = False
    bulk_select_option = False
    table_width = False
    enable_sorting = False
    # Scoped explicitly to the requested team below (get_queryset), and
    # DefaultOpportunityMember has no OWNER_FIELDS for the generic
    # view/view_own permission gate to resolve against - without this,
    # the gate falls through to an empty queryset for normal users.
    owner_filtration = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        request = getattr(_thread_local, "request", None)
        obj_id = request.GET.get("obj")
        if obj_id:
            self.main_url = reverse_lazy(
                "opportunities:opportunity_team_detail_view", kwargs={"pk": obj_id}
            )

    columns = ["user", "team_role", "opportunity_access_level"]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "attrs": """
                      hx-get="{get_edit_url}?new=true"
                      hx-target="#modalBox"
                      hx-swap="innerHTML"
                      onclick="openModal()"
                     """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "attrs": """
                hx-post="{get_delete_url}"
                hx-target="#deleteModeBox"
                hx-swap="innerHTML"
                hx-trigger="click"
                hx-vals='{{"check_dependencies": "true"}}'
                onclick="openDeleteModeModal()"
            """,
        },
    ]

    def get_queryset(self):
        obj_id = self.request.GET.get("obj")
        queryset = super().get_queryset()
        queryset = queryset.filter(team=obj_id)
        return queryset


@method_decorator(htmx_required, name="dispatch")
class OpportunityTeamMemberCreateView(
    LoginRequiredMixin, TeamSellingRequiredMixin, HorillaSingleFormView
):
    """Form view to create new members in an opportunity team."""

    model = DefaultOpportunityMember
    form_class = OpportunityTeamMemberForm
    condition_fields = ["user", "team_role", "opportunity_access_level"]
    modal_height = False
    hidden_fields = ["team"]
    condition_field_title = _("Add Members")
    save_and_new = False

    def has_permission(self):
        """
        Any authenticated user may manage default members of an Opportunity
        Team they own, without needing an admin-granted permission.
        """
        if super().has_permission():
            return True
        obj_id = self.request.GET.get("obj")
        if obj_id:
            obj_id = str(obj_id).split("?")[0].strip()
        if not obj_id:
            return False
        team = OpportunityTeam.objects.filter(pk=obj_id).first()
        return bool(team and team.owner_id == self.request.user.pk)

    def get_initial(self):
        """Set initial team from GET parameter obj (handles malformed query e.g. ?obj=3?obj=3)."""
        initial = super().get_initial()
        obj_id = self.request.GET.get("obj")
        if obj_id:
            # Normalize: use only the first token if param looks like "3?obj=3"
            obj_id = str(obj_id).split("?")[0].strip()
        if obj_id:
            try:
                initial["team"] = OpportunityTeam.objects.get(pk=obj_id)
            except (OpportunityTeam.DoesNotExist, ValueError, TypeError):
                pass
        return initial

    @cached_property
    def form_url(self):
        """Get form URL based on create or update mode; preserve obj for create so POST keeps team context."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "opportunities:edit_opportunity_team_member", kwargs={"pk": pk}
            )
        base = reverse_lazy("opportunities:create_opportunity_team_member")
        obj_id = self.request.GET.get("obj")
        if obj_id:
            obj_id = str(obj_id).split("?")[0].strip()
        if obj_id:
            return f"{base}?obj={obj_id}"
        return base

    def validate_form_for_multiple_instances(self, form):
        """Validate form before creating multiple instances"""
        team_id = form.cleaned_data.get("team")
        if not team_id:
            form.add_error("team", _("Team is required."))
            return False
        return True

    def check_duplicate_instance(self, row_data, unique_cache, form):
        """Check for duplicate users in the same team"""
        user_id = row_data.get("user")
        if not user_id:
            return None  # Skip empty rows

        # Get team_id from form
        team_id = form.cleaned_data.get("team")
        team_pk = team_id.id if hasattr(team_id, "id") else team_id

        # Check if user already in this submission
        cache_key = (user_id, team_pk)
        if cache_key in unique_cache:
            return str(_("User has already been added to this team."))

        # Check if user already exists in team
        if self.model.objects.filter(user_id=user_id, team_id=team_pk).exists():
            try:
                user = User.objects.get(pk=user_id)
                name = f"{user.first_name} {user.last_name}".strip() or user.username
            except Exception:
                name = f"User ID {user_id}"
            return _("%(name)s is already a member of this team.") % {"name": name}

        unique_cache.add(cache_key)
        return None  # No duplicate

    def get_duplicate_error_message(self, row_data, error_msg):
        """Get friendly error message for duplicate errors"""
        user_id = row_data.get("user")
        if (
            user_id
            and "UNIQUE constraint failed" in error_msg
            and "user_id" in error_msg
        ):
            try:
                user = User.objects.get(pk=user_id)
                name = f"{user.first_name} {user.last_name}".strip() or user.username
                return f"{name} is already a member of this team."
            except Exception:
                pass
        return error_msg


@method_decorator(htmx_required, name="dispatch")
class OpportunityTeamMemberUpdateView(
    LoginRequiredMixin, TeamSellingRequiredMixin, HorillaSingleFormView
):
    """Form view to update an existing opportunity team member."""

    model = DefaultOpportunityMember
    fields = ["team", "user", "team_role", "opportunity_access_level"]
    full_width_fields = ["user", "team_role", "opportunity_access_level"]
    modal_height = False
    hidden_fields = ["team"]

    def has_permission(self):
        """
        Any authenticated user may edit default members of an Opportunity
        Team they own, without needing an admin-granted permission.
        """
        if super().has_permission():
            return True
        pk = self.kwargs.get("pk")
        if not pk:
            return False
        member = (
            DefaultOpportunityMember.objects.filter(pk=pk)
            .select_related("team")
            .first()
        )
        return bool(
            member and member.team and member.team.owner_id == self.request.user.pk
        )

    def get_form(self, form_class=None):
        """Scope the "user" field to the active company.

        The form has no custom form_class, so "user" is built by the
        generic ForeignKey-widget branch, which defaults to an unfiltered
        ``User.objects.all()[:100]``. Narrow it here the same way the
        condition-field version of this picker already does.
        """
        form = super().get_form(form_class)
        active_company = getattr(self.request, "active_company", None)
        if "user" in form.fields and active_company:
            user_field = form.fields["user"]
            user_qs = User.objects.filter(company=active_company)
            user_field.queryset = user_qs
            choices = [("", "---------")] + [
                (user.pk, str(user)) for user in user_qs[:100]
            ]
            selected_value = user_field.widget.attrs.get("data-initial")
            if selected_value and selected_value not in [str(c[0]) for c in choices]:
                selected_user = User.objects.filter(pk=selected_value).first()
                if selected_user:
                    choices.insert(1, (selected_user.pk, str(selected_user)))
            user_field.widget.choices = choices
        return form

    @cached_property
    def form_url(self):
        """Constructs the form URL for editing a team member."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "opportunities:edit_opportunity_team_member", kwargs={"pk": pk}
            )
        return None


@method_decorator(htmx_required, name="dispatch")
class OpportunityMemberUpdateView(
    LoginRequiredMixin, TeamSellingRequiredMixin, HorillaSingleFormView
):
    """Form view to update an existing opportunity  member."""

    model = OpportunityTeamMember
    fields = ["team_role", "opportunity_access"]
    full_width_fields = ["team_role", "opportunity_access"]
    modal_height = False

    def has_permission(self):
        """
        Anyone who can change the parent Opportunity (owner, granted
        edit/owner-level team access, or an admin) may edit a team member's
        role/access level - OpportunityTeamMember has no OWNER_FIELDS of its
        own, so the generic change_own_opportunityteammember fallback can
        never resolve; ownership lives on the opportunity it belongs to.
        """
        if super().has_permission():
            return True
        pk = self.kwargs.get("pk")
        if not pk:
            return False
        member = (
            OpportunityTeamMember.objects.filter(pk=pk)
            .select_related("opportunity")
            .first()
        )
        return bool(
            member
            and member.opportunity
            and check_record_change_access(self.request.user, member.opportunity)
        )

    @cached_property
    def form_url(self):
        """Constructs the form URL for editing a team member."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "opportunities:edit_opportunity_member", kwargs={"pk": pk}
            )
        return None


@method_decorator(htmx_required, name="dispatch")
class OpportunityTeamDeleteView(
    LoginRequiredMixin, TeamSellingRequiredMixin, HorillaSingleDeleteView
):
    """Deletes an opportunity team and returns HTMX response."""

    model = OpportunityTeam
    check_delete_permission = False

    def get_object(self, queryset=None):
        """
        Any authenticated user may delete an Opportunity Team they own,
        without needing an admin-granted delete permission.
        """
        obj = super().get_object(queryset)
        user = self.request.user
        if getattr(user, "is_superuser", False) or obj.owner_id == user.pk:
            return obj
        app_label = self.model._meta.app_label
        model_name = self.model._meta.model_name
        if user.has_perm(f"{app_label}.delete_{model_name}") or user.has_perm(
            f"{app_label}.delete_own_{model_name}"
        ):
            return obj
        raise PermissionDenied(
            _("You don't have permission to delete this %(model)s.")
            % {"model": force_str(self.model._meta.verbose_name)}
        )

    def get_post_delete_response(self):
        return HxTriggerResponse()


@method_decorator(htmx_required, name="dispatch")
class OpportunityTeamMembersDeleteView(
    LoginRequiredMixin, TeamSellingRequiredMixin, HorillaSingleDeleteView
):
    """Deletes an opportunity team member and returns HTMX response."""

    model = DefaultOpportunityMember
    check_delete_permission = False

    def get_object(self, queryset=None):
        """
        Any authenticated user may remove a default member from an
        Opportunity Team they own, without needing an admin-granted
        delete permission.
        """
        obj = super().get_object(queryset)
        user = self.request.user
        if getattr(user, "is_superuser", False) or (
            obj.team and obj.team.owner_id == user.pk
        ):
            return obj
        app_label = self.model._meta.app_label
        model_name = self.model._meta.model_name
        if user.has_perm(f"{app_label}.delete_{model_name}") or user.has_perm(
            f"{app_label}.delete_own_{model_name}"
        ):
            return obj
        raise PermissionDenied(
            _("You don't have permission to delete this %(model)s.")
            % {"model": force_str(self.model._meta.verbose_name)}
        )

    def get_post_delete_response(self):
        return HxTriggerResponse()


@method_decorator(htmx_required, name="dispatch")
class OpportunityMembersDeleteView(
    LoginRequiredMixin, TeamSellingRequiredMixin, HorillaSingleDeleteView
):
    """Deletes an opportunity team member and returns HTMX response."""

    model = OpportunityTeamMember
    check_delete_permission = False

    def get_object(self, queryset=None):
        """
        Anyone who can change the parent Opportunity (owner, granted
        edit/owner-level team access, or an admin) may remove a team member -
        OpportunityTeamMember has no OWNER_FIELDS/has_granted_access of its
        own, so ownership is resolved via the opportunity it belongs to.
        """
        obj = super().get_object(queryset)
        user = self.request.user
        if getattr(user, "is_superuser", False) or (
            obj.opportunity and check_record_change_access(user, obj.opportunity)
        ):
            return obj
        app_label = self.model._meta.app_label
        model_name = self.model._meta.model_name
        if user.has_perm(f"{app_label}.delete_{model_name}") or user.has_perm(
            f"{app_label}.delete_own_{model_name}"
        ):
            return obj
        raise PermissionDenied(
            _("You don't have permission to delete this %(model)s.")
            % {"model": force_str(self.model._meta.verbose_name)}
        )

    def delete(self, request, *args, **kwargs):
        """
        Override delete to check if member has splits assigned before deletion.
        """
        self.object = self.get_object()
        try:
            team_member = self.object
            opportunity = team_member.opportunity
            user = team_member.user

            # Check if this user has any splits assigned in this opportunity
            has_splits = OpportunitySplit.objects.filter(
                opportunity=opportunity, user=user
            ).exists()

            if has_splits:
                # Get split types where user has splits
                split_types_with_user = (
                    OpportunitySplit.objects.filter(opportunity=opportunity, user=user)
                    .select_related("split_type")
                    .values_list("split_type__split_label", flat=True)
                )

                split_types_list = ", ".join(split_types_with_user)

                messages.error(
                    request,
                    _(
                        f"Cannot delete {user.get_full_name() or user.username} from the opportunity team. "
                        f"This member has splits assigned in: {split_types_list}. "
                    ),
                )
                return ScriptResponse(
                    reload=True, msgs=True, extra="closeDeleteModeModal();"
                )

            # If no splits, proceed with normal deletion
            return super().delete(request, *args, **kwargs)

        except Exception as e:
            logger.error("Error in OpportunityMembersDeleteView.delete: %s", e)
            messages.error(
                request, _("An error occurred while deleting the team member.")
            )
            return ScriptResponse(
                reload=True, msgs=True, extra="closeDeleteModeModal();"
            )

    def get_post_delete_response(self):
        return HxTriggerResponse()


@method_decorator(htmx_required, name="dispatch")
class AddDefaultTeamView(
    LoginRequiredMixin, TeamSellingRequiredMixin, HorillaSingleFormView
):
    """
    View to add default team members from an OpportunityTeam to an Opportunity
    """

    form_class = AddDefaultTeamForm
    form_title = _("Add Default Team")
    view_id = "add-default-team"
    full_width_fields = ["team"]
    modal_height = False
    save_and_new = False

    def has_permission(self):
        """
        Anyone who can change the target Opportunity (owner, granted
        edit/owner-level team access, or an admin) may apply a default team
        to it, without needing a separate admin-granted permission.
        """
        user = self.request.user
        if getattr(user, "is_superuser", False) or user.has_perm(
            "opportunities.add_opportunityteammember"
        ):
            return True
        opp_id = self.request.GET.get("id") or self.request.GET.get("opportunity_id")
        if not opp_id:
            return False
        opportunity = Opportunity.objects.filter(pk=opp_id).first()
        return bool(opportunity and check_record_change_access(user, opportunity))

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        opportunity_id = self.request.GET.get("opportunity_id")
        if opportunity_id:
            kwargs["opportunity"] = get_object_or_404(Opportunity, pk=opportunity_id)
        return kwargs

    def form_valid(self, form):
        """
        When form is valid, add all default members from the selected team
        to the opportunity as OpportunityTeamMembers
        """
        opportunity_id = self.request.GET.get("id")

        if not opportunity_id:
            messages.error(self.request, _("Opportunity ID is required"))
            return self.form_invalid(form)

        try:
            opportunity = get_object_or_404(Opportunity, pk=opportunity_id)
            selected_team = form.cleaned_data["team"]

            # Get all default members from the selected team
            default_members = DefaultOpportunityMember.objects.filter(
                team=selected_team
            )

            if not default_members.exists():
                messages.warning(
                    self.request,
                    _("The selected team has no default members configured."),
                )
                return ScriptResponse(close=True)

            added_count = 0
            skipped_count = 0

            for default_member in default_members:
                existing_member = OpportunityTeamMember.objects.filter(
                    opportunity=opportunity, user=default_member.user
                ).first()

                if existing_member:
                    skipped_count += 1
                    continue

                OpportunityTeamMember.objects.create(
                    opportunity=opportunity,
                    user=default_member.user,
                    team_role=default_member.team_role,
                    opportunity_access=default_member.opportunity_access_level,
                    created_by=self.request.user,
                    updated_by=self.request.user,
                    company=self.request.user.company,
                )
                added_count += 1

            if added_count > 0:
                messages.success(
                    self.request,
                    _(
                        f"Successfully added {added_count} team member(s) from {selected_team.team_name}."
                    ),
                )

            if skipped_count > 0:
                messages.info(
                    self.request,
                    _(
                        f"{skipped_count} member(s) were already part of the opportunity team."
                    ),
                )

            return ScriptResponse(reload=True, close=True)

        except Exception as e:
            messages.error(
                self.request, _(f"Error adding default team members: {str(e)}")
            )
            return ScriptResponse(msgs=True, close=True)

    @cached_property
    def form_url(self):
        """Constructs the form URL for editing a team member."""
        return reverse_lazy("opportunities:add_default_team")


@method_decorator(htmx_required, name="dispatch")
class AddOpportunityMemberView(
    LoginRequiredMixin, TeamSellingRequiredMixin, HorillaSingleFormView
):
    """Form view to create new members in an opportunity team."""

    model = OpportunityTeamMember
    form_class = OpportunityMemberForm
    condition_fields = ["user", "team_role", "opportunity_access"]
    modal_height = False
    form_title = _("Add Opportunity Members")
    hidden_fields = ["opportunity"]
    condition_field_title = _("Add Members")
    save_and_new = False

    def has_permission(self):
        """
        Anyone who can change the target Opportunity (owner, granted
        edit/owner-level team access, or an admin) may add members to its
        team, without needing a separate admin-granted permission.
        """
        if super().has_permission():
            return True
        opp_id = self.request.GET.get("id")
        if not opp_id:
            return False
        opportunity = Opportunity.objects.filter(pk=opp_id).first()
        return bool(
            opportunity and check_record_change_access(self.request.user, opportunity)
        )

    def get_initial(self):
        """Set initial opportunity from GET parameter"""
        initial = super().get_initial()
        obj_id = self.request.GET.get("id")
        if obj_id:
            try:
                initial["opportunity"] = Opportunity.objects.get(pk=obj_id)
            except (Opportunity.DoesNotExist, ValueError, TypeError):
                pass
        return initial

    @cached_property
    def form_url(self):
        """Constructs the form URL for adding  member."""
        return reverse_lazy("opportunities:add_opportunity_member")

    def validate_form_for_multiple_instances(self, form):
        """Validate form before creating multiple instances"""
        opp_id = form.cleaned_data.get("opportunity")
        if not opp_id:
            form.add_error("opportunity", _("Opportunity is required."))
            return False
        return True

    def check_duplicate_instance(self, row_data, unique_cache, form):
        """Check for duplicate users in the same submission and existing members"""
        user_id = row_data.get("user")
        if not user_id:
            return None  # Skip empty rows

        opp_id = form.cleaned_data.get("opportunity")
        opp_pk = opp_id.id if hasattr(opp_id, "id") else opp_id

        # Check if user already in this submission
        cache_key = (user_id, opp_pk)
        if cache_key in unique_cache:
            return str(_("Duplicate user in submission"))

        if self.model.objects.filter(user_id=user_id, opportunity_id=opp_pk).exists():
            try:
                user_obj = User.objects.get(pk=user_id)
                user_name = (
                    f"{user_obj.first_name} {user_obj.last_name}".strip()
                    or user_obj.username
                )
                return _("%(name)s is already a member of this opportunity") % {
                    "name": user_name
                }
            except Exception:
                return _(
                    "User ID %(user_id)s is already a member of this opportunity"
                ) % {"user_id": user_id}

        unique_cache.add(cache_key)
        return None

    def update_unique_check_cache(self, row_data, unique_cache, instance):
        """Update cache after creating instance"""
        cache_key = (instance.user_id, instance.opportunity_id)
        unique_cache.add(cache_key)


@method_decorator(
    permission_required_or_denied("opportunities.view_opportunitysettings"),
    name="dispatch",
)
class TeamSellingSetupView(LoginRequiredMixin, TemplateView):
    """
    View to display and manage Team Selling setup
    """

    template_name = "opportunity_team/team_selling_setup.html"

    def get_context_data(self, **kwargs):
        """Build setup page context with current company team-selling settings."""
        context = super().get_context_data(**kwargs)
        company = self.request.active_company
        settings = OpportunitySettings.get_settings(company)
        if not settings:
            context["settings"] = None
            context["team_selling_enabled"] = False
            return context
        context["settings"] = settings
        context["team_selling_enabled"] = settings.team_selling_enabled
        return context


@method_decorator(
    permission_required_or_denied("opportunities.change_opportunitysettings"),
    name="dispatch",
)
class ToggleTeamSellingView(LoginRequiredMixin, View):
    """
    HTMX view to toggle team selling feature on/off
    """

    def post(self, request, *args, **kwargs):
        """Handle POST request to toggle team selling feature."""
        company = self.request.active_company
        view_url = reverse_lazy("opportunities:team_selling_setup")

        response_html = format_html(
            '<span hx-trigger="load" hx-get="{}" '
            'hx-select="#opportunity-team-settings" '
            'hx-target="#opportunity-team-settings" '
            'hx-swap="outerHTML" hx-push-url="false" '
            'hx-select-oob="#settings-sidebar"></span>',
            view_url,
        )
        if not company:
            messages.error(request, _("No active company found. Cannot save settings."))
            return HttpResponse(response_html)
        settings = OpportunitySettings.get_settings(company)
        action = request.POST.get("action")

        if action == "enable":
            settings.team_selling_enabled = True
            settings.save()
            messages.success(
                request,
                _(
                    "Team Selling has been enabled successfully. "
                    "Users can now create opportunity teams and add team members."
                ),
            )
        elif action == "disable":
            splits_were_enabled = settings.split_enabled
            settings.team_selling_enabled = False
            # OpportunitySettings.save() automatically disables Opportunity
            # Splits (they require Team Selling) and clears existing splits.
            settings.save()
            OpportunityTeam.objects.all().delete()
            OpportunityTeamMember.objects.all().delete()
            if splits_were_enabled:
                messages.success(
                    request,
                    _(
                        "Team Selling has been disabled and all existing opportunity teams "
                        "and their members have been deleted. Opportunity Splits, which "
                        "require Team Selling, have also been disabled."
                    ),
                )
            else:
                messages.success(
                    request,
                    _(
                        "Team Selling has been disabled and all existing opportunity teams "
                        "and their members have been deleted."
                    ),
                )

        return HttpResponse(response_html)
