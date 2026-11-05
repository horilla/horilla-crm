"""views for dashboard - helper functions for components"""

# Standard library imports
import json
import logging
from urllib.parse import urlencode

# Third-party imports (Django)
from django.core.paginator import Paginator

# First party imports (Horilla)
from horilla.apps import apps
from horilla.contrib.generics.views import HorillaListView
from horilla.contrib.generics.views.helpers.queryset_utils import (
    apply_conditions,
    get_queryset_for_module,
    get_viewable_queryset,
)
from horilla.contrib.reports.utils import (
    NO_VALUE_OPERATORS,
    annotate_virtual_fields,
    build_report_filter_q,
    coerce_virtual_filter_value,
    get_virtual_field,
)
from horilla.contrib.utils.methods import get_section_info_for_model
from horilla.db.models import Avg, Count, Max, Min, Sum
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _

# Local imports
from ..utils import (
    DATE_RANGE_CHOICES,
    annotate_component_virtual_fields,
    apply_date_range_to_queryset,
)

logger = logging.getLogger(__name__)


def get_kpi_data(component, request):
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
        queryset = get_queryset_for_module(request.user, model)

        conditions = component.conditions.all().order_by("sequence")
        queryset = apply_conditions(queryset, conditions)
        queryset = annotate_component_virtual_fields(queryset, model, component)

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

        return {
            "value": float(value),
            "url": section_info["url"],
            "section": section_info["section"],
            "label": f"{metric_label} of {field_label_str}",
        }
    except Exception:
        return None


def apply_report_filters(queryset, report):
    """Narrow ``queryset`` by the report's saved filters, as the report page does."""
    model = queryset.model
    filters = report.filters_dict
    if not filters:
        return queryset

    queryset = annotate_virtual_fields(
        queryset,
        model,
        [data.get("original_field", name) for name, data in filters.items()],
    )
    query = None
    for index, (field_name, filter_data) in enumerate(filters.items()):
        operator = filter_data.get("operator", "exact")
        value = filter_data.get("value")
        if not value and operator not in NO_VALUE_OPERATORS:
            continue
        actual_field = filter_data.get("original_field", field_name)
        value = coerce_virtual_filter_value(model, actual_field, value)
        built_query = build_report_filter_q(model, actual_field, operator, value)
        if built_query is None:
            continue
        logic = filter_data.get("logic", "and") if index > 0 else "and"
        if query is None:
            query = built_query
        elif logic == "or":
            query |= built_query
        else:
            query &= built_query
    return queryset.filter(query) if query else queryset


def apply_report_table_queryset(queryset, report):
    """Queryset of a report's Detail Table: its saved filters, plus the virtual
    (computed) fields among its columns so they can be shown and sorted."""
    queryset = apply_report_filters(queryset, report)
    return annotate_virtual_fields(
        queryset, queryset.model, report.selected_columns_list
    )


def get_report_chart_data(component, request):
    """
    Generate chart data for report-based dashboard components.
    """
    try:
        report = component.reports
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

        queryset = apply_report_filters(
            get_queryset_for_module(request.user, model), report
        )

        if queryset.count() == 0:
            return None

        group_by_field = component.grouping_field

        if not group_by_field:
            return None

        try:
            field_obj = model._meta.get_field(group_by_field)
            is_fk = field_obj.is_relation
        except Exception:
            is_fk = False

        if is_fk:
            chart_data = (
                queryset.values(group_by_field, f"{group_by_field}_id")
                .annotate(value=Count("id"))
                .order_by("-value")
            )
        else:
            chart_data = (
                queryset.values(group_by_field)
                .annotate(value=Count("id"))
                .order_by("-value")
            )

        if not chart_data.exists():
            return None

        labels = []
        data = []
        urls = []

        section_info = get_section_info_for_model(model)

        for item in chart_data:
            label_value = item[group_by_field]

            try:
                field = model._meta.get_field(group_by_field)
                if hasattr(field, "choices") and field.choices:
                    for choice_value, choice_label in field.choices:
                        if choice_value == label_value:
                            label_value = choice_label
                            break
                elif field.is_relation and label_value is not None:
                    related_model = field.related_model
                    try:
                        related_obj = related_model.objects.get(pk=label_value)
                        label_value = str(related_obj)
                    except related_model.DoesNotExist:
                        pass
            except Exception:
                pass

            labels.append(str(label_value) if label_value is not None else "Unknown")
            data.append(float(item["value"]) if item["value"] is not None else 0)

            filter_value = item[group_by_field]
            try:
                field = model._meta.get_field(group_by_field)
                if field.is_relation:
                    filter_value = item.get(f"{group_by_field}_id", filter_value)
            except Exception:
                pass

            query = urlencode(
                {
                    "section": section_info["section"],
                    "apply_filter": "true",
                    "field": group_by_field,
                    "operator": "exact",
                    "value": filter_value,
                }
            )
            urls.append(f"{section_info['url']}?{query}")

        return {
            "title": component.name,
            "type": component.chart_type or "column",
            "data": {
                "labels": labels,
                "data": data,
                "urls": urls,
                "labelField": group_by_field.replace("_", " ").title(),
            },
            "is_from_report": True,  # Flag to identify report-based charts
            "report_name": report.name,
        }

    except Exception as e:
        logger.warning(
            "Failed to generate report chart for component %s: %s", component.id, e
        )
        return None


