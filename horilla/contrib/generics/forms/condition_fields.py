"""
Condition fields and HTMX support for single-step forms.

Module-level functions for dynamic condition field building, model_name resolution,
condition choices, initial values, and condition validation. Use from HorillaModelForm
by passing the form instance as the first argument (no extra mixin required).
"""

# Standard library imports
import json
import logging

# Third-party imports (Django)
from django import forms

from horilla.apps import apps

# First party imports (Horilla)
from horilla.db import models
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View

logger = logging.getLogger(__name__)


def _condition_field_label(model_field, field_name):
    return model_field.verbose_name or field_name.replace("_", " ").title()


def _condition_select_attrs(field_name, row_id, data_placeholder=None):
    # No data-placeholder: Select2 would treat the empty option as the placeholder
    # and hide it, leaving no way to clear the row's selection.
    return {
        "class": "js-example-basic-single headselect",
        "id": f"id_{field_name}_{row_id}",
        "name": f"{field_name}_{row_id}",
    }


def add_condition_fields(form):
    """Add condition fields dynamically to the form (condition model or main model)."""
    row_id = getattr(form, "row_id", "0")
    model_name = getattr(form, "model_name", "")
    model_for_fields = form.condition_model if form.condition_model else form.Meta.model
    for field_name in form.condition_fields:
        try:
            model_field = model_for_fields._meta.get_field(field_name)
            if field_name == "field" and field_name in form.condition_field_choices:
                existing_field = ""
                existing_value = ""
                if hasattr(form, "initial") and isinstance(form.initial, dict):
                    existing_field = form.initial.get("_existing_field", "")
                    existing_value = form.initial.get("_existing_value", "")
                if (
                    not existing_field
                    and getattr(form, "instance_obj", None)
                    and form.instance_obj
                    and form.instance_obj.pk
                ):
                    related_name = (
                        getattr(form, "condition_related_name", None) or "conditions"
                    )
                    if not hasattr(form.instance_obj, related_name):
                        for name in (
                            getattr(form, "condition_related_name_candidates", ()) or ()
                        ):
                            if hasattr(form.instance_obj, name):
                                related_name = name
                                break
                    if hasattr(form.instance_obj, related_name):
                        existing_conditions = getattr(
                            form.instance_obj, related_name
                        ).all()
                        if existing_conditions.exists():
                            try:
                                row_index = int(row_id) if row_id.isdigit() else 0
                                conditions_list = list(existing_conditions)
                                if 0 <= row_index < len(conditions_list):
                                    condition = conditions_list[row_index]
                                    existing_field = (
                                        getattr(condition, "field", "") or ""
                                    )
                                    existing_value = (
                                        getattr(condition, "value", "") or ""
                                    )
                            except (ValueError, IndexError):
                                if row_id == "0":
                                    first_condition = existing_conditions.first()
                                    existing_field = (
                                        getattr(first_condition, "field", "") or ""
                                    )
                                    existing_value = (
                                        getattr(first_condition, "value", "") or ""
                                    )
                hx_vals_dict = {"model_name": model_name or "", "row_id": row_id}
                condition_model = getattr(form, "condition_model", None)
                if condition_model:
                    hx_vals_dict["condition_model"] = (
                        f"{condition_model._meta.app_label}.{condition_model._meta.model_name}"
                    )
                if existing_value:
                    hx_vals_dict[f"value_{row_id}"] = str(existing_value)
                hx_vals = json.dumps(hx_vals_dict)
                hx_include = f'[name="field_{row_id}"],[name="operator_{row_id}"],[name="value_{row_id}"]'
                if getattr(form, "condition_hx_include", None):
                    hx_include += f",{form.condition_hx_include}"
                attrs = _condition_select_attrs(field_name, row_id)
                attrs.update(
                    {
                        "hx-get": reverse_lazy("generics:get_field_value_widget"),
                        "hx-target": f"#id_value_{row_id}_container",
                        "hx-swap": "innerHTML",
                        "hx-vals": hx_vals,
                        "hx-include": hx_include,
                        "hx-trigger": "change,load",
                    }
                )
                form_field = forms.ChoiceField(
                    choices=form.condition_field_choices[field_name],
                    required=False,
                    label=_condition_field_label(model_field, field_name),
                    widget=forms.Select(attrs=attrs),
                )
                if existing_field:
                    form_field.initial = existing_field
                if field_name in getattr(form, "hidden_fields", []):
                    form_field.widget = forms.HiddenInput(attrs=attrs)
                form.fields[field_name] = form_field
            elif field_name == "value":
                pass
            elif field_name in form.condition_field_choices or (
                hasattr(model_field, "choices") and model_field.choices
            ):
                if field_name in form.condition_field_choices:
                    choices = form.condition_field_choices[field_name]
                    is_custom = False
                    placeholder = f"Select {field_name.replace('_', ' ').title()}"
                else:
                    choices = [("", "---------")] + list(model_field.choices)
                    is_custom = True
                    placeholder = _("Select %(field)s") % {
                        "field": field_name.replace("_", " ").title()
                    }
                form_field = forms.ChoiceField(
                    choices=choices,
                    required=False,
                    label=_condition_field_label(model_field, field_name),
                    widget=forms.Select(
                        attrs=_condition_select_attrs(
                            field_name, row_id, data_placeholder=placeholder
                        )
                    ),
                )
                if is_custom:
                    form_field.is_custom_field = True
                if field_name in getattr(form, "hidden_fields", []):
                    form_field.widget = forms.HiddenInput(
                        attrs=_condition_select_attrs(field_name, row_id)
                    )
                form.fields[field_name] = form_field
            elif isinstance(model_field, models.ForeignKey):
                related_model = model_field.related_model
                app_label = related_model._meta.app_label
                model_name_fk = related_model._meta.model_name
                initial_choices = []
                try:
                    queryset = related_model.objects.all()[:100]
                    initial_choices = [(obj.pk, str(obj)) for obj in queryset]
                except Exception as e:
                    logger.error(
                        "Error fetching choices for condition field %s: %s",
                        field_name,
                        str(e),
                    )
                _attrs = {
                    "data-url": reverse_lazy(
                        "generics:model_select2",
                        kwargs={"app_label": app_label, "model_name": model_name_fk},
                    ),
                    "data-placeholder": _("Select %(field)s")
                    % {"field": model_field.verbose_name},
                    "data-field-name": field_name,
                    "data-form-class": f"{form.__module__}.{form.__class__.__name__}",
                    **_condition_select_attrs(field_name, row_id),
                    "class": "select2-pagination w-full",
                }
                form_field = forms.ChoiceField(
                    choices=[("", "---------")] + initial_choices,
                    required=False,
                    label=_condition_field_label(model_field, field_name),
                    widget=forms.Select(attrs=_attrs),
                )
                form_field.is_custom_field = True
                form.fields[field_name] = form_field
            else:
                _input_class = (
                    "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border "
                    "border-dark-50 rounded-md focus-visible:outline-0 placeholder:text-dark-100 "
                    "text-sm [transition:.3s] focus:border-primary-600"
                )
                _placeholder = _("Enter %(field)s") % {
                    "field": field_name.replace("_", " ").title()
                }
                _base_attrs = {
                    "class": _input_class,
                    "placeholder": _placeholder,
                    "id": f"id_{field_name}_{row_id}",
                    "name": f"{field_name}_{row_id}",
                }
                if isinstance(model_field, models.CharField):
                    form_field = forms.CharField(
                        max_length=model_field.max_length,
                        required=False,
                        label=_condition_field_label(model_field, field_name),
                        widget=forms.TextInput(attrs=_base_attrs),
                    )
                elif isinstance(model_field, models.IntegerField):
                    form_field = forms.IntegerField(
                        required=False,
                        label=_condition_field_label(model_field, field_name),
                        widget=forms.NumberInput(attrs=_base_attrs),
                    )
                elif isinstance(model_field, models.BooleanField):
                    form_field = forms.BooleanField(
                        required=False,
                        label=_condition_field_label(model_field, field_name),
                        widget=forms.CheckboxInput(
                            attrs={
                                "class": "sr-only peer",
                                "id": f"id_{field_name}_{row_id}",
                                "name": f"{field_name}_{row_id}",
                            }
                        ),
                    )
                else:
                    form_field = forms.CharField(
                        required=False,
                        label=_condition_field_label(model_field, field_name),
                        widget=forms.TextInput(attrs=_base_attrs),
                    )
                form_field.is_custom_field = True
                form.fields[field_name] = form_field
        except Exception as e:
            logger.error("Error adding condition field %s: %s", field_name, str(e))

    # Always add HTMX to operator so changing to "between" refetches value widget (two date inputs)
    if "operator" in form.fields and form.condition_model:
        row_id = getattr(form, "row_id", "0")
        model_name = getattr(form, "model_name", "")
        hx_vals_dict = {"model_name": model_name or "", "row_id": row_id}
        hx_vals_dict["condition_model"] = (
            f"{form.condition_model._meta.app_label}.{form.condition_model._meta.model_name}"
        )
        hx_include = (
            f'[name="field_{row_id}"],[name="operator_{row_id}"],'
            f'[name="value_{row_id}"],[name="value_start_{row_id}"],[name="value_end_{row_id}"],[name="model"]'
        )
        if getattr(form, "condition_hx_include", None):
            hx_include += f",{form.condition_hx_include}"
        form.fields["operator"].widget.attrs.update(
            {
                "hx-get": str(reverse_lazy("generics:get_field_value_widget")),
                "hx-target": f"#id_value_{row_id}_container",
                "hx-swap": "innerHTML",
                "hx-vals": json.dumps(hx_vals_dict),
                "hx-include": hx_include,
                "hx-trigger": "change",
            }
        )


