"""
Shared helpers for Horilla's detail-field picker and bulk inline field edit.

Horilla's selector and ``get_field`` paths only know about model columns.
The functions here are consumed by extension registrations, not applied as
monkey-patches themselves:

- ``add_custom_fields_to_selector_context``,
  ``append_custom_fields_to_defaults``, ``relabel_custom_field_pairs`` are
  used by ``CustomFieldDetailRenderExtension``,
  ``CustomFieldDetailDefaultsExtension``, and
  ``CustomFieldDetailEnsureSerializableExtension`` in
  ``custom_fields/mixin_extensions.py`` (``detail_field.render``/
  ``._get_detail_field_defaults``/``._ensure_json_serializable`` are bare
  module functions, extended through ``MixinExtension``/``_inherit_mixin``).
- ``build_custom_field_info``, ``get_custom_field_entries``,
  ``save_custom_field_from_post`` are used by
  ``CustomFieldExtraFieldsProviderExtension`` in
  ``custom_fields/view_extensions.py`` (``ViewExtension``/``_inherit_view``
  on ``ExtraFieldsProvider``, the "Edit Details" bulk-edit form's extension
  seam for non-model fields).
"""

from decimal import Decimal, InvalidOperation

from django.utils.encoding import force_str
from django.utils.translation import gettext_lazy as _

from custom_fields.models import CustomFieldDefinition, to_date_value, to_datetime_value
from custom_fields.utils import (
    DATE_FIELD_TYPES,
    INLINE_FIELD_TYPES,
    custom_field_form_name,
    custom_field_input_value,
    format_custom_field_display,
    get_custom_field_definitions,
    get_definition_by_form_name,
    load_custom_field_values,
    parse_custom_field_pk,
    safe_custom_field_label,
    save_custom_field_values,
)
from horilla.apps import apps


def field_names_from_list(fields_list):
    """Extract field names from ``[[verbose, name], ...]`` or name strings."""
    names = []
    for item in fields_list or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            names.append(str(item[1]))
        else:
            names.append(str(item))
    return names


def relabel_custom_field_pairs(fields_list):
    """Replace stored ``cf_*`` labels with the definition name."""
    pairs = list(fields_list or [])
    pks = []
    for item in pairs:
        if not (isinstance(item, (list, tuple)) and len(item) >= 2):
            continue
        pk = parse_custom_field_pk(item[1])
        if pk is not None:
            pks.append(pk)
    if not pks:
        return pairs
    labels = {
        custom_field_form_name(defn): safe_custom_field_label(defn)
        for defn in CustomFieldDefinition.objects.filter(pk__in=pks)
    }
    relabeled = []
    for item in pairs:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            name = str(item[1])
            verbose = labels.get(name, item[0])
            relabeled.append([force_str(verbose), name])
        else:
            relabeled.append(item)
    return relabeled


def custom_field_selector_items(model):
    """Return ``[[name, cf_<id>], ...]`` for the model's active definitions."""
    return [
        [safe_custom_field_label(defn), custom_field_form_name(defn)]
        for defn in get_custom_field_definitions(model)
    ]


def _pair_name(item):
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        return str(item[1])
    return str(item)


def _partition_selector_lists(selected_pairs, available_pairs, extras):
    """Keep each ``cf_*`` key in selected XOR available for one picker section."""
    selected = relabel_custom_field_pairs(selected_pairs)
    available = relabel_custom_field_pairs(available_pairs)
    selected_names = set(field_names_from_list(selected))
    available = [item for item in available if _pair_name(item) not in selected_names]
    available_names = set(field_names_from_list(available))
    for item in extras:
        key = item[1]
        if key in selected_names or key in available_names:
            continue
        available.append(item)
        available_names.add(key)
    return selected, available


def add_custom_fields_to_selector_context(context, request=None):
    """
    Add custom fields to the Change Detail View Fields modal lists.

    Selected columns keep saved order. A custom field that has never been
    placed in either section (new, or before the user's first save) only
    appears in the Details Available list, matching where it renders by
    default (``append_custom_fields_to_defaults``) — otherwise it would show
    as "available to add" in the header even though it is already visible,
    unplaced, in the Details tab. Once the user moves/saves a field into the
    header, it shows there like any other selected/available field.
    A field is never listed as both selected and available in the same
    section.
    """
    app_label = context.get("app_label")
    model_name = context.get("model_name")
    if not app_label or not model_name:
        return context
    try:
        model = apps.get_model(app_label, model_name)
    except LookupError:
        return context

    extras = custom_field_selector_items(model)
    if not extras:
        return context

    header_selected_names = set(
        field_names_from_list(relabel_custom_field_pairs(context.get("header_fields")))
    )
    details_selected_names = set(
        field_names_from_list(relabel_custom_field_pairs(context.get("details_fields")))
    )
    placed_names = header_selected_names | details_selected_names
    header_extras = [item for item in extras if item[1] in placed_names]
    details_extras = extras

    header_fields, header_available = _partition_selector_lists(
        context.get("header_fields"),
        context.get("header_available"),
        header_extras,
    )
    details_fields, details_available = _partition_selector_lists(
        context.get("details_fields"),
        context.get("details_available"),
        details_extras,
    )

    context["header_fields"] = header_fields
    context["details_fields"] = details_fields
    context["header_available"] = header_available
    context["details_available"] = details_available
    return context


def append_custom_fields_to_defaults(model, default_header, default_details):
    """Put custom fields in the default Details-tab selected list."""
    extras = custom_field_selector_items(model)
    if not extras:
        return default_header, default_details
    header_names = set(field_names_from_list(default_header))
    details_names = set(field_names_from_list(default_details))
    details = list(default_details or [])
    for item in extras:
        key = item[1]
        if key not in details_names and key not in header_names:
            details.append(item)
            details_names.add(key)
    return default_header, details


