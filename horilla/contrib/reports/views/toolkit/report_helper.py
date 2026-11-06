"""Shared toolkit helpers for report preview rendering."""

# Standard library imports
import copy

# Third-party imports (Django)
from django.core.exceptions import PermissionDenied

# First party imports (Horilla)
from horilla.shortcuts import get_object_or_404, render
from horilla.utils.translation import gettext_lazy as _

# Local imports
from ...models import Report

# Permissions that allow a user to export a report definition's data
REPORT_EXPORT_PERMS = (
    "reports.export_report",
    "reports.export_own_report",
)

# Fields used for creating temporary report objects with preview data
TEMP_REPORT_FIELDS = (
    "selected_columns",
    "row_groups",
    "column_groups",
    "aggregate_columns",
    "filters",
    "chart_type",
    "chart_field",
    "chart_field_stacked",
    "chart_value_field",
)


def user_can_access_report(user, report):
    """A report definition is open to its owner or to users with view_report."""
    return report.report_owner_id == user.pk or user.has_perm("reports.view_report")


def user_can_export_report(user, model_class):
    """
    Whether the export actions should be offered: the user may export reports
    (export_ or export_own_report) and, for models with export
    permissions, holds export_ or export_own_ on the report's model.
    """
    # Local import to avoid circular import during app initialization
    from horilla.registry.feature import FEATURE_REGISTRY

    if not user.has_any_perms(REPORT_EXPORT_PERMS):
        return False
    if model_class not in FEATURE_REGISTRY.get("export_models", []):
        return True
    app_label = model_class._meta.app_label
    model_name = model_class._meta.model_name
    return user.is_superuser or any(
        user.has_perm(f"{app_label}.{prefix}_{model_name}")
        for prefix in ("export", "export_own")
    )


def limit_reports_to_viewable_modules(queryset, user):
    """Keep only reports whose module the user may view (view_ or view_own_)."""
    # Local import to avoid circular import during app initialization
    from horilla.contrib.core.models import HorillaContentType

    module_ids = Report.objects.values_list("module_id", flat=True).distinct()
    allowed_ids = [
        content_type.pk
        for content_type in HorillaContentType.objects.filter(pk__in=module_ids)
        if user.has_perm(f"{content_type.app_label}.view_{content_type.model}")
        or user.has_perm(f"{content_type.app_label}.view_own_{content_type.model}")
    ]
    return queryset.filter(module_id__in=allowed_ids)


def get_accessible_report_or_404(request, pk):
    """Load a report, raising PermissionDenied unless the user owns it or has view_report."""
    report = get_object_or_404(Report, pk=pk)
    if not user_can_access_report(request.user, report):
        raise PermissionDenied
    return report


def render_report_detail_with_preview(view, request, report, preview_data):
    """Helper to rebuild the report detail view with a temporary report."""
    # Local import to avoid circular import during app initialization
    # Local imports
    from ..report_detail import ReportDetailView

    temp_report = view.create_temp_report(report, preview_data)
    detail_view = ReportDetailView()
    detail_view.request = view.request
    detail_view.object = temp_report
    detail_view.kwargs = {"pk": report.pk}
    context = detail_view.get_context_data()
    return render(request, "report_detail.html", context)


def create_temp_report_with_preview(original_report, preview_data):
    """Create a temporary Report instance with preview data applied."""
    temp_report = copy.copy(original_report)
    for field in TEMP_REPORT_FIELDS:
        if field in preview_data:
            setattr(temp_report, field, preview_data[field])
    return temp_report


class ReportPreviewMixin:
    """Shared helpers for report preview session handling."""

    def get_session_key(self, report):
        """to get the session key"""
        return f"report_preview_{report.pk}"

    def get_preview_data(self, request, report):
        """Function to get the preview data"""
        session_key = self.get_session_key(report)
        return request.session.get(session_key, {})

    def save_preview_data(self, request, report, preview_data):
        """Function to save the preview data"""
        session_key = self.get_session_key(report)
        request.session[session_key] = preview_data
        request.session.modified = True

    def update_comma_list(self, preview_data, key, original_value, item, mode="toggle"):
        """
        Update a comma-separated list field in preview_data.

        mode:
            - "toggle": add if missing, remove if present
            - "add": add if missing (no removal)
            - "remove": remove if present
        """
        if not item:
            return preview_data

        current = preview_data.get(key, original_value)
        items = [v.strip() for v in current.split(",") if v.strip()] if current else []

        if mode == "toggle":
            if item in items:
                items.remove(item)
            else:
                items.append(item)
        elif mode == "add":
            if item not in items:
                items.append(item)
        elif mode == "remove":
            if item in items:
                items.remove(item)

        preview_data[key] = ",".join(items)
        return preview_data


def should_skip_pivot_key(key_or_value):
    """
    Return True if a pivot key/value represents an ID-only entry that should be hidden.
    Examples: "|4", "| 5", "|123" are treated as technical IDs and skipped.
    """
    if not key_or_value:
        return False

    key_str = str(key_or_value).strip()

    if key_str.startswith("|"):
        rest = key_str[1:].strip()
        if rest.isdigit():
            return True

    if "|" in key_str:
        parts = key_str.split("|")
        if len(parts) == 2 and parts[0] == "" and parts[1].strip().isdigit():
            return True

    return False


def extract_display_value(key_or_value):
    """
    Extract the human-readable display value from composite keys like "Label||ID".
    Fallbacks to a generic "Unspecified (-)" when the value is empty.
    """
    if not key_or_value:
        return str(_("Unspecified (-)"))

    key_str = str(key_or_value)

    if "||" in key_str:
        return key_str.split("||")[0]

    return key_str


def filter_pivot_data(pivot_table, pivot_index, pivot_columns):
    """
    Filter out ID-only keys from pivot table data.
    Returns cleaned (pivot_table, pivot_index, pivot_columns).
    """
    filtered_index = []
    for key in pivot_index:
        if not should_skip_pivot_key(key):
            filtered_index.append(key)

    filtered_columns = []
    for key in pivot_columns:
        if not should_skip_pivot_key(key):
            filtered_columns.append(key)

    filtered_table = {}
    for row_key in filtered_index:
        if row_key in pivot_table:
            filtered_table[row_key] = {}
            for col_key in filtered_columns:
                if col_key in pivot_table[row_key]:
                    filtered_table[row_key][col_key] = pivot_table[row_key][col_key]

    return filtered_table, filtered_index, filtered_columns