def _get_content_type_field_name_from_view(request):
    """Return the view's declared ``content_type_field`` name, if any."""
    if not request:
        return None
    resolver_match = getattr(request, "resolver_match", None)
    if not resolver_match or not resolver_match.func:
        return None
    view_class = getattr(resolver_match.func, "view_class", None)
    if not view_class:
        return None
    return getattr(view_class, "content_type_field", None)


def _get_content_type_field_name_from_model(form):
    """Guess the content-type-field name from a ForeignKey to HorillaContentType.

    Requires ``form.fields`` to already be built (i.e. after ``super().__init__()``);
    returns ``None`` harmlessly if called earlier.
    """
    if not hasattr(form, "fields"):
        return None
    for field_name, field in form.fields.items():
        if isinstance(field, forms.ModelChoiceField):
            try:
                model_field = form._meta.model._meta.get_field(field_name)
                if (
                    isinstance(model_field, models.ForeignKey)
                    and model_field.remote_field.limit_choices_to
                ):
                    related_model = model_field.related_model
                    if related_model and related_model.__name__ == "HorillaContentType":
                        return field_name
            except (models.FieldDoesNotExist, AttributeError):
                continue
    return None


def get_content_type_field_name(form):
    """Resolve the name of the field that selects the condition builder's target model.

    Checks the view's declared ``content_type_field`` first (works for any field
    name, e.g. ``model``, ``module``, ``content_type``), then falls back to
    auto-detecting a ForeignKey to ``HorillaContentType`` on the form's model.
    """
    content_type_field_name = _get_content_type_field_name_from_view(
        getattr(form, "request", None)
    )
    if not content_type_field_name:
        content_type_field_name = _get_content_type_field_name_from_model(form)
    return content_type_field_name


