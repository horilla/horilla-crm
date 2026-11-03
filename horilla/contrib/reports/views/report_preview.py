"""HTMX views for live report preview and configuration changes."""

# Standard library imports
import copy
import json

# Third-party imports (Django)
from django.contrib import messages
from django.views.decorators.http import require_POST

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.core.exceptions import FieldDoesNotExist
from horilla.shortcuts import get_object_or_404, render
from horilla.utils.decorators import method_decorator, permission_required_or_denied
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import RefreshResponse

# Local imports
from ..models import Report
from ..utils import (
    NO_VALUE_OPERATORS,
    get_report_filter_operators,
    get_virtual_field,
    resolve_report_field,
)
from ..views.report_detail import ReportDetailView
from .toolkit.report_helper import (
    TEMP_REPORT_FIELDS,
    ReportPreviewMixin,
    create_temp_report_with_preview,
    render_report_detail_with_preview,
)


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class ToggleAggregateView(LoginRequiredMixin, View):
    """View for toggling aggregate functions on report columns."""

    @method_decorator(require_POST)
    def dispatch(self, *args, **kwargs):
        """Restrict to POST and delegate to parent dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Toggle aggregate column presence for the report preview session."""
        try:
            report = get_object_or_404(Report, pk=pk)
        except Exception as e:
            messages.error(request, str(e))
            return RefreshResponse(request)

        field_name = request.POST.get("field_name")
        session_key = f"report_preview_{report.pk}"

        # Validate the field name exists on the model
        if field_name:
            model_class = report.model_class
            try:
                model_class._meta.get_field(field_name)
            except FieldDoesNotExist:
                messages.error(
                    request,
                    _(
                        "Invalid field '{}'. This field does not exist on the model."
                    ).format(field_name),
                )
                return RefreshResponse(request)

        preview_data = request.session.get(session_key, {})
        current_aggregate = preview_data.get(
            "aggregate_columns", report.aggregate_columns
        )
        try:
            aggregate_list = json.loads(current_aggregate) if current_aggregate else []
            if not isinstance(aggregate_list, list):
                aggregate_list = [aggregate_list] if aggregate_list else []
        except (json.JSONDecodeError, TypeError):
            aggregate_list = []

        # Check how many times this field already appears
        field_count = sum(1 for agg in aggregate_list if agg.get("field") == field_name)

        # Define the aggregation functions in order
        aggfunc_order = ["sum", "avg", "count", "max", "min"]

        if field_count < len(aggfunc_order):
            # Add the next aggregation function for this field
            next_aggfunc = aggfunc_order[field_count]
            aggregate_list.append({"field": field_name, "aggfunc": next_aggfunc})

            preview_data["aggregate_columns"] = json.dumps(aggregate_list)
            request.session[session_key] = preview_data

        return render_report_detail_with_preview(self, request, report, preview_data)

    def create_temp_report(self, original_report, preview_data):
        """Create a temporary report object with preview data applied for ToggleAggregateView."""
        return create_temp_report_with_preview(original_report, preview_data)


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class UpdateAggregateFunctionView(LoginRequiredMixin, View):
    """View for updating aggregate function (SUM, AVG, COUNT, etc.) on report columns."""

    @method_decorator(require_POST)
    def dispatch(self, *args, **kwargs):
        """Restrict to POST and delegate to parent dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Update aggregation function for a field in the report preview session."""
        try:
            report = get_object_or_404(Report, pk=pk)
        except Exception as e:
            messages.error(request, str(e))
            return RefreshResponse(request)
        aggfunc = request.POST.get("aggfunc")
        field_name = request.POST.get("field_name")
        session_key = f"report_preview_{report.pk}"

        preview_data = request.session.get(session_key, {})
        current_aggregate = preview_data.get(
            "aggregate_columns", report.aggregate_columns
        )
        try:
            aggregate_list = json.loads(current_aggregate) if current_aggregate else []
            if not isinstance(aggregate_list, list):
                aggregate_list = [aggregate_list] if aggregate_list else []
        except (json.JSONDecodeError, TypeError):
            aggregate_list = []

        # Update the aggregation function for the specified field
        for agg in aggregate_list:
            if agg.get("field") == field_name:
                agg["aggfunc"] = aggfunc

        preview_data["aggregate_columns"] = json.dumps(aggregate_list)
        request.session[session_key] = preview_data

        return render_report_detail_with_preview(self, request, report, preview_data)

    def create_temp_report(self, original_report, preview_data):
        """Create a temporary report object with preview data applied for UpdateAggregateFunctionView."""
        return create_temp_report_with_preview(original_report, preview_data)


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class AddColumnView(ReportPreviewMixin, LoginRequiredMixin, View):
    """View for adding columns to a report."""

    @method_decorator(require_POST)
    def dispatch(self, *args, **kwargs):
        """Restrict to POST and delegate to parent dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Add a column to the report preview's selected columns list."""
        try:
            report = get_object_or_404(Report, pk=pk)
        except Exception as e:
            messages.error(request, str(e))
            return RefreshResponse(request)

        field_name = request.POST.get("field_name")

        # Validate the field name exists on the model
        if field_name:
            model_class = report.model_class
            virtual_field = get_virtual_field(model_class, field_name)
            try:
                # Virtual fields shown in the detail table are valid columns.
                if virtual_field is None or not virtual_field.show_in_detail:
                    model_class._meta.get_field(field_name)
            except FieldDoesNotExist:
                messages.error(
                    request,
                    _(
                        "Invalid field '{}'. This field does not exist on the model."
                    ).format(field_name),
                )
                return RefreshResponse(request)

        # Get current preview data or start from original
        preview_data = self.get_preview_data(request, report)

        # Add the column if not already present
        preview_data = self.update_comma_list(
            preview_data,
            key="selected_columns",
            original_value=report.selected_columns,
            item=field_name,
            mode="add",
        )
        self.save_preview_data(request, report, preview_data)

        # Rebuild and return the full report content
        return render_report_detail_with_preview(self, request, report, preview_data)

    def create_temp_report(self, original_report, preview_data):
        """Create a temporary report object with preview data applied for AddColumnView."""
        return create_temp_report_with_preview(original_report, preview_data)


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class RemoveColumnView(ReportPreviewMixin, LoginRequiredMixin, View):
    """View for removing columns from a report."""

    @method_decorator(require_POST)
    def dispatch(self, *args, **kwargs):
        """Restrict to POST and delegate to parent dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Remove a column from the report preview's selected columns list."""
        try:
            report = get_object_or_404(Report, pk=pk)
        except Exception as e:
            messages.error(request, str(e))
            return RefreshResponse(request)

        field_name = request.POST.get("field_name")

        # Get current preview data or start from original
        preview_data = self.get_preview_data(request, report)

        # Remove the column if present
        preview_data = self.update_comma_list(
            preview_data,
            key="selected_columns",
            original_value=report.selected_columns,
            item=field_name,
            mode="remove",
        )
        self.save_preview_data(request, report, preview_data)

        # Return the full report content
        return render_report_detail_with_preview(self, request, report, preview_data)

    def create_temp_report(self, original_report, preview_data):
        """Create a temporary copy of the report with preview data applied."""
        return create_temp_report_with_preview(original_report, preview_data)


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class AddFilterFieldView(LoginRequiredMixin, View):
    """View for adding filter fields to a report."""

    @method_decorator(require_POST)
    def dispatch(self, *args, **kwargs):
        """Restrict to POST and delegate to parent dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Handle POST request to add a filter field to the report."""
        try:
            report = get_object_or_404(Report, pk=pk)
        except Exception as e:
            messages.error(request, str(e))
            return RefreshResponse(request)

        field_name = request.POST.get("field_name")
        session_key = f"report_preview_{report.pk}"

        # Validate the field name exists on the model (direct field or one
        # level of related-field traversal, e.g. "stage__stage_type")
        if field_name:
            model_class = report.model_class
            try:
                resolve_report_field(model_class, field_name)
            except FieldDoesNotExist:
                messages.error(
                    request,
                    _(
                        "Invalid field '{}'. This field does not exist on the model."
                    ).format(field_name),
                )
                return RefreshResponse(request)

        # Get current preview data or start from original
        preview_data = request.session.get(session_key, {})

        # Get current filters (from preview or original)
        current_filters = preview_data.get("filters", report.filters)
        try:
            filters_dict = json.loads(current_filters) if current_filters else {}
        except (json.JSONDecodeError, TypeError):
            filters_dict = {}

        # Generate a unique key for the filter
        base_field_name = field_name
        index = 1
        unique_field_name = field_name
        while unique_field_name in filters_dict:
            unique_field_name = f"{base_field_name}_{index}"
            index += 1

        # Add new filter with default logic 'and'
        filters_dict[unique_field_name] = {
            "value": "",
            "operator": get_report_filter_operators(
                report.model_class, base_field_name
            )[0][0],
            "logic": "and",
            "original_field": base_field_name,
        }

        preview_data["filters"] = json.dumps(filters_dict)
        request.session[session_key] = preview_data

        # Determine if the field is a choice field or foreign key and get its options
        is_choice_or_fk = report.is_choice_or_foreign_key_field(field_name)
        field_choices = report.get_field_choices(field_name) if is_choice_or_fk else []

        # Create temp report for context
        temp_report = self.create_temp_report(report, preview_data)

        # Generate available fields, including one level of related-field
        # traversal (e.g. "stage__stage_type") for the filter/grouping pickers.
        # The Columns tab keeps using direct-fields-only (get_available_fields).
        available_grouping_fields = [
            {
                "name": info["name"],
                "verbose_name": info["verbose_name"],
                "field_type": info["type"],
            }
            for info in report.get_available_grouping_fields()
        ]
        available_fields = [
            {
                "name": info["name"],
                "verbose_name": info["verbose_name"],
                "field_type": info["type"],
            }
            for info in report.get_available_fields()
        ]

        # Render the entire panel template with updated context
        return render(
            request,
            "partials/report_panel.html",
            {
                "report": temp_report,
                "available_fields": available_fields,
                "available_grouping_fields": available_grouping_fields,
                "has_unsaved_changes": True,
                "is_choice_or_fk": is_choice_or_fk,
                "field_choices": field_choices,
            },
        )

    def create_temp_report(self, original_report, preview_data):
        """Create a temporary report object with preview data applied for AddFilterFieldView."""
        temp_report = copy.copy(original_report)
        for field in TEMP_REPORT_FIELDS:
            if field in preview_data:
                setattr(temp_report, field, preview_data[field])
        return temp_report


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class UpdateFilterOperatorView(View):
    """View for updating the operator (equals, contains, etc.) for a report filter."""

    @method_decorator(require_POST)
    def dispatch(self, *args, **kwargs):
        """Restrict to POST and delegate to parent dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Handle POST request to update filter operator for a report filter."""
        try:
            report = get_object_or_404(Report, pk=pk)
        except Exception as e:
            messages.error(request, str(e))
            return RefreshResponse(request)
        field_name = request.POST.get("field_name")
        operator = request.POST.get("operator")
        session_key = f"report_preview_{report.pk}"

        # Get current preview data or start from original
        preview_data = request.session.get(session_key, {})

        # Get current filters (from preview or original)
        current_filters = preview_data.get("filters", report.filters)
        try:
            filters_dict = json.loads(current_filters) if current_filters else {}
        except (json.JSONDecodeError, TypeError):
            filters_dict = {}

        # Update operator and preserve or set default logic
        if field_name in filters_dict:
            if isinstance(filters_dict[field_name], dict):
                if filters_dict[field_name].get("operator") != operator:
                    filters_dict[field_name]["value"] = ""
                filters_dict[field_name]["operator"] = operator
                filters_dict[field_name].setdefault(
                    "logic", "and"
                )  # Preserve or set default logic
            else:
                filters_dict[field_name] = {
                    "value": str(filters_dict[field_name]),
                    "operator": operator,
                    "logic": "and",
                }
        else:
            filters_dict[field_name] = {
                "value": "",
                "operator": operator,
                "logic": "and",
            }

        preview_data["filters"] = json.dumps(filters_dict)
        request.session[session_key] = preview_data

        try:
            response = render_report_detail_with_preview(
                self, request, report, preview_data
            )
        except (ValueError, TypeError) as e:
            # Invalid filter value for field type
            preview_data.pop("filters", None)
            if preview_data:
                request.session[session_key] = preview_data
            else:
                request.session.pop(session_key, None)
            messages.error(request, _("Invalid filter value: {}").format(str(e)))
            return RefreshResponse(request)

        return response

    def create_temp_report(self, original_report, preview_data):
        """Create a temporary copy of the report with preview data applied.

        Args:
            original_report: The original report instance to copy.
            preview_data: Dictionary containing preview configuration data including chart settings.

        Returns:
            A copy of the original report with preview data applied.
        """
        temp_report = copy.copy(original_report)
        for field in TEMP_REPORT_FIELDS:
            if field in preview_data:
                setattr(temp_report, field, preview_data[field])
        return temp_report

    def get_available_fields(self, model_class):
        """Get available fields from the model class for filter/group selection."""
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
        return available_fields


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class ApplyFiltersView(LoginRequiredMixin, View):
    """Replace the report's filters with the rows of the filter panel (Apply)."""

    @method_decorator(require_POST)
    def dispatch(self, *args, **kwargs):
        """Restrict to POST and delegate to parent dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Rebuild the filters from the submitted rows, then re-render the report."""
        report = get_object_or_404(Report, pk=pk)
        session_key = f"report_preview_{report.pk}"
        preview_data = request.session.get(session_key, {})
        current_filters = preview_data.get("filters", report.filters)
        try:
            old_filters = json.loads(current_filters) if current_filters else {}
        except (json.JSONDecodeError, TypeError):
            old_filters = {}

        new_filters = {}
        if not request.POST.get("clear_all"):
            for key in request.POST.getlist("filter_key"):
                old = (
                    old_filters.get(key)
                    if isinstance(old_filters.get(key), dict)
                    else {}
                )
                field = request.POST.get(f"field__{key}") or old.get("original_field")
                if not field:
                    continue
                try:
                    resolve_report_field(report.model_class, field)
                except Exception:  # unknown field: skip the row
                    continue
                operator = request.POST.get(f"operator__{key}") or "exact"
                if operator == "between":
                    start = request.POST.get(f"start__{key}", "").strip()
                    end = request.POST.get(f"end__{key}", "").strip()
                    value = f"{start},{end}" if (start or end) else ""
                elif operator in NO_VALUE_OPERATORS:
                    # No value is needed; a marker keeps the row active
                    value = "1"
                else:
                    values = [
                        v for v in request.POST.getlist(f"value__{key}") if v != ""
                    ]
                    value = ",".join(values)
                if not value:
                    continue  # an unfilled row contributes nothing
                unique_key, index = field, 1
                while unique_key in new_filters:
                    unique_key = f"{field}_{index}"
                    index += 1
                new_filters[unique_key] = {
                    "value": value,
                    "operator": operator,
                    "logic": request.POST.get(f"logic__{key}") or "and",
                    "original_field": field,
                }

        preview_data["filters"] = json.dumps(new_filters)
        request.session[session_key] = preview_data
        try:
            return render_report_detail_with_preview(
                self, request, report, preview_data
            )
        except (ValueError, TypeError) as e:
            messages.error(request, _("Invalid filter value: {}").format(str(e)))
            return RefreshResponse(request)

    def create_temp_report(self, original_report, preview_data):
        """Return a copy of the report with the preview data applied."""
        return create_temp_report_with_preview(original_report, preview_data)


