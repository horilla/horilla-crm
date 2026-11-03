"""Forms for dashboards app."""

# Standard library imports
import json
import logging

# Third-party imports (Django)
from django import forms

# First party imports (Horilla)
from horilla.apps import apps
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.forms import HorillaModelForm
from horilla.registry.feature import FEATURE_REGISTRY
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .field_choice_helpers import (
    add_current_metric_choice,
    get_displayable_field_choices,
    get_metric_choices,
)
from .models import ComponentCriteria, Dashboard, DashboardComponent, DashboardFolder

logger = logging.getLogger(__name__)


def get_dashboard_component_models():
    """
    Return a list of (module_key, model_class) for every model that
    is registered for dashboard components.
    """
    models = []
    for model_cls in FEATURE_REGISTRY.get("dashboard_component_models", []):
        key = model_cls.__name__.lower()
        models.append((key, model_cls))
    return models


class DashboardForm(HorillaModelForm):
    """Form for creating and and editing dashboards"""

    field_order = [
        "name",
        "description",
        "folder",
        "is_default",
        "dashboard_owner",
    ]

    class Meta:
        """Meta options for DashboardForm."""

        model = Dashboard
        fields = "__all__"
        exclude = ["favourited_by"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["folder"].queryset = (
            DashboardFolder.objects.all()
            if self.request.user.is_superuser
            else DashboardFolder.objects.filter(folder_owner=self.request.user)
        )


class DashboardCreateForm(HorillaModelForm):
    """Dashboard Create Form"""

    htmx_field_choices_url = "dashboard:get_module_field_choices"

    def get_extra_choices(self, model, purpose):
        """
        Extra ``(name, label)`` pairs for a field picker, for fields that aren't
        model columns. ``purpose`` is "detail" (table column), "grouping"
        (chart grouping) or "numeric" (metric). Extensions override this.
        """
        return []

    field_order = [
        "name",
        "component_type",
        "chart_type",
        "module",
        "grouping_field",
        "secondary_grouping",
        "metric_type",
        "y_axis_metric_type",
        "columns",
        "icon",
        "dashboard",
        "sequence",
        "component_owner",
        "reports",
    ]

    class Meta:
        """Meta class for DashboardCreateForm"""

        model = DashboardComponent
        fields = "__all__"
        widgets = {
            "component_type": forms.Select(
                attrs={
                    "id": "id_component_type",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        self.row_id = kwargs.pop("row_id", "0")
        kwargs["condition_model"] = ComponentCriteria
        self.instance_obj = kwargs.get("instance")
        request = kwargs.get("request")
        self.request = request

        super().__init__(*args, **kwargs)

        if self.instance_obj and self.instance_obj.pk and self.instance_obj.columns:
            if isinstance(self.instance_obj.columns, str):
                try:
                    parsed = json.loads(self.instance_obj.columns)
                    if isinstance(parsed, list):
                        self.instance_obj.columns = parsed
                except json.JSONDecodeError:
                    pass

        # Get model_name after base class initialization
        model_name = getattr(self, "model_name", None)

        if "module" in self.fields and request and hasattr(request, "user"):
            user = request.user
            allowed_modules = []

            for module_key, model_cls in get_dashboard_component_models():
                app_label = model_cls._meta.app_label
                meta_model_name = model_cls._meta.model_name

                view_perm = f"{app_label}.view_{meta_model_name}"
                view_own_perm = f"{app_label}.view_own_{meta_model_name}"

                if user.has_perm(view_perm) or user.has_perm(view_own_perm):
                    label = model_cls._meta.verbose_name
                    allowed_modules.append((module_key, label))

            if not self.instance_obj or not self.instance_obj.pk:
                self.fields["module"].choices = [("", "---------")] + allowed_modules
                self.fields["module"].initial = ""
            else:
                self.fields["module"].choices = allowed_modules

        def hide_fields(field_list, nullify=False):
            for name in field_list:
                if name in self.fields:
                    self.fields[name].widget = forms.HiddenInput(
                        attrs={"required": False}
                    )
                    if nullify:
                        self.fields[name].initial = None
                        if self.data:
                            self.data = self.data.copy()
                            self.data[name] = None

        # Hide fields based on component_type.
        if (
            hasattr(self, "request")
            and getattr(self.request, "method", "").upper() == "POST"
        ):
            component_type = (
                self.data.get("component_type")
                or self.request.POST.get("component_type")
                or (self.instance_obj.component_type if self.instance_obj else "")
            )

        else:
            component_type = self.request.GET.get("component_type") or (
                self.instance_obj.component_type if self.instance_obj else ""
            )

        nullify_values = (
            self.request.method == "GET" if hasattr(self, "request") else True
        )
        if component_type != "chart":
            hide_fields(
                [
                    "chart_type",
                    "secondary_grouping",
                    "grouping_field",
                    "y_axis_metric_type",
                ],
                nullify=nullify_values,
            )
        else:
            # Hide secondary_grouping unless chart type uses two groupings
            two_group_chart_types = [
                "stacked_vertical",
                "stacked_horizontal",
                "radar",
                "heatmap",
                "sankey",
            ]
            if (
                hasattr(self, "request")
                and getattr(self.request, "method", "").upper() == "POST"
            ):
                chart_type = (
                    self.data.get("chart_type")
                    or self.request.POST.get("chart_type")
                    or (
                        getattr(self.instance_obj, "chart_type", None)
                        if self.instance_obj
                        else ""
                    )
                )
            else:
                chart_type = self.request.GET.get("chart_type") or (
                    getattr(self.instance_obj, "chart_type", None)
                    if self.instance_obj
                    else ""
                )
            if chart_type not in two_group_chart_types:
                hide_fields(["secondary_grouping"], nullify=nullify_values)

        if component_type != "kpi":
            hide_fields(["icon", "metric_type"], nullify=nullify_values)
        else:
            if "metric_type" in self.fields:
                model = None

                # 1) Prefer the instance's module when editing
                if (
                    self.instance_obj
                    and getattr(self.instance_obj, "module", None)
                    and getattr(self.instance_obj.module, "model", None)
                ):
                    instance_model_name = self.instance_obj.module.model
                    for app_config in apps.get_app_configs():
                        try:
                            model = apps.get_model(
                                app_label=app_config.label,
                                model_name=instance_model_name.lower(),
                            )
                            break
                        except LookupError:
                            continue

                # 2) Fallback to module value coming from the form (create flow)
                if not model:
                    module_value = (
                        (self.data.get("module") or "").strip()
                        if hasattr(self, "data")
                        else ""
                    )
                    if not module_value and hasattr(self, "request"):
                        module_value = (
                            self.request.GET.get("module")
                            or self.request.POST.get("module")
                            or ""
                        )

                    if module_value:
                        # If it's a HorillaContentType id, resolve to model name
                        if module_value.isdigit():
                            try:
                                ct = HorillaContentType.objects.get(pk=module_value)
                                module_key = (ct.model or "").strip().lower()
                            except Exception:
                                module_key = ""
                        else:
                            module_key = module_value.strip().lower()

                        if module_key:
                            # First, check the dashboard registry
                            for key, model_cls in get_dashboard_component_models():
                                if key == module_key:
                                    model = model_cls
                                    break

                            # Fallback: search installed apps
                            if not model:
                                for app_config in apps.get_app_configs():
                                    try:
                                        model = apps.get_model(
                                            app_label=app_config.label,
                                            model_name=module_key,
                                        )
                                        break
                                    except LookupError:
                                        continue

                metric_choices = get_metric_choices(
                    model, self.get_extra_choices(model, "numeric") if model else ()
                )

                current_metric = (
                    (self.data.get("metric_type") or "").strip()
                    if hasattr(self, "data")
                    else ""
                )
                if (
                    not current_metric
                    and self.instance_obj
                    and getattr(self.instance_obj, "metric_type", None)
                ):
                    current_metric = (self.instance_obj.metric_type or "").strip()
                if not current_metric:
                    current_metric = (
                        (self.initial.get("metric_type") or "").strip()
                        if hasattr(self, "initial")
                        else ""
                    )

                add_current_metric_choice(metric_choices, current_metric)

                self.fields["metric_type"] = forms.ChoiceField(
                    choices=metric_choices,
                    required=False,
                    initial=current_metric or "count",
                    widget=forms.Select(
                        attrs={
                            "class": "js-example-basic-single headselect",
                            "id": "id_metric_type",
                            "name": "metric_type",
                        }
                    ),
                )

        # For chart components, provide a y-axis metric selector that mirrors KPI metric choices.
        if component_type == "chart":
            if "y_axis_metric_type" in self.fields:
                model = None

                if (
                    self.instance_obj
                    and getattr(self.instance_obj, "module", None)
                    and getattr(self.instance_obj.module, "model", None)
                ):
                    instance_model_name = self.instance_obj.module.model
                    for app_config in apps.get_app_configs():
                        try:
                            model = apps.get_model(
                                app_label=app_config.label,
                                model_name=instance_model_name.lower(),
                            )
                            break
                        except LookupError:
                            continue

                if not model:
                    module_value = (
                        (self.data.get("module") or "").strip()
                        if hasattr(self, "data")
                        else ""
                    )
                    if not module_value and hasattr(self, "request"):
                        module_value = (
                            self.request.GET.get("module")
                            or self.request.POST.get("module")
                            or ""
                        )

                    if module_value:
                        if module_value.isdigit():
                            try:
                                ct = HorillaContentType.objects.get(pk=module_value)
                                module_key = (ct.model or "").strip().lower()
                            except Exception:
                                module_key = ""
                        else:
                            module_key = module_value.strip().lower()

                        if module_key:
                            for key, model_cls in get_dashboard_component_models():
                                if key == module_key:
                                    model = model_cls
                                    break

                            if not model:
                                for app_config in apps.get_app_configs():
                                    try:
                                        model = apps.get_model(
                                            app_label=app_config.label,
                                            model_name=module_key,
                                        )
                                        break
                                    except LookupError:
                                        continue

                y_metric_choices = get_metric_choices(
                    model, self.get_extra_choices(model, "numeric") if model else ()
                )

                current_y_metric = (
                    (self.data.get("y_axis_metric_type") or "").strip()
                    if hasattr(self, "data")
                    else ""
                )
                if (
                    not current_y_metric
                    and self.instance_obj
                    and getattr(self.instance_obj, "y_axis_metric_type", None)
                ):
                    current_y_metric = (
                        self.instance_obj.y_axis_metric_type or ""
                    ).strip()
                if not current_y_metric:
                    current_y_metric = (
                        (self.initial.get("y_axis_metric_type") or "").strip()
                        if hasattr(self, "initial")
                        else ""
                    )

                add_current_metric_choice(y_metric_choices, current_y_metric)

                self.fields["y_axis_metric_type"] = forms.ChoiceField(
                    choices=y_metric_choices,
                    required=False,
                    initial=current_y_metric or "count",
                    widget=forms.Select(
                        attrs={
                            "class": "js-example-basic-single headselect",
                            "id": "id_y_axis_metric_type",
                            "name": "y_axis_metric_type",
                        }
                    ),
                )

        if component_type == "table_data":
            hide_fields(
                ["grouping_field", "metric_field", "metric_type", "y_axis_metric_type"],
                nullify=nullify_values,
            )

        if component_type != "table_data":
            hide_fields(["columns"], nullify=True)
        else:
            if "columns" in self.fields:
                if (
                    self.instance_obj
                    and self.instance_obj.pk
                    and self.instance_obj.columns
                ):
                    instance_model_name = None
                    if self.instance_obj.module:
                        instance_model_name = self.instance_obj.module.model

                    if instance_model_name:
                        if isinstance(self.instance_obj.columns, str):
                            if self.instance_obj.columns.startswith("["):
                                columns_list = json.loads(self.instance_obj.columns)
                            else:
                                columns_list = [
                                    col.strip()
                                    for col in self.instance_obj.columns.split(",")
                                    if col.strip()
                                ]
                        else:
                            columns_list = (
                                self.instance_obj.columns
                                if isinstance(self.instance_obj.columns, list)
                                else []
                            )

                        # Find the model
                        model = None
                        for app_config in apps.get_app_configs():
                            try:
                                model = apps.get_model(
                                    app_label=app_config.label,
                                    model_name=instance_model_name.lower(),
                                )
                                break
                            except LookupError:
                                continue

                        if model:
                            column_choices = get_displayable_field_choices(model)
                            column_choices.extend(
                                self.get_extra_choices(model, "detail")
                            )

                            # Recreate the field with choices
                            if self.request.method == "GET":
                                self.fields["columns"] = forms.MultipleChoiceField(
                                    choices=column_choices,
                                    required=False,
                                    widget=forms.SelectMultiple(
                                        attrs={
                                            "class": "js-example-basic-multiple headselect",
                                            "id": "id_columns",
                                            "name": "columns",
                                            "data-placeholder": _("Add Columns"),
                                            "tabindex": "-1",
                                            "aria-hidden": "true",
                                            "multiple": True,
                                        }
                                    ),
                                )

                            # Set the initial value with the saved columns
                            self.initial["columns"] = columns_list
                else:
                    # New instance - set up empty multi-select
                    self.fields["columns"].widget = forms.SelectMultiple(
                        attrs={
                            "class": "js-example-basic-multiple headselect",
                            "id": "id_columns",
                            "name": "columns",
                            "data-placeholder": _("Add Columns"),
                            "tabindex": "-1",
                            "aria-hidden": "true",
                            "multiple": True,
                        }
                    )

        if "module" in self.fields:
            module_field = self.fields.get("module")
            if module_field and hasattr(module_field.widget, "attrs"):
                module_field.widget.attrs.update(
                    {
                        "hx-get-grouping": reverse_lazy(
                            "dashboard:get_grouping_field_choices"
                        ),
                        "hx-target-grouping": "#id_grouping_field_container",
                        "hx-get-columns": reverse_lazy(
                            "dashboard:get_columns_field_choices"
                        ),
                        "hx-target-columns": "#columns_container",
                        "hx-get-secondary-grouping": reverse_lazy(
                            "dashboard:get_secondary_grouping_field_choices"
                        ),
                        "hx-target-secondary-grouping": "#id_secondary_grouping_container",
                    }
                )

        if self.instance_obj and self.instance_obj.pk and model_name:
            self._initialize_select_fields_for_edit(model_name)
        elif self.instance_obj and self.instance_obj.pk and self.instance_obj.module_id:
            self._initialize_select_fields_for_edit(str(self.instance_obj.module_id))
        else:
            module_value = ""
            if hasattr(self, "data") and self.data:
                module_value = (self.data.get("module") or "").strip()
            if not module_value and hasattr(self, "request"):
                module_value = (self.request.GET.get("module") or "").strip() or (
                    self.request.POST.get("module") or ""
                ).strip()
            if module_value:
                self._initialize_select_fields_for_edit(module_value)

    def _initialize_select_fields_for_edit(self, model_name):
        """Initialize select fields in edit mode by mimicking HTMX view behavior"""
        try:
            # Get component_type / chart_type to check which fields should be visible
            component_type = self.request.GET.get("component_type") or (
                self.instance_obj.component_type if self.instance_obj else ""
            )
            chart_type = self.request.GET.get("chart_type") or (
                getattr(self.instance_obj, "chart_type", None)
                if self.instance_obj
                else ""
            )

            model = None
            if model_name:
                module_key = (model_name or "").strip().lower()
                if model_name.isdigit():
                    try:
                        ct = HorillaContentType.objects.get(pk=model_name)
                        module_key = (ct.model or "").strip().lower()
                    except Exception:
                        module_key = ""
                for key, model_cls in get_dashboard_component_models():
                    if key == module_key:
                        model = model_cls
                        break
                if not model and module_key:
                    for app_config in apps.get_app_configs():
                        try:
                            model = apps.get_model(
                                app_label=app_config.label,
                                model_name=module_key,
                            )
                            break
                        except LookupError:
                            continue

            if not model:
                return

            # Only initialize grouping_field if component_type is 'chart'
            if "grouping_field" in self.fields and component_type == "chart":
                grouping_fields = get_displayable_field_choices(model)
                grouping_fields.extend(self.get_extra_choices(model, "grouping"))

                current_value = (
                    getattr(self.instance_obj, "grouping_field", "")
                    if self.instance_obj
                    else ""
                )
                self.fields["grouping_field"] = forms.ChoiceField(
                    choices=[("", "Select Grouping Field")] + grouping_fields,
                    required=False,
                    initial=current_value,
                    widget=forms.Select(
                        attrs={
                            "class": "js-example-basic-single headselect",
                            "id": "id_grouping_field",
                            "name": "grouping_field",
                        }
                    ),
                )

            # Only initialize secondary_grouping if component_type is 'chart'
            # AND the chart type actually supports a second grouping axis.
            two_group_chart_types = [
                "stacked_vertical",
                "stacked_horizontal",
                "radar",
                "heatmap",
                "sankey",
            ]
            if (
                "secondary_grouping" in self.fields
                and component_type == "chart"
                and (chart_type or "") in two_group_chart_types
            ):
                secondary_grouping_fields = get_displayable_field_choices(model)
                secondary_grouping_fields.extend(
                    self.get_extra_choices(model, "grouping")
                )

                if self.instance_obj:
                    current_value = (
                        getattr(self.instance_obj, "secondary_grouping", None) or ""
                    )
                else:
                    current_value = ""
                self.fields["secondary_grouping"] = forms.ChoiceField(
                    choices=[("", "Select Secondary Grouping Field")]
                    + secondary_grouping_fields,
                    required=False,
                    initial=current_value,
                    widget=forms.Select(
                        attrs={
                            "class": "js-example-basic-single headselect",
                            "id": "id_secondary_grouping",
                            "name": "secondary_grouping",
                        }
                    ),
                )

        except Exception as e:
            logger.error("Error initializing select fields for edit: {%s}", e)

    def clean(self):
        """Process columns field and extract condition_rows"""
        cleaned_data = super().clean()

        # Extract condition_rows using base class method
        if self.condition_fields:
            condition_rows = self._extract_condition_rows()
            cleaned_data["condition_rows"] = condition_rows

        return cleaned_data

    def clean_columns(self):
        """Clean the columns field to store as JSON list string."""

        component_type = (self.data.get("component_type") or "").strip()
        if not component_type and self.instance_obj:
            component_type = getattr(self.instance_obj, "component_type", "") or ""
        if component_type and component_type != "table_data":
            return ""

        raw_columns = self.data.getlist("columns")
        columns = self.cleaned_data.get("columns")

        if raw_columns:
            columns = raw_columns

        elif isinstance(columns, str):
            columns = [col.strip() for col in columns.split(",") if col.strip()]

        elif not isinstance(columns, (list, tuple)):
            columns = raw_columns if raw_columns else [columns]

        if not columns:
            return ""

        column_list = []
        for col in columns:
            if not col:
                continue
            s = str(col).strip()
            # Avoid nested JSON strings from bad double-submit (preview include)
            if s.startswith("[") and s.endswith("]") and len(s) > 80:
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, list):
                        column_list.extend(str(x) for x in parsed if x)
                        continue
                except json.JSONDecodeError:
                    pass
            if s and s not in column_list:
                column_list.append(s)

        if not column_list:
            return ""

        return json.dumps(column_list)