def add_generic_htmx_to_field(form):
    """Add HTMX attributes to ForeignKey fields used as content_type_field for condition fields."""
    if not form.condition_fields:
        return
    content_type_field_name = get_content_type_field_name(form)
    if not content_type_field_name or content_type_field_name not in form.fields:
        return
    row_id = getattr(form, "row_id", "0")
    field = form.fields[content_type_field_name]
    if "hx-get" in field.widget.attrs:
        return
    hx_get_url = None
    if hasattr(form.__class__, "htmx_field_choices_url"):
        try:
            hx_get_url = reverse_lazy(form.__class__.htmx_field_choices_url)
            str(hx_get_url)
        except Exception:
            hx_get_url = None

    def try_reverse(pattern):
        try:
            url = reverse_lazy(pattern)
            str(url)
            return url
        except Exception:
            return None

    if hx_get_url is None:
        app_label = form._meta.model._meta.app_label
        model_name = form._meta.model._meta.model_name.lower()
        for pattern in [
            f"{app_label}:{model_name}_field_choices_view",
            f"{app_label}:{content_type_field_name}_field_choices_view",
            f"{app_label}:get_{model_name}_field_choices",
        ]:
            hx_get_url = try_reverse(pattern)
            if hx_get_url:
                break
    if hx_get_url is None:
        hx_get_url = reverse_lazy("generics:get_model_field_choices")
    first_condition_field = (
        form.condition_fields[0] if form.condition_fields else "field"
    )
    hx_target = f"#id_{first_condition_field}_{row_id}_container"
    field_name_pattern = f"{first_condition_field}_{{row_id}}"
    hx_vals_parts = [
        f'"row_id": "{row_id}"',
        f'"field_name_pattern": "{field_name_pattern}"',
    ]
    condition_model = getattr(form, "condition_model", None)
    if condition_model:
        condition_model_str = (
            f"{condition_model._meta.app_label}.{condition_model._meta.model_name}"
        )
        hx_vals_parts.append(f'"condition_model": "{condition_model_str}"')
    if hasattr(form.__class__, "htmx_field_filter"):
        filter_config = form.__class__.htmx_field_filter
        if filter_config.get("only_text_fields"):
            hx_vals_parts.append('"only_text_fields": "true"')
        if filter_config.get("exclude_choice_fields"):
            hx_vals_parts.append('"exclude_choice_fields": "true"')
        if filter_config.get("field_types"):
            hx_vals_parts.append(
                f'"field_types": "{",".join(filter_config["field_types"])}"'
            )
    if getattr(form, "instance_obj", None) and form.instance_obj.pk:
        model_name_lower = form._meta.model._meta.model_name.lower()
        instance_id_name = (
            f"{model_name_lower.replace('horilla', '')}_id"
            if model_name_lower.startswith("horilla")
            else f"{model_name_lower}_id"
        )
        hx_vals_parts.append(f'"{instance_id_name}": "{form.instance_obj.pk}"')
    hx_vals = "{" + ", ".join(hx_vals_parts) + "}"
    hx_include = f'[name="{content_type_field_name}"]'
    if getattr(form, "condition_hx_include", None):
        hx_include += f",{form.condition_hx_include}"
    field.widget.attrs.update(
        {
            "hx-get": hx_get_url,
            "hx-target": hx_target,
            "hx-swap": "innerHTML",
            "hx-include": hx_include,
            "hx-vals": hx_vals,
            "hx-trigger": "change",
        }
    )


