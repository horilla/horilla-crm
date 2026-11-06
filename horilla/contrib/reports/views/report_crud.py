"""CRUD views for creating, updating, and managing reports."""

# Standard library imports
import copy
from functools import cached_property

# Third-party imports (Django)
from django import forms
from django.contrib import messages
from django.views.decorators.http import require_POST

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin, login_redirect
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.forms import HorillaModelForm
from horilla.contrib.generics.views import HorillaSingleFormView
from horilla.shortcuts import get_object_or_404, redirect, render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import DetailView, View
from horilla.web import (
    Http404,
    HttpNotFound,
    HttpResponse,
    RefreshResponse,
    ScriptResponse,
)

# Local imports
from ..forms import ReportForm
from ..models import Report, ReportFolder
from ..utils import detail_virtual_fields
from ..views.report_detail import ReportDetailView
from ..views.toolkit.report_helper import (
    TEMP_REPORT_FIELDS,
    create_temp_report_with_preview,
)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class ChangeChartTypeView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Unified "Change Chart" view: lets the user change chart type,
    primary (X-axis) field, and stacked (second group) field in one place.
    """

    model = Report
    fields = ["chart_type", "chart_field", "chart_field_stacked", "chart_value_field"]
    modal_height = False
    full_width_fields = [
        "chart_type",
        "chart_field",
        "chart_field_stacked",
        "chart_value_field",
    ]
    save_and_new = False

    def get_form_class(self):
        report = get_object_or_404(Report, pk=self.kwargs["pk"])

        # Preview-aware: use temp report if preview data exists
        session_key = f"report_preview_{report.pk}"
        preview_data = self.request.session.get(session_key, {})
        if preview_data:
            temp_report = copy.copy(report)
            for field in TEMP_REPORT_FIELDS:
                if field in preview_data:
                    setattr(temp_report, field, preview_data[field])
        else:
            temp_report = report

        # Chart type choices (reuse ChangeChartReportForm logic, inlined)
        total_groups = self.request.GET.get("total")
        try:
            total_groups = int(total_groups)
        except (TypeError, ValueError):
            total_groups = 0

        chart_choices = Report.CHART_TYPES
        if total_groups <= 1:
            chart_choices = [
                c
                for c in chart_choices
                if c[0]
                not in [
                    "stacked_vertical",
                    "stacked_horizontal",
                    "heatmap",
                    "sankey",
                ]
            ]

        # Field choices from row/column groups
        # Currently selected / previewed chart type (for show/hide stack-by)
        selected_type = self.request.GET.get("chart_type") or temp_report.chart_type
        STACKED_TYPES = {
            "stacked_vertical",
            "stacked_horizontal",
            "heatmap",
            "sankey",
            "radar",
        }
        show_stack = selected_type in STACKED_TYPES

        # X / Stack field choices from row/column groups
        field_choices = []
        for field_name in temp_report.row_groups_list:
            try:
                field = temp_report.model_class._meta.get_field(field_name)
                verbose_name = field.verbose_name
                field_choices.append((field_name, f"{verbose_name} (Row Group)"))
            except Exception:
                field_choices.append((field_name, f"{field_name.title()} (Row Group)"))

        for field_name in temp_report.column_groups_list:
            try:
                field = temp_report.model_class._meta.get_field(field_name)
                verbose_name = field.verbose_name
                field_choices.append((field_name, f"{verbose_name} (Column Group)"))
            except Exception:
                field_choices.append(
                    (field_name, f"{field_name.title()} (Column Group)")
                )

        field_choices.insert(0, ("", "-- Select Field --"))

        CHART_METRIC_CHOICES = [
            ("sum", _("Sum")),
            ("avg", _("Average")),
            ("min", _("Minimum")),
            ("max", _("Maximum")),
        ]

        numeric_choices = [("", _("Record count"))]
        try:
            available_fields = temp_report.get_available_fields()
            for info in available_fields:
                if not info.get("is_numeric"):
                    continue
                field_name = info["name"]
                verbose_name = info["verbose_name"]
                for mkey, mlabel in CHART_METRIC_CHOICES:
                    value = f"{mkey}__{field_name}"
                    label = _("%(metric)s of %(field)s") % {
                        "metric": mlabel,
                        "field": verbose_name,
                    }
                    numeric_choices.append((value, label))
        except Exception:
            pass

        class ChangeChartForm(HorillaModelForm):
            """Dynamic form for chart type + X-axis + stacked field."""

            chart_type = forms.ChoiceField(
                choices=chart_choices,
                label=_("Chart type"),
                required=True,
                widget=forms.Select(attrs={"class": "w-full p-2 border rounded"}),
            )

            chart_field = forms.ChoiceField(
                choices=field_choices,
                label=_("X-axis (Group by)"),
                required=False,
                widget=forms.Select(attrs={"class": "w-full p-2 border rounded"}),
            )

            chart_field_stacked = forms.ChoiceField(
                choices=field_choices,
                label=_("Stack by (second group)"),
                required=False,
                widget=forms.Select(attrs={"class": "w-full p-2 border rounded"}),
            )

            chart_value_field = forms.ChoiceField(
                choices=numeric_choices,
                label=_("Y-axis (Value)"),
                required=False,
                widget=forms.Select(attrs={"class": "w-full p-2 border rounded"}),
            )

            class Meta:
                """Meta class to specify model and fields for the form."""

                model = Report
                fields = [
                    "chart_type",
                    "chart_field",
                    "chart_field_stacked",
                    "chart_value_field",
                ]

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                # HTMX: when chart type changes, reload this modal so we can
                # hide/show the Stack by field server-side based on type.
                try:
                    url = reverse_lazy(
                        "reports:change_chart_type",
                        kwargs={"pk": self.instance.pk},
                    )
                    self.fields["chart_type"].widget.attrs.update(
                        {
                            "hx-get": url,
                            "hx-target": "#modalBox",
                            "hx-swap": "innerHTML",
                            "hx-trigger": "change",
                            "hx-include": "closest form",
                        }
                    )
                except Exception:
                    pass

                # Hide Stack by field for non-stacked chart types
                if not show_stack:
                    self.fields.pop("chart_field_stacked", None)

        return ChangeChartForm

    def get_initial(self):
        """Initial values: prefer GET params (HTMX form re-render) so chart type
        and other fields stay as the user just selected when the modal reloads."""
        report = get_object_or_404(Report, pk=self.kwargs["pk"])
        session_key = f"report_preview_{report.pk}"
        preview_data = self.request.session.get(session_key, {})

        initial = super().get_initial()
        if preview_data:
            initial["chart_type"] = preview_data.get("chart_type", report.chart_type)
            initial["chart_field"] = preview_data.get(
                "chart_field", report.chart_field or ""
            )
            initial["chart_field_stacked"] = preview_data.get(
                "chart_field_stacked", report.chart_field_stacked or ""
            )
            initial["chart_value_field"] = preview_data.get(
                "chart_value_field", report.chart_value_field or ""
            )
        else:
            initial["chart_type"] = report.chart_type
            initial["chart_field"] = report.chart_field or ""
            initial["chart_field_stacked"] = report.chart_field_stacked or ""
            initial["chart_value_field"] = report.chart_value_field or ""

        # HTMX re-render: keep the user’s current selection (e.g. chart type change)
        if self.request.method == "GET":
            for key in (
                "chart_type",
                "chart_field",
                "chart_field_stacked",
                "chart_value_field",
            ):
                val = self.request.GET.get(key)
                if val is not None:
                    initial[key] = val
        return initial

    def form_valid(self, form):
        report = get_object_or_404(Report, pk=self.kwargs["pk"])
        chart_type_value = form.cleaned_data.get("chart_type")
        chart_field_value = form.cleaned_data.get("chart_field")
        chart_field_stacked_value = form.cleaned_data.get("chart_field_stacked")
        chart_value_field_value = form.cleaned_data.get("chart_value_field")

        session_key = f"report_preview_{report.pk}"
        preview_data = self.request.session.get(session_key, {})

        if preview_data:
            preview_data["chart_type"] = chart_type_value
            preview_data["chart_field"] = chart_field_value
            preview_data["chart_field_stacked"] = chart_field_stacked_value
            preview_data["chart_value_field"] = chart_value_field_value
            self.request.session[session_key] = preview_data
            self.request.session.modified = True
        else:
            report.chart_type = chart_type_value
            report.chart_field = chart_field_value
            report.chart_field_stacked = chart_field_stacked_value
            report.chart_value_field = chart_value_field_value
            report.save(
                update_fields=[
                    "chart_type",
                    "chart_field",
                    "chart_field_stacked",
                    "chart_value_field",
                ]
            )

        return ScriptResponse(reload=True, close=True)

    @cached_property
    def form_url(self):
        """Return the form URL for the unified change chart view."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("reports:change_chart_type", kwargs={"pk": pk})
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class ChangeChartFieldView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Deprecated in favour of ChangeChartTypeView (kept for backward compatibility
    but not used in the UI). Submits immediately to reload the report.
    """

    model = Report
    fields = ["chart_type", "chart_field", "chart_field_stacked"]
    modal_height = False
    full_width_fields = ["chart_type", "chart_field", "chart_field_stacked"]

    def form_valid(self, form):
        report = get_object_or_404(Report, pk=self.kwargs["pk"])
        for field in ["chart_type", "chart_field", "chart_field_stacked"]:
            if field in form.cleaned_data:
                setattr(report, field, form.cleaned_data[field])
        report.save(update_fields=["chart_type", "chart_field", "chart_field_stacked"])
        return ScriptResponse(reload=True, close=True)


@method_decorator(htmx_required, name="dispatch")
class CreateReportView(LoginRequiredMixin, HorillaSingleFormView):
    """View for creating new reports with module, columns, and folder selection."""

    model = Report
    modal_height = False
    form_class = ReportForm
    hidden_fields = ["report_owner"]
    full_width_fields = ["name", "module", "folder", "selected_columns"]
    detail_url_name = "reports:report_detail"

    @cached_property
    def form_url(self):
        """Return the form URL for creating a new report."""
        return reverse_lazy("reports:create_report")

    def get_initial(self):
        """Set initial folder from query param and report_owner to current user."""
        initial = super().get_initial()
        pk = self.request.GET.get("pk")
        initial["folder"] = pk if pk else None
        initial["report_owner"] = self.request.user
        return initial

    def form_invalid(self, form):
        module_id = self.request.POST.get("module") or getattr(
            form.instance, "module_id", None
        )
        selected_values = self.request.POST.getlist("selected_columns") or (
            form.instance.selected_columns.split(",")
            if form.instance.selected_columns
            else []
        )
        choices = []
        if module_id:
            try:
                content_type = HorillaContentType.objects.get(id=module_id)
                temp_report = Report(module=content_type)
                fields = temp_report.get_available_fields()
                choices = [
                    (field["name"], f"{field['verbose_name']}") for field in fields
                ]
            except HorillaContentType.DoesNotExist:
                choices = []

        form.fields["selected_columns"].choices = choices
        form.fields["selected_columns"].widget.choices = choices
        if selected_values:
            form.fields["selected_columns"].widget.value = selected_values
        return super().form_invalid(form)


@method_decorator(htmx_required, name="dispatch")
class UpdateReportView(LoginRequiredMixin, HorillaSingleFormView):
    """View for updating report name and basic information."""

    model = Report
    fields = ["name"]
    modal_height = False
    full_width_fields = ["name"]
    detail_url_name = "reports:report_detail"

    @cached_property
    def form_url(self):
        """Return the form URL for updating a report."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("reports:update_report", kwargs={"pk": pk})
        return None

    def get(self, request, *args, **kwargs):
        """Allow GET only if user has change/add permission or is the report owner."""
        report_id = self.kwargs.get("pk")
        if request.user.has_perm("reports.change_report") or request.user.has_perm(
            "reports.add_report"
        ):
            return super().get(request, *args, **kwargs)

        if report_id:
            try:
                report = get_object_or_404(Report, pk=report_id)
            except Http404:
                messages.error(
                    request,
                    f"{self.model._meta.verbose_name} not found or no longer exists.",
                )
                return ScriptResponse(
                    reload=True,
                    close=True,
                )
            if report.report_owner == request.user:
                return super().get(request, *args, **kwargs)

        return render(request, "403.html")


