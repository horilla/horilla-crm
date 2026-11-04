"""
This view handles the methods for user view
"""

# Standard library imports
from functools import cached_property
from urllib.parse import urlencode, urlparse

# Third-party imports (Django)
from django.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.auth.models import User
from horilla.contrib.generics.mixins import RecentlyViewedMixin
from horilla.contrib.generics.views import (
    HorillaDetailView,
    HorillaGroupByView,
    HorillaInlineEditMixin,
    HorillaInlineEditNavMixin,
    HorillaKanbanView,
    HorillaListView,
    HorillaMultiStepFormView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaTabView,
    HorillaView,
    resolves_within_settings_shell,
)
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse, reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.html import escape
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView, View
from horilla.web import HxTriggerResponse, ScriptResponse

# Local imports
from ..filters import UserFilter
from ..forms import (
    ChangeUserCompanyForm,
    UserDetailsInlineForm,
    UserFormClass,
    UserFormSingle,
)
from ..models import Company, Department, MultipleCurrency, Role


def filter_users_by_active_company(view, queryset):
    """
    Filter a User queryset down to the request's active company, unless the
    session has opted into viewing all companies.
    """
    # Archived users are hidden by default, unless the user explicitly filters
    # on the Active field (e.g. Active = False).
    if "is_active" not in view.request.GET.getlist("field"):
        queryset = queryset.filter(is_active=True)
    if view.request.session.get("show_all_companies", False):
        return queryset
    company = getattr(view.request, "active_company", None)
    return queryset.filter(company=company)


