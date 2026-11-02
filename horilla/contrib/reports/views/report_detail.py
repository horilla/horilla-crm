"""Views for displaying interactive report details and pivots."""

# Standard library imports
import json
import logging
from urllib.parse import urlencode, urlparse

# Third-party imports (Others)
# Third-party imports (Django)
import pandas as pd
from django.contrib import messages
from django.utils.encoding import force_str

# First party imports (Horilla)
from horilla.auth.mixins import login_redirect
from horilla.contrib.generics.mixins import RecentlyViewedMixin
from horilla.contrib.generics.views import HorillaListView
from horilla.contrib.utils.methods import get_section_info_for_model
from horilla.db.models import ForeignKey
from horilla.shortcuts import render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import method_decorator, permission_required_or_denied
from horilla.utils.functional import Promise
from horilla.views.generic import DetailView
from horilla.web import HttpNotFound, HttpResponse, RefreshResponse

# Local imports
from ..models import Report
from ..utils import (
    NO_VALUE_OPERATORS,
    annotate_virtual_fields,
    build_report_filter_q,
    coerce_virtual_filter_value,
    get_virtual_field,
    is_duration_virtual_field,
    resolve_report_field,
)
from ..views.toolkit.report_detail_mixin import ReportDetailDataMixin

logger = logging.getLogger(__name__)