@method_decorator(htmx_required, name="dispatch")
class MoveReportView(LoginRequiredMixin, HorillaSingleFormView):
    """View for moving reports between folders."""

    model = Report
    fields = ["folder"]
    modal_height = False
    full_width_fields = ["folder"]

    @cached_property
    def form_url(self):
        """Return the form URL for moving a report to a folder."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("reports:move_report_to_folder", kwargs={"pk": pk})
        return None

    def get(self, request, *args, **kwargs):
        """Allow GET only if user has change/add permission or is the report owner."""
        report_id = self.kwargs.get("pk")
        if request.user.has_perm("reports.change_report") or request.user.has_perm(
            "reports.add_report"
        ):
            return super().get(request, *args, **kwargs)

        if report_id:
            try:
                report = get_object_or_404(Report, pk=report_id)
            except Http404:
                messages.error(
                    request,
                    f"{self.model._meta.verbose_name} not found or no longer exists.",
                )
                return ScriptResponse(
                    reload=True,
                    close=True,
                )
            if report.report_owner == request.user:
                return super().get(request, *args, **kwargs)

        return render(request, "403.html")

    def get_form(self, form_class=None):
        """Return form with folder widget styling and queryset limited to user's folders for non-superusers."""
        form = super().get_form(form_class)
        user = getattr(self.request, "user", None)
        if user:
            form.fields["folder"].widget.attrs.update(
                {
                    "class": "js-example-basic-single",
                }
            )
            if not user.is_superuser:
                form.fields["folder"].queryset = ReportFolder.objects.filter(
                    report_folder_owner=user
                )
        return form


