"""Views for managing dashboard folders, including creation, listing, favoriting, moving, and deletion."""

# Standard library imports
import logging
from urllib.parse import urlencode

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
)
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
from horilla.web import (
    HttpNotFound,
    HxTriggerResponse,
    QueryDict,
    RefreshResponse,
    ScriptResponse,
)

# Local imports
from ..filters import DashboardFilter, DashboardFolderFilter
from ..models import Dashboard, DashboardFolder

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
class DashboardFolderCreate(LoginRequiredMixin, HorillaSingleFormView):
    """View to handle creation and updating of dashboard folders."""

    model = DashboardFolder
    fields = ["name", "folder_owner", "description", "parent_folder"]
    modal_height = False
    full_width_fields = ["name", "folder_owner", "description", "parent_folder"]
    hidden_fields = ["parent_folder", "folder_owner"]
    save_and_new = False

    def get_form(self, form_class=None):
        """In edit mode (pk set), show only the name field."""
        form = super().get_form(form_class)
        if self.kwargs.get("pk"):
            form.fields = {k: v for k, v in form.fields.items() if k in ["name"]}
        return form

    def get_initial(self):
        """Set parent_folder from GET and folder_owner to current user."""
        initial = super().get_initial()
        pk = self.request.GET.get("pk")
        initial["parent_folder"] = pk if pk else None
        initial["folder_owner"] = self.request.user
        return initial

    @cached_property
    def form_url(self):
        """Determine the form URL based on whether it's a create or update operation."""
        pk = self.kwargs.get("pk")
        if pk:
            return reverse_lazy("dashboard:dashboard_folder_update", kwargs={"pk": pk})
        return reverse_lazy("dashboard:dashboard_folder_create")


@method_decorator(htmx_required, name="dispatch")
class DashboardFolderFavoriteView(LoginRequiredMixin, View):
    """View to handle adding/removing a dashboard folder to/from user's favorites."""

    def post(self, request, *args, **kwargs):
        """Handle POST requests to toggle favorite status of a dashboard folder."""
        try:
            folder = DashboardFolder.objects.get(pk=kwargs["pk"])
        except Exception as e:
            messages.error(request, str(e))
            return ScriptResponse(reload=True)

        user = request.user
        if (
            user.has_perm("dashboard.change_dashboardfolder")
            or folder.folder_owner == user
        ):
            if user in folder.favourited_by.all():
                folder.favourited_by.remove(user)
            else:
                folder.favourited_by.add(user)
        return ScriptResponse(reload=True)

    def get(self, request, *args, **kwargs):
        """Handle GET requests by returning a 403 error page."""
        return render(request, "403.html")