@method_decorator(
    permission_required_or_denied(
        f"{User._meta.app_label}.view_{User._meta.model_name}"
    ),
    name="dispatch",
)
class UserView(LoginRequiredMixin, HorillaView):
    """
    TemplateView for user page.
    """

    template_name = "settings/users/users_view.html"
    nav_url = reverse_lazy("core:user_nav_view")
    list_url = reverse_lazy("core:user_list_view")
    kanban_url = reverse_lazy("core:user_kanban_view")
    group_by_url = reverse_lazy("core:user_group_by_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required(f"{User._meta.app_label}.view_{User._meta.model_name}"),
    name="dispatch",
)
class UserNavbar(LoginRequiredMixin, HorillaNavView):
    """
    navbar view for users
    """

    nav_description = _(
        "Manage user accounts, roles, and access across your organization."
    )
    search_url = reverse_lazy("core:user_list_view")
    main_url = reverse_lazy("core:user_view")
    filterset_class = UserFilter
    kanban_url = reverse_lazy("core:user_kanban_view")
    model_name = str(User.__name__)
    model_app_label = str(User._meta.app_label)
    nav_width = False
    group_by_url = reverse_lazy("core:user_group_by_view")
    column_selector_exclude_fields = [
        "password",
        "last_login",
        "date_joined",
        "is_staff",
        "is_active",
        "groups",
        "user_permissions",
        "profile",
    ]
    enable_actions = True

    @cached_property
    def new_button(self):
        """
        Get the configuration for the "New" button in the navbar.
        """
        if self.request.user.has_perm(
            f"{User._meta.app_label}.add_{User._meta.model_name}"
        ):
            return {
                "url": f"""{reverse_lazy("core:user_create_single_form")}?new=true""",
                "attrs": {"id": "user-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        f"{User._meta.app_label}.view_{User._meta.model_name}"
    ),
    name="dispatch",
)
class UserListView(LoginRequiredMixin, HorillaListView):
    """
    List view of users
    """

    model = User
    view_id = "UsersList"
    filterset_class = UserFilter
    search_url = reverse_lazy("core:user_list_view")
    main_url = reverse_lazy("core:user_view")
    bulk_update_two_column = True
    bulk_delete_enabled = False

    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        if self.request.user.has_perm(
            f"{User._meta.app_label}.add_{User._meta.model_name}"
        ):
            return {
                "url": f"""{reverse_lazy("core:user_create_single_form")}?new=true""",
                "attrs": 'id="user-create"',
            }
        return None

    bulk_update_fields = [
        "department",
        "role",
        "city",
        "state",
        "country",
        "zip_code",
        "language",
        "time_zone",
        "currency",
        "time_format",
        "date_format",
        "number_format",
    ]

    columns = [
        (_("Name"), "get_avatar_with_name"),
        "email",
        "state",
        "country",
        "contact_number",
        "role",
    ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": f"{User._meta.app_label}.change_{User._meta.model_name}",
            "attrs": """
                        hx-get="{get_edit_url}?new=true"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        },
        {
            "action": "Change Company",
            "src": "assets/icons/change.svg",
            "img_class": "w-4 h-4",
            "permission": f"{User._meta.app_label}.change_{User._meta.model_name}",
            "attrs": """
                        hx-get="{get_change_company_url}?new=true"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": f"{User._meta.app_label}.delete_{User._meta.model_name}",
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

    @cached_property
    def col_attrs(self):
        """
        Get the column attributes for the list view.
        """
        query_params = self.request.GET.dict()
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {
            "hx-get": f"{{get_detail_view_url}}?{query_string}",
            "hx-target": "#users-view",
            "hx-swap": "innerHTML",
            "hx-push-url": "true",
            "hx-select": "#users-view",
            "permission": f"{User._meta.app_label}.view_{User._meta.model_name}",
        }
        return [
            {
                "get_avatar_with_name": {
                    **attrs,
                }
            }
        ]

    def get_queryset(self):
        """
        Get the queryset for the list view, filtered by active company.
        """
        return filter_users_by_active_company(self, super().get_queryset())


@method_decorator(
    permission_required_or_denied(
        f"{User._meta.app_label}.view_{User._meta.model_name}"
    ),
    name="dispatch",
)
class UserKanbanView(LoginRequiredMixin, HorillaKanbanView):
    """
    Kanban View for user
    """

    model = User
    view_id = "UsersKanban"
    filterset_class = UserFilter
    search_url = reverse_lazy("core:user_list_view")
    main_url = reverse_lazy("core:user_view")
    group_by_field = "department"
    height_kanban = "h-[550px]"

    columns = [
        "first_name",
        "roledepartment",
        "contact_number",
        "state",
        "country",
    ]

    actions = UserListView.actions

    def get_queryset(self):
        """
        Get the queryset for the kanban view, filtered by active company.
        """
        return filter_users_by_active_company(self, super().get_queryset())


@method_decorator(
    permission_required_or_denied(
        f"{User._meta.app_label}.view_{User._meta.model_name}"
    ),
    name="dispatch",
)
class UserGroupByView(LoginRequiredMixin, HorillaGroupByView):
    """
    User Group By view
    """

    model = User
    view_id = "user-group-by"
    filterset_class = UserFilter
    search_url = reverse_lazy("core:user_list_view")
    enable_quick_filters = True
    main_url = reverse_lazy("core:user_view")
    group_by_field = "department"

    columns = [
        (_("Name"), "get_avatar_with_name"),
        "email",
        "state",
        "country",
        "contact_number",
        "role",
    ]
    actions = UserListView.actions

    def get_queryset(self):
        """
        Get the queryset for the group-by view, filtered by active company.
        """
        return filter_users_by_active_company(self, super().get_queryset())

    @cached_property
    def col_attrs(self):
        """
        Get the column attributes for the list view.
        """
        query_params = self.request.GET.dict()
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {
            "hx-get": f"{{get_detail_view_url}}?{query_string}",
            "hx-target": "#users-view",
            "hx-swap": "innerHTML",
            "hx-push-url": "true",
            "hx-select": "#users-view",
            "permission": f"{User._meta.app_label}.view_{User._meta.model_name}",
        }
        return [
            {
                "get_avatar_with_name": {
                    **attrs,
                }
            }
        ]

    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        if self.request.user.has_perm(
            f"{User._meta.app_label}.add_{User._meta.model_name}"
        ):
            return {
                "url": f"""{reverse_lazy("core:user_create_single_form")}?new=true""",
                "attrs": 'id="user-create"',
            }
        return None


@method_decorator(htmx_required, name="dispatch")
class UserFormView(LoginRequiredMixin, HorillaMultiStepFormView):
    """
    Form view for user create and update
    """

    form_class = UserFormClass
    model = User
    total_steps = 4
    step_titles = {
        "1": _("Personal Information"),
        "2": _("Address Information"),
        "3": _("Work Information"),
        "4": _("Localization Information"),
    }

    detail_url_name = "core:user_detail_view"

    form_mode = [
        {
            "title": _("Single-Step Form"),
            "url_name": {
                "create": "core:user_create_single_form",
                "edit": "core:user_edit_single_form",
            },
            "active": False,
        },
        {
            "title": _("Multi-Step Form"),
            "url_name": {
                "create": "core:user_create_form",
                "edit": "core:user_edit_form",
            },
            "active": True,
        },
    ]

    @cached_property
    def form_url(self):
        """
        Get the form URL for create or edit actions.
        """
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("core:user_edit_form", kwargs={"pk": pk})
        return reverse_lazy("core:user_create_form")

    def has_permission(self):
        """
        Override permission check for user profile editing.
        """
        user = self.request.user
        pk = self.kwargs.get(self.pk_url_kwarg)

        if pk:
            if int(pk) == user.pk:
                return user.has_perm("core.can_change_profile")

            return user.has_perm(
                f"{User._meta.app_label}.change_{User._meta.model_name}"
            )

        return user.has_perm(f"{User._meta.app_label}.add_{User._meta.model_name}")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            f"{User._meta.app_label}.add_{User._meta.model_name}",
            f"{User._meta.app_label}.change_{User._meta.model_name}",
        ]
    ),
    name="dispatch",
)
class GetCompanyRelatedFieldsView(LoginRequiredMixin, View):
    """HTMX endpoint to get role, department, and currency fields based on selected company"""

    def get(self, request):
        """Return roles, departments, and currencies for selected company for HTMX."""
        company_list = request.GET.getlist("company")
        company_id = company_list[-1] if company_list else request.GET.get("company")
        user_pk = request.GET.get("user_pk")

        context = {
            "roles": [],
            "departments": [],
            "currencies": [],
            "selected_role": None,
            "selected_department": None,
            "selected_currency": None,
        }

        if company_id:
            try:
                company_id = (
                    int(company_id) if isinstance(company_id, str) else company_id
                )
                company = Company.objects.get(pk=company_id)
                context["roles"] = list(
                    Role.all_objects.filter(company=company, is_active=True)
                )
                context["departments"] = list(
                    Department.all_objects.filter(company=company, is_active=True)
                )
                context["currencies"] = list(
                    MultipleCurrency.all_objects.filter(company=company, is_active=True)
                )

                # If editing existing user, try to maintain selections if they're valid
                if user_pk:
                    try:
                        user_pk = int(user_pk) if isinstance(user_pk, str) else user_pk
                        user = User.objects.get(pk=user_pk)
                        if user.role and user.role.company == company:
                            context["selected_role"] = user.role.pk
                        if user.department and user.department.company == company:
                            context["selected_department"] = user.department.pk
                        if user.currency and user.currency.company == company:
                            context["selected_currency"] = user.currency.pk
                    except (User.DoesNotExist, ValueError, TypeError):
                        pass

            except (Company.DoesNotExist, ValueError, TypeError):
                pass

        return render(request, "settings/users/company_related_fields.html", context)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        f"{User._meta.app_label}.change_{User._meta.model_name}"
    ),
    name="dispatch",
)
class ChangeUserCompanyView(LoginRequiredMixin, HorillaSingleFormView):
    """View for changing user's company with custom template for chained form fields"""

    model = User
    form_title = _("Change Company")
    form_class = ChangeUserCompanyForm
    template_name = "settings/users/change_company_form.html"
    view_id = "change-company-form"

    @cached_property
    def form_url(self):
        """
        Get the URL for form submission based on whether it's a create or update action.
        """
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("core:user_change_company_form", kwargs={"pk": pk})
        return None

    def get_context_data(self, **kwargs):
        """Add user_pk to context for HTMX requests"""
        context = super().get_context_data(**kwargs)
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        context["user_pk"] = pk
        return context