def get_model_name_from_request_or_instance(form, kwargs):
    """Extract model_name from request or instance."""
    model_name = None
    request = kwargs.get("request") or getattr(form, "request", None)
    instance_obj = kwargs.get("instance") or getattr(form, "instance_obj", None)
    if request:
        if "initial" in kwargs and "model_name" in kwargs["initial"]:
            model_name = kwargs["initial"]["model_name"]
        else:
            content_type_field_name = _get_content_type_field_name_from_view(request)
            param_names = ["model_name", "model"]
            if content_type_field_name and content_type_field_name not in param_names:
                param_names.append(content_type_field_name)
            for param_name in param_names:
                model_name = request.GET.get(param_name) or (
                    request.POST.get(param_name) if hasattr(request, "POST") else None
                )
                if model_name:
                    break
            if model_name and model_name.isdigit():
                try:
                    from horilla.contrib.core.models import HorillaContentType

                    content_type = HorillaContentType.objects.get(pk=model_name)
                    model_name = content_type.model
                except Exception:
                    model_name = None
    if not model_name and instance_obj and instance_obj.pk:
        if hasattr(instance_obj, "model") and hasattr(instance_obj.model, "model"):
            model_name = instance_obj.model.model
        elif hasattr(instance_obj, "rule") and hasattr(instance_obj.rule, "module"):
            model_name = getattr(instance_obj.rule.module, "model", None)

        elif hasattr(instance_obj, "module"):
            module = getattr(instance_obj, "module", None)
            if module and hasattr(module, "model"):
                model_name = module.model
            elif isinstance(module, str):
                model_name = module
    return model_name


# --- Condition-field extension registry ---------------------------------
#
# Lets optional apps contribute "synthetic" condition fields — ones that
# aren't real model columns (e.g. the custom_fields app's user-defined
# fields) — to condition builders and rule engines (e.g. assignment rules)
# without this core/generics module importing those apps by name.
#
# An extension implements:
#   owns(field_name) -> bool
#   get_choices(model) -> list[(value, label)]
#   get_label(field_name) -> str | None
#   get_value(field_name, instance) -> str | None
#       (None means "can't resolve, treat as no match"; "" means "no value")
#   get_widget_info(field_name) -> dict | None
#       Value-widget/operator metadata for condition_widget.py, so a
#       synthetic field renders something better than a plain text input.
#       {"widget": "text" | "textarea" | "number" | "select" | "multiselect",
#        "choices": [(value, label), ...],  # required for select/multiselect
#        "operator_type": a key into horilla.contrib.generics.filters.OPERATOR_CHOICES}
#       None means "no widget-specific info, fall back to a text input".
#
# Apps register their extension from an auto-imported module, e.g.
# field_management/extensions/custom_fields_condition_field.py.