class ReportFilterRowView(LoginRequiredMixin, View):
    """Return one blank filter row ("Add more filter") for the filter panel."""

    def get(self, request, pk):
        """Render an empty row with the given client-generated key."""
        report = get_object_or_404(Report, pk=pk)
        row_key = "".join(
            c for c in request.GET.get("row_key", "n0") if c.isalnum() or c == "_"
        )
        return render(
            request,
            "partials/report_filter_row.html",
            {
                "report": report,
                "row_key": row_key or "n0",
                "field": "",
                "op": "exact",
                "value": "",
                "is_first": False,
                "grouping_fields": report.get_available_grouping_fields(),
            },
        )


class ReportFilterRowBodyView(LoginRequiredMixin, View):
    """Return the operator and value cells of a row after its field changes."""

    def get(self, request, pk):
        """Render operator/value widgets for the field picked in a row."""
        report = get_object_or_404(Report, pk=pk)
        row_key = "".join(
            c for c in request.GET.get("row_key", "n0") if c.isalnum() or c == "_"
        )
        field = request.GET.get(f"field__{row_key}", "")
        operators = (
            get_report_filter_operators(report.model_class, field) if field else []
        )
        return render(
            request,
            "partials/report_filter_row_body.html",
            {
                "report": report,
                "row_key": row_key,
                "field": field,
                "op": operators[0][0] if operators else "exact",
                "value": "",
            },
        )


