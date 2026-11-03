"""Views for providing field choices based on selected modules in dashboard."""

# Standard library imports
import logging

# Third-party imports (Django)
from django.utils.encoding import force_str

# First party imports (Horilla)
from horilla.apps import apps
from horilla.contrib.core.models import HorillaContentType
from horilla.shortcuts import render
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import HttpResponse

# Local imports
from ..field_choice_helpers import (
    add_current_metric_choice,
    get_displayable_field_choices,
    get_metric_choices,
)
from ..forms import get_dashboard_component_models

logger = logging.getLogger(__name__)


def _resolve_model_from_module(module):
    """
    Resolve model class from module param (content type pk or registry key).
    Prefer dashboard registry so we match the same model as the module dropdown.
    """
    if not module:
        return None
    if module.isdigit():
        try:
            content_type = HorillaContentType.objects.get(pk=module)
            module = content_type.model
        except HorillaContentType.DoesNotExist:
            return None
    module_key = (module or "").strip().lower()
    if not module_key:
        return None
    for key, model_cls in get_dashboard_component_models():
        if key == module_key:
            return model_cls
    # Fallback: first app with this model name
    for app_config in apps.get_app_configs():
        try:
            return apps.get_model(app_label=app_config.label, model_name=module_key)
        except LookupError:
            continue
    return None


