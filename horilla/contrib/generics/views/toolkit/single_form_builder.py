"""
Single-form view builder: dynamic form class and condition row logic for HorillaSingleFormView.
Provides get_dynamic_form_class, condition helpers (get_existing_conditions, get_submitted_condition_data,
add_condition_row, get_add_condition_url, save_conditions), and build_condition_context.
"""

# Standard library imports
import json

# Third-party imports (Django)
from django import forms
from django.template.loader import render_to_string

from horilla.contrib.core.mixins import OwnerQuerysetMixin
from horilla.contrib.utils.middlewares import get_active_company
from horilla.core.exceptions import FieldDoesNotExist, ValidationError

# First party imports (Horilla)
from horilla.db import models
from horilla.utils.translation import gettext_lazy as _
from horilla.web import HttpResponse, QueryDict

from ...forms import HORILLA_FORM_EXCLUDE, HorillaModelForm
from ...forms.condition_fields import (
    get_extension_field_choices_for_model_name,
    get_model_field_choices,
)

# Local imports
from ..helpers import GetFieldValueWidgetView

# -----------------------------------------------------------------------------
# Condition row helpers
# -----------------------------------------------------------------------------


def fill_mandatory_condition_defaults(condition_model, condition_fields, row_data):
    """
    Fill missing mandatory (NOT NULL, not blank) condition fields in row_data
    with sensible defaults so DB constraint errors are avoided when a field
    is required but not shown or submitted in the form.

    - Uses the model field's default if set.
    - For fields with choices (e.g. CharField with choices), uses the first
      choice value.
    - Does not fill ForeignKey fields without a default (no safe generic default).

    Returns a new dict; does not mutate row_data.
    """
    if not condition_model or not condition_fields:
        return dict(row_data)
    row_data = dict(row_data)
    for field_name in condition_fields:
        try:
            model_field = condition_model._meta.get_field(field_name)
        except FieldDoesNotExist:
            continue
        # Only fill when field is mandatory (NOT NULL and not blank)
        if model_field.null or model_field.blank:
            continue
        value = row_data.get(field_name)
        if value is not None and value != "":
            continue
        default_value = None
        if model_field.has_default():
            default_value = model_field.default
            if callable(default_value):
                default_value = default_value()
        elif getattr(model_field, "choices", None):
            choices = list(model_field.choices)
            if choices:
                default_value = choices[0][0]
        if default_value is not None:
            row_data[field_name] = default_value
    return row_data


# -----------------------------------------------------------------------------
# Dynamic form builder
# -----------------------------------------------------------------------------