@method_decorator(htmx_required, name="dispatch")
class UserFormViewSingle(LoginRequiredMixin, HorillaSingleFormView):
    """
    Single form view for user create and update
    """

    model = User
    view_id = "user-form-view"
    form_class = UserFormSingle
    detail_url_name = "core:user_detail_view"

    form_mode = [
        {
            "title": _("Single-Step Form"),
            "url_name": {
                "create": "core:user_create_single_form",
                "edit": "core:user_edit_single_form",
            },
            "active": True,
        },
        {
            "title": _("Multi-Step Form"),
            "url_name": {
                "create": "core:user_create_form",
                "edit": "core:user_edit_form",
            },
            "active": False,
        },
    ]

    @cached_property
    def form_url(self):
        """
        Get the URL for form submission based on whether it's a create or update action.
        """
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("core:user_edit_single_form", kwargs={"pk": pk})
        return reverse_lazy("core:user_create_single_form")

    def has_permission(self):
        """
        Override permission check for user profile editing.
        """
        user = self.request.user
        pk = self.kwargs.get("pk")

        if pk:
            if int(pk) == user.pk:
                return user.has_perm("core.can_change_profile")

            return user.has_perm(
                f"{User._meta.app_label}.change_{User._meta.model_name}"
            )

        return user.has_perm(f"{User._meta.app_label}.add_{User._meta.model_name}")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        f"{User._meta.app_label}.delete_{User._meta.model_name}", modal=True
    ),
    name="dispatch",
)
class UserDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    View to delete a User
    """

    model = User

    def get_post_delete_response(self):
        """Get the response after deleting a user."""
        return HxTriggerResponse()


class UserBackLinkMixin:
    """Where the user detail page's back arrow goes: the page the user came from."""

    model = User

    def _referer_from_referrer_params(self):
        """Rebuild the source record's own detail URL from referrer_* GET params.

        These are set explicitly by the link the user clicked (e.g. a user
        chip on a Lead's detail page), so they reflect where the user actually
        navigated from, unlike a session-stored referer which can go stale
        once the browser's address bar moves on (e.g. after visiting an
        unrelated page in the same tab).
        """
        referrer_app = self.request.GET.get("referrer_app")
        referrer_model = self.request.GET.get("referrer_model")
        referrer_id = self.request.GET.get("referrer_id")
        referrer_url = self.request.GET.get("referrer_url")

        if not (referrer_app and referrer_model and referrer_id and referrer_url):
            return None

        try:
            model_class = apps.get_model(
                app_label=referrer_app, model_name=referrer_model
            )
            if not model_class.objects.filter(pk=referrer_id).exists():
                return None
            return reverse(f"{referrer_app}:{referrer_url}", kwargs={"pk": referrer_id})
        except Exception:
            return None

    def get_previous_url(self, obj):
        """Return ``(url, is_external)`` for the back arrow of ``obj``'s detail page.

        ``is_external`` is True when the previous page lives outside the
        Settings shell, so it needs a full page navigation instead of an htmx swap.
        """
        referer_session_key = f"detail_referer_{self.model._meta.model_name}_{obj.pk}"
        explicit_referer = self._referer_from_referrer_params()
        if explicit_referer:
            self.request.session[referer_session_key] = explicit_referer
        stored_referer = explicit_referer or self.request.session.get(
            referer_session_key
        )
        user_view_url = reverse("core:user_view")

        if stored_referer:
            parsed = urlparse(stored_referer)
            referer_path = parsed.path
            stored_referer = referer_path + (f"?{parsed.query}" if parsed.query else "")
            if "login-history-view" in referer_path:
                self.request.session[referer_session_key] = user_view_url
                return user_view_url, False
        previous_url = stored_referer or user_view_url
        return previous_url, not resolves_within_settings_shell(
            urlparse(previous_url).path
        )