@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class ReportDetailView(ReportDetailDataMixin, RecentlyViewedMixin, DetailView):
    """Detail view for displaying individual report with data and configuration."""

    model = Report
    template_name = "report_detail.html"
    context_object_name = "report"

    def dispatch(self, request, *args, **kwargs):
        """Ensure the user is authenticated and the object exists; handle HTMX errors gracefully."""
        if not request.user.is_authenticated:
            return login_redirect(request)
        try:
            self.object = self.get_object()
        except Exception as e:
            if request.headers.get("HX-Request") == "true":
                messages.error(self.request, e)
                return RefreshResponse(request)
            raise HttpNotFound(e) from e

        temp_report = self.create_temp_report(
            self.object,
            request.session.get(f"report_preview_{self.object.pk}", {}),
        )
        if temp_report.model_class is None:
            self.object.delete()
            messages.error(
                request,
                str(
                    "Module not found: the model linked to this report no longer exists. The report has been deleted."
                ),
            )
            list_url = str(reverse_lazy("reports:reports_list_view"))
            if request.headers.get("HX-Request") == "true":
                resp = HttpResponse()
                resp["HX-Redirect"] = list_url
                return resp
            return HttpResponse(
                f'<html><body><script>window.location.replace("{list_url}");</script></body></html>'
            )

        return super().dispatch(request, *args, **kwargs)

    def col_attrs(self):
        """Define column attributes for clickable rows in the report list view."""
        query_params = {}
        report = self.object
        model_class = report.model_class
        section = get_section_info_for_model(model_class)
        section_value = section["section"]
        query_params["section"] = section_value
        query_params["session_url"] = False
        query_string = urlencode(query_params)
        attrs = {}

        if self.request.user.has_perm("reports.view_report"):
            attrs = {
                "hx-get": f"{{get_detail_url}}?{query_string}",
                "hx-target": "#mainContent",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "hx-select-oob": "#sideMenuContainer",
                "hx-select": "#mainContent",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }

        columns_with_attrs = []

        for col in report.selected_columns_list:
            columns_with_attrs.append({col: {**attrs}})

        return columns_with_attrs

    def get(self, request, *args, **kwargs):
        """Return the report detail if the user has permission to view it; otherwise render 403."""
        self.object = self.get_object()
        if not self.model.objects.filter(
            report_owner_id=self.request.user, pk=self.kwargs["pk"]
        ).first() and not self.request.user.has_perm("reports.view_report"):
            return render(self.request, "403.html")

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Build the context data for the report detail view including preview and aggregate info."""
        context = super().get_context_data(**kwargs)
        report = self.object

        session_key = f"report_preview_{report.pk}"
        preview_data = self.request.session.get(session_key, {})

        temp_report = self.create_temp_report(report, preview_data)

        aggregate_columns_dict = temp_report.aggregate_columns_dict
        if not isinstance(aggregate_columns_dict, list):
            aggregate_columns_dict = (
                [aggregate_columns_dict] if aggregate_columns_dict else []
            )

        # Get model data
        model_class = temp_report.model_class

        fields = []
        if temp_report.selected_columns_list:
            fields.extend(temp_report.selected_columns_list)
        if temp_report.row_groups_list:
            fields.extend(temp_report.row_groups_list)
        if temp_report.column_groups_list:
            fields.extend(temp_report.column_groups_list)
        for agg in aggregate_columns_dict:
            if agg.get("field"):
                fields.append(agg["field"])

        # Ensure selected Y-axis (value) field is present in the DataFrame so
        # chart_value_field can be aggregated instead of just counts.
        raw_value = getattr(temp_report, "chart_value_field", None)
        value_field = None
        if raw_value:
            if "__" in raw_value:
                # New style: "metric__fieldname"
                _, f = raw_value.split("__", 1)
                value_field = f
            else:
                # Backward compatibility: plain field name
                value_field = raw_value
        if value_field:
            fields.append(value_field)

        # Remove duplicates while preserving order
        fields = list(dict.fromkeys(fields))

        # Optimize: Create base queryset with select_related for foreign keys
        # This reduces N+1 queries significantly
        base_queryset = model_class.objects.all()

        # Annotate any virtual (computed, e.g. "days_open") fields referenced
        # by columns/groups/aggregates or filters, before filtering/values().
        filter_field_names = [
            filter_data.get("original_field", field_name)
            for field_name, filter_data in temp_report.filters_dict.items()
        ]
        base_queryset = annotate_virtual_fields(
            base_queryset, model_class, fields + filter_field_names
        )

        # Optimize: Add select_related/prefetch_related for foreign key fields
        select_related_fields = []
        for field_name in fields:
            try:
                field = resolve_report_field(model_class, field_name)
                if isinstance(field, ForeignKey):
                    select_related_fields.append(field_name)
                elif "__" in field_name:
                    select_related_fields.append(field_name.split("__", 1)[0])
            except Exception:
                pass

        if select_related_fields:
            # Remove duplicates from select_related_fields
            select_related_fields = list(dict.fromkeys(select_related_fields))
            base_queryset = base_queryset.select_related(*select_related_fields)

        # Apply filters
        filters = temp_report.filters_dict
        if filters:
            query = None
            for index, (field_name, filter_data) in enumerate(filters.items()):
                if (
                    not filter_data.get("value")
                    and filter_data.get("operator") not in NO_VALUE_OPERATORS
                ):
                    continue  # Skip empty filters
                operator = filter_data.get("operator", "exact")
                value = filter_data.get("value")
                logic = (
                    filter_data.get("logic", "and") if index > 0 else "and"
                )  # Default to AND for first filter

                # Use original_field instead of field_name
                actual_field = filter_data.get("original_field", field_name)

                # Virtual duration fields (e.g. "days_open") are stored as
                # timedelta at the DB level — the filter UI only ever
                # collects a plain number of days, so convert it here.
                value = coerce_virtual_filter_value(model_class, actual_field, value)

                built_query = build_report_filter_q(
                    model_class, actual_field, operator, value
                )
                # Combine filters with AND or OR
                if built_query is None:
                    continue
                current_query = built_query

                if query is None:
                    query = current_query
                elif logic == "or":
                    query |= current_query
                else:  # logic == 'and'
                    query &= current_query

            if query:
                base_queryset = base_queryset.filter(query)

        if fields:
            data_queryset = base_queryset.values(*fields)
            data = list(data_queryset.iterator(chunk_size=1000))
            # Duration-typed virtual fields (e.g. "days_open") come back as
            # timedelta from DurationField annotations — convert to plain
            # integer days so pandas groupby/aggregation treats them like any
            # numeric field. Non-duration virtual fields (e.g. "close_month",
            # a date) are left as-is.
            duration_fields = [
                f for f in fields if is_duration_virtual_field(model_class, f)
            ]
            if duration_fields and data:
                for row in data:
                    for f in duration_fields:
                        value = row.get(f)
                        row[f] = value.days if value is not None else None
            df = pd.DataFrame(data) if data else pd.DataFrame(columns=fields)
            record_count = len(data)
        else:
            record_count = base_queryset.count()
            data = [{}] * record_count
            df = pd.DataFrame()

        queryset = base_queryset

        context["panel_open"] = bool(preview_data)
        context["hierarchical_data"] = []
        context["pivot_columns"] = []
        context["pivot_table"] = {}
        context["pivot_index"] = []
        context["aggregate_columns"] = []
        context["has_hierarchical_groups"] = len(temp_report.row_groups_list) > 1
        context["configuration_type"] = self.get_configuration_type(temp_report)
        panel_open = self.request.GET.get("panel_open") == "true" or bool(preview_data)
        context["panel_open"] = panel_open
        context["has_unsaved_changes"] = bool(preview_data)
        context["temp_report"] = temp_report

        # Add verbose names for row and column groups
        context["row_group_verbose_names"] = [
            self.get_verbose_name(field_name, model_class)
            for field_name in temp_report.row_groups_list
        ]
        context["column_group_verbose_names"] = [
            self.get_verbose_name(field_name, model_class)
            for field_name in temp_report.column_groups_list
        ]

        all_grouping_fields = (
            temp_report.row_groups_list + temp_report.column_groups_list
        )
        fk_cache = (
            self._batch_load_foreign_keys(df, model_class, all_grouping_fields)
            if not df.empty
            else {}
        )

        context["_fk_cache"] = fk_cache

        row_count = len(temp_report.row_groups_list)
        col_count = len(temp_report.column_groups_list)

        if row_count == 0 and col_count == 0:
            self.handle_0_row_0_col(df, temp_report, context, total_count=record_count)
        elif row_count == 1 and col_count == 0:
            self.handle_1_row_0_col(df, temp_report, context, fk_cache)
        elif row_count == 1 and col_count == 1:
            self.handle_1_row_1_col(df, temp_report, context, fk_cache)
        elif row_count == 1 and col_count == 2:
            self.handle_1_row_2_col(df, temp_report, context, fk_cache)
        elif row_count == 2 and col_count == 0:
            self.handle_2_row_0_col(df, temp_report, context, fk_cache)
        elif row_count == 2 and col_count == 1:
            self.handle_2_row_1_col(df, temp_report, context, fk_cache)
        elif row_count == 3 and col_count == 0:
            self.handle_3_row_0_col(df, temp_report, context, fk_cache)
        else:
            context["error"] = (
                f"Configuration not supported: {row_count} rows, {col_count} columns"
            )

        pivot_sort_field = self.request.GET.get("pivot_sort")
        pivot_sort_direction = self.request.GET.get("pivot_direction", "asc")
        context["pivot_sort_field"] = pivot_sort_field
        context["pivot_sort_direction"] = pivot_sort_direction
        if pivot_sort_field and context.get("pivot_index"):
            self.sort_pivot_table(context, pivot_sort_field, pivot_sort_direction)

        chart_data = self.generate_chart_data(
            df, temp_report, fk_cache, record_count=record_count
        )
        if chart_data.get("stacked_data"):

            class _ReportChartEncoder(json.JSONEncoder):
                def default(self, obj):
                    if isinstance(obj, Promise):
                        return force_str(obj)
                    return super().default(obj)

            chart_data = {
                **chart_data,
                "stacked_data": json.dumps(
                    chart_data["stacked_data"], cls=_ReportChartEncoder
                ),
            }
        context["chart_data"] = chart_data
        context["total_count"] = record_count
        context["total_amount"] = sum(
            [
                float(
                    df[agg["field"]].sum()
                    if agg["field"] in df.columns and agg.get("aggfunc") == "sum"
                    else 0
                )
                for agg in aggregate_columns_dict
            ]
        )

        columns = []
        for col in temp_report.selected_columns_list:
            # Virtual (computed) fields have no renderer on the underlying
            # HorillaListView queryset — they only support row/column
            # grouping, filtering, and aggregation, not the Detail table —
            # unless registered with show_in_detail, in which case the
            # annotated value on each row is shown as a plain column.
            virtual_field = get_virtual_field(model_class, col)
            if virtual_field is not None:
                if virtual_field.show_in_detail:
                    columns.append((virtual_field.verbose_name, col))
                continue
            field = model_class._meta.get_field(col)
            verbose_name = field.verbose_name
            if field.choices:
                columns.append((verbose_name, f"get_{col}_display"))
            else:
                columns.append((verbose_name, col))

        list_view = HorillaListView(
            model=model_class,
            view_id="report-details-sec",
            search_url=reverse_lazy("reports:report_detail", kwargs={"pk": report.pk}),
            main_url=reverse_lazy("reports:report_detail", kwargs={"pk": report.pk}),
            table_width=False,
            columns=columns,
        )
        list_view.request = self.request
        list_view.table_width = False
        list_view.table_auto = True
        list_view.bulk_select_option = False
        list_view.list_column_visibility = False
        list_view.paginate_by = 10
        list_view.table_height_as_class = "h-[200px]"
        if hasattr(report.model_class, "get_detail_url"):
            list_view.col_attrs = self.col_attrs()
        sort_field = self.request.GET.get("sort")
        sort_direction = self.request.GET.get("direction", "asc")

        if columns:
            # Apply sorting to the queryset for list view
            if sort_field:
                queryset = list_view._apply_sorting(
                    queryset, sort_field, sort_direction
                )
            else:
                queryset = queryset.order_by("-id")
        else:
            queryset = model_class.objects.none()
        list_view.object_list = queryset
        context.update(list_view.get_context_data(object_list=queryset))

        session_referer_key = f"report_detail_referer_{report.pk}"
        current_referer = self.request.META.get("HTTP_REFERER")
        hx_current_url = self.request.headers.get("HX-Current-URL")
        stored_referer = self.request.session.get(session_referer_key)
        report_detail_base = f"/reports/report-detail/{report.pk}/"
        session_url_value = self.request.GET.get("session_url")

        if stored_referer:
            stored_parsed = urlparse(stored_referer)
            stored_referer = stored_parsed.path + (
                f"?{stored_parsed.query}" if stored_parsed.query else ""
            )

        if hx_current_url:
            hx_parsed = urlparse(hx_current_url)
            hx_path = hx_parsed.path
            hx_relative = hx_path + (f"?{hx_parsed.query}" if hx_parsed.query else "")
            is_from_report_detail = hx_path == report_detail_base
            if not is_from_report_detail and session_url_value != "False":
                self.request.session[session_referer_key] = hx_relative
                previous_url = hx_relative
            else:
                previous_url = (
                    stored_referer
                    if stored_referer
                    else reverse_lazy("reports:reports_list_view")
                )
        elif stored_referer:
            previous_url = stored_referer
        elif current_referer and self.request.get_host() in current_referer:
            referer_parsed = urlparse(current_referer)
            referer_path = referer_parsed.path
            if referer_path != report_detail_base:
                referer_relative = referer_path + (
                    f"?{referer_parsed.query}" if referer_parsed.query else ""
                )
                previous_url = referer_relative
                self.request.session[session_referer_key] = referer_relative
            else:
                previous_url = reverse_lazy("reports:reports_list_view")
        else:
            previous_url = reverse_lazy("reports:reports_list_view")
        context["previous_url"] = previous_url
        context["total_groups_count"] = len(temp_report.row_groups_list) + len(
            temp_report.column_groups_list
        )
        return context

    def generate_chart_data(self, df, report, fk_cache=None, record_count=None):
        """Generate chart-friendly labels and datasets for the given DataFrame and report configuration."""
        chart_data = {
            "labels": [],
            "data": [],
            "type": report.chart_type,
            "label_field": "Count",
            "stacked_data": {},
            "has_multiple_groups": False,
            "urls": [],
        }

        if df.empty:
            if record_count is not None and record_count > 0:
                model_class = report.model_class
                section_info = get_section_info_for_model(model_class)
                chart_data["labels"] = ["Records"]
                chart_data["data"] = [record_count]
                chart_data["label_field"] = "Records"
                chart_data["urls"] = [section_info["url"]]
            return chart_data

        config_type = self.get_configuration_type(report)
        model_class = report.model_class
        section_info = get_section_info_for_model(model_class)

        # Optional Y-axis: when set and present in DataFrame, aggregate that
        # column instead of using record counts. Supports metric+field
        # configuration like "sum__amount", "avg__amount", etc.
        raw_value = getattr(report, "chart_value_field", None)
        metric = "sum"
        value_field = None
        if raw_value:
            if "__" in raw_value:
                m, f = raw_value.split("__", 1)
                if f in df.columns:
                    value_field = f
                    metric = m.lower() or "sum"
            elif raw_value in df.columns:
                # Backward compatibility: plain field name implies sum
                value_field = raw_value
                metric = "sum"
        has_value_field = bool(value_field)

        total_groups = len(report.row_groups_list) + len(report.column_groups_list)
        chart_data["has_multiple_groups"] = total_groups >= 2

        try:
            if config_type == "0_row_0_col":
                chart_data["labels"] = ["Records"]
                chart_data["data"] = [len(df)]
                chart_data["label_field"] = "Records"
                chart_data["urls"] = [section_info["url"]]

            elif (
                report.chart_type
                in [
                    "stacked_vertical",
                    "stacked_horizontal",
                    "heatmap",
                    "sankey",
                    "radar",
                ]
                and chart_data["has_multiple_groups"]
            ):
                chart_data.update(
                    self._generate_stacked_chart_data(df, report, model_class, fk_cache)
                )

            else:
                chart_field = None

                # Prefer current row/column grouping over saved chart_field so the
                if report.row_groups_list and report.row_groups_list[0] in df.columns:
                    chart_field = report.row_groups_list[0]
                    if not hasattr(report, "_temp_report"):
                        if not report.chart_field:
                            report.chart_field = chart_field
                            report.save(update_fields=["chart_field"])
                elif (
                    report.column_groups_list
                    and report.column_groups_list[0] in df.columns
                ):
                    chart_field = report.column_groups_list[0]
                    if not hasattr(report, "_temp_report"):
                        if not report.chart_field:
                            report.chart_field = chart_field
                            report.save(update_fields=["chart_field"])
                elif (
                    hasattr(report, "chart_field")
                    and report.chart_field
                    and report.chart_field in df.columns
                ):
                    chart_field = report.chart_field

                if chart_field:
                    if has_value_field:
                        if metric == "avg":
                            grouped_series = df.groupby(chart_field)[value_field].mean()
                        elif metric == "min":
                            grouped_series = df.groupby(chart_field)[value_field].min()
                        elif metric == "max":
                            grouped_series = df.groupby(chart_field)[value_field].max()
                        else:
                            grouped_series = df.groupby(chart_field)[value_field].sum()
                    else:
                        grouped_series = df.groupby(chart_field).size()

                    display_labels = []
                    display_count = {}

                    for k in grouped_series.index:
                        display_info = self.get_display_value(
                            k, chart_field, model_class, fk_cache
                        )
                        if isinstance(display_info, dict):
                            base_display = display_info["display"]
                        else:
                            base_display = str(display_info)

                        if base_display in display_count:
                            display_count[base_display] += 1
                            unique_label = (
                                f"{base_display} ({display_count[base_display]})"
                            )
                        else:
                            display_count[base_display] = 1
                            unique_label = base_display

                        display_labels.append(unique_label)

                    chart_data["labels"] = display_labels
                    chart_data["data"] = [float(v) for v in grouped_series.values]
                    chart_data["label_field"] = self.get_verbose_name(
                        chart_field, model_class
                    )
                    urls = []
                    drillable_chart_field = self._drillable_field(
                        chart_field, model_class
                    )
                    for value in grouped_series.index:
                        params = {"section": section_info["section"]}
                        if drillable_chart_field:
                            params.update(
                                {
                                    "apply_filter": "true",
                                    "field": drillable_chart_field,
                                    "operator": "exact",
                                    "value": value if value is not None else "",
                                }
                            )
                        urls.append(f"{section_info['url']}?{urlencode(params)}")
                    chart_data["urls"] = urls
                else:
                    chart_data["labels"] = ["Records"]
                    chart_data["data"] = [len(df)]
                    chart_data["label_field"] = "Records"
                    chart_data["urls"] = [section_info["url"]]

        except Exception as e:
            chart_data["error"] = f"Error generating chart data: {str(e)}"

        return chart_data

    def _drillable_field(self, field_name, model_class):
        """Return field_name if it's a real field the CRM list view can
        filter on, or None if it's a virtual/computed field (e.g. "days_open",
        "close_month") that only exists inside the reports engine's own
        annotated queryset — the list view has no idea how to filter on it,
        so drill-down links must omit the filter entirely rather than send
        a field name that will error or silently no-op there."""
        if get_virtual_field(model_class, field_name) is not None:
            return None
        return field_name

    def _report_drill_value_str(self, value):
        """Serialize filter value for report chart drill URL (match list view apply_filter)."""
        if value is True:
            return "true"
        if value is False:
            return "false"
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        return str(value)

    def _report_drill_url_two(
        self,
        section_info,
        primary_field,
        primary_value,
        secondary_field,
        secondary_value,
        model_class=None,
    ):
        """Build list URL with both filters (primary + secondary) for chart segment click.

        Either field is dropped from the filter (not the URL) if it's a
        virtual/computed field the CRM list view can't filter on.
        """
        base = (section_info.get("url") or "").split("?")[0].rstrip("/")
        if not base:
            return None
        v1 = self._report_drill_value_str(primary_value)
        v2 = self._report_drill_value_str(secondary_value)
        drillable_primary = self._drillable_field(primary_field, model_class)
        drillable_secondary = self._drillable_field(secondary_field, model_class)

        pairs = [("section", section_info.get("section", ""))]
        if drillable_primary or drillable_secondary:
            pairs.append(("apply_filter", "true"))
            if drillable_primary:
                pairs += [
                    ("field", drillable_primary),
                    ("operator", "exact"),
                    ("value", v1),
                ]
            if drillable_secondary:
                pairs += [
                    ("field", drillable_secondary),
                    ("operator", "exact"),
                    ("value", v2),
                ]
        return f"{base}?{urlencode(pairs)}"

    def _generate_stacked_chart_data(self, df, report, model_class, fk_cache=None):
        """Generate data for stacked charts when multiple grouping fields are available."""
        try:
            primary_field = None
            secondary_field = None

            # Prefer current row/column grouping over saved chart_field so the chart
            # reflects the grouping selected in the panel.
            if report.row_groups_list and report.column_groups_list:
                if (
                    report.row_groups_list[0] in df.columns
                    and report.column_groups_list[0] in df.columns
                ):
                    primary_field = report.row_groups_list[0]
                    secondary_field = report.column_groups_list[0]
            if (not primary_field or not secondary_field) and len(
                report.row_groups_list
            ) >= 2:
                if (
                    report.row_groups_list[0] in df.columns
                    and report.row_groups_list[1] in df.columns
                ):
                    primary_field = report.row_groups_list[0]
                    secondary_field = report.row_groups_list[1]
            if (not primary_field or not secondary_field) and len(
                report.column_groups_list
            ) >= 2:
                if (
                    report.column_groups_list[0] in df.columns
                    and report.column_groups_list[1] in df.columns
                ):
                    primary_field = report.column_groups_list[0]
                    secondary_field = report.column_groups_list[1]

            # Fall back to saved chart_field / chart_field_stacked
            if (
                hasattr(report, "chart_field")
                and report.chart_field
                and report.chart_field in df.columns
            ):
                if not primary_field:
                    primary_field = report.chart_field
                if (
                    hasattr(report, "chart_field_stacked")
                    and report.chart_field_stacked
                    and report.chart_field_stacked in df.columns
                    and report.chart_field_stacked != primary_field
                    and not secondary_field
                ):
                    secondary_field = report.chart_field_stacked

            if not secondary_field and (
                hasattr(report, "chart_field_stacked")
                and report.chart_field_stacked
                and report.chart_field_stacked in df.columns
            ):
                secondary_field = report.chart_field_stacked
                all_fields = report.row_groups_list + report.column_groups_list
                if not primary_field:
                    primary_field = next(
                        (
                            f
                            for f in all_fields
                            if f != secondary_field and f in df.columns
                        ),
                        None,
                    )

            if not primary_field or not secondary_field:
                return self._fallback_chart_data(df, report, model_class, fk_cache)

            if primary_field not in df.columns or secondary_field not in df.columns:
                return self._fallback_chart_data(df, report, model_class, fk_cache)

            if not hasattr(report, "_temp_report"):
                fields_to_update = []
                if not report.chart_field:
                    report.chart_field = primary_field
                    fields_to_update.append("chart_field")
                if not report.chart_field_stacked:
                    report.chart_field_stacked = secondary_field
                    fields_to_update.append("chart_field_stacked")
                if fields_to_update:
                    report.save(update_fields=fields_to_update)

            try:
                # Support metric + field configuration for stacked charts as well.
                raw_value = getattr(report, "chart_value_field", None)
                metric = "sum"
                value_field = None
                if raw_value:
                    if "__" in raw_value:
                        m, f = raw_value.split("__", 1)
                        if f in df.columns:
                            value_field = f
                            metric = m.lower() or "sum"
                    elif raw_value in df.columns:
                        value_field = raw_value
                        metric = "sum"

                if value_field and value_field in df.columns:
                    aggfunc = "sum"
                    if metric == "avg":
                        aggfunc = "mean"
                    elif metric == "min":
                        aggfunc = "min"
                    elif metric == "max":
                        aggfunc = "max"
                    pivot_table = pd.pivot_table(
                        df,
                        index=[primary_field],
                        columns=[secondary_field],
                        values=value_field,
                        aggfunc=aggfunc,
                        fill_value=0,
                    )
                else:
                    pivot_table = pd.pivot_table(
                        df,
                        index=[primary_field],
                        columns=[secondary_field],
                        aggfunc="size",
                        fill_value=0,
                    )
            except Exception:
                return self._fallback_chart_data(df, report, model_class, fk_cache)

            if pivot_table.empty:
                return self._fallback_chart_data(df, report, model_class, fk_cache)

            categories = []
            category_count = {}

            for idx in pivot_table.index:
                display_info = self.get_display_value(
                    idx, primary_field, model_class, fk_cache
                )
                if isinstance(display_info, dict):
                    base_display = display_info["display"]
                else:
                    base_display = str(display_info)

                if base_display in category_count:
                    category_count[base_display] += 1
                    unique_label = f"{base_display} ({category_count[base_display]})"
                else:
                    category_count[base_display] = 1
                    unique_label = base_display

                categories.append(unique_label)

            section_info = get_section_info_for_model(model_class)
            series = []
            series_name_count = {}

            for col in pivot_table.columns:
                col_display_info = self.get_display_value(
                    col, secondary_field, model_class, fk_cache
                )
                if isinstance(col_display_info, dict):
                    base_col_display = col_display_info["display"]
                else:
                    base_col_display = str(col_display_info)

                if base_col_display in series_name_count:
                    series_name_count[base_col_display] += 1
                    col_display = (
                        f"{base_col_display} ({series_name_count[base_col_display]})"
                    )
                else:
                    series_name_count[base_col_display] = 1
                    col_display = base_col_display

                series_data = []

                for idx in pivot_table.index:
                    try:
                        value = pivot_table.loc[idx, col]
                        v = int(value) if pd.notna(value) else 0
                        drill_url = self._report_drill_url_two(
                            section_info,
                            primary_field,
                            idx,
                            secondary_field,
                            col,
                            model_class,
                        )
                        if drill_url and v > 0:
                            series_data.append({"value": v, "url": drill_url})
                        else:
                            series_data.append(v)
                    except Exception as val_error:
                        logger.error(
                            "Value extraction error for %s, %s: %s",
                            idx,
                            col,
                            str(val_error),
                        )
                        series_data.append(0)

                series.append({"name": col_display, "data": series_data})

            totals = []
            for i in range(len(categories)):
                total = 0
                for s in series:
                    if i >= len(s["data"]):
                        continue
                    cell = s["data"][i]
                    total += cell["value"] if isinstance(cell, dict) else cell
                totals.append(total)

            section_info = get_section_info_for_model(model_class)
            urls = []
            drillable_primary_field = self._drillable_field(primary_field, model_class)
            for idx in pivot_table.index:
                params = {"section": section_info["section"]}
                if drillable_primary_field:
                    params.update(
                        {
                            "apply_filter": "true",
                            "field": drillable_primary_field,
                            "operator": "exact",
                            "value": idx if idx is not None else "",
                        }
                    )
                urls.append(f"{section_info['url']}?{urlencode(params)}")

            stacked_data = {"categories": categories, "series": series}

            primary_verbose = self.get_verbose_name(primary_field, model_class)
            secondary_verbose = self.get_verbose_name(secondary_field, model_class)

            return {
                "labels": categories,
                "data": totals,
                "urls": urls,
                "stacked_data": stacked_data,
                "label_field": f"{primary_verbose} by {secondary_verbose}",
                "has_stacked_data": True,
                "primary_field": primary_field,
                "secondary_field": secondary_field,
            }

        except Exception as e:
            logger.error("Error in stacked chart generation: %s", str(e))
            return self._fallback_chart_data(df, report, model_class)

    def _fallback_chart_data(self, df, report, model_class, fk_cache=None):
        """Fallback to simple chart when stacking fails."""
        fallback_field = None
        # Prefer current row/column grouping over saved chart_field
        if report.row_groups_list and report.row_groups_list[0] in df.columns:
            fallback_field = report.row_groups_list[0]
        elif report.column_groups_list and report.column_groups_list[0] in df.columns:
            fallback_field = report.column_groups_list[0]
        elif (
            hasattr(report, "chart_field")
            and report.chart_field
            and report.chart_field in df.columns
        ):
            fallback_field = report.chart_field

        section_info = get_section_info_for_model(model_class)

        if fallback_field:
            try:
                raw_value = getattr(report, "chart_value_field", None)
                metric = "sum"
                value_field = None
                if raw_value:
                    if "__" in raw_value:
                        m, f = raw_value.split("__", 1)
                        if f in df.columns:
                            value_field = f
                            metric = m.lower() or "sum"
                    elif raw_value in df.columns:
                        value_field = raw_value
                        metric = "sum"

                if value_field and value_field in df.columns:
                    if metric == "avg":
                        grouped_series = df.groupby(fallback_field)[value_field].mean()
                    elif metric == "min":
                        grouped_series = df.groupby(fallback_field)[value_field].min()
                    elif metric == "max":
                        grouped_series = df.groupby(fallback_field)[value_field].max()
                    else:
                        grouped_series = df.groupby(fallback_field)[value_field].sum()
                else:
                    grouped_series = df.groupby(fallback_field).size()

                display_labels = []
                display_count = {}

                for k in grouped_series.index:
                    display_info = self.get_display_value(
                        k, fallback_field, model_class, fk_cache
                    )
                    if isinstance(display_info, dict):
                        base_display = display_info["display"]
                    else:
                        base_display = str(display_info)

                    if base_display in display_count:
                        display_count[base_display] += 1
                        unique_label = f"{base_display} ({display_count[base_display]})"
                    else:
                        display_count[base_display] = 1
                        unique_label = base_display

                    display_labels.append(unique_label)

                urls = []
                drillable_fallback_field = self._drillable_field(
                    fallback_field, model_class
                )
                for value in grouped_series.index:
                    params = {"section": section_info["section"]}
                    if drillable_fallback_field:
                        params.update(
                            {
                                "apply_filter": "true",
                                "field": drillable_fallback_field,
                                "operator": "exact",
                                "value": value if value is not None else "",
                            }
                        )
                    urls.append(f"{section_info['url']}?{urlencode(params)}")

                return {
                    "labels": display_labels,
                    "data": [float(v) for v in grouped_series.values],
                    "urls": urls,
                    "stacked_data": {},
                    "label_field": self.get_verbose_name(fallback_field, model_class),
                    "has_stacked_data": False,
                }
            except Exception as e:
                logger.error("Fallback chart error: %s", str(e))

        return {
            "labels": ["Records"],
            "data": [len(df)],
            "urls": [section_info["url"]],
            "stacked_data": {},
            "label_field": "Records",
            "has_stacked_data": False,
        }
