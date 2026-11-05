"""
Condition widget and operator views for horilla.contrib.generics.

HTMX views for dynamic condition rows and field-value widgets in filter/automation forms.
"""

# Standard library imports
import json
import logging

# Third-party imports (Django)
from django.template import Context, Template
from django.utils.encoding import force_str
from django.utils.safestring import mark_safe

from horilla.apps import apps

# First-party (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.forms.condition_fields import (
    CONDITION_EXCLUDED_FIELDS,
    _get_related_field_choices,
    get_condition_field_widget_info,
    get_condition_model_fields,
)
from horilla.contrib.generics.related_fields import resolve_field_path
from horilla.db import models
from horilla.shortcuts import render
from horilla.urls import reverse_lazy
from horilla.utils.choices import FIELD_TYPE_MAP
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.html import escape, format_html, format_html_join
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import HttpResponse

# Local imports
from ...filters import OPERATOR_CHOICES, RELATIVE_DATE_OPERATORS

NO_VALUE_OPERATORS = {"isnull", "isnotnull", *RELATIVE_DATE_OPERATORS}

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
class RemoveConditionRowView(LoginRequiredMixin, View):
    """View for removing condition rows from multi-condition filter forms."""

    def delete(self, request, row_id, *args, **kwargs):
        """
        Remove a condition row from a multi-condition form via HTMX.

        Returns an empty 200 response on success to indicate the row was removed.
        """

        return HttpResponse("")