class ExtraFieldChoicesView(View):
    """
    Base of the dashboard field-picker views.

    ``get_extra_choices`` is the extension point for fields that aren't model
    columns: it returns extra ``(name, label)`` pairs for a picker.
    ``purpose`` is "condition" (condition field list), "detail" (table
    column), "grouping" (chart grouping) or "numeric" (metric). Extensions
    override it.
    """

    def get_extra_choices(self, model, purpose):
        """Extra ``(name, label)`` pairs for ``purpose``; none by default."""
        return []

    def get_displayable_choices(self, model, purpose):
        """Model field choices for ``purpose`` followed by the extension's extras."""
        return get_displayable_field_choices(model) + [
            (name, force_str(label))
            for name, label in self.get_extra_choices(model, purpose)
        ]

    def get_numeric_metric_choices(self, model, current_metric):
        """Metric choices for ``model``, keeping ``current_metric`` selectable."""
        extra_fields = self.get_extra_choices(model, "numeric") if model else ()
        return add_current_metric_choice(
            get_metric_choices(model, extra_fields), current_metric
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("dashboard.add_dashboard"), name="dispatch"
)
class ModuleFieldChoicesView(ExtraFieldChoicesView):
    """
    Class-based view to return field choices for a selected module via HTMX.
    """

    def get(self, request, *args, **kwargs):
        """
        Handle GET request to return a <select> element with field choices.
        """
        module = request.GET.get("module")
        row_id = request.GET.get("row_id", "0")
        if not row_id.isdigit():
            row_id = "0"

        field_name = f"field_{row_id}"
        field_id = f"id_field_{row_id}"

        if module and module.isdigit():
            try:
                content_type = HorillaContentType.objects.get(pk=module)
                module = content_type.model
            except HorillaContentType.DoesNotExist:
                pass

        if not module:
            return render(
                request,
                "partials/field_select_empty.html",
                {"field_name": field_name, "field_id": field_id},
            )

        model = _resolve_model_from_module(module)
        if not model:
            return render(
                request,
                "partials/field_select_empty.html",
                {"field_name": field_name, "field_id": field_id},
            )

        # Same rules as the generic condition field list: forward fields only
        # (no reverse relations), editable, and without the default excludes.
        default_exclude = {
            "id",
            "pk",
            "additional_info",
        }
        model_fields = []
        for field in list(model._meta.fields) + list(model._meta.many_to_many):
            if field.name in default_exclude:
                continue
            if not getattr(field, "editable", True):
                continue
            verbose_name = (
                getattr(field, "verbose_name", None)
                or field.name.replace("_", " ").title()
            )
            model_fields.append((field.name, force_str(verbose_name)))

        model_fields.extend(
            (name, force_str(label))
            for name, label in self.get_extra_choices(model, "condition")
            if name not in default_exclude
        )

        field_choices = [("", "Select Field")] + model_fields

        return render(
            request,
            "partials/module_field_select.html",
            {
                "field_name": field_name,
                "field_id": field_id,
                "row_id": row_id,
                "model_name": module,
                "field_choices": field_choices,
            },
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("dashboard.add_dashboard"), name="dispatch"
)
class ColumnFieldChoicesView(ExtraFieldChoicesView):
    """
    View to return metric field choices for a selected module via HTMX.
    """

    def get(self, request, *args, **kwargs):
        """Handle GET request to return a <select> element with column field choices."""
        module = request.GET.get("module")

        if not module:
            return HttpResponse(
                '<select name="columns" id="id_columns" class="js-example-basic-multiple headselect" multiple ><option value="">---------</option></select>'
            )

        model = _resolve_model_from_module(module)
        if not model:
            return render(
                request,
                "partials/column_field_select_empty.html",
            )

        column_fields = self.get_displayable_choices(model, "detail")

        field_choices = [("", "Add Columns")] + column_fields

        return render(
            request,
            "partials/column_field_select.html",
            {"field_choices": field_choices},
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("dashboard.add_dashboard"), name="dispatch"
)
class GroupingFieldChoicesView(ExtraFieldChoicesView):
    """
    View to return grouping field choices for a selected module via HTMX.
    """

    def get(self, request, *args, **kwargs):
        """Handle GET request to return a <select> element with grouping field choices."""
        module = request.GET.get("module")
        current_grouping = (request.GET.get("grouping_field") or "").strip()

        model = _resolve_model_from_module(module)
        if not model:
            return render(
                request,
                "partials/grouping_field_select_empty.html",
            )

        grouping_fields = self.get_displayable_choices(model, "grouping")

        field_choices = [("", force_str(_("Select Grouping Field")))] + grouping_fields

        return render(
            request,
            "partials/grouping_field_select.html",
            {
                "field_choices": field_choices,
                "current_grouping": current_grouping,
            },
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("dashboard.add_dashboard"), name="dispatch"
)
class SecondaryGroupingFieldChoicesView(ExtraFieldChoicesView):
    """
    View to return secondary grouping field choices for a selected module via HTMX.
    """

    def get(self, request, *args, **kwargs):
        """Handle GET request to return a <select> element with secondary grouping field choices."""
        module = request.GET.get("module")
        current_secondary = (request.GET.get("secondary_grouping") or "").strip()

        model = _resolve_model_from_module(module)
        if not model:
            return render(
                request,
                "partials/secondary_grouping_field_select_empty.html",
            )

        grouping_fields = self.get_displayable_choices(model, "grouping")

        field_choices = [
            ("", force_str(_("Select Secondary Grouping Field")))
        ] + grouping_fields

        return render(
            request,
            "partials/secondary_grouping_field_select.html",
            {
                "field_choices": field_choices,
                "current_secondary": current_secondary,
            },
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("dashboard.add_dashboard"), name="dispatch"
)
class MetricFieldChoicesView(ExtraFieldChoicesView):
    """
    View to return metric type choices for KPI components based on the selected module.
    """

    def get(self, request, *args, **kwargs):
        """
        Build choices like:
        - Count of records
        - Sum/Average/Minimum/Maximum of each numeric field on the model.
        Only active when component_type == 'kpi'.
        """
        _component_type = (request.GET.get("component_type") or "").strip()

        module = request.GET.get("module")
        current_metric = (request.GET.get("metric_type") or "").strip()

        model = _resolve_model_from_module(module)
        metric_choices = self.get_numeric_metric_choices(model, current_metric)

        return render(
            request,
            "partials/metric_field_select.html",
            {
                "field_choices": metric_choices,
                "current_metric": current_metric or "count",
            },
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("dashboard.add_dashboard"), name="dispatch"
)
class YAxisMetricFieldChoicesView(ExtraFieldChoicesView):
    """
    View to return y-axis metric type choices for chart components based on the selected module.
    Uses the same logic as MetricFieldChoicesView but binds to the y_axis_metric_type field.
    """

    def get(self, request, *args, **kwargs):
        """Method to handle GET request and return metric choices for y-axis based on the selected module."""
        component_type = (request.GET.get("component_type") or "").strip()
        # Only charts use the dedicated y-axis metric; others fall back to simple count.
        if component_type != "chart":
            metric_choices = [("count", "Count of records")]
            current_metric = (request.GET.get("y_axis_metric_type") or "").strip()
            return render(
                request,
                "partials/y_axis_metric_field_select.html",
                {
                    "field_choices": metric_choices,
                    "current_metric": current_metric or "count",
                },
            )

        module = request.GET.get("module")
        current_metric = (request.GET.get("y_axis_metric_type") or "").strip()

        model = _resolve_model_from_module(module)
        metric_choices = self.get_numeric_metric_choices(model, current_metric)

        return render(
            request,
            "partials/y_axis_metric_field_select.html",
            {
                "field_choices": metric_choices,
                "current_metric": current_metric or "count",
            },
        )
