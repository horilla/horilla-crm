"""
Views for the `horilla.contrib.reports` app.

Contains list, detail, and utility views used by the reports UI.
"""

# Standard library imports
import copy
import logging
from functools import cached_property
from urllib.parse import urlencode

# Third-party imports (Django)
from django.contrib import messages
from django.views.decorators.http import require_POST

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin, login_redirect
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
)
from horilla.contrib.utils.middlewares import _thread_local
from horilla.db import models
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse, reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import DetailView, View
from horilla.web import (
    HttpNotFound,
    HttpResponse,
    HxTriggerResponse,
    QueryDict,
    RefreshResponse,
    ScriptResponse,
)

# Local imports
from ..filters import ReportFilter
from ..models import Report, ReportFolder
from ..utils import detail_virtual_fields
from ..views.toolkit.report_helper import (
    TEMP_REPORT_FIELDS,
    limit_reports_to_viewable_modules,
)

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class ReportNavbar(LoginRequiredMixin, HorillaNavView):
    """Navigation bar view for reports with search and filtering capabilities."""

    search_url = reverse_lazy("reports:reports_list_view")
    main_url = reverse_lazy("reports:reports_list_view")
    filterset_class = ReportFilter
    one_view_only = True
    filter_option = False
    reload_option = False
    model_name = "Report"
    model_app_label = "reports"
    search_option = False
    all_view_types = False
    enable_actions = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        request = getattr(_thread_local, "request", None)
        title = request.GET.get("title")
        self.all_view_types = title == "Reports"

    def get_context_data(self, **kwargs):
        """Add navigation title from query params into the context."""
        context = super().get_context_data(**kwargs)
        title = self.request.GET.get("title")
        context["nav_title"] = _(title) if title else ""
        return context

    @cached_property
    def new_button(self):
        """Return the configuration for the 'New Report' button when permitted."""
        if self.request.user.has_perm(
            "reports.add_report"
        ) or self.request.user.has_perm("reports.add_own_report"):
            return {
                "title": _("New Report"),
                "url": f"""{reverse_lazy("reports:create_report")}""",
                "attrs": {"id": "report-create"},
            }
        return None

    @cached_property
    def actions(self):
        """Actions for reports"""
        if self.request.user.has_perm(
            "reports.add_report"
        ) or self.request.user.has_perm("reports.add_own_reports"):
            return [
                {
                    "action": _("Load Default Reports"),
                    "attrs": f"""
                            id="reports-load"
                            hx-get="{reverse_lazy("reports:load_default_reports")}"
                            hx-on:click="openModal();"
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            """,
                },
            ]
        return None

    @cached_property
    def second_button(self):
        """Return the configuration for the 'New Folder' button when permitted."""
        if self.request.user.has_perm(
            "reports.add_reportfolder"
        ) or self.request.user.has_perm("reports.add_own_reportfolder"):
            return {
                "title": _("New Folder"),
                "url": f"""{reverse_lazy("reports:create_folder")}?pk={self.request.GET.get("pk", "")}""",
                "attrs": {"id": "report-folder-create"},
            }
        return None


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class ReportsListView(LoginRequiredMixin, HorillaListView):
    """List view for displaying all reports with filtering and search."""

    model = Report
    template_name = "report_list_view.html"
    view_id = "reports-list"
    filterset_class = ReportFilter
    search_url = reverse_lazy("reports:reports_list_view")
    main_url = reverse_lazy("reports:reports_list_view")
    max_visible_actions = 5
    sorting_target = f"#tableview-{view_id}"

    def get_queryset(self):
        """Load report modules with each row to avoid ContentType N+1 queries."""
        queryset = super().get_queryset().select_related("module")
        return limit_reports_to_viewable_modules(queryset, self.request.user)

    def get_context_data(self, **kwargs):
        """Add page title to the template context."""
        context = super().get_context_data(**kwargs)
        context["title"] = "Reports"
        return context

    def no_record_add_button(self):
        """Return configuration for the 'no records' add button when permitted."""
        if self.request.user.has_perm(
            "reports.add_reports"
        ) or self.request.user.has_perm("reports.add_own_reports"):
            return {
                "url": f"""{reverse_lazy("reports:load_default_reports")}?new=true""",
                "attrs": 'id="reports-load"',
                "title": _("Load Default Reports"),
            }
        return None

    columns = ["name", ("module", "module_verbose_name"), "folder"]

    @cached_property
    def action_method(self):
        """Return the action method name when user has change/delete permissions."""
        action_method = ""
        if self.request.user.has_perm(
            "reports.change_report"
        ) or self.request.user.has_perm("reports.delete_report"):
            action_method = "actions"
        return action_method

    @cached_property
    def col_attrs(self):
        """Return column attributes for clickable rows in the reports list view."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {}
        if self.request.user.has_perm(
            "reports.view_report"
        ) or self.request.user.has_perm("reports.view_own_report"):
            attrs = {
                "hx-get": f"{{get_detail_view_url}}?{query_string}",
                "hx-target": "#mainContent",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "hx-select": "#mainContent",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }
        return [
            {
                "name": {
                    **attrs,
                }
            }
        ]


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class FavouriteReportsListView(LoginRequiredMixin, HorillaListView):
    """List view for displaying user's favourite reports."""

    model = Report
    template_name = "favourite_report_list_view.html"
    view_id = "favourite-reports-list"
    filterset_class = ReportFilter
    search_url = reverse_lazy("reports:favourite_reports_list_view")
    main_url = reverse_lazy("reports:favourite_reports_list_view")
    sorting_target = f"#tableview-{view_id}"

    def get_queryset(self):
        """Load report modules with each row to avoid ContentType N+1 queries."""
        queryset = super().get_queryset().select_related("module")
        return limit_reports_to_viewable_modules(queryset, self.request.user)

    @cached_property
    def action_method(self):
        """Return the action method name when user has change/delete permissions for favourites."""
        action_method = ""
        if self.request.user.has_perm(
            "reports.change_report"
        ) or self.request.user.has_perm("reports.delete_report"):
            action_method = "actions"
        return action_method

    def get_context_data(self, **kwargs):
        """Set page title to 'Favourite Reports'."""
        context = super().get_context_data(**kwargs)
        context["title"] = "Favourite Reports"
        return context

    def get_queryset(self):
        """Return queryset filtered to favourite reports only."""
        queryset = super().get_queryset()
        queryset = queryset.filter(is_favourite=True)
        return limit_reports_to_viewable_modules(queryset, self.request.user)

    columns = ["name", ("module", "module_verbose_name"), "folder"]

    @cached_property
    def col_attrs(self):
        """Return column attributes for clickable rows in the favourite reports list view."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {}
        if self.request.user.has_perm(
            "reports.view_report"
        ) or self.request.user.has_perm("reports.view_own_report"):
            attrs = {
                "hx-get": f"{{get_detail_view_url}}?{query_string}",
                "hx-target": "#mainContent",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "hx-select": "#mainContent",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }
        return [
            {
                "name": {
                    **attrs,
                }
            }
        ]


@method_decorator(htmx_required, name="dispatch")
class CreateFolderView(LoginRequiredMixin, HorillaSingleFormView):
    """View for creating new report folders."""

    model = ReportFolder
    fields = ["name", "parent", "report_folder_owner"]
    modal_height = False
    full_width_fields = ["name", "parent", "report_folder_owner"]
    hidden_fields = ["parent", "report_folder_owner"]

    def get_form(self, form_class=None):
        """Limit form to name field when updating an existing folder (pk in URL)."""
        form = super().get_form(form_class)
        if self.kwargs.get("pk"):
            form.fields = {k: v for k, v in form.fields.items() if k in ["name"]}
        return form

    def get_initial(self):
        """Set initial parent from query param and report_folder_owner to current user."""
        initial = super().get_initial()
        pk = self.request.GET.get("pk")
        initial["parent"] = pk if pk else None
        initial["report_folder_owner"] = self.request.user
        return initial

    @cached_property
    def form_url(self):
        """Return the form URL for creating or updating a folder."""
        pk = self.kwargs.get("pk")
        if pk:
            return reverse_lazy("reports:update_folder", kwargs={"pk": pk})
        return reverse_lazy("reports:create_folder")


@method_decorator(
    permission_required_or_denied(
        ["reports.view_reportfolder", "reports.view_own_reportfolder"]
    ),
    name="dispatch",
)
class ReportFolderListView(LoginRequiredMixin, HorillaListView):
    """List view for displaying report folders."""

    template_name = "report_folder_detail.html"
    model = ReportFolder
    view_id = "folder-list-view"
    sorting_target = f"#tableview-{view_id}"

    columns = ["name"]

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(parent=None)
        return queryset

    @cached_property
    def col_attrs(self):
        """Return attributes for folder list columns used to link to details."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {}
        if self.request.user.has_perm(
            "reports.view_reportfolder"
        ) or self.request.user.has_perm("reports.view_own_reportfolder"):
            attrs = {
                "hx-get": f"{{get_detail_view_url}}?{query_string}",
                "hx-target": "#mainContent",
                "hx-swap": "outerHTML",
                "hx-select": "#mainContent",
                "hx-push-url": "true",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }
        return [
            {
                "name": {
                    **attrs,
                }
            }
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Folders"
        return context

    @cached_property
    def action_method(self):
        """Return the action method name based on user permissions."""
        action_method = ""
        if self.request.user.has_perm(
            "reports.change_report"
        ) or self.request.user.has_perm("reports.delete_report"):
            action_method = "actions"
        return action_method


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class FavouriteReportFolderListView(LoginRequiredMixin, HorillaListView):
    """List view for displaying user's favourite report folders."""

    template_name = "favourite_folder_list.html"
    model = ReportFolder
    view_id = "favourite-folder-list-view"
    sorting_target = f"#tableview-{view_id}"

    def action_method(self):
        """Return the action method name for favourite folder list view based on user permissions."""
        action_method = ""
        if self.request.user.has_perm(
            "reports.change_report"
        ) or self.request.user.has_perm("reports.delete_report"):
            action_method = "actions"
        return action_method

    columns = ["name"]

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(parent=None, is_favourite=True)
        return queryset

    @cached_property
    def col_attrs(self):
        """Return attributes for favourite folder list columns used to link to details."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {}
        if self.request.user.has_perm(
            "reports.view_reportfolder"
        ) or self.request.user.has_perm("reports.view_own_reportfolder"):
            attrs = {
                "hx-get": f"{{get_detail_view_url}}?{query_string}&source=favourites",
                "hx-target": "#mainContent",
                "hx-swap": "outerHTML",
                "hx-select": "#mainContent",
                "hx-push-url": "true",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }
        return [
            {
                "name": {
                    **attrs,
                }
            }
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Favourite Folders"
        return context


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class ReportFolderDetailView(LoginRequiredMixin, HorillaListView):
    """Detail view for displaying reports within a specific folder."""

    template_name = "report_folder_detail.html"
    model = ReportFolder
    view_id = "report-folder-detail-view"
    bulk_select_option = False
    sorting_target = f"#tableview-{view_id}"

    columns = [
        "name",
        (_("Type"), "get_item_type"),
    ]

    def action_method(self):
        """Return the action method name for folder detail view based on user permissions."""
        action_method = ""
        if self.request.user.has_perm(
            "reports.change_reportfolder"
        ) or self.request.user.has_perm("reports.delete_report"):
            action_method = "actions_detail"
        return action_method

    def get_queryset(self):
        folder_id = self.kwargs.get("pk")

        folders = ReportFolder.objects.filter(parent__id=folder_id).annotate(
            content_type=models.Value("folder", output_field=models.CharField())
        )
        _reports = Report.objects.filter(folder__id=folder_id).annotate(
            content_type=models.Value("report", output_field=models.CharField())
        )
        return folders

    def get(self, request, *args, **kwargs):
        folder_id = self.kwargs.get("pk")
        if not self.model.objects.filter(
            report_folder_owner_id=self.request.user, pk=self.kwargs["pk"]
        ).first() and not self.request.user.has_perm("reports.view_report"):
            return render(self.request, "403.html")
        try:
            ReportFolder.objects.get(pk=folder_id)
        except Exception as e:
            if request.headers.get("HX-Request") == "true":
                messages.error(self.request, e)
                return RefreshResponse(request)
            raise HttpNotFound(e) from e

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        folder_id = self.kwargs.get("pk")
        reports = limit_reports_to_viewable_modules(
            Report.objects.filter(folder__id=folder_id), self.request.user
        )
        folders = list(context["object_list"])
        reports_list = list(reports)
        title = ReportFolder.objects.filter(id=folder_id).first()
        context["title"] = title.name if title else "All Folders"
        context["pk"] = folder_id

        for folder in folders:
            folder.item_type = "Folder"
            folder.hx_target = "#mainContent"
            folder.hx_swap = "outerHTML"
            folder.hx_select = "#mainContent"
        for report in reports_list:
            report.item_type = "Report"
            report.hx_target = "#mainContent"
            report.hx_swap = "outerHTML"
            report.hx_select = "#mainContent"

        combined = folders + reports_list
        combined.sort(key=lambda x: x.name.lower())
        context["object_list"] = combined
        context["queryset"] = combined

        query_params = QueryDict(mutable=True)
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        if "source" in self.request.GET:
            query_params["source"] = self.request.GET.get("source")
        query_string = urlencode(query_params)

        context["col_attrs"] = {
            "name": {
                "hx-get": f"{{get_detail_view_url}}?{query_string}",
                "hx-target": "{hx_target}",
                "hx-swap": "{hx_swap}",
                "hx-push-url": "true",
                "hx-select": "{hx_select}",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            },
            "get_item_type": {},
        }

        # Add breadcrumbs
        breadcrumbs = []
        source = self.request.GET.get("source")
        if source == "favourites":
            breadcrumbs.append(
                {
                    "name": "Favourites",
                    "url": f"{reverse('reports:favourite_folder_list_view')}?{query_string}",
                    "active": False,
                }
            )
        else:
            breadcrumbs.append(
                {
                    "name": "All Folders",
                    "url": f"{reverse('reports:report_folder_list')}?{query_string}",
                    "active": False,
                }
            )

        # Build dynamic breadcrumbs for parent folders
        current_folder = ReportFolder.objects.filter(id=folder_id).first()
        folder_chain = []
        while current_folder:
            folder_chain.append(
                {
                    "name": current_folder.name,
                    "url": f"{reverse('reports:report_folder_detail', kwargs={'pk': current_folder.id})}?{query_string}",
                    "active": current_folder.id == folder_id,
                }
            )
            current_folder = current_folder.parent

        folder_chain.reverse()

        breadcrumbs.extend(folder_chain)

        context["breadcrumbs"] = breadcrumbs
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("reports.view_reportfolder"),
    name="dispatch",
)
class MarkFolderAsFavouriteView(LoginRequiredMixin, View):
    """View for marking/unmarking report folders as favourites."""

    @method_decorator(require_POST)
    def dispatch(self, *args, **kwargs):
        """Restrict to POST and delegate to parent dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Handle POST request to toggle folder favourite status."""
        try:
            folder = get_object_or_404(ReportFolder, pk=pk)
        except Exception as e:
            messages.error(request, str(e))
            return ScriptResponse(reload=True)

        user = request.user
        if user.has_perm("reports.change_report") or folder.report_folder_owner == user:
            folder.is_favourite = not folder.is_favourite
            folder.save(update_fields=["is_favourite"])

        return ScriptResponse(reload=True)

    def get(self, request, *args, **kwargs):
        """Return 403 error page for GET requests."""
        return render(request, "403.html")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("reports.view_report"),
    name="dispatch",
)
class MarkReportAsFavouriteView(LoginRequiredMixin, View):
    """View for marking/unmarking reports as favourites."""

    @method_decorator(require_POST)
    def dispatch(self, *args, **kwargs):
        """Restrict to POST and delegate to parent dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Handle POST request to toggle report favourite status."""
        try:
            report = get_object_or_404(Report, pk=pk)
        except Exception as e:
            messages.error(request, str(e))
            return ScriptResponse(reload=True)

        user = request.user
        if user.has_perm("reports.change_report") or report.report_owner == user:
            report.is_favourite = not report.is_favourite
            report.save(update_fields=["is_favourite"])

        return ScriptResponse(reload=True)

    def get(self, request, *args, **kwargs):
        """Return 403 error page for GET requests."""
        return render(request, "403.html")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("reports.delete_report", modal=True),
    name="dispatch",
)
class ReportDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View for deleting reports."""

    model = Report

    def get_post_delete_response(self):
        return HxTriggerResponse()


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("reports.delete_reportfolder", modal=True),
    name="dispatch",
)
class FolderDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View for deleting report folders."""

    model = ReportFolder

    def get_post_delete_response(self):
        return HxTriggerResponse()


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class SearchAvailableFieldsView(DetailView):
    """View for searching and selecting available fields for report configuration."""

    model = Report

    def dispatch(self, request, *args, **kwargs):
        """Ensure user is authenticated and report exists before dispatching."""
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

    def get(self, request, *args, **kwargs):
        """Return filtered available fields HTML for columns, grouping, or filter based on search."""
        report = self.get_object()
        search_query = request.GET.get("search_columns", "").strip().lower()
        search_grouping = request.GET.get("search_grouping", "").strip().lower()
        search_filter = request.GET.get("search_filter", "").strip().lower()
        field_type = request.GET.get("field_type", "columns")

        # Get all available fields. Grouping/Filter tabs may also pick one
        # level of related-field paths (e.g. "stage__stage_type"); the
        # Columns tab stays direct-fields-only.
        model_class = report.model_class
        if field_type in ("grouping", "filter"):
            available_fields = [
                {
                    "name": info["name"],
                    "verbose_name": info["verbose_name"],
                    "field_type": info["type"],
                }
                for info in report.get_available_grouping_fields()
            ]
        else:
            available_fields = []
            for field in model_class._meta.get_fields():
                if not field.many_to_many and not field.one_to_many:
                    if field.name in ("id", "pk"):
                        continue
                    if not getattr(field, "editable", True):
                        continue
                    available_fields.append(
                        {
                            "name": field.name,
                            "verbose_name": field.verbose_name,
                            "field_type": field.__class__.__name__,
                        }
                    )
            available_fields.extend(detail_virtual_fields(model_class))

        # Get the appropriate search query based on field type
        search_term = ""
        if field_type == "columns":
            search_term = search_query
        elif field_type == "grouping":
            search_term = search_grouping
        elif field_type == "filter":
            search_term = search_filter

        # Filter fields based on search term
        if search_term:
            filtered_fields = [
                field
                for field in available_fields
                if search_term in field["verbose_name"].lower()
                or search_term in field["name"].lower()
            ]
        else:
            filtered_fields = available_fields

        # Get preview data for temp report
        session_key = f"report_preview_{report.pk}"
        preview_data = self.request.session.get(session_key, {})
        temp_report = self.create_temp_report(report, preview_data)

        # Render the appropriate template based on field type
        context = {"available_fields": filtered_fields, "report": temp_report}
        if field_type == "columns":
            return render(
                self.request,
                "partials/available_columns_list.html",
                context,
            )
        if field_type == "grouping":
            return render(
                self.request,
                "partials/available_grouping_list.html",
                context,
            )
        if field_type == "filter":
            return render(
                self.request,
                "partials/available_filter_list.html",
                context,
            )
        return HttpResponse("<div>Invalid field type</div>")

    def create_temp_report(self, original_report, preview_data):
        """Create a temporary report object with preview data"""

        temp_report = copy.copy(original_report)

        for field in TEMP_REPORT_FIELDS:
            if field in preview_data:
                setattr(temp_report, field, preview_data[field])

        return temp_report
