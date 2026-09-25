"""
Inject custom fields into bare mixins/functions and a handful of concrete
classes with no other reachable extension point, through MixinExtension
(_inherit_mixin).

Most targets here are never dispatched via ``as_view()`` and never resolved
via a ``get_*_class()`` call — nothing calls either of those on a mixin that
is only ever composed in through ordinary Python inheritance, or on a plain
module-level function — so ``_inherit_view``/``_inherit_list``/
``_inherit_form`` etc. cannot reach them. See
``docs/horilla/extension/mixin/inherit.md`` for the full mechanism.

- ``HorillaListFilterFieldsMixin._get_model_fields`` — the "Filter Records"
  field dropdown. Mixed into every ``HorillaListView`` subclass.
- ``HorillaBulkExportMixin.get_export_objects``/``.handle_export`` — the
  actual export-file writer. Mixed into ``ExportView``.
- ``get_export_cell_value`` — a bare module-level function that renders one
  export cell.
- ``detail_field.render``/``._get_detail_field_defaults``/
  ``._ensure_json_serializable`` — bare module-level functions in the detail
  field selector/inline-edit module.
- ``ColumnSelectionForm.__init__`` — a plain ``django.forms.Form`` (not a
  ``HorillaModelForm``/``HorillaMultiStepForm``), routed to as a literal
  ``FormView.form_class`` attribute, never through ``get_form_class()`` /
  ``resolve_form_class()`` — so ``FormExtension`` cannot reach it either. Its
  own ``__init__`` also builds ``self.fields["visible_fields"].choices`` and
  immediately filters posted data against those same choices, in one method
  — there is no "after real `__init__`" hook (``FormExtension``'s
  ``setup_form_extension_fields()``) that runs early enough to add ``cf_*``
  choices before that filtering happens.
- ``GetFieldValueWidgetView._get_value_widget_html`` — the condition-builder
  value widget. Horilla only renders date pickers for real model date
  fields; this renders them for custom Date / Date and Time fields too.
- ``horilla_crm.leads.signals._eval_single_criterion`` — a bare module-level
  function (Lead assignment rules). It compares values as text or floats, so
  "after"/"before"/"between"/"today" never match a date; custom date fields
  are evaluated by value here instead. Registered only when the Leads app is
  installed.
"""

import logging

from django.apps import apps as django_apps
from django.utils.encoding import force_str

from custom_fields.condition_field_extensions import (
    evaluate_date_criterion,
    render_date_condition_value_widget,
)
from custom_fields.detail_hooks import (
    add_custom_fields_to_selector_context,
    append_custom_fields_to_defaults,
    custom_field_selector_items,
    relabel_custom_field_pairs,
)
from custom_fields.export_hooks import (
    _install_export_properties,
    _uninstall_export_properties,
)
from custom_fields.filter_hooks import add_custom_fields_to_field_dicts
from custom_fields.list_hooks import attach_custom_field_values_to_objects
from horilla.extension.mixin import MixinExtension

logger = logging.getLogger(__name__)


class CustomFieldFilterFieldsExtension(MixinExtension):
    """Append custom-field dicts onto the Filter Records field dropdown."""

    _inherit_mixin = "horilla.contrib.generics.mixins.HorillaListFilterFieldsMixin"

    def _get_model_fields(self, original, include_properties=False, for_export=False):
        fields = list(
            original(include_properties=include_properties, for_export=for_export)
        )
        model = getattr(self, "model", None)
        if model is None:
            return fields
        try:
            filterset_class = None
            if hasattr(self, "get_filterset_class"):
                try:
                    filterset_class = self.get_filterset_class()
                except Exception:
                    filterset_class = getattr(self, "filterset_class", None)
            else:
                filterset_class = getattr(self, "filterset_class", None)
            add_custom_fields_to_field_dicts(fields, model, filterset_class)
        except Exception:
            logger.exception("custom_fields: could not inject filter fields")
        return fields


class CustomFieldBulkExportExtension(MixinExtension):
    """
    Attach custom-field values onto exported objects before ``handle_export``
    writes rows from them, so the writer's own row-building sees ``cf_*``
    attributes on each in-memory object.

    ``HorillaBulkExportMixin.get_export_objects`` exists specifically as the
    overridable seam for this: it is the one place ``handle_export`` reads
    its queryset from, so materializing it here and attaching values onto
    the resulting list reaches the row-building loop without touching
    Django's ``QuerySet`` globally.
    """

    _inherit_mixin = (
        "horilla.contrib.generics.views.toolkit.bulk_export.HorillaBulkExportMixin"
    )

    def get_export_objects(self, original, queryset):
        model = getattr(self, "model", None)
        extras = custom_field_selector_items(model) if model is not None else []
        if not extras:
            return original(queryset)

        items = list(original(queryset))
        try:
            attach_custom_field_values_to_objects(model, items, extras=extras)
        except Exception:
            logger.exception("custom_fields: could not attach export values")
        return items

    def handle_export(self, original, record_ids, columns, export_format):
        """Expose ``cf_*`` as export columns while Horilla streams the export."""
        model = getattr(self, "model", None)
        extras = custom_field_selector_items(model) if model is not None else []
        if not extras:
            return original(record_ids, columns, export_format)

        installed, old_labels = _install_export_properties(model, extras)
        try:
            return original(record_ids, columns, export_format)
        finally:
            _uninstall_export_properties(model, installed, old_labels)


