"""Views for filtering and listing report data."""

# Standard library imports
import logging
from urllib.parse import urlencode

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import HorillaListView
from horilla.contrib.utils.methods import get_section_info_for_model
from horilla.db.models import ForeignKey, Q
from horilla.shortcuts import render
from horilla.urls import reverse_lazy
from horilla.utils.choices import TABLE_FALLBACK_FIELD_TYPES
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View

# Local imports
from ..models import Report
from ..utils import (
    NO_VALUE_OPERATORS,
    annotate_virtual_fields,
    build_report_filter_q,
    coerce_virtual_filter_value,
    resolve_report_field,
)
from .toolkit.report_helper import create_temp_report_with_preview

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["reports.view_report", "reports.view_own_report"]),
    name="dispatch",
)
class ReportDetailFilteredView(LoginRequiredMixin, View):
    """View for displaying filtered report data with dynamic column and row grouping."""

    def col_attrs(self):
        """Define column attributes for clickable rows in the report list view."""
        query_params = {}
        pk = self.kwargs.get("pk")
        report = Report.objects.get(pk=pk)

        model_class = report.model_class
        section = get_section_info_for_model(model_class)
        section_value = section["section"]
        query_params["section"] = section_value
        query_string = urlencode(query_params)
        attrs = {}

        if self.request.user.has_perm("reports.view_report"):
            attrs = {
                "hx-get": f"{{get_detail_url}}?{query_string}",
                "hx-target": "#mainContent",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "hx-on:click": "closeContentModal()",
                "hx-select": "#mainContent",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }

        columns_with_attrs = []

        for col in report.selected_columns_list:
            columns_with_attrs.append({col: {**attrs}})

        return columns_with_attrs

    def get(self, request, pk, *args, **kwargs):
        """Handle GET request to render the report detail or preview."""
        # Get the report
        try:
            report = Report.objects.get(pk=pk)
        except Report.DoesNotExist:
            return render(request, "list_view.html")

        # Check if we have preview data in session
        session_key = f"report_preview_{report.pk}"
        preview_data = request.session.get(session_key, {})

        # Create a temporary report object with preview data
        temp_report = self.create_temp_report(report, preview_data)

        model_class = temp_report.model_class
        queryset = model_class.objects.all()

        # Apply original report filters using temp_report
        filters = temp_report.filters_dict
        if filters:
            queryset = annotate_virtual_fields(
                queryset,
                model_class,
                [
                    filter_data.get("original_field", field_name)
                    for field_name, filter_data in filters.items()
                ],
            )
            try:
                # Use the same filter logic as ReportDetailView
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
                    value = coerce_virtual_filter_value(
                        model_class, actual_field, value
                    )

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
                    queryset = queryset.filter(query)
            except Exception as e:
                logger.error("Filter Error in ReportDetailFilteredView: %s", e)
                queryset = model_class.objects.none()

        row_group1 = request.GET.get("row_group1")
        row_group2 = request.GET.get("row_group2")
        row_group3 = request.GET.get("row_group3")
        col = request.GET.get("col")
        col1 = request.GET.get("col1")
        col2 = request.GET.get("col2")
        # simple_aggregate = request.GET.get("simple_aggregate")

        # Use temp_report instead of report for row_groups and column_groups
        row_fields = temp_report.row_groups_list
        col_fields = temp_report.column_groups_list
        filter_kwargs = {}

        def get_dynamic_lookup_fields(related_model, original_field_name):
            """
            Dynamically determine lookup fields for a related model.
            Returns a list of field names to try for lookups.
            """
            lookup_fields = []

            # Get all fields from the related model
            for field in related_model._meta.get_fields():
                if hasattr(field, "name"):
                    field_name = field.name

                    # Prioritize common display fields
                    if field_name in ["name", "title", "display_name", "label"]:
                        lookup_fields.insert(0, field_name)  # Add to front
                    # Include string/char fields that might be used for display
                    elif (
                        hasattr(field, "get_internal_type")
                        and field.get_internal_type() in TABLE_FALLBACK_FIELD_TYPES[:2]
                    ):  # [CharField, TextField]
                        lookup_fields.append(field_name)

            # Add the original field name as fallback
            if original_field_name not in lookup_fields:
                lookup_fields.append(original_field_name)

            # Add 'pk' and 'id' as final fallbacks
            if "pk" not in lookup_fields:
                lookup_fields.append("pk")
            if "id" not in lookup_fields:
                lookup_fields.append("id")

            return lookup_fields

        def get_filter_value(field_name, value, model):
            """Convert a filter string/value into an actual model field value for lookup."""
            if value is None or not field_name:
                return None
            try:
                field = resolve_report_field(model, field_name)
                if isinstance(field, ForeignKey):
                    if isinstance(value, str) and "||" in value:
                        parts = value.split("||")
                        if len(parts) == 2:
                            try:
                                pk_value = int(parts[1])
                                related_model = field.related_model
                                try:
                                    return related_model.objects.get(pk=pk_value)
                                except related_model.DoesNotExist:
                                    logger.warning(
                                        "Related object not found with pk=%s", pk_value
                                    )
                                    return None
                            except (ValueError, TypeError):
                                value = parts[0]  # Use display part for lookup

                    related_model = field.related_model
                    lookup_fields = get_dynamic_lookup_fields(related_model, field_name)

                    for lookup_field in lookup_fields:
                        try:
                            related_obj = related_model.objects.get(
                                **{lookup_field: value}
                            )
                            return related_obj
                        except related_model.DoesNotExist:
                            continue
                        except AttributeError:
                            continue
                        except Exception as e:
                            logger.error("Error trying lookup %s: %s", lookup_field, e)
                            continue

                    # If exact match fails, try case-insensitive for string fields
                    for lookup_field in lookup_fields:
                        try:
                            field_obj = related_model._meta.get_field(lookup_field)
                            if (
                                hasattr(field_obj, "get_internal_type")
                                and field_obj.get_internal_type()
                                in TABLE_FALLBACK_FIELD_TYPES[:2]
                            ):  # [CharField, TextField]
                                related_obj = related_model.objects.get(
                                    **{f"{lookup_field}__iexact": value}
                                )
                                return related_obj
                        except (related_model.DoesNotExist, AttributeError, Exception):
                            continue
                    return None
                if field.choices:
                    # Check if value is a composite key for choices
                    if isinstance(value, str) and "||" in value:
                        parts = value.split("||")
                        value = parts[0]  # Use display part

                    choice_map = {
                        display.lower(): value for value, display in field.choices
                    }
                    normalized_value = value.lower()
                    if normalized_value in choice_map:
                        return choice_map[normalized_value]
                    return value  # Fallback to original value if no match
                # else:
                # For non-FK fields, check if it's a composite key and extract the value
                if isinstance(value, str) and "||" in value:
                    parts = value.split("||")
                    # For non-FK fields, try to convert to appropriate type
                    try:
                        if hasattr(field, "get_internal_type"):
                            field_type = field.get_internal_type()
                            if field_type in [
                                "IntegerField",
                                "BigIntegerField",
                                "SmallIntegerField",
                            ]:
                                return int(parts[1])
                            if field_type in ["FloatField", "DecimalField"]:
                                return float(parts[1])
                    except (ValueError, TypeError, IndexError):
                        pass
                    # If conversion fails, use the display part
                    value = parts[0]
                return value
            except Exception as e:
                logger.error(
                    "Error resolving filter value for %s=%s: %s", field_name, value, e
                )
                return None

        def apply_group_filter(field_name, value, model, fkwargs):
            """Apply a pivot group filter, handling empty/null values correctly."""
            if field_name is None:
                return None
            if value == "":
                # Empty string means the field is null or blank — return a Q for OR handling
                try:
                    field = resolve_report_field(model, field_name)
                    if isinstance(field, ForeignKey):
                        return Q(**{f"{field_name}__isnull": True})
                    return Q(**{f"{field_name}__isnull": True}) | Q(**{field_name: ""})
                except Exception:
                    return Q(**{f"{field_name}__isnull": True})
            filter_value = get_filter_value(field_name, value, model)
            if filter_value is not None:
                fkwargs[field_name] = filter_value
            return None

        null_q_filters = []

        if row_group1 is not None and row_fields:
            q = apply_group_filter(
                row_fields[0], row_group1, model_class, filter_kwargs
            )
            if q is not None:
                null_q_filters.append(q)
        if row_group2 is not None and len(row_fields) > 1:
            q = apply_group_filter(
                row_fields[1], row_group2, model_class, filter_kwargs
            )
            if q is not None:
                null_q_filters.append(q)
        if row_group3 is not None and len(row_fields) > 2:
            q = apply_group_filter(
                row_fields[2], row_group3, model_class, filter_kwargs
            )
            if q is not None:
                null_q_filters.append(q)
        if col is not None and col_fields:
            q = apply_group_filter(col_fields[0], col, model_class, filter_kwargs)
            if q is not None:
                null_q_filters.append(q)
        if col1 is not None and col2 is not None and len(col_fields) > 1:
            q1 = apply_group_filter(col_fields[0], col1, model_class, filter_kwargs)
            q2 = apply_group_filter(col_fields[1], col2, model_class, filter_kwargs)
            if q1 is not None:
                null_q_filters.append(q1)
            if q2 is not None:
                null_q_filters.append(q2)
        # if simple_aggregate and temp_report.aggregate_columns_dict.get('field'):
        # filter_kwargs[temp_report.aggregate_columns_dict['field']] = simple_aggregate

        if filter_kwargs or null_q_filters:
            try:
                if filter_kwargs:
                    queryset = queryset.filter(**filter_kwargs)
                for q in null_q_filters:
                    queryset = queryset.filter(q)
            except Exception as e:
                logger.error("Filter Error: %s", e)
                queryset = model_class.objects.none()

        columns = []
        for col in temp_report.selected_columns_list:
            field = model_class._meta.get_field(col)
            verbose_name = field.verbose_name
            if field.choices:
                columns.append((verbose_name, f"get_{col}_display"))
            else:
                columns.append((verbose_name, col))

        list_view = HorillaListView(
            model=model_class,
            view_id="report-details",
            search_url=reverse_lazy(
                "reports:report_detail_filtered", kwargs={"pk": report.pk}
            ),
            main_url=reverse_lazy(
                "reports:report_detail_filtered", kwargs={"pk": report.pk}
            ),
            table_width=False,
            columns=columns,
        )
        list_view.request = request
        list_view.table_width = False
        list_view.table_auto = True
        list_view.bulk_select_option = False
        list_view.paginate_by = 10
        list_view.list_column_visibility = False
        list_view.table_height_as_class = "h-[200px]"
        if hasattr(report.model_class, "get_detail_url"):
            list_view.col_attrs = self.col_attrs()
        sort_field = self.request.GET.get("sort")
        sort_direction = self.request.GET.get("direction", "asc")
        if sort_field:
            queryset = list_view._apply_sorting(queryset, sort_field, sort_direction)
        else:
            queryset = queryset.order_by("-id")
        list_view.queryset = queryset
        list_view.object_list = queryset
        context = list_view.get_context_data(object_list=queryset)

        # Add no_record_msg if queryset is empty
        if not queryset.exists():
            context["no_record_msg"] = _("No records found")

        # Render only the list_view.html template
        return render(request, "list_view.html", context)

    def create_temp_report(self, original_report, preview_data):
        """Create a temporary report object with preview data (same as ReportDetailView)."""
        return create_temp_report_with_preview(original_report, preview_data)