def get_dynamic_form_class(view):
    """
    Return a dynamic form class for the given single-form view.
    Uses view.model, view.fields, view.exclude, and view's condition/permission config.
    """
    full_width_fields = view.full_width_fields or []
    dynamic_create_fields = view.dynamic_create_fields or []
    hidden_fields = getattr(view, "hidden_fields", [])
    condition_fields = view.condition_fields or []
    condition_model = view.condition_model
    condition_field_choices = view.condition_field_choices or {}
    condition_hx_include = view.condition_hx_include
    save_and_new = view.save_and_new

    default_exclude = HORILLA_FORM_EXCLUDE

    class DynamicForm(OwnerQuerysetMixin, HorillaModelForm):
        """Dynamically generated form based on model and view configuration."""

        class Meta:
            """Meta class for Dynamic form"""

            model = view.model
            fields = view.fields if view.fields is not None else "__all__"
            exclude = (
                (view.exclude + default_exclude)
                if view.exclude is not None
                else default_exclude
            )
            widgets = {
                field.name: forms.DateInput(attrs={"type": "date"})
                for field in view.model._meta.fields
                if isinstance(field, models.DateField)
            }

        def __init__(self, *args, **kwargs):
            field_permissions = kwargs.pop("field_permissions", {})
            self.field_permissions = field_permissions
            duplicate_mode = kwargs.pop("duplicate_mode", False)

            kwargs["dynamic_create_fields"] = dynamic_create_fields
            kwargs["full_width_fields"] = full_width_fields
            kwargs["hidden_fields"] = hidden_fields
            kwargs["condition_fields"] = condition_fields
            kwargs["condition_model"] = condition_model
            kwargs["condition_field_choices"] = condition_field_choices
            kwargs["condition_hx_include"] = condition_hx_include
            kwargs["save_and_new"] = save_and_new
            super().__init__(*args, **kwargs)

            is_create_mode = not (self.instance and self.instance.pk)
            is_duplicate_mode = duplicate_mode
            fields_to_remove = []
            readonly_fields = []

            for field_name, field in list(self.fields.items()):
                if field_name in condition_fields or field_name in hidden_fields:
                    continue
                permission = field_permissions.get(field_name, "readwrite")
                is_mandatory = _is_field_mandatory(self, field_name, field)

                if permission == "hidden":
                    if is_create_mode or is_duplicate_mode:
                        if not is_mandatory:
                            fields_to_remove.append(field_name)
                    else:
                        fields_to_remove.append(field_name)
                elif permission == "readonly":
                    if (is_create_mode or is_duplicate_mode) and not is_mandatory:
                        fields_to_remove.append(field_name)
                    else:
                        readonly_fields.append(field_name)

            for field_name in fields_to_remove:
                del self.fields[field_name]

            for field_name in readonly_fields:
                if field_name not in self.fields:
                    continue
                _apply_readonly(self, field_name, duplicate_mode)

        def clean(self):
            cleaned_data = super().clean()
            if self.instance and self.instance.pk:
                for field_name, permission in self.field_permissions.items():
                    if permission != "readonly" or field_name not in self.fields:
                        continue
                    try:
                        model_field = self._meta.model._meta.get_field(field_name)
                    except Exception:
                        continue
                    original_value = _get_original_value(
                        self.instance, field_name, model_field
                    )
                    submitted_value = cleaned_data.get(field_name)
                    if _value_changed(model_field, original_value, submitted_value):
                        cleaned_data[field_name] = original_value
                        self.add_error(
                            field_name,
                            ValidationError(
                                _("This field is read-only and cannot be modified."),
                                code="readonly_field",
                            ),
                        )
                    else:
                        cleaned_data[field_name] = original_value
            return cleaned_data

    return DynamicForm


def _is_field_mandatory(form, field_name, field):
    """Return True if the model field is required (no null/blank)."""
    try:
        model_field = form._meta.model._meta.get_field(field_name)
        return not model_field.null and not model_field.blank
    except Exception:
        return field.required


def _get_original_value(instance, field_name, model_field):
    """Get original value from instance for a given field."""
    if isinstance(model_field, models.ManyToManyField):
        return list(getattr(instance, field_name).all())
    return getattr(instance, field_name, None)


def _value_changed(model_field, original_value, submitted_value):
    """Return True if submitted value differs from original."""
    if isinstance(model_field, models.ManyToManyField):
        orig_pks = set(obj.pk for obj in (original_value or []))
        sub_pks = set(obj.pk for obj in (submitted_value or []))
        return orig_pks != sub_pks
    if isinstance(model_field, models.ForeignKey):
        orig_pk = original_value.pk if original_value else None
        sub_pk = submitted_value.pk if submitted_value else None
        return orig_pk != sub_pk
    return original_value != submitted_value