_condition_field_extensions = []


class ConditionFieldProvider(View):
    """
    Extension seam for condition fields that aren't model columns.

    Apps override these methods with an ``_inherit_view`` extension (resolved
    through :func:`get_condition_field_provider`, the same late-binding
    pattern as ``ExtraFieldsProvider``). The defaults mean "owns no field".
    Never dispatched via ``as_view()``. Implements the same interface as a
    registered extension (see the notes above), plus:

      build_condition_q(model, field_name, operator, value) -> Q | None
          Filter for queryset-based condition engines (None: can't express it).
      evaluate_condition(field_name, instance, operator, value) -> bool | None
          Own the comparison for ``field_name`` (None: use the default text
          comparison of the resolved value).
    """

    def owns(self, field_name):
        """Return True when this provider supplies ``field_name``."""
        return False

    def get_choices(self, model):
        """Return extra ``(value, label)`` condition fields for ``model``."""
        return []

    def get_label(self, field_name):
        """Return the display label for ``field_name``, or None."""
        return None

    def get_value(self, field_name, instance):
        """Return ``field_name``'s value on ``instance`` as text, or None."""
        return None

    def get_widget_info(self, field_name):
        """Return value-widget / operator metadata for ``field_name``, or None."""
        return None

    def build_condition_q(self, model, field_name, operator, value):
        """Return a ``Q`` for a condition on ``field_name``, or None."""
        return None

    def evaluate_condition(self, field_name, instance, operator, value):
        """Return True/False for a condition on ``instance``, or None to use the default text comparison."""
        return None


def get_condition_field_provider():
    """Return a ConditionFieldProvider with ``_inherit_view`` extensions applied."""
    from horilla.extension.view.resolve import resolve_view_class

    return resolve_view_class(ConditionFieldProvider)()


def _condition_field_sources():
    """Registered extensions followed by the (extendable) provider."""
    return [*_condition_field_extensions, get_condition_field_provider()]


def register_condition_field_extension(extension):
    """Register a synthetic condition-field provider (see module docstring above)."""
    if extension not in _condition_field_extensions:
        _condition_field_extensions.append(extension)


def get_condition_field_extension(field_name):
    """Return the registered extension that owns ``field_name``, or None."""
    for extension in _condition_field_sources():
        try:
            if extension.owns(field_name):
                return extension
        except Exception as e:
            logger.error(
                "Error checking condition-field extension %s for %s: %s",
                extension,
                field_name,
                str(e),
                exc_info=True,
            )
    return None


def get_condition_field_label(field_name):
    """Return the display label a registered extension gives ``field_name``, or None."""
    extension = get_condition_field_extension(field_name)
    if not extension:
        return None
    try:
        return extension.get_label(field_name)
    except Exception as e:
        logger.error(
            "Error getting condition-field label from %s for %s: %s",
            extension,
            field_name,
            str(e),
            exc_info=True,
        )
        return None


def evaluate_extension_condition(field_name, instance, operator, value, compare):
    """
    Evaluate a condition on a field contributed by a registered extension.

    ``compare(operator, left, right)`` is the caller's own string comparator,
    so each rule engine keeps its operator semantics. Returns ``(handled,
    result)``; ``handled`` is False when no extension owns ``field_name``.
    """
    extension = get_condition_field_extension(field_name)
    if not extension:
        return False, None
    result = get_extension_condition_result(field_name, instance, operator, value)
    if result is not None:
        return True, result
    resolved = get_condition_field_value(field_name, instance)
    if resolved is None:
        return True, False
    return True, bool(
        compare(operator, str(resolved), "" if value is None else str(value))
    )


def get_extension_condition_result(field_name, instance, operator, value):
    """
    Return True/False when a registered extension evaluates the condition
    itself, or None to fall back to the caller's own comparison.
    """
    extension = get_condition_field_extension(field_name)
    evaluator = getattr(extension, "evaluate_condition", None)
    if evaluator is None:
        return None
    try:
        return evaluator(field_name, instance, operator, value)
    except Exception as e:
        logger.error(
            "Error evaluating condition with %s for %s: %s",
            extension,
            field_name,
            str(e),
            exc_info=True,
        )
        return False