def get_chart_data(component, request):
    """
    Generate chart data for a dashboard component.
    Returns a dictionary with chart configuration.
    """
    try:
        if component.reports:
            return get_report_chart_data(component, request)
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

        queryset = get_queryset_for_module(request.user, model)

        conditions = component.conditions.all().order_by("sequence")
        queryset = apply_conditions(queryset, conditions)
        queryset = annotate_component_virtual_fields(queryset, model, component)

        if queryset.count() == 0:
            return None

        group_by_field = component.grouping_field

        if not group_by_field:
            return None

        try:
            field_obj = model._meta.get_field(group_by_field)
            is_fk = field_obj.is_relation
        except Exception:
            is_fk = False

        if is_fk:
            chart_data = (
                queryset.values(group_by_field, f"{group_by_field}_id")
                .annotate(value=Count("id"))
                .order_by("-value")
            )
        else:
            chart_data = (
                queryset.values(group_by_field)
                .annotate(value=Count("id"))
                .order_by("-value")
            )

        if not chart_data.exists():
            return None

        labels = []
        data = []
        urls = []

        section_info = get_section_info_for_model(model)

        for item in chart_data:
            label_value = item[group_by_field]

            try:
                field = model._meta.get_field(group_by_field)
                if hasattr(field, "choices") and field.choices:
                    for choice_value, choice_label in field.choices:
                        if choice_value == label_value:
                            label_value = choice_label
                            break
            except Exception:
                pass

            labels.append(str(label_value) if label_value is not None else "Unknown")
            data.append(float(item["value"]) if item["value"] is not None else 0)

            filter_value = item[group_by_field]
            try:
                field = model._meta.get_field(group_by_field)
                if field.is_relation:
                    filter_value = item.get(f"{group_by_field}_id", filter_value)
            except Exception:
                pass

            query = urlencode(
                {
                    "section": section_info["section"],
                    "apply_filter": "true",
                    "field": group_by_field,
                    "operator": "exact",
                    "value": filter_value,
                }
            )
            urls.append(f"{section_info['url']}?{query}")

        return {
            "title": component.name,
            "type": component.chart_type or "column",
            "data": {
                "labels": labels,
                "data": data,
                "urls": urls,
                "labelField": group_by_field.replace("_", " ").title(),
            },
            "is_report": component.reports is not None,
        }

    except Exception as e:
        logger.warning("Failed to generate chart for component %s: %s", component.id, e)
        return None