@method_decorator(
    permission_required_or_denied(
        [
            "dashboard.view_dashboardfolder",
            "dashboard.view_own_dashboardfolder",
        ]
    ),
    name="dispatch",
)
class DashboardFolderListView(LoginRequiredMixin, HorillaListView):
    """View to display the list of dashboard folders."""

    template_name = "dashboard_folder_detail.html"
    model = DashboardFolder
    view_id = "dashboard-folder-list-view"
    filterset_class = DashboardFolderFilter
    search_url = reverse_lazy("dashboard:dashboard_folder_list_view")
    main_url = reverse_lazy("dashboard:dashboard_folder_list_view")
    bulk_select_option = False
    sorting_target = f"#tableview-{view_id}"

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(parent_folder=None)
        return queryset

    columns = ["name", "description"]

    @cached_property
    def action_method(self):
        """Determine the action method based on user permissions."""
        action_method = ""
        if (
            self.request.user.has_perm("dashboard.change_dashboardfolder")
            or self.request.user.has_perm("dashboard.delete_dashboardfolder")
            or self.request.user.has_perm("dashboard.view_own_dashboardfolder")
        ):
            action_method = "actions"

        return action_method

    @cached_property
    def col_attrs(self):
        """Define attributes for the 'name' column to make it clickable if the user has view permissions."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {}
        if self.request.user.has_perm(
            "dashboard.view_dashboardfolder"
        ) or self.request.user.has_perm("dashboard.view_own_dashboardfolder"):
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Folders"
        for folder in context["object_list"]:
            folder.get_detail_view_url = reverse_lazy(
                "dashboard:dashboard_folder_detail_list",
                kwargs={"pk": folder.pk},
            )

        return context


@method_decorator(
    permission_required_or_denied(
        ["dashboard.view_dashboard", "dashboard.view_own_dashboard"]
    ),
    name="dispatch",
)
class FolderDetailListView(LoginRequiredMixin, HorillaListView):
    """View to display the contents of a specific dashboard folder."""

    template_name = "dashboard_folder_detail.html"
    model = DashboardFolder
    view_id = "dashboard-folder-detail-view"
    filterset_class = DashboardFolderFilter
    bulk_select_option = False
    sorting_target = f"#tableview-{view_id}"

    columns = [
        (_("Name"), "name"),
        (_("Type"), "get_item_type"),
    ]

    @cached_property
    def action_method(self):
        """Determine the action method based on user permissions."""
        action_method = ""
        if (
            self.request.user.has_perm("dashboard.change_dashboardfolder")
            or self.request.user.has_perm("dashboard.delete_dashboardfolder")
            or self.request.user.has_perm("dashboard.change_dashboard")
            or self.request.user.has_perm("dashboard.delete_dashboard")
        ):
            action_method = "actions_detail"

        return action_method

    def get(self, request, *args, **kwargs):
        if not self.model.objects.filter(
            folder_owner_id=self.request.user, pk=self.kwargs["pk"]
        ).first() and not self.request.user.has_perm("dashboard.view_dashboard"):
            return render(self.request, "403.html")
        try:
            DashboardFolder.objects.get(pk=self.kwargs["pk"])
        except Exception as e:
            if request.headers.get("HX-Request") == "true":
                messages.error(self.request, e)
                return RefreshResponse(request)
            raise HttpNotFound(e) from e
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        folder_id = self.kwargs.get("pk")
        self.filterset = DashboardFolderFilter(
            self.request.GET,
            queryset=DashboardFolder.objects.filter(parent_folder__id=folder_id),
            request=self.request,
        )
        return self.filterset.qs

    def render_search_suggest(self, request):
        """Search dropdown whose counts cover both sub-folders and dashboards."""
        text = request.GET.get("search_suggest", "").strip()
        folder_id = self.kwargs.get("pk")
        folder_set = self.filterset
        dashboard_set = DashboardFilter(
            request.GET,
            queryset=Dashboard.objects.filter(folder__id=folder_id),
            request=request,
        )
        folders = DashboardFolder.objects.filter(parent_folder__id=folder_id)
        dashboards = Dashboard.objects.filter(folder__id=folder_id)
        rows = []
        if text:
            labels = folder_set.get_search_field_labels()
            for lookup, label in labels.items():
                count = (
                    folders.filter(folder_set.build_field_q(lookup, text)).count()
                    + dashboards.filter(
                        dashboard_set.build_field_q(lookup, text)
                    ).count()
                )
                rows.append({"field": lookup, "label": label, "count": count})
        return render(
            request,
            "partials/list_search_suggest.html",
            {
                "text": text,
                "field_rows": rows,
                "filter_rows": [],
                "show_fields": False,
                "has_matches": any(r["count"] for r in rows[:1]),
            },
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        folder_id = self.kwargs.get("pk")

        folders = self.filterset.qs
        dashboard = DashboardFilter(
            self.request.GET,
            queryset=Dashboard.objects.filter(folder__id=folder_id),
            request=self.request,
        ).qs

        folders_list = list(folders)
        dashboards_list = list(dashboard)

        for folder in folders_list:
            folder.item_type = _("Folder")
            folder.get_item_type = _("Folder")
            folder.hx_target = "#mainContent"
            folder.hx_swap = "outerHTML"
            folder.hx_select = "#mainContent"
            folder.get_detail_view_url = reverse_lazy(
                "dashboard:dashboard_folder_detail_list",
                kwargs={"pk": folder.pk},
            )

        for dashboard in dashboards_list:
            dashboard.item_type = _("Dashboard")
            dashboard.get_item_type = _("Dashboard")
            dashboard.hx_target = "#mainContent"
            dashboard.hx_swap = "outerHTML"
            dashboard.hx_select = "#mainContent"
            dashboard.get_detail_view_url = reverse_lazy(
                "dashboard:dashboard_detail_view", kwargs={"pk": dashboard.pk}
            )

        combined = folders_list + dashboards_list
        combined.sort(key=lambda x: x.name.lower())

        context["object_list"] = combined
        context["queryset"] = combined

        context["total_records_count"] = len(combined)

        title = DashboardFolder.objects.filter(id=folder_id).first()
        context["title"] = title.name if title else "All Folders"
        context["pk"] = folder_id

        query_params = QueryDict(mutable=True)
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
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

        breadcrumbs = []
        current_folder = DashboardFolder.objects.filter(id=folder_id).first()

        breadcrumbs.append(
            {
                "name": "All Folders",
                "url": f"{reverse_lazy('dashboard:dashboard_folder_list_view')}?{query_string}",
            }
        )

        folder_chain = []
        temp_folder = current_folder
        while temp_folder:
            folder_chain.append(temp_folder)
            temp_folder = temp_folder.parent_folder

        folder_chain.reverse()

        for folder in folder_chain:
            breadcrumbs.append(
                {
                    "name": folder.name,
                    "url": f"{reverse_lazy('dashboard:dashboard_folder_detail_list', kwargs={'pk': folder.id})}?{query_string}",
                    "active": folder.id == int(folder_id),
                }
            )

        context["breadcrumbs"] = breadcrumbs

        return context


@method_decorator(htmx_required, name="dispatch")
class FolderDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View to delete a dashboard folder."""

    model = DashboardFolder

    def get_post_delete_response(self):
        return HxTriggerResponse()