class CustomFieldExportCellExtension(MixinExtension):
    """Render ``cf_*`` export cells directly from the object's attached value."""

    _inherit_mixin = "horilla.contrib.core.views.export_data.get_export_cell_value"

    def get_export_cell_value(self, original, obj, field_name, field, user):
        """Return attached ``cf_*`` values; otherwise defer to Horilla."""
        if str(field_name).startswith("cf_"):
            value = obj.__dict__.get(field_name, "")
            return "" if value is None else str(value)
        return original(obj, field_name, field, user)


class CustomFieldDetailRenderExtension(MixinExtension):
    """Inject custom fields into the "Change Detail View Fields" selector modal."""

    _inherit_mixin = "horilla.contrib.generics.views.helpers.detail_field.render"

    def render(self, original, request, template_name, context=None, *args, **kwargs):
        """Add custom fields to the detail field-picker template context."""
        if template_name == "add_field_to_detail.html" and context is not None:
            add_custom_fields_to_selector_context(context, request)
        return original(request, template_name, context, *args, **kwargs)


class CustomFieldDetailDefaultsExtension(MixinExtension):
    """Add custom fields to the default header/detail field lists."""

    _inherit_mixin = (
        "horilla.contrib.generics.views.helpers.detail_field._get_detail_field_defaults"
    )

    def _get_detail_field_defaults(self, original, model, request):
        default_header, default_details = original(model, request)
        try:
            return append_custom_fields_to_defaults(
                model, default_header, default_details
            )
        except Exception:
            logger.exception("custom_fields: could not add defaults for %s", model)
            return default_header, default_details


class CustomFieldDetailEnsureSerializableExtension(MixinExtension):
    """Relabel ``cf_*`` pairs to their live custom-field label."""

    _inherit_mixin = (
        "horilla.contrib.generics.views.helpers.detail_field._ensure_json_serializable"
    )

    def _ensure_json_serializable(self, original, fields_list):
        return relabel_custom_field_pairs(original(fields_list))


class CustomFieldColumnSelectionFormExtension(MixinExtension):
    """
    Include ``cf_*`` in ``ColumnSelectionForm``'s ``visible_fields`` choices
    so posted custom-field columns are not dropped.

    Patches ``__init__`` directly (not through ``FormExtension`` — see the
    module docstring): the real ``__init__`` builds
    ``self.fields["visible_fields"].choices`` from the model's own fields
    and, in the same call, filters any posted ``visible_fields`` down to
    just those choices — so custom-field choices must exist *before* that
    filtering runs, not after it (which is the earliest
    ``FormExtension.setup_form_extension_fields()`` could run).
    """

    _inherit_mixin = "horilla.contrib.generics.forms.generics.ColumnSelectionForm"

    def __init__(self, original, *args, **kwargs):
        model = kwargs.get("model")
        original_data = kwargs.get("data")
        if original_data is None and args:
            original_data = args[0]

        original(*args, **kwargs)

        if model is None:
            return
        extras = custom_field_selector_items(model)
        if not extras:
            return
        extra_by_name = {name: force_str(label) for label, name in extras}
        field = self.fields.get("visible_fields")
        if field is not None:
            existing = {choice[0] for choice in field.choices}
            new_choices = list(field.choices)
            for name, label in extra_by_name.items():
                if name not in existing:
                    new_choices.append((name, label))
            field.choices = new_choices
        if original_data is None or not hasattr(original_data, "getlist"):
            return
        if field is None or getattr(self, "data", None) is None:
            return
        allowed = {choice[0] for choice in field.choices}
        posted = original_data.getlist("visible_fields")
        kept = [name for name in posted if name in allowed]
        current = (
            list(self.data.getlist("visible_fields"))
            if hasattr(self.data, "getlist")
            else []
        )
        if kept == current:
            return
        data = self.data.copy()
        if hasattr(data, "setlist"):
            data.setlist("visible_fields", kept)
        else:
            data["visible_fields"] = kept
        self.data = data


class CustomFieldDateConditionWidgetExtension(MixinExtension):
    """Render date pickers for custom date fields in condition builders."""

    _inherit_mixin = (
        "horilla.contrib.generics.views.helpers.condition_widget."
        "GetFieldValueWidgetView"
    )

    def _get_value_widget_html(
        self,
        original,
        field_name,
        model_name,
        row_id,
        existing_value="",
        existing_operator="",
    ):
        try:
            html = render_date_condition_value_widget(
                self, field_name, row_id, existing_value, existing_operator
            )
        except Exception:
            logger.exception("custom_fields: could not render date condition widget")
            html = None
        if html is not None:
            return html
        return original(
            field_name, model_name, row_id, existing_value, existing_operator
        )


if django_apps.is_installed("horilla_crm.leads"):

    class CustomFieldDateLeadAssignmentExtension(MixinExtension):
        """Evaluate Lead assignment-rule criteria on custom date fields by value."""

        _inherit_mixin = "horilla_crm.leads.signals._eval_single_criterion"

        def _eval_single_criterion(self, original, criteria, lead):
            try:
                result = evaluate_date_criterion(
                    criteria.field, criteria.operator, criteria.value, lead
                )
            except Exception:
                logger.exception(
                    "custom_fields: could not evaluate date criterion %s",
                    criteria.field,
                )
                return False
            if result is None:
                return original(criteria, lead)
            return result