def _apply_readonly(form, field_name, duplicate_mode):
    """Apply readonly (or disabled) to a single field based on type."""
    field = form.fields[field_name]
    is_create_mode = not (form.instance and form.instance.pk)
    is_mandatory = _is_field_mandatory(form, field_name, field)

    if (is_create_mode or duplicate_mode) and is_mandatory:
        for attr in (
            "readonly",
            "readOnly",
            "data-readonly",
            "disabled",
            "data-disabled",
        ):
            if hasattr(field.widget, "attrs") and attr in field.widget.attrs:
                del field.widget.attrs[attr]
        field.disabled = False
        if hasattr(field.widget, "attrs") and "class" in field.widget.attrs:
            field.widget.attrs["class"] = (
                field.widget.attrs["class"]
                .replace("bg-gray-200", "")
                .replace("bg-gray-100", "")
                .replace("border-gray-300", "")
                .replace("cursor-not-allowed", "")
                .replace("opacity-75", "")
                .replace("opacity-60", "")
                .strip()
            )
        return

    try:
        model_field = form._meta.model._meta.get_field(field_name)
    except Exception:
        model_field = None
    has_choices = model_field and getattr(model_field, "choices", None)
    text_field_types = (
        models.CharField,
        models.TextField,
        models.IntegerField,
        models.BigIntegerField,
        models.SmallIntegerField,
        models.PositiveIntegerField,
        models.DecimalField,
        models.FloatField,
        models.EmailField,
        models.URLField,
        models.SlugField,
        models.DateField,
        models.DateTimeField,
        models.TimeField,
    )
    is_text_field = (
        model_field and isinstance(model_field, text_field_types) and not has_choices
    )
    is_select_widget = isinstance(field.widget, (forms.Select, forms.SelectMultiple))
    text_widgets = (
        forms.TextInput,
        forms.Textarea,
        forms.NumberInput,
        forms.EmailInput,
        forms.URLInput,
        forms.DateInput,
        forms.DateTimeInput,
        forms.TimeInput,
    )
    is_text_widget = isinstance(field.widget, text_widgets)

    if (is_text_field or is_text_widget) and not has_choices and not is_select_widget:
        if not hasattr(field.widget, "attrs"):
            field.widget.attrs = {}
        field.widget.attrs["readonly"] = "readonly"
        if "disabled" in field.widget.attrs:
            del field.widget.attrs["disabled"]
        field.disabled = False
        field.widget.attrs["tabindex"] = "-1"
        existing_class = (
            field.widget.attrs.get("class", "")
            .replace("bg-white", "")
            .replace("bg-gray-50", "")
            .strip()
        )
        field.widget.attrs["class"] = (
            f"{existing_class} bg-gray-200 border-gray-300 cursor-not-allowed opacity-75".strip()
        )
        field.widget.attrs["style"] = (
            field.widget.attrs.get("style", "")
            + " background-color: #e5e7eb !important; border-color: #d1d5db !important;"
        )
        field.widget.attrs["data-readonly"] = "true"
        field._readonly_permission = True
        orig_get_context = field.widget.get_context

        def readonly_get_context(name, value, attrs):
            ctx = orig_get_context(name, value, attrs)
            if "widget" in ctx and "attrs" in ctx["widget"]:
                ctx["widget"]["attrs"]["readonly"] = "readonly"
            return ctx

        field.widget.get_context = readonly_get_context
    else:
        field.disabled = True
        if not hasattr(field.widget, "attrs"):
            field.widget.attrs = {}
        field.widget.attrs["disabled"] = "disabled"
        existing_class = field.widget.attrs.get("class", "")
        if "bg-gray-100" not in existing_class:
            field.widget.attrs["class"] = (
                f"{existing_class} bg-gray-100 cursor-not-allowed opacity-60".strip()
            )
        elif "cursor-not-allowed" not in existing_class:
            field.widget.attrs["class"] = (
                f"{existing_class} cursor-not-allowed opacity-60".strip()
            )


# -----------------------------------------------------------------------------
# Condition field logic
# -----------------------------------------------------------------------------