@method_decorator(htmx_required, name="dispatch")
class MoveDashboardView(LoginRequiredMixin, HorillaSingleFormView):
    """View to move a dashboard into a folder."""

    model = Dashboard
    fields = ["folder"]
    modal_height = False
    full_width_fields = ["folder"]

    @cached_property
    def form_url(self):
        """Get the URL for the form, using the dashboard's primary key."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("dashboard:move_dashboard_to_folder", kwargs={"pk": pk})
        return None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def get(self, request, *args, **kwargs):
        dashboard_id = self.kwargs.get("pk")
        if request.user.has_perm("dashboard.change_dashboard") or request.user.has_perm(
            "dashboard.add_dashboard"
        ):
            return super().get(request, *args, **kwargs)

        if dashboard_id:
            dashboard = get_object_or_404(Dashboard, pk=dashboard_id)
            if dashboard.dashboard_owner == request.user:
                return super().get(request, *args, **kwargs)

        return render(request, "403.html")

    def get_form(self, form_class=None):
        """Add widget attrs and restrict folder queryset for non-superusers."""
        form = super().get_form(form_class)
        user = getattr(self.request, "user", None)
        if user:
            form.fields["folder"].widget.attrs.update(
                {
                    "class": "js-example-basic-single",
                }
            )
            if not user.is_superuser:
                form.fields["folder"].queryset = DashboardFolder.objects.filter(
                    folder_owner=user
                )
        return form


@method_decorator(htmx_required, name="dispatch")
class MoveFolderView(LoginRequiredMixin, HorillaSingleFormView):
    """View to move a dashboard folder into another folder."""

    model = DashboardFolder
    fields = ["parent_folder"]
    modal_height = False
    full_width_fields = ["parent_folder"]

    @cached_property
    def form_url(self):
        """Get the URL for the form, using the folder's primary key."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("dashboard:move_folder_to_folder", kwargs={"pk": pk})
        return None

    def get(self, request, *args, **kwargs):
        folder_id = self.kwargs.get("pk")
        if request.user.has_perm("dashboard.change_dashboard") or request.user.has_perm(
            "dashboard.add_dashboard"
        ):
            return super().get(request, *args, **kwargs)

        if folder_id:
            folder = get_object_or_404(DashboardFolder, pk=folder_id)
            if folder.folder_owner == request.user:
                return super().get(request, *args, **kwargs)

        return render(request, "403.html")

    def get_form(self, form_class=None):
        """Add widget attrs and restrict parent_folder queryset for non-superusers."""
        form = super().get_form(form_class)
        user = getattr(self.request, "user", None)
        if user:
            form.fields["parent_folder"].widget.attrs.update(
                {
                    "class": "js-example-basic-single",
                }
            )
            if not user.is_superuser:
                form.fields["parent_folder"].queryset = DashboardFolder.objects.filter(
                    folder_owner=user
                )
        return form