@method_decorator(htmx_required, name="dispatch")
class MoveFolderView(LoginRequiredMixin, HorillaSingleFormView):
    """View for moving report folders to different parent folders."""

    model = ReportFolder
    fields = ["parent"]
    modal_height = False
    full_width_fields = ["parent"]

    @cached_property
    def form_url(self):
        """Return the form URL for moving a folder to a different parent folder."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("reports:move_folder_to_folder", kwargs={"pk": pk})
        return None

    def get(self, request, *args, **kwargs):
        """Allow GET only if user has change/add permission or is the folder owner."""
        folder_id = self.kwargs.get("pk")
        if request.user.has_perm("reports.change_report") or request.user.has_perm(
            "reports.add_report"
        ):
            return super().get(request, *args, **kwargs)

        if folder_id:
            try:
                folder = get_object_or_404(ReportFolder, pk=folder_id)
            except Http404:
                messages.error(
                    request,
                    f"{self.model._meta.verbose_name} not found or no longer exists.",
                )
                return ScriptResponse(
                    reload=True,
                    close=True,
                )
            if folder.report_folder_owner == request.user:
                return super().get(request, *args, **kwargs)

        return render(request, "403.html")

    def get_form(self, form_class=None):
        """Return form with parent widget styling and queryset limited to user's folders for non-superusers."""
        form = super().get_form(form_class)
        user = getattr(self.request, "user", None)
        if user:
            form.fields["parent"].widget.attrs.update(
                {
                    "class": "js-example-basic-single",
                }
            )
            if not user.is_superuser:
                form.fields["parent"].queryset = ReportFolder.objects.filter(
                    report_folder_owner=user
                )
        return form


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "reports.add_report",
            "reports.add_own_report",
            "reports.change_report",
            "reports.change_own_report",
        ]
    ),
    name="dispatch",
)
class GetModuleColumnsHTMXView(LoginRequiredMixin, View):
    """HTMX view to return updated selected_columns field based on module selection"""

    def get(self, request, *args, **kwargs):
        """Handle GET request to return updated selected_columns widget HTML based on module."""
        module_id = request.GET.get("module")

        widget_html = self.get_columns_widget_html(module_id)

        return HttpResponse(widget_html)

    def get_columns_widget_html(self, module_id):
        """Generate HTML for the select widget with choices based on module"""
        choices = []

        if module_id:
            try:
                content_type = HorillaContentType.objects.get(id=module_id)
                temp_report = Report(module=content_type)
                fields = temp_report.get_available_fields()

                choices = [
                    (field["name"], f"{field['verbose_name']}") for field in fields
                ]
            except HorillaContentType.DoesNotExist:
                choices = []

        widget = forms.SelectMultiple(
            attrs={
                "class": "js-example-basic-multiple headselect w-full",
                "id": "id_columns",
                "name": "selected_columns",
                "tabindex": "-1",
                "aria-hidden": "true",
                "multiple": True,
            }
        )

        field = forms.MultipleChoiceField(
            choices=choices, widget=widget, required=False
        )
        return field.widget.render("selected_columns", None, attrs=widget.attrs)


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class ReportUpdateView(DetailView):
    """View for updating report configuration in a panel interface."""

    model = Report
    template_name = "partials/report_panel.html"
    context_object_name = "report"

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

    def get_context_data(self, **kwargs):
        """Build context with report, preview data, active tab, and available fields for the panel."""
        context = super().get_context_data(**kwargs)
        report = self.object
        model_class = report.model_class

        # Get preview data for panel display
        session_key = f"report_preview_{report.pk}"
        preview_data = self.request.session.get(session_key, {})

        # Get the active tab from request (for maintaining state)
        active_tab = self.request.GET.get("active_tab", "columns")
        context["active_tab"] = active_tab

        temp_report = self.create_temp_report(report, preview_data)
        context["report"] = temp_report
        context["has_unsaved_changes"] = bool(preview_data)
        context["panel_open"] = True

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

        # Grouping/Filter tabs may also pick one level of related-field
        # paths (e.g. "stage__stage_type"); Columns tab stays direct-only.
        available_grouping_fields = [
            {
                "name": info["name"],
                "verbose_name": info["verbose_name"],
                "field_type": info["type"],
            }
            for info in report.get_available_grouping_fields()
        ]

        context["available_fields"] = available_fields
        context["available_grouping_fields"] = available_grouping_fields
        return context

    def create_temp_report(self, original_report, preview_data):
        """Create a temporary report object with preview data."""
        return create_temp_report_with_preview(original_report, preview_data)


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class DiscardReportChangesView(LoginRequiredMixin, View):
    """View for discarding temporary report configuration changes."""

    @method_decorator(require_POST)
    def dispatch(self, *args, **kwargs):
        """Restrict to POST and delegate to parent dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Discard any preview changes for the given report by clearing session data."""
        try:
            report = get_object_or_404(Report, pk=pk)
        except Exception as e:
            messages.error(request, str(e))
            return RefreshResponse(request)

        session_key = f"report_preview_{pk}"

        # Clear the session preview data
        if session_key in request.session:
            del request.session[session_key]

        # Use ReportDetailView to get the full context
        detail_view = ReportDetailView()
        detail_view.request = request
        detail_view.object = report
        context = detail_view.get_context_data()

        # Ensure panel is closed and no unsaved changes
        context["panel_open"] = False
        context["has_unsaved_changes"] = False

        # Render the report_detail.html template with the full context
        return render(request, "report_detail.html", context)


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class SaveReportChangesView(LoginRequiredMixin, View):
    """View for saving temporary report configuration changes."""

    @method_decorator(require_POST)
    def dispatch(self, *args, **kwargs):
        """Restrict to POST and delegate to parent dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Persist preview changes to the Report model when requested."""
        try:
            report = get_object_or_404(Report, pk=pk)
        except Exception as e:
            messages.error(request, str(e))
            return RefreshResponse(request)

        session_key = f"report_preview_{report.pk}"
        preview_data = request.session.get(session_key, {})

        if preview_data:
            # Apply all changes to the actual model
            for field in TEMP_REPORT_FIELDS:
                if field in preview_data:
                    setattr(report, field, preview_data[field])
            report.save()

            # Clear the session preview data
            if session_key in request.session:
                del request.session[session_key]

        # Use ReportDetailView to get the full context
        detail_view = ReportDetailView()
        detail_view.request = request
        detail_view.object = report
        context = detail_view.get_context_data()

        # Ensure panel is closed and no unsaved changes
        context["panel_open"] = False
        context["has_unsaved_changes"] = False

        # Render the report_detail.html template with the full context
        return render(request, "report_detail.html", context)


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class CloseReportPanelView(LoginRequiredMixin, View):
    """View for closing the report configuration panel and returning to detail view."""

    def get(self, request, pk):
        """Close the report panel and redirect to detail view"""
        # Clear any session data if needed
        session_key = f"report_preview_{pk}"
        if session_key in request.session:
            pass

        return redirect("reports:report_detail", pk=pk)