def get_existing_conditions(view):
    """Retrieve existing conditions for the current object in edit mode."""
    if not (view.kwargs.get("pk") and hasattr(view, "object") and view.object):
        return None

    related_name = view.condition_related_name
    if not related_name:
        candidates = getattr(
            view,
            "condition_related_name_candidates",
            ["conditions", "criteria", "team_members"],
        )
        for name in candidates:
            if hasattr(view.object, name):
                related_name = name
                break

    if related_name:
        related_manager = getattr(view.object, related_name, None)
        if related_manager and hasattr(related_manager, "all"):
            order_by = getattr(view, "condition_order_by", ["order", "created_at"])
            if isinstance(order_by, list):
                return related_manager.all().order_by(*order_by)
            return related_manager.all().order_by(order_by)
    return None


def get_model_name_from_content_type(view, request=None):
    """Extract model_name from content_type field (POST or GET)."""
    if not view.content_type_field:
        return None
    req = request or view.request
    model_name = None
    content_type_id = (
        req.POST.get(view.content_type_field)
        if req.method == "POST"
        else req.GET.get(view.content_type_field)
    )
    if content_type_id:
        try:
            from horilla.contrib.core.models import HorillaContentType

            content_type = HorillaContentType.objects.get(pk=content_type_id)
            model_name = content_type.model
        except Exception:
            pass
    elif view.object and hasattr(view.object, view.content_type_field):
        content_type = getattr(view.object, view.content_type_field)
        if content_type:
            if hasattr(content_type, "model"):
                model_name = content_type.model
            elif hasattr(content_type, "model_class"):
                model_name = content_type.model_class()._meta.model_name
    return model_name


def get_submitted_condition_data(view):
    """Extract condition field data from submitted form data (POST)."""
    condition_data = {}
    if view.condition_fields and view.request.method == "POST":
        row_ids = set()
        for key in view.request.POST:
            for field_name in view.condition_fields:
                if key.startswith(f"{field_name}_") and key != field_name:
                    try:
                        row_id = key.replace(f"{field_name}_", "")
                        if row_id and (row_id.isdigit() or row_id == "0"):
                            row_ids.add(row_id)
                    except Exception:
                        continue
        for row_id in row_ids:
            condition_data[row_id] = {}
            for field_name in view.condition_fields:
                param_key = f"{field_name}_{row_id}"
                if field_name == "value":
                    values = view.request.POST.getlist(param_key)
                    condition_data[row_id][field_name] = (
                        ",".join(str(v) for v in values if v)
                        if values
                        else view.request.POST.get(param_key, "")
                    )
                else:
                    condition_data[row_id][field_name] = view.request.POST.get(
                        param_key, ""
                    )
    return condition_data