def get_table_data(component, request):
    """
    Generate table data and context for a dashboard component using HorillaListView.
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
        return None, {}

    queryset = get_viewable_queryset(request.user, model)
    if component.reports:
        queryset = apply_report_table_queryset(queryset, component.reports)
    conditions = component.conditions.all().order_by("sequence")
    queryset = apply_conditions(queryset, conditions)
    queryset = annotate_component_virtual_fields(queryset, model, component)

    date_range = request.GET.get("date_range")
    if date_range and (
        str(date_range) in [str(d) for d in DATE_RANGE_CHOICES]
        or date_range == "custom"
    ):
        date_from = request.GET.get("date_from") if date_range == "custom" else None
        date_to = request.GET.get("date_to") if date_range == "custom" else None
        queryset = apply_date_range_to_queryset(
            queryset, model, date_range, date_from=date_from, date_to=date_to
        )

    # Sorting uses the list view's own rules (sort_keys, e.g. "name:asc,date:desc").
    sorter = HorillaListView(model=model, request=request)
    sort_pairs = []
    for token in request.GET.get("sort_keys", "").split(","):
        token = token.strip()
        if ":" in token:
            field_name, direction = token.rsplit(":", 1)
            sort_pairs.append((field_name.strip(), direction.strip()))
        elif token:
            sort_pairs.append((token, "asc"))
    if sort_pairs:
        queryset = sorter._apply_multi_sorting(queryset, sort_pairs)
    elif request.GET.get("sort"):
        queryset = sorter._apply_sorting(
            queryset, request.GET["sort"], request.GET.get("direction", "asc")
        )
    queryset = queryset.order_by(*queryset.query.order_by, "id")

    paginator = Paginator(queryset, 10)
    page = request.GET.get("page", 1)
    page_obj = paginator.get_page(page)
    has_next = page_obj.has_next()
    next_page = page_obj.next_page_number() if has_next else None

    columns = []
    if component.reports:
        selected_columns = component.reports.selected_columns_list
    elif component.columns:
        try:
            if isinstance(component.columns, str):
                if component.columns.startswith("["):
                    selected_columns = json.loads(component.columns)
                else:
                    selected_columns = [
                        col.strip()
                        for col in component.columns.split(",")
                        if col.strip()
                    ]
            else:
                selected_columns = component.columns
        except Exception:
            selected_columns = []
    else:
        selected_columns = []
        for field in model._meta.get_fields()[:5]:
            if field.concrete and not field.is_relation:
                selected_columns.append(field.name)

    for column in selected_columns:
        virtual_field = get_virtual_field(model, column)
        if virtual_field is not None:
            if virtual_field.show_in_detail:
                columns.append((virtual_field.verbose_name, column))
            continue
        try:
            field = model._meta.get_field(column)
            verbose_name = field.verbose_name or column.replace("_", " ").title()
            if hasattr(field, "choices") and field.choices:
                columns.append((verbose_name, f"get_{column}_display"))
            else:
                columns.append((verbose_name, column))
        except Exception:
            continue

    if not columns:
        for field in model._meta.get_fields()[:3]:
            if field.concrete and not field.is_relation:
                columns.append(
                    (
                        field.verbose_name or field.name.replace("_", " ").title(),
                        field.name,
                    )
                )

    query_params = request.GET.urlencode()

    table_data_url = reverse_lazy(
        "dashboard:component_table_data",
        kwargs={"component_id": component.id},
    )

    list_view = HorillaListView(
        model=model,
        view_id=f"dashboard_component_{component.id}",
        search_url=table_data_url,
        # sorting reloads only this table, from the component's own endpoint
        main_url=table_data_url,
        table_width=False,
        filterset_class=getattr(model, "FilterSet", None),
        columns=columns,
    )
    list_view.request = request
    list_view.table_width = False
    list_view.main_session_id = list_view.view_id
    list_view.bulk_select_option = True
    list_view.bulk_export_option = True
    list_view.bulk_update_option = False
    list_view.bulk_delete_enabled = False
    list_view.list_column_visibility = False
    list_view.table_height_as_class = "h-[300px]"
    list_view.object_list = page_obj.object_list
    list_view.enable_sorting = True
    list_view.has_next = has_next
    list_view.next_page = next_page
    list_view.search_params = query_params
    list_view.model_verbose_name = model._meta.verbose_name_plural
    list_view.total_records_count = queryset.count()
    list_view.selected_ids_json = json.dumps([])
    list_view.list_column_visibility = False

    filtered_ids = list(queryset.values_list("id", flat=True))
    list_view.selected_ids_json = json.dumps(filtered_ids)

    first_col_field = None
    if columns:
        first_col_field = columns[0][1]
        if first_col_field.startswith("get_") and first_col_field.endswith("_display"):
            first_col_field = first_col_field[4:-8]

    first_obj = page_obj.object_list[0] if page_obj.object_list else None
    col_attrs = {}

    if first_col_field and hasattr(model, "get_detail_url") and first_obj:
        if request.user.has_perm(
            f"{model._meta.app_label}.view_{model._meta.model_name}"
        ):
            section_info = get_section_info_for_model(model)
            section = section_info["section"]

            col_attrs[first_col_field] = {
                "hx-get": f"{first_obj.get_detail_url()}?section={section}",
                "hx-target": "#mainContent",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "hx-select": "#mainContent",
                "hx-select-oob": "#sideMenuContainer",
                "class": "hover:text-primary-600",
                "style": "cursor:pointer;",
            }

    context = list_view.get_context_data(object_list=page_obj.object_list)

    context.update(
        {
            "no_record_msg": _(
                f"No {model._meta.verbose_name_plural} found matching the specified criteria."
            ),
            "header_attrs": {},
            "col_attrs": col_attrs,
            "visible_actions": [],
            "custom_bulk_actions": [],
            "additional_action_button": [],
            "filter_set_class": None,
            "filter_fields": list_view._get_model_fields(),
            "total_records_count": queryset.count(),
            "selected_ids": filtered_ids,
            "selected_ids_json": json.dumps(filtered_ids),
            "queryset": page_obj.object_list,
            "page_obj": page_obj,
            "search_url": table_data_url,
            "search_params": query_params,
            "has_next": has_next,
            "next_page": next_page,
            "component": component,
            "view_id": f"dashboard_component_{component.id}",
            "app_label": model._meta.app_label,
            "model_name": model._meta.model_name,
            "model_verbose_name": model._meta.verbose_name_plural,
        }
    )

    return model, context