def get_extension_condition_q(model, field_name, operator, value):
    """
    Return a ``Q`` for a condition on a registered extension's field, or None.

    None means no extension owns ``field_name`` (or it can't express the
    operator), so the caller should filter on the model column as usual.
    """
    extension = get_condition_field_extension(field_name)
    builder = getattr(extension, "build_condition_q", None)
    if builder is None:
        return None
    try:
        return builder(model, field_name, operator, value)
    except Exception as e:
        logger.error(
            "Error building condition filter from %s for %s: %s",
            extension,
            field_name,
            str(e),
            exc_info=True,
        )
        return None


def get_extension_field_choices_for_model_name(model_name):
    """Extension (value, label) field pairs for the model named ``model_name``."""
    if not model_name:
        return []
    for app_config in apps.get_app_configs():
        try:
            model = apps.get_model(app_config.label, str(model_name).lower())
        except (LookupError, ValueError):
            continue
        return get_extension_field_choices(model)
    return []


def get_condition_field_value(field_name, instance):
    """Return the resolved value a registered extension gives ``field_name`` on ``instance``, or None."""
    extension = get_condition_field_extension(field_name)
    if not extension:
        return None
    try:
        return extension.get_value(field_name, instance)
    except Exception as e:
        logger.error(
            "Error getting condition-field value from %s for %s: %s",
            extension,
            field_name,
            str(e),
            exc_info=True,
        )
        return None


def get_condition_field_widget_info(field_name):
    """Return the value-widget/operator metadata a registered extension gives ``field_name``, or None."""
    extension = get_condition_field_extension(field_name)
    if not extension:
        return None
    try:
        return extension.get_widget_info(field_name)
    except Exception as e:
        logger.error(
            "Error getting condition-field widget info from %s for %s: %s",
            extension,
            field_name,
            str(e),
            exc_info=True,
        )
        return None


def get_extension_field_choices(model):
    """Collect extra (choice_value, label) pairs from every registered extension."""
    choices = []
    for extension in _condition_field_sources():
        try:
            choices.extend(extension.get_choices(model))
        except Exception as e:
            logger.error(
                "Error getting condition-field choices from %s for %s: %s",
                extension,
                model,
                str(e),
                exc_info=True,
            )
    return choices


_get_extension_field_choices = get_extension_field_choices


# Fields never offered in condition field dropdowns
CONDITION_EXCLUDED_FIELDS = frozenset(
    {
        "id",
        "pk",
        "company",
        "additional_info",
        "password",
        "last_login",
        "date_joined",
        "groups",
        "user_permissions",
        "is_staff",
    }
)

# Non-editable audit fields that are still valid in conditions
AUDIT_FIELDS = ("created_at", "updated_at", "created_by", "updated_by")


def get_condition_model_fields(model, exclude=CONDITION_EXCLUDED_FIELDS):
    """Forward fields of ``model`` usable in conditions (no reverse relations, no excluded, editable or audit)."""
    return [
        field
        for field in list(model._meta.fields) + list(model._meta.many_to_many)
        if field.name not in exclude
        and (getattr(field, "editable", True) or field.name in AUDIT_FIELDS)
    ]


def get_model_field_choices(form, model_name):
    """Get field choices for a model (excluding reverse relations and common non-editable)."""
    field_choices = [("", "---------")]
    if not model_name:
        return field_choices
    try:
        model = None
        for app_config in apps.get_app_configs():
            try:
                model = apps.get_model(
                    app_label=app_config.label, model_name=model_name.lower()
                )
                break
            except (LookupError, ValueError):
                continue
        if model:
            for field in get_condition_model_fields(model):
                verbose_name = (
                    getattr(field, "verbose_name", None)
                    or field.name.replace("_", " ").title()
                )
                field_choices.append((field.name, verbose_name))
            field_choices.extend(_get_extension_field_choices(model))
    except Exception as e:
        logger.error("Error fetching model %s: %s", model_name, str(e), exc_info=True)
    return field_choices


def get_condition_field_choices_from_model(form, field_name, condition_model=None):
    """Get choices for a condition field from the condition model."""
    condition_model = condition_model or getattr(form, "condition_model", None)
    if not condition_model:
        return [("", "---------")]
    try:
        model_field = condition_model._meta.get_field(field_name)
        if hasattr(model_field, "choices") and model_field.choices:
            return [("", "---------")] + list(model_field.choices)
    except (AttributeError, Exception):
        pass
    return [("", "---------")]


def build_condition_field_choices(form, model_name=None):
    """Build condition_field_choices from condition_model."""
    if not form.condition_model or not form.condition_fields:
        return {}
    condition_field_choices = {}
    for field_name in form.condition_fields:
        if field_name == "field":
            condition_field_choices["field"] = (
                get_model_field_choices(form, model_name)
                if model_name
                else [("", "---------")]
            )
        else:
            condition_field_choices[field_name] = (
                get_condition_field_choices_from_model(
                    form, field_name, form.condition_model
                )
            )
    return condition_field_choices