@method_decorator(htmx_required, name="dispatch")
class GetFieldValueWidgetView(LoginRequiredMixin, View):
    """HTMX view to return dynamic value field widget based on selected field"""

    def get(self, request):
        """
        Return HTML for the input widget corresponding to the chosen field.

        Accepts query parameters to determine the row and field and returns the
        rendered widget HTML to be injected by HTMX.
        """
        row_id = request.GET.get("row_id", "")
        field_name = request.GET.get(f"field_{row_id}", request.GET.get("field", ""))
        model_name = request.GET.get("model_name", "")
        # Resolve model_name from content type id when missing (e.g. automation create, operator-triggered request)
        # Dashboard uses "module" param name; automations use "model" — check both.
        if not model_name and field_name:
            model_id = request.GET.get("model", "") or request.GET.get("module", "")
            if model_id and str(model_id).isdigit():
                try:
                    ct = HorillaContentType.objects.get(pk=model_id)
                    model_name = ct.model
                except (HorillaContentType.DoesNotExist, ValueError):
                    pass
        condition_model_str = request.GET.get("condition_model", "")

        # Try to get existing value from the request (single value or combined for "between")
        existing_value = request.GET.get(f"value_{row_id}", "")
        existing_operator = request.GET.get(f"operator_{row_id}", "")
        if existing_operator == "between":
            start_val = request.GET.get(f"value_start_{row_id}", "").strip()
            end_val = request.GET.get(f"value_end_{row_id}", "").strip()
            if start_val or end_val:
                existing_value = f"{start_val},{end_val}"

        # Get the model field to determine appropriate widget (pass operator for "between" two-input)
        widget_html = self._get_value_widget_html(
            field_name, model_name, row_id, existing_value, existing_operator
        )

        # For single-form condition fields: update operator dropdown by field type
        # (same operator matching as filter: boolean=equals/not_equals, text=contains/etc.)
        operator_oob = self._get_operator_oob_html(
            row_id, field_name, model_name, condition_model_str, existing_operator
        )
        if operator_oob:
            widget_html = mark_safe(widget_html + operator_oob)

        # The value cell sits in a flex row alongside field/operator/logical
        # operator; when the operator needs no value (e.g. "Is empty"), the
        # widget itself renders as a hidden input, but its flex-1 cell would
        # still reserve a visible blank gap unless we collapse it here too.
        cell_style = self._get_value_cell_style_html(row_id, existing_operator)
        if cell_style:
            widget_html = mark_safe(widget_html + cell_style)

        # Render via template engine to satisfy XSS defenses (content is built with format_html)
        template = Template("{{ widget_html }}")
        return HttpResponse(template.render(Context({"widget_html": widget_html})))

    def _get_field_type_for_condition(self, model_field):
        """Return field type string for operator matching (same logic as filter)."""
        field_class_name = model_field.__class__.__name__
        if field_class_name == "ForeignKey":
            return "foreignkey"
        if field_class_name == "ManyToManyField":
            return "manytomany"
        if hasattr(model_field, "choices") and model_field.choices:
            return "choice"
        if field_class_name == "DateTimeField":
            return "datetime"
        if field_class_name == "DateField":
            return "date"
        if field_class_name in ("BooleanField", "NullBooleanField"):
            return "boolean"
        return FIELD_TYPE_MAP.get(field_class_name, "other")

    def _get_operator_oob_html(
        self, row_id, field_name, model_name, condition_model_str, existing_operator
    ):
        """
        Return OOB (out-of-band) HTML to swap the operator dropdown in single-form
        condition fields. Operators are filtered by field type (same logic as filter).
        """
        if not condition_model_str or not row_id:
            return ""

        try:
            # Resolve target model and get selected field
            target_model = None
            for app_config in apps.get_app_configs():
                try:
                    target_model = apps.get_model(
                        app_label=app_config.label, model_name=model_name
                    )
                    break
                except LookupError:
                    continue
            if not target_model or not field_name:
                return ""

            try:
                model_field = resolve_field_path(target_model, field_name)
            except Exception:
                model_field = None

            if model_field is not None:
                field_type = self._get_field_type_for_condition(model_field)
            else:
                # Not a real model field (e.g. a synthetic "cf_<id>" custom field) —
                # ask the condition-field extension registry for its operator type.
                widget_info = get_condition_field_widget_info(field_name)
                if not widget_info:
                    return ""
                field_type = widget_info.get("operator_type", "other")

            filter_ops_for_type = OPERATOR_CHOICES.get(
                field_type, OPERATOR_CHOICES.get("other", [])
            )
            operator_choices = [("", "---------")] + list(filter_ops_for_type)

            options_iter = (
                (
                    escape(force_str(val)),
                    (
                        ' selected="selected"'
                        if str(val) == str(existing_operator)
                        else ""
                    ),
                    escape(force_str(label)),
                )
                for val, label in operator_choices
            )
            options_html = format_html_join(
                "",
                '<option value="{}" {}>{}</option>',
                options_iter,
            )
            # HTMX so changing operator refetches value widget (e.g. "between" -> two inputs)
            hx_vals = json.dumps(
                {
                    "model_name": model_name or "",
                    "row_id": row_id,
                    "condition_model": condition_model_str,
                }
            )
            hx_include = (
                f'[name="field_{row_id}"],[name="operator_{row_id}"],'
                f'[name="value_{row_id}"],[name="value_start_{row_id}"],[name="value_end_{row_id}"],'
                f'[name="model"],[name="module"]'
            )
            get_widget_url = reverse_lazy("generics:get_field_value_widget")
            return format_html(
                '<div id="id_operator_{}_container" hx-swap-oob="true">'
                '<select name="operator_{}" id="id_operator_{}" '
                'class="js-example-basic-single headselect" '
                'hx-get="{}" hx-target="#id_value_{}_container" hx-swap="innerHTML" '
                'hx-vals="{}" hx-include="{}" hx-trigger="change">{}</select></div>',
                row_id,
                row_id,
                row_id,
                get_widget_url,
                row_id,
                escape(hx_vals),
                hx_include,
                options_html,
            )
        except Exception as e:
            logger.debug("GetFieldValueWidgetView operator OOB: %s", e)
            return ""

    def _get_value_widget_html(
        self, field_name, model_name, row_id, existing_value="", existing_operator=""
    ):
        """Generate appropriate widget HTML based on selected field and operator."""

        if not field_name or not model_name:
            # Return default text input
            return self._render_text_input(row_id, existing_value)

        # Operators that don't need a value (e.g. "Today", "Yesterday",
        # "Is empty") shouldn't show any input at all, regardless of field type.
        if existing_operator in NO_VALUE_OPERATORS:
            return self._render_no_value_input(row_id)

        try:
            # Find the model
            model = None
            for app_config in apps.get_app_configs():
                try:
                    model = apps.get_model(
                        app_label=app_config.label, model_name=model_name
                    )
                    break
                except LookupError:
                    continue

            if not model:
                return self._render_text_input(row_id, existing_value)

            # Get the field from the model
            model_field = resolve_field_path(model, field_name)
            if model_field is None:
                # Not a real model field (e.g. a synthetic "cf_<id>" custom field) —
                # ask the condition-field extension registry how to render it.
                extension_widget = self._render_extension_value_widget(
                    field_name, row_id, existing_value
                )
                return (
                    extension_widget
                    if extension_widget is not None
                    else self._render_text_input(row_id, existing_value)
                )

            # For date/datetime with operator "between", show two inputs
            between_widget = self._render_between_widget(
                model_field, existing_operator, row_id, existing_value
            )
            return (
                between_widget
                if between_widget is not None
                else self._render_widget_for_field_type(
                    model_field, row_id, existing_value
                )
            )

        except Exception as e:
            logger.error("Error generating value widget: %s", str(e))
            return self._render_text_input(row_id, existing_value)

    def _render_between_widget(
        self, model_field, existing_operator, row_id, existing_value
    ):
        """
        Render the two-input "between" widget for DateField/DateTimeField when the
        selected operator is "between". Returns None when not applicable, so the
        caller falls through to the regular field-type widget.
        """
        if existing_operator != "between":
            return None
        if isinstance(model_field, models.DateField):
            parts = [p.strip() for p in (existing_value or "").split(",", 1)]
            start_val = parts[0] if len(parts) > 0 else ""
            end_val = parts[1] if len(parts) > 1 else ""
            return self._render_date_between_input(row_id, start_val, end_val)
        if isinstance(model_field, models.DateTimeField):
            parts = [p.strip() for p in (existing_value or "").split(",", 1)]
            start_val = parts[0] if len(parts) > 0 else ""
            end_val = parts[1] if len(parts) > 1 else ""
            return self._render_datetime_between_input(row_id, start_val, end_val)
        return None

    def _render_widget_for_field_type(self, model_field, row_id, existing_value):
        """Determine and render the appropriate widget based on the model field's type."""
        relational_widget = self._render_relational_field_widget(
            model_field, row_id, existing_value
        )
        if relational_widget is not None:
            return relational_widget
        if hasattr(model_field, "choices") and model_field.choices:
            existing_ids = [
                v.strip() for v in (existing_value or "").split(",") if v.strip()
            ]
            return self._render_multiselect_input(
                list(model_field.choices), row_id, existing_ids
            )
        return self._render_simple_field_widget(model_field, row_id, existing_value)

    def _render_relational_field_widget(self, model_field, row_id, existing_value):
        """Render ManyToManyField/ForeignKey widgets. Returns None if not applicable."""
        if isinstance(model_field, models.ManyToManyField):
            related_model = model_field.related_model
            queryset = related_model.objects.all()
            choices = [(obj.pk, str(obj)) for obj in queryset]
            existing_ids = [
                v.strip() for v in (existing_value or "").split(",") if v.strip()
            ]
            return self._render_multiselect_input(choices, row_id, existing_ids)
        if isinstance(model_field, models.ForeignKey):
            related_model = model_field.related_model
            # Get all objects for the select, but ensure existing_value is included
            queryset = related_model.objects.all()
            choices = [(obj.pk, str(obj)) for obj in queryset]
            existing_ids = [
                v.strip() for v in (existing_value or "").split(",") if v.strip()
            ]
            known = {str(c[0]) for c in choices}
            for pk in existing_ids:
                if pk not in known:
                    try:
                        obj = related_model.objects.get(pk=pk)
                        choices.append((obj.pk, str(obj)))
                    except (related_model.DoesNotExist, ValueError):
                        pass
            return self._render_multiselect_input(choices, row_id, existing_ids)
        return None

    def _render_simple_field_widget(self, model_field, row_id, existing_value):
        """Render the widget for scalar field types with no extra choices/relations."""
        # Ordered by isinstance specificity (DateTimeField is a DateField subclass).
        renderers = [
            (models.BooleanField, self._render_boolean_input),
            (models.DateTimeField, self._render_datetime_input),
            (models.DateField, self._render_date_input),
            (models.TimeField, self._render_time_input),
            (models.IntegerField, self._render_number_input),
            (
                models.DecimalField,
                lambda rid, val: self._render_number_input(rid, val, step="0.01"),
            ),
            (models.EmailField, self._render_email_input),
            (models.URLField, self._render_url_input),
            (models.TextField, self._render_textarea_input),
        ]
        for field_type, renderer in renderers:
            if isinstance(model_field, field_type):
                return renderer(row_id, existing_value)
        # else:
        return self._render_text_input(row_id, existing_value)

    def _render_extension_value_widget(self, field_name, row_id, existing_value=""):
        """
        Render the value widget for a synthetic (non-model) condition field using
        its condition-field extension's widget metadata (see condition_fields.py's
        get_condition_field_widget_info). Returns None if no extension owns the
        field or it has no widget info, so the caller falls back to a text input.
        """
        widget_info = get_condition_field_widget_info(field_name)
        if not widget_info:
            return None
        widget = widget_info.get("widget")
        choices = widget_info.get("choices", [])
        if widget == "select":
            return self._render_select_input(choices, row_id, existing_value)
        if widget == "multiselect":
            existing_ids = [
                v.strip() for v in (existing_value or "").split(",") if v.strip()
            ]
            return self._render_multiselect_input(choices, row_id, existing_ids)
        if widget == "number":
            return self._render_number_input(row_id, existing_value)
        if widget == "textarea":
            return self._render_textarea_input(row_id, existing_value)
        return self._render_text_input(row_id, existing_value)

    def _render_text_input(self, row_id, existing_value=""):
        return format_html(
            '<input type="text" name="value_{}" id="id_value_{}" value="{}" placeholder="{}" '
            'class="text-color-820 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md  focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600">',
            row_id,
            row_id,
            existing_value,
            _("Enter Value"),
        )

    def _render_no_value_input(self, row_id):
        """Hidden placeholder for operators that don't need a value input."""
        return format_html(
            '<input type="hidden" name="value_{}" id="id_value_{}" value="">',
            row_id,
            row_id,
        )

    def _get_value_cell_style_html(self, row_id, existing_operator):
        """Scoped style so a hidden "no value" input (e.g. for "Is empty")
        doesn't leave a blank gap in the flex condition row — and so the
        cell goes back to normal width once a real value widget returns.
        A plain inline <style> tag (rather than OOB-swapping the cell div
        itself) avoids wiping out the value container it wraps."""
        if not row_id:
            return ""
        if existing_operator not in NO_VALUE_OPERATORS:
            return format_html(
                "<style>#id_value_{}_cell {{ display: block; flex: 1 1 0%; min-width: 0; }}</style>",
                row_id,
            )
        # display:none removes the cell from the flex row entirely, so it
        # stops consuming a "gap" slot too (width:0 alone would not).
        return format_html(
            "<style>#id_value_{}_cell {{ display: none; }}</style>",
            row_id,
        )

    def _render_select_input(self, choices, row_id, existing_value=""):
        options_iter = (
            (
                choice_value,
                "selected" if str(choice_value) == str(existing_value) else "",
                choice_label,
            )
            for choice_value, choice_label in choices
        )
        options_html = format_html(
            '<option value="">---------{}</option>', ""
        ) + format_html_join(
            "",
            '<option value="{}" {}>{}</option>',
            options_iter,
        )
        return format_html(
            '<select name="value_{}" id="id_value_{}" class="js-example-basic-single headselect">{}</select>',
            row_id,
            row_id,
            options_html,
        )

    def _render_multiselect_input(self, choices, row_id, existing_values=None):
        """Render a multi-select for ManyToManyField; existing_values is a list of selected IDs (str or int)."""
        existing_set = set(force_str(v) for v in (existing_values or []))
        options_iter = (
            (
                choice_value,
                "selected" if force_str(choice_value) in existing_set else "",
                choice_label,
            )
            for choice_value, choice_label in choices
        )
        options_html = format_html_join(
            "",
            '<option value="{}" {}>{}</option>',
            options_iter,
        )
        selected_joined = ",".join(force_str(v) for v in (existing_values or []))
        # Like the filter panel: the select itself is never submitted; its picks are
        # joined into the hidden value_<row> input (see global.js) so the backend
        # still receives exactly one comma-separated value per row.
        return format_html(
            '<input type="hidden" name="value_{}" id="id_value_{}" class="conditionValue" value="{}">'
            '<select id="id_value_{}_multi" multiple class="js-example-basic-multiple conditionMultiSelect headselect w-full h-full" data-placeholder="{}">{}</select>',
            row_id,
            row_id,
            selected_joined,
            row_id,
            _("Select value(s)"),
            options_html,
        )

    def _render_boolean_input(self, row_id, existing_value=""):
        true_selected = "selected" if existing_value == "True" else ""
        false_selected = "selected" if existing_value == "False" else ""
        return format_html(
            '<select name="value_{}" id="id_value_{}" class="js-example-basic-single headselect">'
            '<option value="">---------</option>'
            '<option value="True" {}>True</option>'
            '<option value="False" {}>False</option></select>',
            row_id,
            row_id,
            true_selected,
            false_selected,
        )

    def _render_date_input(self, row_id, existing_value=""):
        return format_html(
            '<input type="date" name="value_{}" id="id_value_{}" value="{}" '
            'class="text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 rounded-md focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600">',
            row_id,
            row_id,
            existing_value,
        )

    def _render_datetime_input(self, row_id, existing_value=""):
        return format_html(
            '<input type="datetime-local" name="value_{}" id="id_value_{}" value="{}" '
            'class="text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 rounded-md focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600">',
            row_id,
            row_id,
            existing_value,
        )

    def _render_date_between_input(self, row_id, existing_start="", existing_end=""):
        """Two date inputs for operator 'between' (start and end) in a single row, no labels."""
        # Reuse the same input classes as the normal date input
        input_class = (
            "text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 "
            "rounded-md focus-visible:outline-0 placeholder:text-dark-100 text-sm "
            "[transition:.3s] focus:border-primary-600"
        )
        return format_html(
            '<div class="flex items-center gap-0.5">'
            '<div class="w-1/2">'
            '<input type="date" name="value_start_{}" id="id_value_start_{}" value="{}" class="{}">'
            "</div>"
            '<div class="w-1/2">'
            '<input type="date" name="value_end_{}" id="id_value_end_{}" value="{}" class="{}">'
            "</div>"
            "</div>",
            row_id,
            row_id,
            existing_start,
            input_class,
            row_id,
            row_id,
            existing_end,
            input_class,
        )

    def _render_datetime_between_input(
        self, row_id, existing_start="", existing_end=""
    ):
        """Two datetime inputs for operator 'between' (start and end) in a single row, no labels."""
        # Reuse the same input classes as the normal datetime input
        input_class = (
            "text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 "
            "rounded-md focus-visible:outline-0 placeholder:text-dark-100 text-sm "
            "[transition:.3s] focus:border-primary-600"
        )
        return format_html(
            '<div class="flex items-center gap-0.5">'
            '<div class="w-1/2">'
            '<input type="datetime-local" name="value_start_{}" id="id_value_start_{}" value="{}" class="{}">'
            "</div>"
            '<div class="w-1/2">'
            '<input type="datetime-local" name="value_end_{}" id="id_value_end_{}" value="{}" class="{}">'
            "</div>"
            "</div>",
            row_id,
            row_id,
            existing_start,
            input_class,
            row_id,
            row_id,
            existing_end,
            input_class,
        )

    def _render_time_input(self, row_id, existing_value=""):
        return format_html(
            '<input type="time" name="value_{}" id="id_value_{}" value="{}" '
            'class="text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 rounded-md focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600">',
            row_id,
            row_id,
            existing_value,
        )

    def _render_number_input(self, row_id, existing_value="", step="1"):
        return format_html(
            '<input type="number" name="value_{}" id="id_value_{}" value="{}" step="{}" '
            'class="text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 rounded-md focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600" placeholder="{}">',
            row_id,
            row_id,
            existing_value,
            step,
            _("Enter Number"),
        )

    def _render_email_input(self, row_id, existing_value=""):
        return format_html(
            '<input type="email" name="value_{}" id="id_value_{}" value="{}" '
            'class="text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 rounded-md focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600" placeholder="{}">',
            row_id,
            row_id,
            existing_value,
            _("Enter Email"),
        )

    def _render_url_input(self, row_id, existing_value=""):
        return format_html(
            '<input type="url" name="value_{}" id="id_value_{}" value="{}" '
            'class="text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 rounded-md focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600" placeholder="{}">',
            row_id,
            row_id,
            existing_value,
            _("Enter URL"),
        )

    def _render_textarea_input(self, row_id, existing_value=""):
        return format_html(
            '<textarea name="value_{}" id="id_value_{}" rows="3" '
            'class="text-color-600 p-2 w-full border border-dark-50 rounded-md focus-visible:outline-0 text-sm transition focus:border-primary-600" placeholder="{}">{}</textarea>',
            row_id,
            row_id,
            _("Enter Value"),
            existing_value,
        )