@method_decorator(
    permission_required_or_denied(
        f"{User._meta.app_label}.view_{User._meta.model_name}"
    ),
    name="dispatch",
)
class UserDetailView(
    UserBackLinkMixin, RecentlyViewedMixin, LoginRequiredMixin, HorillaDetailView
):
    """
    Detail view for user page: a navbar and the Details / Login History tabs.
    """

    template_name = "settings/users/user_detail_view.html"
    model = User

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj = context.get("obj") or self.get_object()
        context["previous_url"], context["previous_url_is_external"] = (
            self.get_previous_url(obj)
        )
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        f"{User._meta.app_label}.view_{User._meta.model_name}"
    ),
    name="dispatch",
)
class UserDetailNavbar(UserBackLinkMixin, LoginRequiredMixin, HorillaNavView):
    """Navbar of the user detail page: back arrow, avatar and name."""

    model_name = str(User.__name__)
    model_app_label = str(User._meta.app_label)
    navbar_indication = True
    nav_width = False
    one_view_only = True
    all_view_types = False
    reload_option = False
    filter_option = False
    search_option = False
    recently_viewed_option = False

    @cached_property
    def nav_object(self):
        """The user named in the URL."""
        return get_object_or_404(User, pk=self.kwargs["pk"])

    @property
    def nav_title(self):
        """The user's full name."""
        return self.nav_object.get_full_name()

    @property
    def nav_avatar(self):
        """The user's profile image, or their generated avatar."""
        user = self.nav_object
        return user.profile.url if user.profile else user.get_avatar()

    def get_navbar_indication_attrs(self):
        """Back arrow to the page the user came from."""
        url, is_external = self.get_previous_url(self.nav_object)
        title = escape(str(_("Back")))
        if is_external:
            return {
                "onclick": "window.location.assign(this.dataset.href)",
                "data-href": escape(url),
                "title": title,
            }
        return {
            "hx-get": escape(url),
            "hx-target": "#mainContent",
            "hx-swap": "outerHTML",
            "hx-select": "#mainContent",
            "hx-push-url": "true",
            "title": title,
        }


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        f"{User._meta.app_label}.view_{User._meta.model_name}"
    ),
    name="dispatch",
)
class UserDetailTabView(LoginRequiredMixin, HorillaTabView):
    """Details and Login History tabs of the user detail page."""

    view_id = "user-detail-tab-view"
    background_class = "bg-primary-100 rounded-md"

    def get_tabs(self):
        """Build the tab list for the user named in the URL."""
        pk = self.kwargs["pk"]
        return [
            {
                "title": _("Details"),
                "url": reverse_lazy("core:user_details_tab", kwargs={"pk": pk}),
                "target": "user-details-view-content",
                "id": "user-details-view",
            },
            {
                "title": _("Login History"),
                "url": reverse_lazy("core:user_login_history_tab", kwargs={"pk": pk}),
                "target": "user-login-history-view-content",
                "id": "user-login-history-view",
            },
        ]