def set_initial_condition_values(form):
    """Set initial values for condition fields in edit mode."""
    if not (
        getattr(form, "instance_obj", None)
        and form.instance_obj
        and form.instance_obj.pk
    ):
        return
    if not (getattr(form, "condition_fields", None) and form.condition_fields):
        return
    related_name = getattr(form, "condition_related_name", None) or "conditions"
    if not hasattr(form.instance_obj, related_name):
        for name in getattr(form, "condition_related_name_candidates", ()) or ():
            if hasattr(form.instance_obj, name):
                related_name = name
                break
        else:
            return
    existing_conditions = getattr(form.instance_obj, related_name).all()
    if getattr(form, "row_id", None) and form.row_id != "0":
        return
    if existing_conditions.exists():
        first_condition = existing_conditions.first()
        for field_name in form.condition_fields:
            if field_name in form.fields:
                value = getattr(first_condition, field_name, "")
                form.fields[field_name].initial = value
                if f"{field_name}_0" in form.fields:
                    form.fields[f"{field_name}_0"].initial = value


def extract_condition_rows(form):
    """Extract condition rows from form data."""
    condition_rows = []
    if (
        not (getattr(form, "condition_fields", None) and form.condition_fields)
        or not form.data
    ):
        return condition_rows
    row_ids = set()
    for key in form.data.keys():
        for field_name in form.condition_fields:
            if key.startswith(f"{field_name}_"):
                row_id = key.replace(f"{field_name}_", "")
                if row_id.isdigit():
                    row_ids.add(row_id)
        # "Between" operator uses value_start_ and value_end_
        if key.startswith("value_start_"):
            rid = key.replace("value_start_", "")
            if rid.isdigit():
                row_ids.add(rid)
        if key.startswith("value_end_"):
            rid = key.replace("value_end_", "")
            if rid.isdigit():
                row_ids.add(rid)
    if any(f in form.data for f in form.condition_fields) or any(
        f"{f}_0" in form.data for f in form.condition_fields
    ):
        row_ids.add("0")
    for row_id in sorted(row_ids, key=int):
        row_data = {}
        has_required_data = True
        for field_name in form.condition_fields:
            field_key = (
                f"{field_name}_0"
                if row_id == "0" and f"{field_name}_0" in form.data
                else (field_name if row_id == "0" else f"{field_name}_{row_id}")
            )
            value = form.data.get(field_key, "").strip()
            # For operator "between", value may come from value_start_ and value_end_
            if field_name == "value" and row_data.get("operator") == "between":
                start_key = (
                    "value_start_0" if row_id == "0" else f"value_start_{row_id}"
                )
                end_key = "value_end_0" if row_id == "0" else f"value_end_{row_id}"
                start_val = form.data.get(start_key, "").strip()
                end_val = form.data.get(end_key, "").strip()
                if start_val or end_val:
                    value = f"{start_val},{end_val}"
            row_data[field_name] = value
            if field_name in ["field", "operator"] and not value:
                has_required_data = False
        if has_required_data and row_data.get("field") and row_data.get("operator"):
            row_data["order"] = int(row_id)
            condition_rows.append(row_data)
    return condition_rows