class UpdateFilterValueView(LoginRequiredMixin, View):
    """View for updating the value of a report filter."""

    @method_decorator(require_POST)
    def dispatch(self, *args, **kwargs):
        """Restrict to POST and delegate to parent dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Handle POST request to update filter value for a report filter."""
        try:
            report = get_object_or_404(Report, pk=pk)
        except Exception as e:
            messages.error(request, str(e))
            return RefreshResponse(request)

        field_name = request.POST.get("field_name")
        # A multi-select posts several "value" params; store them comma-joined
        # (the operator stays "Equals", as in the list filter panel).
        values = [v for v in request.POST.getlist("value") if v != ""]
        value = ",".join(values) if len(values) > 1 else request.POST.get("value")
        # "Between" posts a start and an end value; store them as "start,end"
        end_value = request.POST.get("end_value")
        if end_value is not None:
            value = f"{request.POST.get('value', '')},{end_value}"
        session_key = f"report_preview_{report.pk}"

        # Get current preview data or start from original
        preview_data = request.session.get(session_key, {})

        # Get current filters (from preview or original)
        current_filters = preview_data.get("filters", report.filters)
        try:
            filters_dict = json.loads(current_filters) if current_filters else {}
        except (json.JSONDecodeError, TypeError):
            filters_dict = {}

        # Update value and preserve or set default logic
        if field_name in filters_dict:
            if isinstance(filters_dict[field_name], dict):
                filters_dict[field_name]["value"] = value
                filters_dict[field_name].setdefault(
                    "logic", "and"
                )  # Preserve or set default logic
            else:
                filters_dict[field_name] = {
                    "value": value,
                    "operator": "exact",
                    "logic": "and",
                }
        else:
            filters_dict[field_name] = {
                "value": value,
                "operator": "exact",
                "logic": "and",
            }

        preview_data["filters"] = json.dumps(filters_dict)
        request.session[session_key] = preview_data

        try:
            response = render_report_detail_with_preview(
                self, request, report, preview_data
            )
        except (ValueError, TypeError) as e:
            # Invalid filter value for field type (e.g., text in numeric field)
            # Revert the filter change from session
            preview_data.pop("filters", None)
            if preview_data:
                request.session[session_key] = preview_data
            else:
                request.session.pop(session_key, None)
            messages.error(request, _("Invalid filter value: {}").format(str(e)))
            return RefreshResponse(request)

        return response

    def create_temp_report(self, original_report, preview_data):
        """Create a temporary copy of the report with preview data applied.

        Args:
            original_report: The original report instance to copy.
            preview_data: Dictionary containing preview configuration data including chart settings.

        Returns:
            A copy of the original report with preview data applied.
        """
        temp_report = copy.copy(original_report)
        for field in TEMP_REPORT_FIELDS:
            if field in preview_data:
                setattr(temp_report, field, preview_data[field])
        return temp_report

    def get_available_fields(self, model_class):
        """Get available fields from the model class for filter/group selection."""
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
        return available_fields


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class UpdateFilterLogicView(LoginRequiredMixin, View):
    """View for updating the logic operator (AND/OR) between report filters."""

    @method_decorator(require_POST)
    def dispatch(self, *args, **kwargs):
        """Restrict to POST and delegate to parent dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Handle POST request to update filter logic (AND/OR) between report filters."""
        try:
            report = get_object_or_404(Report, pk=pk)
        except Exception as e:
            messages.error(request, str(e))
            return RefreshResponse(request)
        field_name = request.POST.get(
            "field_name"
        )  # This is the unique field name (e.g., field_name_1)
        logic = request.POST.get("logic")
        session_key = f"report_preview_{report.pk}"

        # Get current preview data or start from original
        preview_data = request.session.get(session_key, {})

        # Get current filters (from preview or original)
        current_filters = preview_data.get("filters", report.filters)
        try:
            filters_dict = json.loads(current_filters) if current_filters else {}
        except (json.JSONDecodeError, TypeError):
            filters_dict = {}

        # Update the logic for the specific filter
        if field_name in filters_dict:
            filters_dict[field_name]["logic"] = logic

        preview_data["filters"] = json.dumps(filters_dict)
        request.session[session_key] = preview_data

        temp_report = self.create_temp_report(report, preview_data)
        detail_view = ReportDetailView()
        detail_view.request = self.request
        detail_view.object = temp_report
        detail_view.kwargs = {"pk": report.pk}

        try:
            context = detail_view.get_context_data()
        except (ValueError, TypeError) as e:
            # Invalid filter value for field type
            preview_data.pop("filters", None)
            if preview_data:
                request.session[session_key] = preview_data
            else:
                request.session.pop(session_key, None)
            messages.error(request, _("Invalid filter value: {}").format(str(e)))
            return RefreshResponse(request)

        return render(request, "report_detail.html", context)

    def create_temp_report(self, original_report, preview_data):
        """Create a temporary report object with preview data applied for UpdateFilterLogicView."""
        temp_report = copy.copy(original_report)
        for field in TEMP_REPORT_FIELDS:
            if field in preview_data:
                setattr(temp_report, field, preview_data[field])
        return temp_report


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class RemoveFilterView(LoginRequiredMixin, View):
    """View for removing filters from a report."""

    @method_decorator(require_POST)
    def dispatch(self, *args, **kwargs):
        """Restrict to POST and delegate to parent dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Handle POST request to remove a filter from the report."""
        try:
            report = get_object_or_404(Report, pk=pk)
        except Exception as e:
            messages.error(request, str(e))
            return RefreshResponse(request)
        field_name = request.POST.get("field_name")
        session_key = f"report_preview_{report.pk}"

        preview_data = request.session.get(session_key, {})
        current_filters = preview_data.get("filters", report.filters)
        try:
            filters_dict = json.loads(current_filters) if current_filters else {}
        except (json.JSONDecodeError, TypeError):
            filters_dict = {}

        if field_name in filters_dict:
            del filters_dict[field_name]

        preview_data["filters"] = json.dumps(filters_dict)
        request.session[session_key] = preview_data

        return render_report_detail_with_preview(self, request, report, preview_data)

    def create_temp_report(self, original_report, preview_data):
        """Create a temporary copy of the report with preview data applied.

        Args:
            original_report: The original report instance to copy.
            preview_data: Dictionary containing preview configuration data including chart settings.

        Returns:
            A copy of the original report with preview data applied.
        """
        temp_report = copy.copy(original_report)
        for field in TEMP_REPORT_FIELDS:
            if field in preview_data:
                setattr(temp_report, field, preview_data[field])
        return temp_report

    def get_available_fields(self, model_class):
        """Get available fields from the model class for filter/group selection."""
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
        return available_fields


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class ToggleRowGroupView(ReportPreviewMixin, LoginRequiredMixin, View):
    """View for toggling row grouping on/off for a report."""

    @method_decorator(require_POST)
    def dispatch(self, *args, **kwargs):
        """Restrict to POST and delegate to parent dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Handle POST request to toggle row grouping on/off for a report."""
        try:
            report = get_object_or_404(Report, pk=pk)
        except Exception as e:
            messages.error(request, str(e))
            return RefreshResponse(request)
        field_name = request.POST.get("field_name")

        # Validate the field name exists on the model (direct field or one
        # level of related-field traversal, e.g. "stage__stage_type")
        if field_name:
            model_class = report.model_class
            try:
                resolve_report_field(model_class, field_name)
            except FieldDoesNotExist:
                messages.error(
                    request,
                    _(
                        "Invalid field '{}'. This field does not exist on the model."
                    ).format(field_name),
                )
                return RefreshResponse(request)

        # Get current preview data or start from original
        preview_data = self.get_preview_data(request, report)

        # Toggle the row group field
        preview_data = self.update_comma_list(
            preview_data,
            key="row_groups",
            original_value=report.row_groups,
            item=field_name,
            mode="toggle",
        )
        self.save_preview_data(request, report, preview_data)

        return render_report_detail_with_preview(self, request, report, preview_data)

    def create_temp_report(self, original_report, preview_data):
        """Create a temporary report object with preview data applied for ToggleRowGroupView."""
        return create_temp_report_with_preview(original_report, preview_data)


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class RemoveRowGroupView(ReportPreviewMixin, LoginRequiredMixin, View):
    """View for removing row grouping from a report."""

    @method_decorator(require_POST)
    def dispatch(self, *args, **kwargs):
        """Restrict to POST and delegate to parent dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Handle POST request to remove a field from row grouping."""
        try:
            report = get_object_or_404(Report, pk=pk)
        except Exception as e:
            messages.error(request, str(e))
            return RefreshResponse(request)
        field_name = request.POST.get("field_name")

        # Get current preview data or start from original
        preview_data = self.get_preview_data(request, report)

        # Remove the row group field if present
        preview_data = self.update_comma_list(
            preview_data,
            key="row_groups",
            original_value=report.row_groups,
            item=field_name,
            mode="remove",
        )
        self.save_preview_data(request, report, preview_data)

        # Rebuild and return the full report content
        return render_report_detail_with_preview(self, request, report, preview_data)

    def create_temp_report(self, original_report, preview_data):
        """Create a temporary report object with preview data applied for RemoveRowGroupView."""
        return create_temp_report_with_preview(original_report, preview_data)


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class ToggleColumnGroupView(ReportPreviewMixin, LoginRequiredMixin, View):
    """View for toggling column grouping on/off for a report."""

    @method_decorator(require_POST)
    def dispatch(self, *args, **kwargs):
        """Restrict to POST and delegate to parent dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Handle POST request to toggle column grouping for a field in the report.

        Args:
            request: The HTTP request object.
            pk: Primary key of the report.

        Returns:
            Rendered report detail template with updated column grouping.
        """
        try:
            report = get_object_or_404(Report, pk=pk)
        except Exception as e:
            messages.error(request, str(e))
            return RefreshResponse(request)
        field_name = request.POST.get("field_name")

        # Validate the field name exists on the model (direct field or one
        # level of related-field traversal, e.g. "stage__stage_type")
        if field_name:
            model_class = report.model_class
            try:
                resolve_report_field(model_class, field_name)
            except FieldDoesNotExist:
                messages.error(
                    request,
                    _(
                        "Invalid field '{}'. This field does not exist on the model."
                    ).format(field_name),
                )
                return RefreshResponse(request)

        preview_data = self.get_preview_data(request, report)

        # Toggle the column group field
        preview_data = self.update_comma_list(
            preview_data,
            key="column_groups",
            original_value=report.column_groups,
            item=field_name,
            mode="toggle",
        )
        self.save_preview_data(request, report, preview_data)

        return render_report_detail_with_preview(self, request, report, preview_data)

    def create_temp_report(self, original_report, preview_data):
        """Create a temporary report object with preview data applied for ToggleColumnGroupView."""
        return create_temp_report_with_preview(original_report, preview_data)


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class RemoveColumnGroupView(ReportPreviewMixin, LoginRequiredMixin, View):
    """View for removing column grouping from a report."""

    @method_decorator(require_POST)
    def dispatch(self, *args, **kwargs):
        """Restrict to POST and delegate to parent dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Handle POST request to remove a field from column grouping."""
        try:
            report = get_object_or_404(Report, pk=pk)
        except Exception as e:
            messages.error(request, str(e))
            return RefreshResponse(request)

        field_name = request.POST.get("field_name")

        preview_data = self.get_preview_data(request, report)

        # Remove the column group field if present
        preview_data = self.update_comma_list(
            preview_data,
            key="column_groups",
            original_value=report.column_groups,
            item=field_name,
            mode="remove",
        )
        self.save_preview_data(request, report, preview_data)

        return render_report_detail_with_preview(self, request, report, preview_data)

    def create_temp_report(self, original_report, preview_data):
        """Create a temporary copy of the report with preview data applied."""
        return create_temp_report_with_preview(original_report, preview_data)


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class RemoveAggregateColumnView(LoginRequiredMixin, View):
    """View for removing aggregate columns from a report."""

    @method_decorator(require_POST)
    def dispatch(self, *args, **kwargs):
        """Restrict to POST and delegate to parent dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Handle POST request to remove an aggregate column from the report."""
        try:
            report = get_object_or_404(Report, pk=pk)
        except Exception as e:
            messages.error(request, str(e))
            return RefreshResponse(request)

        field_name = request.POST.get("field_name")
        session_key = f"report_preview_{report.pk}"
        preview_data = request.session.get(session_key, {})
        current_aggregate_columns = preview_data.get(
            "aggregate_columns", report.aggregate_columns
        )
        try:
            aggregate_list = (
                json.loads(current_aggregate_columns)
                if current_aggregate_columns
                else []
            )
            if not isinstance(aggregate_list, list):
                aggregate_list = [aggregate_list] if aggregate_list else []
        except (json.JSONDecodeError, TypeError):
            aggregate_list = []

        aggregate_list = [
            agg for agg in aggregate_list if agg.get("field") != field_name
        ]
        preview_data["aggregate_columns"] = json.dumps(aggregate_list)
        request.session[session_key] = preview_data
        request.session.modified = True

        return render_report_detail_with_preview(self, request, report, preview_data)

    def create_temp_report(self, original_report, preview_data):
        """Create a temporary report object with preview data applied for RemoveAggregateColumnView."""

        temp_report = copy.copy(original_report)

        for field in TEMP_REPORT_FIELDS:
            if field in preview_data:
                setattr(temp_report, field, preview_data[field])

        return temp_report