@method_decorator(htmx_required, name="dispatch")
class GetModelFieldChoicesView(LoginRequiredMixin, View):
    """
    Generic HTMX view to return field choices for a selected model/content_type.
    Returns all fields by default, but can be filtered via query parameters.
    """

    def get_extra_field_choices(self, model):
        """
        Extra ``(value, label)`` field choices that aren't model columns.
        Extensions override this.
        """
        return []

    def get(self, request, *args, **kwargs):
        """Return a select element with field choices for the selected content type"""

        # Get parameters - support both 'content_type' and 'model' parameter names
        content_type_id = request.GET.get("content_type") or request.GET.get("model")
        row_id = request.GET.get("row_id", "0")

        # Get field name pattern - support different patterns
        field_name_pattern = request.GET.get("field_name_pattern", "field_{row_id}")
        field_name = field_name_pattern.format(row_id=row_id)
        field_id = f"id_{field_name}"

        # Preserve condition_model so the rendered select can wire itself up to
        # refetch the value widget and operator choices on change (same as the
        # select built by add_condition_fields on initial form render).
        condition_model_str = request.GET.get("condition_model", "")
        htmx_context = self._build_htmx_context(row_id, field_name, condition_model_str)

        if not content_type_id:
            return render(
                request,
                "partials/field_select_empty.html",
                {"field_name": field_name, "field_id": field_id, **htmx_context},
            )

        try:
            content_type = HorillaContentType.objects.get(pk=content_type_id)
            model_name = content_type.model
        except HorillaContentType.DoesNotExist:
            return render(
                request,
                "partials/field_select_empty.html",
                {"field_name": field_name, "field_id": field_id, **htmx_context},
            )

        # Get the model class
        model_class = None
        for app_config in apps.get_app_configs():
            try:
                model_class = apps.get_model(app_config.label, model_name.lower())
                break
            except (LookupError, ValueError):
                continue

        if not model_class:
            return render(
                request,
                "partials/field_select_empty.html",
                {"field_name": field_name, "field_id": field_id, **htmx_context},
            )

        # Get filter parameters
        field_types = (
            request.GET.get("field_types", "").split(",")
            if request.GET.get("field_types")
            else []
        )
        exclude_fields = (
            request.GET.get("exclude_fields", "").split(",")
            if request.GET.get("exclude_fields")
            else []
        )
        exclude_choice_fields = (
            request.GET.get("exclude_choice_fields", "false").lower() == "true"
        )
        only_text_fields = (
            request.GET.get("only_text_fields", "false").lower() == "true"
        )

        exclude_fields = set(exclude_fields) | CONDITION_EXCLUDED_FIELDS

        # Build field choices
        field_choices = [("", "---------")]

        for field in get_condition_model_fields(model_class, exclude_fields):
            # Filter by field types if specified
            if field_types:
                field_type_name = field.__class__.__name__
                if field_type_name not in field_types:
                    continue

            # If only_text_fields is true, only include CharField, TextField, EmailField
            if only_text_fields:
                if not isinstance(
                    field, (models.CharField, models.TextField, models.EmailField)
                ):
                    continue

            # Skip fields with choices if specified
            if exclude_choice_fields:
                if hasattr(field, "choices") and field.choices:
                    continue

            verbose_name = (
                getattr(field, "verbose_name", None)
                or field.name.replace("_", " ").title()
            )
            field_choices.append((field.name, str(verbose_name)))

        # Related and extra fields have no plain column type, so skip them when
        # filtering by type.
        if not field_types and not only_text_fields:
            field_choices.extend(
                (path, label)
                for path, label in _get_related_field_choices(model_class)
                if path not in exclude_fields
            )
            field_choices.extend(
                (name, str(label))
                for name, label in self.get_extra_field_choices(model_class)
                if name not in exclude_fields
            )

        # Build select HTML — now that model_name is resolved, bake it into the
        # select's own hx-vals so picking a field doesn't depend on re-deriving
        # the module from a guessed request param name.
        htmx_context = self._build_htmx_context(
            row_id, field_name, condition_model_str, model_name
        )
        return render(
            request,
            "partials/field_select_empty.html",
            {
                "field_name": field_name,
                "field_id": field_id,
                "field_choices": field_choices,
                **htmx_context,
            },
        )

    def _build_htmx_context(
        self, row_id, field_name, condition_model_str, model_name=""
    ):
        """HTMX attrs so the rendered Field select refetches the value widget
        and operator choices (filtered by field type) on change, same as the
        select originally built by add_condition_fields."""
        if not condition_model_str:
            return {}
        hx_vals_dict = {"row_id": row_id, "condition_model": condition_model_str}
        if model_name:
            hx_vals_dict["model_name"] = model_name
        hx_vals = json.dumps(hx_vals_dict)
        hx_include = (
            f'[name="{field_name}"],[name="operator_{row_id}"],'
            f'[name="value_{row_id}"]'
        )
        return {
            "hx_get": reverse_lazy("generics:get_field_value_widget"),
            "hx_target": f"#id_value_{row_id}_container",
            "hx_vals": hx_vals,
            "hx_include": hx_include,
        }
