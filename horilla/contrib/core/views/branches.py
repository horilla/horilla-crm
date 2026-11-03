"""
This view handles the methods for user view
"""

# Standard library imports
from urllib.parse import urlencode

# Django imports
# Third-party imports (Django)
from django.contrib import messages
from django.utils.safestring import mark_safe

# First-party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin, login_redirect
from horilla.contrib.generics.views import (
    HorillaDetailView,
    HorillaInlineEditNavMixin,
    HorillaListView,
    HorillaMultiStepFormView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaTabView,
    HorillaView,
)
from horilla.shortcuts import get_object_or_404
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.functional import cached_property
from horilla.utils.html import format_html
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView
from horilla.web import HttpNotFound, HttpResponse, RefreshResponse, ScriptResponse

from ..filters import CompanyFilter

# Local imports
from ..forms import CompanyFormClassSingle, CompanyMultistepFormClass
from ..models import Company
from ..signals import company_created
from .core import CompanyDetailsTab


@method_decorator(
    permission_required_or_denied("core.view_company", wrapper_id="branches-view"),
    name="dispatch",
)
class BranchesView(LoginRequiredMixin, HorillaView):
    """
    TemplateView for branches page.
    """

    template_name = "settings/settings_list_shell.html"
    view_id = "branches-view"
    nav_url = reverse_lazy("core:branches_nav_view")
    list_url = reverse_lazy("core:branches_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("core.view_company"), name="dispatch")
class BranchNavbar(LoginRequiredMixin, HorillaNavView):
    """
    navbar view for users
    """

    nav_description = _("Manage your organization's branches.")
    search_url = reverse_lazy("core:branches_list_view")
    main_url = reverse_lazy("core:branches_view")
    filterset_class = CompanyFilter
    model_name = "Company"
    model_app_label = "core"
    nav_width = False
    url_name = "branches_list_view"
    one_view_only = True
    reload_option = False
    all_view_types = False
    enable_actions = True

    @cached_property
    def new_button(self):
        """
        Return configuration for the "New Branch" button.

        The button is shown only if the user has permission to add a company.
        """
        if self.request.user.has_perm("core.add_company"):
            return {
                "url": f"""{reverse_lazy("core:create_company")}?new=true""",
                "attrs": {"id": "branch-create"},
            }
        return None

    @cached_property
    def actions(self):
        """
        Return available action configurations for the branch navbar view.

        Actions are displayed only if the user has permission to view companies.
        """
        if self.request.user.has_perm("core.view_company"):
            return [
                {
                    "action": _("Add Column to List"),
                    "attrs": f"""
                            hx-get="{reverse_lazy("generics:column_selector")}?app_label={self.model_app_label}&model_name={self.model_name}&url_name={self.url_name}"
                            onclick="openModal()"
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            """,
                }
            ]
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required_or_denied("core.view_company"), name="dispatch")
class BranchListView(LoginRequiredMixin, HorillaListView):
    """
    List view of users
    """

    model = Company
    view_id = "branch-container"
    filterset_class = CompanyFilter
    search_url = reverse_lazy("core:branches_list_view")
    main_url = reverse_lazy("core:branches_view")
    bulk_update_two_column = True
    bulk_select_option = False

    @cached_property
    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        if self.request.user.has_perm("core.add_company"):
            return {
                "url": f"""{reverse_lazy("core:create_company")}?new=true""",
                "attrs": 'id="branch-create"',
            }
        return None

    columns = [
        (_("Name"), "get_avatar_with_name"),
        "email",
        "no_of_employees",
        "hq",
        "currency",
    ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "core.change_company",
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
            "permission": "core.delete_company",
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
        Return column-level HTMX attributes for branch list rows.

        Enables row click navigation to the branch detail view
        when the user has view company permission.
        """
        query_params = self.request.GET.dict()
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {}
        if self.request.user.has_perm("core.view_company"):
            attrs = {
                "hx-get": f"{{get_detail_view_url}}?{query_string}",
                "hx-target": "#branches-view",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "hx-select": "#branches-view",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }
        return [
            {
                "get_avatar_with_name": {
                    **attrs,
                }
            }
        ]


@method_decorator(
    permission_required_or_denied("core.view_company"),
    name="dispatch",
)
class BranchDetailView(HorillaDetailView):
    """
    Detail view for branch (company) page.
    """

    template_name = "branches/branch_detail_view.html"
    model = Company
    fieldsets = (
        (
            _("Branch Information"),
            {
                "fields": (
                    "name",
                    "email",
                    "website",
                    "contact_number",
                    "no_of_employees",
                    "annual_revenue",
                ),
                "icon": "fas fa-building",
            },
        ),
        (
            _("Address"),
            {
                "fields": (
                    "city",
                    "state",
                    "country",
                    "zip_code",
                ),
                "icon": "fas fa-map-marker-alt",
            },
        ),
        (
            _("Localization"),
            {
                "fields": (
                    "time_zone",
                    "language",
                    "currency",
                ),
                "icon": "fas fa-globe",
            },
        ),
    )

    def dispatch(self, request, *args, **kwargs):
        """Require auth, resolve object, and return HX-Refresh or 404 on error."""
        if not request.user.is_authenticated:
            return login_redirect(request)
        try:
            self.object = self.get_object()
        except Exception as e:
            if request.headers.get("HX-Request") == "true":
                messages.error(self.request, e)
                return RefreshResponse(request)
            raise HttpNotFound(e) from e
        return super().dispatch(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required_or_denied("core.view_company"), name="dispatch")
class BranchDetailNavbar(LoginRequiredMixin, HorillaInlineEditNavMixin, HorillaNavView):
    """Navbar of the branch detail page: back arrow, branch name and Edit/Save/Cancel."""

    model = Company
    model_name = "Company"
    model_app_label = "core"
    navbar_indication = True
    content_url_name = "core:branch_details_content"
    edit_url_name = "core:branch_details_edit"
    content_target = "#branch-detail-content"
    form_id = "branch-details-form"

    @property
    def nav_title(self):
        """Branch name."""
        return self.nav_object.name

    @property
    def nav_avatar(self):
        """Branch logo, or its generated avatar."""
        company = self.nav_object
        return company.icon.url if company.icon else company.get_avatar()

    def get_navbar_indication_attrs(self):
        """Back arrow to the branches list."""
        return {
            "hx-get": str(reverse_lazy("core:branches_view")),
            "hx-target": "#branches-view",
            "hx-select": "#branches-view",
            "hx-swap": "outerHTML",
            "hx-push-url": "true",
            "title": str(_("All branches")),
        }


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required_or_denied("core.view_company"), name="dispatch")
class BranchDetailContent(CompanyDetailsTab):
    """Branch detail sections, read-only or as an inline form (``branch_details_edit``)."""

    template_name = "branches/branch_details_content.html"

    def get_object(self):
        """The branch named in the URL."""
        return get_object_or_404(Company, pk=self.kwargs["pk"])

    def on_saved(self, request, obj):
        """Reload the page so the navbar, dropdown and sections all refresh."""
        return ScriptResponse(reload=True)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.delete_company", modal=True),
    name="dispatch",
)
class BranchDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    HTMX-enabled delete view for branches.

    Handles branch deletion and refreshes the branches list
    and company dropdown after successful deletion.
    """

    model = Company
    reassign_all_visibility = False
    reassign_individual_visibility = False
    hx_target = "#branches-view"

    def get_post_delete_response(self):
        branches_view_url = reverse_lazy("core:branches_view")
        response_html = format_html(
            "<span "
            'hx-trigger="load" '
            'hx-get="{}" '
            'hx-select="#branches-view" '
            'hx-target="#branches-view" '
            'hx-swap="outerHTML" '
            'hx-select-oob="#dropdown-companies">'
            "</span>",
            branches_view_url,
        )
        response = HttpResponse(response_html)
        response["HX-Retarget"] = "#branches-view"
        response["HX-Reswap"] = "innerHTML"
        return response


@method_decorator(
    permission_required_or_denied(
        [
            "core.view_company",
            "core.view_fiscalyear",
            "core.view_businesshour",
            "core.view_holiday",
            "core.view_multiplecurrency",
            "core.view_recyclebinpolicy",
        ]
    ),
    name="dispatch",
)
class CompanyInformationTabView(LoginRequiredMixin, HorillaTabView):
    """
    Company information settings tab shell.

    Third-party apps append tabs with ``TabExtension`` /
    ``_inherit_tab`` (see ``horilla.extension.tab``). Override ``get_tabs``.
    """

    view_id = "company-information-view"
    background_class = "bg-primary-100 rounded-md"

    def get_tabs(self):
        """Build the core company information tab list."""
        tabs = []

        # Company Details Tab
        if self.request.user.has_perm("core.view_company"):
            tabs.append(
                {
                    "title": _("Details"),
                    "url": reverse_lazy("core:company_details_tab"),
                    "target": "company-information-view-content",
                    "id": "company-information-view",
                }
            )

        # Fiscal Year Tab
        if self.request.user.has_perm("core.view_fiscalyear"):
            tabs.append(
                {
                    "title": _("Fiscal Year"),
                    "url": reverse_lazy("core:company_fiscal_year_tab"),
                    "target": "fiscal-year-view-content",
                    "id": "fiscal-year-view",
                }
            )

        # Business hours & shift hours tab
        if self.request.user.has_perm("core.view_businesshour"):
            tabs.append(
                {
                    "title": _("Working hours"),
                    "url": reverse_lazy("core:business_hour_view"),
                    "target": "business-hour-content",
                    "id": "business-hour-view",
                }
            )

        # Holidays Tab
        if self.request.user.has_perm("core.view_holiday"):
            tabs.append(
                {
                    "title": _("Holidays"),
                    "url": reverse_lazy("core:holiday_view"),
                    "target": "holidays-view-content",
                    "id": "holidays-view",
                }
            )

        # Currencies Tab
        if self.request.user.has_perm("core.view_multiplecurrency"):
            tabs.append(
                {
                    "title": _("Currencies"),
                    "url": reverse_lazy("core:multiple_currency"),
                    "target": "currency-view-content",
                    "id": "currency-view",
                }
            )

        # Recycle Bin Policy Tab
        if self.request.user.has_perm("core.view_recyclebinpolicy"):
            tabs.append(
                {
                    "title": _("Recycle Bin Policy"),
                    "url": reverse_lazy("core:recycle_bin_policy_view"),
                    "target": "recycle-view-content",
                    "id": "recycle-view",
                }
            )

        return tabs


@method_decorator(
    permission_required_or_denied("core.view_company"),
    name="dispatch",
)
class CompanyInformationView(LoginRequiredMixin, TemplateView):
    """
    TemplateView for company information settings page.
    """

    template_name = "settings/company_information.html"

    def get_context_data(self, **kwargs):
        """
        Get context data for company information view.
        """
        context = super().get_context_data(**kwargs)
        company = getattr(self.request, "active_company", None)
        context["has_company"] = bool(company)
        return context


@method_decorator(htmx_required, name="dispatch")
class CompanyMultiFormView(LoginRequiredMixin, HorillaMultiStepFormView):
    """compnay Create/Update View"""

    form_class = CompanyMultistepFormClass
    model = Company
    view_id = "company-form-view"
    save_and_new = False

    form_mode = [
        {
            "title": _("Single-Step Form"),
            "url_name": {
                "create": "core:create_company",
                "edit": "core:edit_company",
            },
            "active": False,
        },
        {
            "title": _("Multi-Step Form"),
            "url_name": {
                "create": "core:create_company_multi_step",
                "edit": "core:edit_company_multi_step",
            },
            "active": True,
        },
    ]

    def get_signal_kwargs(self):
        """
        Extension point: Override this method to pass additional data to signal.
        Clients can add custom data without modifying source code.
        """
        return {}

    @cached_property
    def form_url(self):
        """Form URL for company"""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("core:edit_company_multi_step", kwargs={"pk": pk})
        return reverse_lazy("core:create_company_multi_step")

    def form_valid(self, form):
        """
        Handle valid form submission.
        """

        step = self.get_initial_step()

        if step < self.total_steps:
            return super().form_valid(form)

        response = super().form_valid(form)
        custom_kwargs = self.get_signal_kwargs()
        signal_kwargs = {
            "instance": self.object,
            "request": self.request,
            "view": self,
            "is_new": not self.kwargs.get("pk"),
            **custom_kwargs,
        }
        responses = company_created.send(sender=self.__class__, **signal_kwargs)

        for _receiver, response in responses:
            if isinstance(response, HttpResponse):
                wrapped_response = HttpResponse(
                    format_html(
                        '<div id="{}-container">{}</div>',
                        self.view_id,
                        mark_safe(response.content.decode()),
                    )
                )
                return wrapped_response

        if self.request.GET.get("details") == "true":
            return ScriptResponse(reload=True, close=True)

        branches_view_url = reverse_lazy("core:branches_view")
        response_html = format_html(
            "<span "
            'hx-trigger="load" '
            'hx-get="{}" '
            'hx-select="#branches-view" '
            'hx-target="#branches-view" '
            'hx-swap="outerHTML" '
            'hx-on::after-request="closeModal();" '
            'hx-select-oob="#dropdown-companies">'
            "</span>",
            branches_view_url,
        )

        return HttpResponse(response_html)

    step_titles = {
        "1": _("Basic Information"),
        "2": _("Business Details"),
        "3": _("Location & Locale"),
        "4": _("Preferences"),
    }

    def get_form_kwargs(self):
        """
        Get form kwargs for company multi-step form.
        """
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs


@method_decorator(htmx_required, name="dispatch")
class CompanyFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    compnay Create/Update View
    """

    model = Company
    view_id = "company-form-view"
    form_class = CompanyFormClassSingle
    save_and_new = False

    def get_signal_kwargs(self):
        """
        Extension point: Override this method to pass additional data to signal.
        Clients can add custom data without modifying source code.
        """
        return {}

    form_mode = [
        {
            "title": _("Single-Step Form"),
            "url_name": {
                "create": "core:create_company",
                "edit": "core:edit_company",
            },
            "active": True,
        },
        {
            "title": _("Multi-Step Form"),
            "url_name": {
                "create": "core:create_company_multi_step",
                "edit": "core:edit_company_multi_step",
            },
            "active": False,
        },
    ]

    @cached_property
    def form_url(self):
        """Form URL for company"""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("core:edit_company", kwargs={"pk": pk})
        return reverse_lazy("core:create_company")

    def form_valid(self, form):
        """
        Handle valid form submission.
        """
        super().form_valid(form)
        custom_kwargs = self.get_signal_kwargs()
        signal_kwargs = {
            "instance": self.object,
            "request": self.request,
            "view": self,
            "is_new": not self.kwargs.get("pk"),
            **custom_kwargs,  # Add any custom kwargs from override
        }
        responses = company_created.send(sender=self.__class__, **signal_kwargs)

        for _receiver, response in responses:
            if isinstance(response, HttpResponse):
                wrapped_response = HttpResponse(
                    format_html(
                        '<div id="{}-container">{}</div>',
                        self.view_id,
                        mark_safe(response.content.decode()),
                    )
                )
                return wrapped_response

        if self.request.GET.get("details") == "true":
            return ScriptResponse(reload=True, close=True)
        branches_view_url = reverse_lazy("core:branches_view")

        response_html = format_html(
            "<span "
            'hx-trigger="load" '
            'hx-get="{}" '
            'hx-select="#branches-view" '
            'hx-target="#branches-view" '
            'hx-swap="outerHTML" '
            'hx-on::after-request="closeModal();" '
            'hx-select-oob="#dropdown-companies">'
            "</span>",
            branches_view_url,
        )

        return HttpResponse(response_html)
