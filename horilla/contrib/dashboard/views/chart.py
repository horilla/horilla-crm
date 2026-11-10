"""Views for rendering charts and KPIs in dashboard components."""

# Standard library imports
import logging
from urllib.parse import urlencode

# Third-party imports (Django)
from django.contrib import messages
from django.utils.encoding import force_str

# First party imports (Horilla)
from horilla.apps import apps
from horilla.contrib.generics.views.helpers.queryset_utils import (
    apply_conditions,
    get_queryset_for_module,
)
from horilla.contrib.reports.utils import resolve_report_field
from horilla.contrib.utils.methods import get_section_info_for_model
from horilla.db.models import Avg, Count, ForeignKey, Max, Min, Sum
from horilla.shortcuts import render
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.html import js_json
from horilla.views.generic import View

# Local imports
from ..models import DashboardComponent
from ..utils import (
    DATE_RANGE_CHOICES,
    annotate_component_virtual_fields,
    apply_date_range_to_queryset,
)
from .dashboard_helper import apply_report_filters

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("dashboard.add_dashboard"), name="dispatch"
)
class ChartPreviewView(View):
    """View to return a preview of the chart based on selected type and component type."""

    def get(self, request, *args, **kwargs):
        """Handle GET request to return chart preview HTML."""
        chart_type = request.GET.get("chart_type", "")
        component_type = request.GET.get("component_type", "")

        if component_type is None or component_type == "None":
            component_type = ""
        if chart_type is None or chart_type == "None":
            chart_type = ""

        if component_type == "kpi":
            return render(
                request,
                "chart/preview_kpi.html",
                {"title": "Total", "value": "574.34"},
            )

        if component_type == "table_data":
            return render(request, "chart/preview_table.html")

        valid_chart_types = (
            "column",
            "bar",
            "pie",
            "donut",
            "line",
            "stacked_vertical",
            "stacked_horizontal",
            "funnel",
            "scatter",
            "heatmap",
            "treemap",
            "area",
            "sankey",
            "radar",
        )
        if (
            component_type == "chart" or (not component_type and chart_type)
        ) and chart_type in valid_chart_types:
            return render(
                request,
                "chart/preview_chart.html",
                {"chart_type": chart_type},
            )

        message = (
            "Select component type to see preview"
            if not component_type and not chart_type
            else (
                f"Preview for {component_type} component"
                if component_type and component_type != "chart" and not chart_type
                else (
                    "Select chart type to see preview"
                    if component_type == "chart" and not chart_type
                    else "Chart type not supported"
                )
            )
        )
        return render(
            request,
            "partials/centered_message.html",
            {"message": message},
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["dashboard.view_dashboard", "dashboard.view_own_dashboard"]
    ),
    name="dispatch",
)
class DashboardComponentChartView(View):
    """
    View to render chart data for dashboard components using ECharts.
    Handles chart components with ECharts and KPIs with custom HTML.
    """

    def get_kpi_data(self, component):
        """
        Calculate KPI data.
        Supports:
        - "count" → total record count
        - "<agg>__<field_name>" for numeric fields, where <agg> is one of:
          sum, average, min, max
        """
        model = None
        module_name = component.module.model if component.module else None
        for app_config in apps.get_app_configs():
            try:
                model = apps.get_model(
                    app_label=app_config.label, model_name=module_name.lower()
                )
                break
            except LookupError:
                continue

        if not model:
            return None

        try:
            queryset = get_queryset_for_module(self.request.user, model)

            conditions = component.conditions.all().order_by("sequence")
            queryset = apply_conditions(queryset, conditions)
            queryset = annotate_component_virtual_fields(queryset, model, component)

            date_range = self.request.GET.get("date_range")
            if date_range and (
                str(date_range) in [str(d) for d in DATE_RANGE_CHOICES]
                or date_range == "custom"
            ):
                date_from = (
                    self.request.GET.get("date_from")
                    if date_range == "custom"
                    else None
                )
                date_to = (
                    self.request.GET.get("date_to") if date_range == "custom" else None
                )
                queryset = apply_date_range_to_queryset(
                    queryset, model, date_range, date_from=date_from, date_to=date_to
                )

            metric_type = (component.metric_type or "").strip()

            # Default: simple record count
            value = queryset.count()
            metric_label = "Count"
            field_label_str = module_name.title() if module_name else "Records"

            if metric_type and metric_type != "count":
                try:
                    agg_key, field_name = metric_type.split("__", 1)
                except ValueError:
                    agg_key, field_name = "", ""

                agg_map = {
                    "sum": Sum,
                    "average": Avg,
                    "min": Min,
                    "max": Max,
                }

                if agg_key in agg_map and field_name:
                    try:
                        field = model._meta.get_field(field_name)
                        field_label_str = str(
                            getattr(field, "verbose_name", field_name) or field_name
                        )
                    except Exception:
                        field_label_str = field_name.replace("_", " ").title()

                    agg_func = agg_map[agg_key]
                    agg_result = queryset.aggregate(result=agg_func(field_name)).get(
                        "result"
                    )
                    value = agg_result or 0

                    metric_label = (
                        "Average"
                        if agg_key == "average"
                        else agg_key.replace("_", " ").title()
                    )

            section_info = get_section_info_for_model(model)

            base_url = section_info["url"]
            if conditions.exists():
                query_params = [
                    ("section", section_info["section"]),
                    ("apply_filter", "true"),
                ]

                for condition in conditions:
                    operator = (
                        "exact"
                        if condition.operator == "equals"
                        else condition.operator
                    )

                    query_params.append(("field", condition.field))
                    query_params.append(("operator", operator))
                    query_params.append(("value", condition.value))

                query = urlencode(query_params, doseq=True)
                filtered_url = f"{base_url}?{query}"
            else:
                filtered_url = f"{base_url}?section={section_info['section']}"

            return {
                "value": float(value),
                "url": filtered_url,
                "section": section_info["section"],
                "label": f"{metric_label} of {field_label_str}",
            }
        except Exception:
            return None

    def get_chart_data(self, component):
        """
        Retrieve chart data based on component configuration.
        Handles only chart-type components.
        Uses Count aggregation by default, or the configured y-axis metric when set.
        """
        model = None
        module_name = component.module.model if component.module else None
        for app_config in apps.get_app_configs():
            try:
                model = apps.get_model(
                    app_label=app_config.label, model_name=module_name.lower()
                )
                break
            except LookupError:
                continue

        if not model or component.component_type != "chart":
            return None

        try:
            queryset = get_queryset_for_module(self.request.user, model)
            conditions = component.conditions.all()

            date_range = self.request.GET.get("date_range")
            if date_range and (
                str(date_range) in [str(d) for d in DATE_RANGE_CHOICES]
                or date_range == "custom"
            ):
                date_from = (
                    self.request.GET.get("date_from")
                    if date_range == "custom"
                    else None
                )
                date_to = (
                    self.request.GET.get("date_to") if date_range == "custom" else None
                )
                queryset = apply_date_range_to_queryset(
                    queryset, model, date_range, date_from=date_from, date_to=date_to
                )

            # Chart types that need primary + secondary grouping → stackedData
            two_group_chart_types = [
                "stacked_vertical",
                "stacked_horizontal",
                "heatmap",
                "sankey",
                "radar",
            ]
            use_two_groupings = component.chart_type in two_group_chart_types and bool(
                component.secondary_grouping
            )

            x_axis_label = (
                component.grouping_field.replace("_", " ").title()
                if component.grouping_field
                else "Category"
            )

            if component.grouping_field:
                field = resolve_report_field(model, component.grouping_field)

                if use_two_groupings:
                    return self.get_stacked_chart_data(
                        queryset, component, conditions, field, x_axis_label, model
                    )

                queryset = apply_conditions(queryset, conditions)
                queryset = annotate_component_virtual_fields(queryset, model, component)

                # Determine aggregation for Y-axis: default count, or numeric metric when configured.
                y_metric = (component.y_axis_metric_type or "").strip()
                agg_func = Count
                agg_field_name = "id"
                if y_metric and y_metric != "count":
                    try:
                        agg_key, field_name = y_metric.split("__", 1)
                    except ValueError:
                        agg_key, field_name = "", ""

                    agg_map = {
                        "sum": Sum,
                        "average": Avg,
                        "min": Min,
                        "max": Max,
                    }
                    if agg_key in agg_map and field_name:
                        agg_func = agg_map[agg_key]
                        agg_field_name = field_name

                if field.is_relation and hasattr(field.remote_field.model, "name"):
                    queryset = queryset.values(
                        f"{component.grouping_field}__name",
                        f"{component.grouping_field}_id",
                    ).annotate(value=agg_func(agg_field_name))
                else:
                    if field.is_relation:
                        queryset = queryset.values(
                            component.grouping_field, f"{component.grouping_field}_id"
                        ).annotate(value=agg_func(agg_field_name))
                    else:
                        queryset = queryset.values(component.grouping_field).annotate(
                            value=agg_func(agg_field_name)
                        )

                labels = []
                data = []
                urls = []
                section_info = get_section_info_for_model(model)

                for item in queryset:
                    label = item.get(
                        f"{component.grouping_field}__name"
                        if field.is_relation
                        and hasattr(field.remote_field.model, "name")
                        else component.grouping_field
                    )

                    try:
                        if hasattr(field, "choices") and field.choices:
                            original_label = label
                            for choice_value, choice_label in field.choices:
                                if choice_value == original_label:
                                    label = choice_label
                                    break
                        elif field.is_relation and label is not None:
                            if not hasattr(field.remote_field.model, "name"):
                                try:
                                    related_obj = field.remote_field.model.objects.get(
                                        pk=label
                                    )
                                    label = str(related_obj)
                                except Exception:
                                    pass
                    except Exception:
                        pass

                    if isinstance(label, (list, dict)):
                        label = str(label)
                    elif label is None:
                        label = "None"

                    labels.append(str(label))
                    # Some aggregations (e.g. Sum on all-null groups) may yield None; treat as 0
                    value = item.get("value")
                    data.append(float(value) if value is not None else 0.0)

                    filter_value = label
                    if field.is_relation:
                        filter_value = item.get(f"{component.grouping_field}_id")
                    else:
                        filter_value = item.get(component.grouping_field)

                    query = urlencode(
                        {
                            "section": section_info["section"],
                            "apply_filter": "true",
                            "field": component.grouping_field,
                            "operator": "exact",
                            "value": filter_value,
                        }
                    )
                    urls.append(f"{section_info['url']}?{query}")

                return {
                    "labels": labels,
                    "data": data,
                    "urls": urls,
                    "labelField": component.grouping_field.replace("_", " ").title(),
                    "x_axis_label": x_axis_label,
                    "is_condition_based": conditions.exists(),
                }

            return None
        except Exception:
            return None

    def get_stacked_chart_data(
        self, queryset, component, conditions, field, x_axis_label, model
    ):
        """
        Handle stacked chart data.
        Uses Count aggregation by default, or the configured y-axis metric when set.
        """
        try:
            queryset = apply_conditions(queryset, conditions)
            queryset = annotate_component_virtual_fields(queryset, model, component)

            section_info = get_section_info_for_model(model)

            if field.is_relation and hasattr(field.remote_field.model, "name"):
                category_keys = list(
                    queryset.values_list(f"{component.grouping_field}__name", flat=True)
                    .distinct()
                    .order_by(f"{component.grouping_field}__name")
                )
            else:
                category_keys = list(
                    queryset.values_list(component.grouping_field, flat=True)
                    .distinct()
                    .order_by(component.grouping_field)
                )

            # Keep raw keys for grouped_dict lookup; build display labels separately.
            # Otherwise CharField+choices stores "finance" but labels are "Finance" —
            # grouped_dict.get("Finance", 0) is always 0 and stacked bars disappear.
            category_keys = [c for c in category_keys if c is not None]
            try:
                if hasattr(field, "choices") and field.choices:
                    category_display = {}
                    for choice_value, choice_label in field.choices:
                        category_display[choice_value] = force_str(choice_label)
                    category_labels = [
                        force_str(category_display.get(cat, cat))
                        for cat in category_keys
                    ]
                else:
                    category_labels = [force_str(cat) for cat in category_keys]
            except Exception:
                category_labels = [force_str(cat) for cat in category_keys]

            is_relation_name = field.is_relation and hasattr(
                field.remote_field.model, "name"
            )

            secondary_field = (
                resolve_report_field(model, component.secondary_grouping)
                if component.secondary_grouping
                else None
            )
            if not secondary_field:
                return None

            # Determine aggregation for Y-axis: default count, or numeric metric when configured.
            y_metric = (component.y_axis_metric_type or "").strip()
            agg_func = Count
            agg_field_name = "id"
            if y_metric and y_metric != "count":
                try:
                    agg_key, field_name = y_metric.split("__", 1)
                except ValueError:
                    agg_key, field_name = "", ""

                agg_map = {
                    "sum": Sum,
                    "average": Avg,
                    "min": Min,
                    "max": Max,
                }
                if agg_key in agg_map and field_name:
                    agg_func = agg_map[agg_key]
                    agg_field_name = field_name

            if secondary_field.is_relation and hasattr(
                secondary_field.remote_field.model, "name"
            ):
                secondary_values = list(
                    queryset.values_list(
                        f"{component.secondary_grouping}__name", flat=True
                    ).distinct()
                )
            else:
                secondary_values = list(
                    queryset.values_list(
                        component.secondary_grouping, flat=True
                    ).distinct()
                )

            secondary_values = [val for val in secondary_values if val is not None]

            if not secondary_values:
                return None

            series_data = []

            for secondary_value in secondary_values:
                display_value = secondary_value

                if secondary_field.is_relation and hasattr(
                    secondary_field.remote_field.model, "name"
                ):
                    related_obj = secondary_field.remote_field.model.objects.filter(
                        name=secondary_value
                    ).first()
                    if related_obj:
                        display_value = str(related_obj)
                elif isinstance(secondary_field, ForeignKey):
                    related_obj = secondary_field.remote_field.model.objects.filter(
                        pk=secondary_value
                    ).first()
                    if related_obj:
                        display_value = str(related_obj)
                elif hasattr(secondary_field, "choices") and secondary_field.choices:
                    for choice_value, choice_label in secondary_field.choices:
                        if choice_value == secondary_value:
                            display_value = force_str(choice_label)
                            break

                if secondary_field.is_relation and hasattr(
                    secondary_field.remote_field.model, "name"
                ):
                    filter_field = f"{component.secondary_grouping}__name"
                elif isinstance(secondary_field, ForeignKey):
                    filter_field = f"{component.secondary_grouping}_id"
                else:
                    filter_field = component.secondary_grouping

                filtered_queryset = queryset.filter(**{filter_field: secondary_value})

                if is_relation_name:
                    grouped_data = filtered_queryset.values(
                        f"{component.grouping_field}__name"
                    ).annotate(value=agg_func(agg_field_name))
                    grouped_dict = {}
                    for item in grouped_data:
                        k = item[f"{component.grouping_field}__name"]
                        if k is not None:
                            value = item.get("value")
                            grouped_dict[k] = float(value) if value is not None else 0.0
                else:
                    grouped_data = filtered_queryset.values(
                        component.grouping_field
                    ).annotate(value=agg_func(agg_field_name))
                    grouped_dict = {}
                    for item in grouped_data:
                        k = item[component.grouping_field]
                        if k is not None:
                            # Same key type as category_keys from values_list
                            value = item.get("value")
                            grouped_dict[k] = float(value) if value is not None else 0.0

                series_values = []
                for cat_key in category_keys:
                    series_values.append(float(grouped_dict.get(cat_key, 0)))

                series_data.append(
                    {
                        "name": force_str(display_value),
                        "data": series_values,
                    }
                )

            urls = []
            if field.is_relation and hasattr(field.remote_field.model, "name"):
                original_categories = list(
                    queryset.values_list(f"{component.grouping_field}_id", flat=True)
                    .distinct()
                    .order_by(f"{component.grouping_field}__name")
                )
            else:
                original_categories = list(
                    queryset.values_list(component.grouping_field, flat=True)
                    .distinct()
                    .order_by(component.grouping_field)
                )
                original_categories = [
                    cat for cat in original_categories if cat is not None
                ]

            for filter_value in original_categories:
                query = urlencode(
                    {
                        "section": section_info["section"],
                        "apply_filter": "true",
                        "field": component.grouping_field,
                        "operator": "exact",
                        "value": filter_value,
                    }
                )
                urls.append(f"{section_info['url']}?{query}")

            return {
                "labels": category_labels,
                "data": [],
                "urls": urls,
                "stackedData": {
                    "categories": category_labels,
                    "series": series_data,
                },
                "labelField": component.grouping_field.replace("_", " ").title(),
                "x_axis_label": x_axis_label,
                "hasMultipleGroups": True,
                "is_condition_based": conditions.exists(),
            }

        except Exception as e:
            messages.error(self.request, e)
            return None

    def get_report_chart_data(self, component):
        """
        Retrieve chart data for report-based components.
        Always uses Count aggregation.
        """
        try:
            report = component.reports
            if not report:
                logger.warning("No report found for component %s", component.id)
                return None

            model = None

            module_name = component.module.model if component.module else None

            for app_config in apps.get_app_configs():
                try:
                    model = apps.get_model(
                        app_label=app_config.label, model_name=module_name.lower()
                    )
                    break
                except LookupError:
                    continue

            if not model:
                logger.warning(
                    "Model not found for component %s, module: %s",
                    component.id,
                    component.module,
                )
                return None

            if not component.grouping_field:
                logger.warning("No grouping field for component %s", component.id)
                return None

            queryset = apply_report_filters(
                get_queryset_for_module(self.request.user, model), report
            )

            conditions = component.conditions.all().order_by("sequence")
            queryset = apply_conditions(queryset, conditions)
            queryset = annotate_component_virtual_fields(queryset, model, component)

            if queryset.count() == 0:
                logger.warning("Empty queryset for component %s", component.id)
                return None

            field = resolve_report_field(model, component.grouping_field)

            two_group_chart_types = [
                "stacked_vertical",
                "stacked_horizontal",
                "heatmap",
                "sankey",
                "radar",
            ]
            use_two_groupings = component.chart_type in two_group_chart_types and bool(
                component.secondary_grouping
            )

            x_axis_label = (
                component.grouping_field.replace("_", " ").title()
                if component.grouping_field
                else "Category"
            )

            if use_two_groupings:
                logger.info("Processing two-group chart for component %s", component.id)
                return self.get_stacked_chart_data(
                    queryset, component, conditions, field, x_axis_label, model
                )

            if field.is_relation and hasattr(field.remote_field.model, "name"):
                aggregated_data = queryset.values(
                    f"{component.grouping_field}__name",
                    f"{component.grouping_field}_id",
                ).annotate(value=Count("id"))
                field_name = f"{component.grouping_field}__name"
                id_field_name = f"{component.grouping_field}_id"
            else:
                aggregated_data = queryset.values(component.grouping_field).annotate(
                    value=Count("id")
                )
                field_name = component.grouping_field
                id_field_name = None

            labels = []
            data = []
            urls = []
            section_info = get_section_info_for_model(model)

            for item in aggregated_data:
                if field.is_relation and id_field_name:
                    filter_value = item.get(id_field_name)  # Use ID for relations
                    label = item.get(field_name)
                else:
                    filter_value = item.get(field_name)
                    label = filter_value

                try:
                    field_obj = model._meta.get_field(component.grouping_field)
                    if hasattr(field_obj, "choices") and field_obj.choices:
                        for choice_value, choice_label in field_obj.choices:
                            if choice_value == label:
                                label = choice_label
                                break
                except Exception:
                    pass

                if isinstance(label, (list, dict)):
                    label = str(label)
                elif label is None:
                    label = "None"
                else:
                    label = str(label)

                labels.append(label)
                data.append(float(item["value"]) if item["value"] is not None else 0)

                query = urlencode(
                    {
                        "section": section_info["section"],
                        "apply_filter": "true",
                        "field": component.grouping_field,
                        "operator": "exact",
                        "value": filter_value,
                    }
                )
                urls.append(f"{section_info['url']}?{query}")

            return {
                "labels": labels,
                "data": data,
                "urls": urls,
                "labelField": component.grouping_field.replace("_", " ").title(),
                "x_axis_label": x_axis_label,
                "is_condition_based": conditions.exists(),
                "is_from_report": True,
                "report_name": report.name,
            }
        except Exception as e:
            logger.error(
                "Failed to generate report chart for component %s: %s",
                component.id,
                e,
                exc_info=True,
            )
            return None

    def get(self, request, *args, **kwargs):
        """
        Handle GET request to render the chart or KPI component.
        Uses ECharts for charts and custom HTML for KPIs with modern card design.
        """
        component_id = kwargs.get("component_id")
        try:
            component = DashboardComponent.objects.get(id=component_id)
            if component.component_type == "kpi":
                kpi_data = self.get_kpi_data(component)
                if not kpi_data:
                    return render(
                        request,
                        "partials/centered_message.html",
                        {"message": "No KPI data available"},
                    )

                bg_colors = [
                    "bg-[#FFF3E0]",  # Light orange
                    "bg-[#E8F5E8]",  # Light green
                    "bg-[#FFE1F4]",  # Light pink
                    "bg-[#E3F2FD]",  # Light blue
                    "bg-[#F3E5F5]",  # Light purple
                    "bg-[#E0F2F1]",  # Light teal
                ]

                icon_colors = [
                    "text-orange-500",  # Orange
                    "text-green-500",  # Green
                    "text-pink-500",  # Pink
                    "text-blue-500",  # Blue
                    "text-purple-500",  # Purple
                    "text-teal-500",  # Teal
                ]

                bg_color = bg_colors[component.id % len(bg_colors)]
                icon_color = icon_colors[component.id % len(icon_colors)]

                formatted_value = f"{int(kpi_data['value']):,}"

                referer = request.META.get("HTTP_REFERER", "")
                is_home_view = "section=home" in referer

                context = {
                    "component_id": component_id,
                    "component_name": component.name,
                    "kpi_url": kpi_data["url"],
                    "section": kpi_data["section"],
                    "formatted_value": formatted_value,
                    "bg_color": bg_color,
                    "icon_color": icon_color,
                    "icon_url": component.icon.url if component.icon else None,
                    "is_home_view": is_home_view,
                    "query_string": request.GET.urlencode(),
                }

                return render(request, "kpi_components.html", context)

            if component.component_type == "chart":
                if component.reports:
                    chart_data = self.get_report_chart_data(component)
                else:
                    chart_data = self.get_chart_data(component)

                if not chart_data:
                    return render(
                        request,
                        "partials/centered_message.html",
                        {"message": "No data available"},
                    )

                conditions = component.conditions.all()
                if conditions.exists():
                    condition_text = "Conditions: " + ", ".join(
                        [
                            f"{cond.field} {cond.get_operator_display()} {cond.value}"
                            for cond in conditions
                        ]
                    )
                    chart_data["title"] = {
                        "subtext": condition_text,
                        "subtextStyle": {"fontSize": 12},
                        "bottom": 0,
                    }

                chart_config = {"type": component.chart_type, **chart_data}
                chart_config_json = js_json(chart_config)
                return render(
                    request,
                    "chart/component_chart.html",
                    {
                        "component_id": component.id,
                        "chart_config_json": chart_config_json,
                    },
                )
            return None

        except DashboardComponent.DoesNotExist:
            return render(
                request,
                "partials/centered_message.html",
                {"message": "Component not found"},
            )
        except Exception as e:
            return render(
                request,
                "partials/centered_message.html",
                {"message": f"Error: {e}"},
            )