def add_condition_row(view, request):
    """Return HttpResponse with rendered additional condition row HTML."""
    row_id = request.GET.get("row_id", "0")
    new_row_id = "0"
    if row_id == "next":
        current_count = request.session.get("condition_row_count", 0)
        current_count += 1
        request.session["condition_row_count"] = current_count
        new_row_id = str(current_count)
    else:
        try:
            new_row_id = str(int(row_id) + 1)
        except ValueError:
            new_row_id = "1"

    original_request = view.request
    view.request = request
    form_kwargs = view.get_form_kwargs()
    form_kwargs["row_id"] = new_row_id

    model_name = None
    if view.content_type_field:
        model_name = get_model_name_from_content_type(view, request)
        if model_name:
            if "initial" not in form_kwargs:
                form_kwargs["initial"] = {}
            form_kwargs["initial"]["model_name"] = model_name
            content_type_id = request.GET.get(
                view.content_type_field
            ) or request.POST.get(view.content_type_field)
            if content_type_id:
                form_kwargs["initial"][view.content_type_field] = content_type_id

    view.request = original_request

    if "pk" in view.kwargs:
        try:
            instance = view.model.objects.get(pk=view.kwargs["pk"])
            form_kwargs["instance"] = instance
            if (
                not model_name
                and view.content_type_field
                and hasattr(instance, view.content_type_field)
            ):
                content_type = getattr(instance, view.content_type_field)
                if content_type and hasattr(content_type, "model"):
                    model_name = content_type.model
                    if "initial" not in form_kwargs:
                        form_kwargs["initial"] = {}
                    form_kwargs["initial"]["model_name"] = model_name
        except view.model.DoesNotExist:
            pass

    existing_field_value = None
    existing_value_value = None
    if "pk" in view.kwargs and hasattr(view, "object") and view.object:
        existing_conditions = get_existing_conditions(view)
        if existing_conditions and existing_conditions.exists():
            try:
                row_index = int(new_row_id) if new_row_id.isdigit() else 0
                conditions_list = list(existing_conditions)
                if 0 <= row_index < len(conditions_list):
                    condition = conditions_list[row_index]
                    existing_field_value = getattr(condition, "field", "")
                    existing_value_value = getattr(condition, "value", "")
                    if "initial" not in form_kwargs:
                        form_kwargs["initial"] = {}
                    form_kwargs["initial"]["_existing_field"] = existing_field_value
                    form_kwargs["initial"]["_existing_value"] = existing_value_value
            except (ValueError, IndexError):
                pass

    form = view.get_form_class()(**form_kwargs)

    if (
        model_name
        and hasattr(form, "condition_field_choices")
        and hasattr(form, "_get_model_field_choices")
    ):
        form.model_name = model_name
        form.condition_field_choices["field"] = list(
            form._get_model_field_choices(model_name)
        ) + get_extension_field_choices_for_model_name(model_name)
        if "field" in form.fields:
            form.fields["field"].choices = form.condition_field_choices["field"]

    if existing_field_value is not None and "field" in form.fields:
        field_widget = form.fields["field"].widget
        if hasattr(field_widget, "attrs"):
            hx_vals_dict = {"model_name": model_name or "", "row_id": new_row_id}
            if getattr(view, "condition_model", None):
                hx_vals_dict["condition_model"] = (
                    f"{view.condition_model._meta.app_label}.{view.condition_model._meta.model_name}"
                )
            if existing_field_value:
                hx_vals_dict[f"field_{new_row_id}"] = str(existing_field_value)
            if existing_value_value:
                hx_vals_dict[f"value_{new_row_id}"] = str(existing_value_value)
            field_widget.attrs["hx-vals"] = json.dumps(hx_vals_dict)
            if "hx-trigger" not in field_widget.attrs:
                field_widget.attrs["hx-trigger"] = "change,load"
            elif "load" not in field_widget.attrs["hx-trigger"]:
                field_widget.attrs["hx-trigger"] = (
                    field_widget.attrs["hx-trigger"] + ",load"
                )
        form.fields["field"].initial = existing_field_value

    submitted_condition_data = get_submitted_condition_data(view)
    if "pk" in view.kwargs and hasattr(view, "object") and view.object:
        existing_conditions = get_existing_conditions(view)
        if existing_conditions and existing_conditions.exists():
            try:
                row_index = int(new_row_id) if new_row_id.isdigit() else 0
                conditions_list = list(existing_conditions)
                if 0 <= row_index < len(conditions_list):
                    condition = conditions_list[row_index]
                    if new_row_id not in submitted_condition_data:
                        submitted_condition_data[new_row_id] = {}
                    for field_name in view.condition_fields:
                        value = getattr(condition, field_name, "")
                        if value is not None:
                            submitted_condition_data[new_row_id][field_name] = str(
                                value
                            )
            except (ValueError, IndexError):
                pass

    context = {
        "form": form,
        "condition_fields": view.condition_fields or [],
        "row_id": new_row_id,
        "submitted_condition_data": submitted_condition_data,
    }
    if hasattr(form, "condition_field_choices"):
        context["condition_field_choices"] = form.condition_field_choices
    if model_name:
        context["model_name"] = model_name

    html = render_to_string("partials/condition_row.html", context, request=request)
    return HttpResponse(html)


