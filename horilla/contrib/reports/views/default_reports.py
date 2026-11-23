"""HTMX-friendly views to load and create default reports provided by installed apps."""

# Standard library imports
import json
from pathlib import Path

# Third-party imports (Django)
from django.contrib import messages

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.utils.middlewares import get_active_company
from horilla.db.models import Q
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView, View
from horilla.web import ScriptResponse

# Local imports
from ..models import Report, ReportFolder


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("reports.add_report", modal=True),
    name="dispatch",
)
class LoadDefaultReportsModalView(LoginRequiredMixin, TemplateView):
    """Modal view that lists default reports provided by installed apps."""

    template_name = "reports/load_default_reports.html"

    def get_context_data(self, **kwargs):
        """Build context with default reports from all installed apps report files."""
        context = super().get_context_data(**kwargs)

        all_reports = []

        # Iterate through all installed apps
        for app_config in apps.get_app_configs():
            # Check if app has report_files attribute
            if hasattr(app_config, "report_files"):
                report_files = app_config.report_files
                app_path = Path(app_config.path)

                for report_file in report_files:
                    json_path = app_path / report_file

                    if json_path.exists():
                        try:
                            with open(json_path, "r", encoding="utf-8") as f:
                                data = json.load(f)

                                reports = [
                                    {
                                        "name": entry["fields"]["name"],
                                        "folder": entry["fields"].get("folder"),
                                        "module": app_config.verbose_name
                                        or app_config.label,
                                        "app_label": app_config.label,
                                        "source_file": report_file,
                                    }
                                    for entry in data
                                    if entry["model"] == "reports.report"
                                ]
                                all_reports.extend(reports)
                        except Exception as e:
                            print(f"Error loading {json_path}: {e}")

        context["reports"] = all_reports
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("reports.add_report", modal=True),
    name="dispatch",
)
class CreateSelectedDefaultReportsView(LoginRequiredMixin, View):
    """Create Report instances for user-selected default reports discovered in installed apps."""

    def post(self, request, *args, **kwargs):
        """Create selected default reports by reading report JSON files from installed apps and creating Report instances."""
        selected_reports = request.POST.getlist("selected_reports")
        self._folder_cache = {}

        # Collect all data from all apps
        all_data = []

        for app_config in apps.get_app_configs():
            if hasattr(app_config, "report_files"):
                report_files = app_config.report_files
                app_path = Path(app_config.path)

                for report_file in report_files:
                    json_path = app_path / report_file

                    if json_path.exists():
                        try:
                            with open(json_path, "r", encoding="utf-8") as f:
                                data = json.load(f)
                                all_data.extend(data)
                        except Exception as e:
                            print(f"Error loading {json_path}: {e}")

        # Process reports
        all_reports = [
            entry["fields"] for entry in all_data if entry["model"] == "reports.report"
        ]
        folder_lookup = {
            entry["pk"]: entry["fields"]
            for entry in all_data
            if entry["model"] == "reports.reportfolder"
        }
        module_pairs = {
            (module.get("app_label"), module.get("model"))
            for report_data in all_reports
            if report_data["name"] in selected_reports
            and isinstance(module := report_data.get("module"), dict)
            and module.get("app_label")
            and module.get("model")
        }
        module_query = Q()
        for app_label, model_name in module_pairs:
            module_query |= Q(app_label=app_label, model=model_name)
        module_lookup = {
            (content_type.app_label, content_type.model): content_type
            for content_type in HorillaContentType.objects.filter(module_query)
        }

        created_reports = []
        skipped_reports = []

        for report_data in all_reports:
            report_name = report_data["name"]
            if report_name not in selected_reports:
                continue

            # Check if report already exists
            if Report.objects.filter(name=report_name).exists():
                skipped_reports.append(report_name)
                continue

            folder = None
            folder_pk = report_data.get("folder")
            if folder_pk:
                folder_data = folder_lookup.get(folder_pk)
                if folder_data:
                    folder = self._ensure_folder(folder_data, folder_lookup, request)

            # Resolve module dynamically
            module_info = report_data.get("module")
            module_ct = None
            if isinstance(module_info, dict):
                app_label = module_info.get("app_label")
                model_name = module_info.get("model")
                if app_label and model_name:
                    module_ct = module_lookup.get((app_label, model_name))
                    if module_ct is None:
                        print(
                            f"HorillaContentType not found for {app_label}.{model_name}"
                        )
                        continue  # skip if module not installed

            if module_ct:
                Report.objects.create(
                    name=report_name,
                    folder=folder,
                    company=get_active_company(request),
                    created_by=request.user,
                    updated_by=request.user,
                    report_owner=request.user,
                    is_active=True,
                    module=module_ct,
                    selected_columns=report_data.get("selected_columns", ""),
                    row_groups=report_data.get("row_groups", ""),
                    column_groups=report_data.get("column_groups", ""),
                    aggregate_columns=report_data.get("aggregate_columns", ""),
                    filters=report_data.get("filters", ""),
                    chart_type=report_data.get("chart_type", ""),
                    chart_field=report_data.get("chart_field", ""),
                    chart_field_stacked=report_data.get("chart_field_stacked", ""),
                )
                created_reports.append(report_name)

        # Show messages
        if created_reports and skipped_reports:
            message = _(
                "%(created)s report(s) loaded successfully. "
                "%(skipped)s report(s) already exist and were skipped."
            ) % {"created": len(created_reports), "skipped": len(skipped_reports)}
            messages.success(self.request, message)
        elif created_reports:
            messages.success(self.request, _("Reports loaded successfully"))
        elif skipped_reports:
            messages.warning(self.request, _("All selected reports already exist"))
        else:
            messages.info(self.request, _("No reports were processed"))

        return ScriptResponse(reload=True, close=True)

    def _ensure_folder(self, folder_data, folder_lookup, request):
        """Create folder and parent if not exists."""
        folder_name = folder_data["name"]
        if folder_name in self._folder_cache:
            return self._folder_cache[folder_name]

        parent = None
        parent_pk = folder_data.get("parent")

        if parent_pk:
            parent_data = folder_lookup.get(parent_pk)
            if parent_data:
                parent = self._ensure_folder(parent_data, folder_lookup, request)

        folder, _created = ReportFolder.objects.get_or_create(
            name=folder_name,
            defaults={
                "company": get_active_company(request),
                "created_by": request.user,
                "updated_by": request.user,
                "report_folder_owner": request.user,
                "is_active": True,
                "parent": parent,
            },
        )
        self._folder_cache[folder_name] = folder
        return folder