def clean_condition_fields(form, cleaned_data):
    """Validate condition fields (FK and Choice) when condition_model is set. Adds errors to form."""
    if not (form.condition_fields and form.condition_model):
        return

    # Validate that operator is provided whenever a field is selected
    if "field" in form.condition_fields and "operator" in form.condition_fields:
        missing_operator = False
        seen_row_ids = set()
        for key in form.data.keys():
            if key.startswith("field_"):
                row_id = key[len("field_") :]
                if not row_id.isdigit():
                    continue
                seen_row_ids.add(row_id)
                field_val = form.data.get(f"field_{row_id}", "").strip()
                operator_val = form.data.get(f"operator_{row_id}", "").strip()
                if field_val and not operator_val:
                    missing_operator = True
        # Also check row_id "0" keys (field_0/operator_0 or bare field/operator)
        if "0" not in seen_row_ids:
            for field_key, op_key in (("field_0", "operator_0"), ("field", "operator")):
                field_val = form.data.get(field_key, "").strip()
                if field_val:
                    operator_val = form.data.get(op_key, "").strip()
                    if not operator_val:
                        missing_operator = True
                    break
        if missing_operator:
            form.add_error(
                None,
                _("Operator is required when a field is selected."),
            )

    # Validate submitted "field" values are actual model fields (whitelist check)
    if "field" in form.condition_fields:
        model_name = (
            form.data.get("model_name")
            or (form.initial.get("model_name") if hasattr(form, "initial") else None)
            or getattr(form, "model_name", None)
        )
        if model_name:
            valid_field_names = {
                choice[0]
                for choice in get_model_field_choices(form, model_name)
                if choice[0]
            }
            invalid_field = False
            seen_row_ids_field = set()
            for key in form.data.keys():
                if key.startswith("field_"):
                    row_id = key[len("field_") :]
                    if not row_id.isdigit():
                        continue
                    seen_row_ids_field.add(row_id)
                    field_val = form.data.get(f"field_{row_id}", "").strip()
                    if field_val and field_val not in valid_field_names:
                        invalid_field = True
            if "0" not in seen_row_ids_field:
                for field_key in ("field_0", "field"):
                    field_val = form.data.get(field_key, "").strip()
                    if field_val:
                        if field_val not in valid_field_names:
                            invalid_field = True
                        break
            if invalid_field:
                form.add_error(
                    None,
                    _(
                        "Select a valid field. That choice is not one of the available fields."
                    ),
                )

    # Validate that value is provided when field and operator are both set,
    # unless the operator doesn't require a value (e.g. isnull/isnotnull)
    _NO_VALUE_OPERATORS = {
        "isnull",
        "isnotnull",
        "is_empty",
        "is_not_empty",
        "today",
        "yesterday",
        "this_week",
        "this_month",
        "this_year",
        "this_fiscal_period",
        "this_fiscal_quarter",
        "this_fiscal_year",
    }
    if "field" in form.condition_fields and "value" in form.condition_fields:
        missing_value = False
        seen_row_ids = set()
        for key in form.data.keys():
            if key.startswith("field_"):
                row_id = key[len("field_") :]
                if not row_id.isdigit():
                    continue
                seen_row_ids.add(row_id)
                field_val = form.data.get(f"field_{row_id}", "").strip()
                operator_val = form.data.get(f"operator_{row_id}", "").strip()
                value_val = form.data.get(f"value_{row_id}", "").strip()
                if (
                    field_val
                    and operator_val
                    and operator_val not in _NO_VALUE_OPERATORS
                    and not value_val
                ):
                    missing_value = True
        # Also check row_id "0"
        if "0" not in seen_row_ids:
            for field_key, op_key, val_key in (
                ("field_0", "operator_0", "value_0"),
                ("field", "operator", "value"),
            ):
                field_val = form.data.get(field_key, "").strip()
                if field_val:
                    operator_val = form.data.get(op_key, "").strip()
                    value_val = form.data.get(val_key, "").strip()
                    if (
                        operator_val
                        and operator_val not in _NO_VALUE_OPERATORS
                        and not value_val
                    ):
                        missing_value = True
                    break
        if missing_value:
            form.add_error(
                None,
                _("Value is required when a field and operator are selected."),
            )

    for field_name in form.condition_fields:
        if field_name not in cleaned_data or not cleaned_data[field_name]:
            continue
        try:
            value = cleaned_data[field_name]
            field = form.fields.get(field_name)
            model_field = form.condition_model._meta.get_field(field_name)
            if not field:
                continue
            if isinstance(field, forms.ModelChoiceField) and isinstance(
                model_field, models.ForeignKey
            ):
                fresh_queryset = form._get_fresh_queryset(
                    field_name, model_field.related_model
                )
                if fresh_queryset is not None:
                    pk_to_check = value.pk if hasattr(value, "pk") else value
                    if not fresh_queryset.filter(pk=pk_to_check).exists():
                        form.add_error(
                            field_name,
                            "Select a valid choice. That choice is not one of the available choices.",
                        )
            elif isinstance(field, forms.ChoiceField) and not isinstance(
                field, forms.ModelChoiceField
            ):
                if hasattr(field, "choices") and field.choices:
                    valid_choices = [choice[0] for choice in field.choices]
                    if value not in valid_choices:
                        form.add_error(
                            field_name,
                            "Select a valid choice. That choice is not one of the available choices.",
                        )
        except Exception as e:
            logger.error("Error validating condition field %s: %s", field_name, str(e))