def get_add_condition_url(view):
    """Return URL that adds a new condition row (with content_type_field if set)."""
    if not view.condition_fields:
        return None
    params = QueryDict(mutable=True)
    params["add_condition_row"] = "1"
    if view.content_type_field:
        content_type_id = None
        if (
            hasattr(view, "object")
            and view.object
            and hasattr(view.object, view.content_type_field)
        ):
            content_type = getattr(view.object, view.content_type_field)
            if content_type:
                content_type_id = str(content_type.pk)
        elif view.request.GET.get(view.content_type_field):
            content_type_id = view.request.GET.get(view.content_type_field)
        elif view.request.POST.get(view.content_type_field):
            content_type_id = view.request.POST.get(view.content_type_field)
        if content_type_id:
            params[view.content_type_field] = content_type_id
    form_url = view.get_form_url()
    return f"{form_url}{'&' if '?' in str(form_url) else '?'}{params.urlencode()}"


def save_conditions(view, form=None):
    """Save conditions from form.cleaned_data or POST; delete existing and create from submitted data."""
    if not (view.condition_fields and view.condition_model and view.object):
        return False
    has_errors = False

    condition_rows = None
    if form and hasattr(form, "cleaned_data") and "condition_rows" in form.cleaned_data:
        condition_rows = form.cleaned_data["condition_rows"]

    if condition_rows:
        condition_data = {
            str(order): row_data for order, row_data in enumerate(condition_rows)
        }
    else:
        condition_data = {}
        for key, value in view.request.POST.items():
            for field_name in view.condition_fields:
                if key.startswith(f"{field_name}_") and key != field_name:
                    row_id = key[len(f"{field_name}_") :]
                    if row_id not in condition_data:
                        condition_data[row_id] = {}
                    condition_data[row_id][field_name] = value

    related_name = view.condition_related_name
    if not related_name:
        for field in view.condition_model._meta.get_fields():
            if (
                isinstance(field, models.ForeignKey)
                and field.related_model == view.model
            ):
                related_name = field.related_name or field.name
                break
    if not related_name:
        candidates = getattr(
            view,
            "condition_related_name_candidates",
            ["conditions", "criteria", "team_members"],
        )
        for name in candidates:
            if hasattr(view.object, name):
                related_name = name
                break

    if related_name:
        related_manager = getattr(view.object, related_name, None)
        if related_manager and hasattr(related_manager, "all"):
            related_manager.all().delete()

    if condition_data:

        def sort_key(x):
            try:
                return int(x)
            except ValueError:
                return 999

        order = 0
        for row_id in sorted(condition_data.keys(), key=sort_key):
            row_data = condition_data[row_id]
            row_data = fill_mandatory_condition_defaults(
                view.condition_model, view.condition_fields, row_data
            )
            required_fields = ["field", "operator"]
            if not all(
                row_data.get(f) for f in required_fields if f in view.condition_fields
            ):
                continue
            if "operator" in view.condition_fields and "operator" in row_data:
                try:
                    operator_field = view.condition_model._meta.get_field("operator")
                    if operator_field.choices:
                        valid_operators = {c[0] for c in operator_field.choices}
                        if row_data["operator"] not in valid_operators:
                            if form is not None:
                                form.add_error(
                                    None,
                                    _(
                                        "Please select a valid choice for the operator field."
                                    ),
                                )
                            has_errors = True
                            continue
                except Exception:
                    pass
            if "field" in view.condition_fields and "field" in row_data:
                field_val = row_data["field"]
                if field_val:
                    valid_field_names = None
                    if (
                        getattr(view, "condition_field_choices", None)
                        and "field" in view.condition_field_choices
                    ):
                        valid_field_names = {
                            choice[0]
                            for choice in view.condition_field_choices["field"]
                            if choice[0]
                        }
                    if valid_field_names is None:
                        model_name = view.request.POST.get(
                            "model_name"
                        ) or view.request.GET.get("model_name")
                        if model_name:
                            valid_field_names = {
                                choice[0]
                                for choice in get_model_field_choices(None, model_name)
                                if choice[0]
                            }
                    if (
                        valid_field_names is not None
                        and field_val not in valid_field_names
                    ):
                        if form is not None:
                            form.add_error(
                                None,
                                _("Please select a valid choice for the field."),
                            )
                        has_errors = True
                        continue
            create_kwargs = {}
            for field in view.condition_model._meta.get_fields():
                if (
                    isinstance(field, models.ForeignKey)
                    and field.related_model == view.model
                ):
                    create_kwargs[field.name] = view.object
                    break
            for field_name in view.condition_fields:
                if field_name in row_data:
                    create_kwargs[field_name] = row_data[field_name]
            if hasattr(view.condition_model, "order"):
                create_kwargs["order"] = row_data.get("order", order)
            if hasattr(view.condition_model, "company"):
                create_kwargs["company"] = get_active_company(view.request)
            if hasattr(view.condition_model, "created_by"):
                create_kwargs["created_by"] = view.request.user
            if hasattr(view.condition_model, "updated_by"):
                create_kwargs["updated_by"] = view.request.user
            view.condition_model.objects.create(**create_kwargs)
            order += 1
    return has_errors