class UserDetailSectionsMixin:
    """Adds the (read-only) company to the Work Info section of the user details."""

    def get_sections(self, obj):
        """Add the company to the Work Info section."""
        company = obj._meta.get_field("company")
        sections = super().get_sections(obj)
        return [
            (
                (title, [(company.verbose_name, "company"), *rows])
                if str(title) == str(_("Work Info"))
                else (title, rows)
            )
            for title, rows in sections
        ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        f"{User._meta.app_label}.view_{User._meta.model_name}"
    ),
    name="dispatch",
)
class UserDetailsTab(
    UserDetailSectionsMixin, LoginRequiredMixin, HorillaInlineEditMixin, TemplateView
):
    """
    User details tab, shown read-only and switched to an inline form by
    ``?edit=true``. Saving reloads the page so the navbar refreshes too.
    """

    template_name = "settings/users/user_details_tab.html"
    model = User
    form_class = UserDetailsInlineForm
    success_message = _("User details updated successfully.")

    def on_saved(self, request, obj):
        """Reload the page so the navbar and sections all refresh."""
        return ScriptResponse(reload=True)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        f"{User._meta.app_label}.view_{User._meta.model_name}"
    ),
    name="dispatch",
)
class UserLoginHistoryTab(LoginRequiredMixin, TemplateView):
    """Login History tab of the user detail page, listing that user's sign-ins."""

    template_name = "settings/users/user_login_history_tab.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["user_pk"] = self.kwargs["pk"]
        return context