def restore_custom_fields_in_order(model, original_list, kept_pairs, exclude_set=None):
    """Re-insert ``cf_*`` rows that Horilla dropped via ``get_field``."""
    exclude_set = {str(name) for name in (exclude_set or set())}
    kept_by_name = {}
    for item in kept_pairs or []:
        name = item[1] if isinstance(item, (list, tuple)) and len(item) >= 2 else item
        kept_by_name[str(name)] = item
    extras = {item[1]: item[0] for item in custom_field_selector_items(model)}
    result = []
    seen = set()
    source = original_list if original_list else kept_pairs
    for field in source or []:
        name = (
            field[1] if isinstance(field, (list, tuple)) and len(field) >= 2 else field
        )
        name = str(name)
        if name in exclude_set or name in seen:
            continue
        if name in kept_by_name:
            result.append(kept_by_name[name])
            seen.add(name)
        elif name in extras:
            result.append((extras[name], name))
            seen.add(name)
    for name, pair in kept_by_name.items():
        if name not in seen and name not in exclude_set:
            result.append(pair)
            seen.add(name)
    return result


def build_custom_field_info(definition, obj):
    """Build the ``field_info`` dict the bulk-edit form's field-type branches expect."""
    from custom_fields.models import parse_choice_values

    key = custom_field_form_name(definition)
    values = load_custom_field_values(obj.__class__, obj.pk)
    value = values.get(key)
    if value is None:
        value = ""
    display = format_custom_field_display(definition, value)
    info = {
        "name": key,
        "verbose_name": safe_custom_field_label(definition),
        "field_type": INLINE_FIELD_TYPES.get(definition.field_type, "text"),
        "value": value,
        "choices": [],
        "display_value": display,
        "use_select2": False,
        "multiple": False,
        "input_attrs": {},
    }
    if definition.field_type == "choice":
        selected = parse_choice_values(value)
        info["value"] = selected
        info["multiple"] = True
        info["display_value"] = display
        info["choices"] = [
            {"value": choice, "label": choice}
            for choice in definition.get_choices_list()
        ]
    if definition.field_type == "single_choice":
        info["choices"] = [
            {"value": choice, "label": choice}
            for choice in definition.get_choices_list()
        ]
    if definition.field_type == "number":
        info["step"] = "0.0001"
    if definition.field_type in DATE_FIELD_TYPES:
        info["value"] = custom_field_input_value(definition, value)
    return info


def get_custom_field_entries(obj, request, editable):
    """
    Return bulk-edit ``{"info": field_info, "editable": bool}`` entries for
    every custom field defined on ``obj``'s model.

    Used by ``CustomFieldExtraFieldsProviderExtension.get_extra_fields``.
    """
    model = obj.__class__
    entries = []
    for definition in get_custom_field_definitions(model):
        field_info = build_custom_field_info(definition, obj)
        entries.append({"info": field_info, "editable": editable})
    return entries


def _inline_posted_value(request, field_name, definition):
    if definition.field_type != "choice":
        return request.POST.get(field_name, "")
    values = [v for v in request.POST.getlist(field_name) if v not in ("", None)]
    if not values:
        values = [
            v for v in request.POST.getlist(f"{field_name}[]") if v not in ("", None)
        ]
    return values


def _validate_inline_value(definition, raw_value):
    from custom_fields.models import parse_choice_values

    if definition.field_type == "choice":
        selected = parse_choice_values(raw_value)
        if definition.is_required and not selected:
            return str(_("This field is required."))
        allowed = set(definition.get_choices_list())
        invalid = [item for item in selected if item not in allowed]
        if invalid:
            return str(_("Select a valid choice."))
        return None
    if definition.field_type == "single_choice":
        value = str(raw_value or "").strip()
        if definition.is_required and not value:
            return str(_("This field is required."))
        if value and value not in set(definition.get_choices_list()):
            return str(_("Select a valid choice."))
        return None
    if definition.is_required and str(raw_value).strip() == "":
        return str(_("This field is required."))
    if definition.field_type == "number" and str(raw_value).strip() != "":
        try:
            Decimal(str(raw_value))
        except (InvalidOperation, ValueError):
            return str(_("Enter a valid number."))
    if definition.field_type == "date" and str(raw_value).strip() != "":
        if to_date_value(raw_value) is None:
            return str(_("Enter a valid date."))
    if definition.field_type == "datetime" and str(raw_value).strip() != "":
        if to_datetime_value(raw_value) is None:
            return str(_("Enter a valid date/time."))
    return None


def save_custom_field_from_post(obj, name, request):
    """
    Parse, validate and save one ``cf_*`` field's submitted value.

    Used by ``CustomFieldExtraFieldsProviderExtension.apply_extra_field``.
    Custom field values live in a separate table (see
    ``save_custom_field_values``), so — unlike a real model field — this
    always saves immediately rather than deferring to the record's own
    ``obj.save()``. Returns ``True`` if ``name`` was a recognized custom
    field AND its value actually changed (raises on validation failure so
    the caller can report the error against this field); ``False`` if
    ``name`` isn't a custom field, or is one but its submitted value
    matches what's already stored — ``save_custom_field_values`` skips a
    no-op write on its own, so this just relays whether it did anything.
    """
    model = obj.__class__
    definition = get_definition_by_form_name(model, name)
    if definition is None:
        return False

    raw_value = _inline_posted_value(request, name, definition)
    error_message = _validate_inline_value(definition, raw_value)
    if error_message:
        raise ValueError(error_message)

    changed = save_custom_field_values(
        model,
        obj.pk,
        {name: raw_value},
        company=getattr(obj, "company", None),
    )
    return bool(changed)