def build_condition_context(view, context):
    """
    Add condition-related keys to context: existing_conditions, condition_field_choices,
    submitted_condition_data (with value_widget_htmls), condition_row_count.
    Mutates context in place.
    """
    if not (
        view.kwargs.get("pk")
        and hasattr(view, "object")
        and view.object
        and view.condition_fields
    ):
        if view.request.method == "POST" and context.get("submitted_condition_data"):
            max_row_id = max(
                [
                    int(rid)
                    for rid in context["submitted_condition_data"].keys()
                    if rid.isdigit()
                ]
                + [0]
            )
            context["condition_row_count"] = max_row_id + 1
        else:
            context["condition_row_count"] = view.request.session.get(
                "condition_row_count", 0
            )
        return

    existing_conditions = get_existing_conditions(view)
    context["existing_conditions"] = existing_conditions
    form = context.get("form")
    if form and hasattr(form, "condition_field_choices"):
        context["condition_field_choices"] = form.condition_field_choices

    if existing_conditions and existing_conditions.exists():
        if not context.get("submitted_condition_data"):
            context["submitted_condition_data"] = {}
        value_widget_htmls = {}
        model_name = getattr(form, "model_name", None) or (
            view.model._meta.model_name if view.model else None
        )
        widget_view = GetFieldValueWidgetView()
        for index, condition in enumerate(existing_conditions):
            row_id = str(index)
            condition_dict = {}
            for field_name in view.condition_fields:
                if hasattr(condition, field_name):
                    value = getattr(condition, field_name)
                    condition_dict[field_name] = value
                    if field_name == "value" and index > 0:
                        field_name_value = (
                            getattr(condition, "field", "")
                            if hasattr(condition, "field")
                            else ""
                        )
                        value_value = str(value) if value else ""
                        if field_name_value and model_name:
                            widget_html = widget_view._get_value_widget_html(
                                field_name_value, model_name, row_id, value_value
                            )
                            if widget_html:
                                value_widget_htmls[f"value_widget_html_{row_id}"] = (
                                    widget_html
                                )
            context["submitted_condition_data"][row_id] = condition_dict
        context.update(value_widget_htmls)

    if view.request.method == "POST" and context.get("submitted_condition_data"):
        max_row_id = max(
            [
                int(rid)
                for rid in context["submitted_condition_data"].keys()
                if rid.isdigit()
            ]
            + [0]
        )
        context["condition_row_count"] = max_row_id + 1
    else:
        context["condition_row_count"] = view.request.session.get(
            "condition_row_count", 0
        )