@method_decorator(
    permission_required_or_denied("core.can_view_profile"), name="dispatch"
)
class MyProfileView(LoginRequiredMixin, TemplateView):
    """My profile page: the navbar and the details load into this shell."""

    template_name = "settings/users/my_profile.html"


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.can_view_profile"), name="dispatch"
)
class MyProfileNavbar(LoginRequiredMixin, HorillaInlineEditNavMixin, HorillaNavView):
    """Navbar of my profile: avatar, name and Edit/Save/Cancel."""

    model = User
    model_name = str(User.__name__)
    model_app_label = str(User._meta.app_label)
    navbar_indication = False
    content_url_name = "core:my_profile_content"
    edit_url_name = "core:my_profile_edit"
    content_target = "#my-profile-content"
    form_id = "my-profile-form"
    change_perm = "core.can_change_profile"

    def get_nav_object(self):
        """The signed-in user, whatever ``pk`` the URL carries."""
        return self.request.user

    @property
    def nav_title(self):
        """The user's full name."""
        return self.nav_object.get_full_name()

    @property
    def nav_avatar(self):
        """The user's profile image, or their generated avatar."""
        user = self.nav_object
        return user.profile.url if user.profile else user.get_avatar()


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.can_view_profile"), name="dispatch"
)
class MyProfileContent(
    UserDetailSectionsMixin, LoginRequiredMixin, HorillaInlineEditMixin, TemplateView
):
    """My profile sections, read-only or as an inline form (``my_profile_edit``)."""

    template_name = "settings/users/my_profile_content.html"
    model = User
    form_class = UserDetailsInlineForm
    change_perm = "core.can_change_profile"
    success_message = _("Profile updated successfully.")

    def get_object(self):
        """The signed-in user, whatever ``pk`` the URL carries."""
        return self.request.user

    def on_saved(self, request, obj):
        """Reload the page so the navbar and sections all refresh."""
        return ScriptResponse(reload=True)


@method_decorator(
    permission_required_or_denied(
        f"{User._meta.app_label}.view_{User._meta.model_name}"
    ),
    name="dispatch",
)
class LoginHistoryView(LoginRequiredMixin, HorillaView):
    """
    Main login history view of user
    """

    template_name = "settings/users/users_view.html"
    nav_url = reverse_lazy("core:login_history_navbar")
    list_url = reverse_lazy("core:login_history_list")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required(f"{User._meta.app_label}.view_{User._meta.model_name}"),
    name="dispatch",
)
class LoginHistoryNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Login history navbar
    """

    nav_title = _("Login History")
    nav_description = _("Review sign-in activity for users across your organization.")
    search_url = reverse_lazy("core:login_history_list")
    main_url = reverse_lazy("core:login_history_view")
    model_name = "LoginHistory"
    model_app_label = "login_history"
    nav_width = False
    navbar_indication = True
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False
    search_option = False

    def get_navbar_indication_attrs(self):
        # When viewing a specific user's login history (?pk=), back goes to that user's detail view
        pk = self.request.GET.get("pk")
        if pk:
            back_url = reverse("core:user_detail_view", kwargs={"pk": pk})
        else:
            back_url = self.request.session.get("last_visited_url")

        if not back_url:
            return {}

        return {
            "hx-get": back_url,
            "hx-target": "#users-view",
            "hx-swap": "innerHTML",
            "hx-push-url": "true",
            "hx-select": "#users-view",
        }


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        f"{User._meta.app_label}.view_{User._meta.model_name}"
    ),
    name="dispatch",
)
class LoginHistoryListView(LoginRequiredMixin, HorillaListView):
    """
    Login History list view of the user
    """

    from login_history.models import LoginHistory

    model = LoginHistory
    view_id = "LoginHistory"

    search_url = reverse_lazy("core:login_history_list")
    main_url = reverse_lazy("core:login_history_view")
    bulk_delete_enabled = False
    bulk_update_option = False
    enable_sorting = False

    no_record_msg = _("No login history available for this user.")

    header_attrs = [
        {
            "short_user_agent": {"style": "width: 250px;"},
            "is_login_icon": {"style": "width: 80px;"},
            "ip": {"style": "width: 100px;"},
            "user_status": {"style": "width: 100px;"},
            "formatted_datetime": {"style": "width: 125px;"},
        },
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        return (
            queryset.filter(user_id=self.request.GET.get("pk"))
            if self.request.GET.get("pk")
            else queryset
        )

    columns = [
        (_("Browser"), "short_user_agent"),
        (_("Login Time"), "formatted_datetime"),
        (_("Is Active"), "is_login_icon"),
        (_("IP"), "ip"),
        (_("Status"), "user_status"),
    ]
