"""
``_inherit_view`` extensions so Horilla export, bulk inline edit, and other
view hooks work for ``cf_*`` fields.

``ExportView`` is a single, concrete, model-agnostic view (routed directly
in ``urls.py``, never subclassed per app) — exactly the shape ``_inherit_view``
targets cleanly, so its two custom-fields hooks live here too, registered
declaratively instead of monkey-patched in ``custom_fields/hooks/export.py``.
This became possible once ``horilla.views.generic.TemplateView`` started
inheriting ``horilla.views.generic.base.View`` (the resolving base) — see
that class's docstring. ``HorillaBulkExportMixin.handle_export`` and the
module-level ``get_export_cell_value`` are registered declaratively too,
through ``MixinExtension``/``_inherit_mixin`` in
``custom_fields/extensions/mixin.py`` — the former is a bare mixin never
itself resolved via ``as_view()``/``get_*_class()``, and the latter is a
plain function, not a view method, so neither has a per-request resolution
point for ``_inherit_view`` to hook into.

``ExtraFieldsProvider`` is the "Edit Details" bulk-edit form's extension seam
for non-model fields (``EditAllFieldsView``/``UpdateAllFieldsView`` only know
about real ``obj._meta.get_fields()`` columns) — same single-concrete-class
shape as ``ExportView``, registered here too.

``CustomFieldMultiStepFormKwargsExtension`` targets the shared
``HorillaMultiStepFormView`` **base** class instead of one concrete wizard —
``resolve_view_class()`` (the same resolver every ``_inherit_view``
registration goes through) checks a concrete-class match first, then falls
back to checking base classes in the MRO, so this one registration applies
to every wizard view automatically. See
``horilla/extension/view/resolve.py``'s ``_resolve_via_base_class``.
"""

from horilla.contrib.field_management.hooks.detail import (
    custom_field_selector_items,
    get_custom_field_entries,
    save_custom_field_from_post,
)
from horilla.contrib.field_management.hooks.filter import (
    relabel_applied_filter_slot_rows,
)
from horilla.contrib.field_management.hooks.list import (
    attach_custom_field_values_to_objects,
)
from horilla.extension.view import ViewExtension


class CustomFieldExportViewExtension(ViewExtension):
    """
    Add custom fields to the Select Columns to Export modal and write their
    values into exported files.

    Statically targets the one concrete ``ExportView`` (not per-model like
    ``custom_fields/extensions/forms.py``/``detail_extensions.py`` — ``ExportView``
    itself already takes ``model`` as a runtime parameter), so real
    ``super()`` resolves correctly here even without the dynamic-registration
    template-copy trick those modules use.
    """

    _inherit_view = "horilla.contrib.core.views.export_data.ExportView"

    def get_available_models(self):
        """Augment export model catalogs with custom-field columns."""
        from horilla.contrib.field_management.hooks.export import (
            add_custom_fields_to_export_modules,
        )

        modules = super().get_available_models()
        try:
            add_custom_fields_to_export_modules(modules)
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "custom_fields: could not inject export columns"
            )
        return modules

    def export_model_data(
        self, model, export_format, queryset=None, selected_fields=None
    ):
        """Export selected ``cf_*`` columns alongside model fields."""
        from horilla.contrib.field_management.hooks.export import (
            _append_custom_field_columns,
            _custom_fields_only_export,
            _MaterializedObjectList,
        )

        extras = custom_field_selector_items(model)
        extra_names = {name for _label, name in extras}
        extra_pairs = [
            (label, name)
            for label, name in extras
            if selected_fields is None or name in selected_fields
        ]
        if not extra_pairs:
            return super().export_model_data(
                model, export_format, queryset, selected_fields
            )

        objects = _MaterializedObjectList(
            model.objects.all() if queryset is None else queryset
        )
        attach_custom_field_values_to_objects(model, objects, extras=extras)

        model_selected = None
        if selected_fields is not None:
            model_selected = [
                name for name in selected_fields if name not in extra_names
            ]
            if not model_selected:
                return _custom_fields_only_export(
                    self, model, export_format, objects, extra_pairs
                )

        filename, data = super().export_model_data(
            model, export_format, objects, model_selected
        )
        if extra_pairs and export_format in ("csv", "xlsx"):
            data = _append_custom_field_columns(
                data, export_format, objects, extra_pairs
            )
        return filename, data


class CustomFieldListColumnSelectFormViewExtension(ViewExtension):
    """
    Add custom fields to the Add Column to List modal and relabel any
    ``cf_*`` entries in the saved column visibility after a successful save.

    Statically targets the one concrete ``ListColumnSelectFormView`` (routed
    directly in ``urls.py``, never subclassed per app), so real ``super()``
    resolves correctly here without the dynamic-registration template-copy
    trick ``custom_fields/extensions/forms.py``/``detail_extensions.py`` use for
    per-model targets.
    """

    _inherit_view = (
        "horilla.contrib.generics.views.helpers.list_column.ListColumnSelectFormView"
    )

    def get_context_data(self, **kwargs):
        """Add custom fields to the list column-selector modal context."""
        from horilla.contrib.field_management.hooks.list import (
            add_custom_fields_to_column_selector,
        )

        context = super().get_context_data(**kwargs)
        try:
            add_custom_fields_to_column_selector(context)
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "custom_fields: could not inject list columns"
            )
        return context

    def form_valid(self, form):
        """Relabel saved ``cf_*`` list columns after a successful save."""
        from horilla.contrib.field_management.hooks.list import (
            relabel_saved_list_column_visibility,
        )

        response = super().form_valid(form)
        try:
            relabel_saved_list_column_visibility(self)
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "custom_fields: could not relabel saved list columns"
            )
        return response


class CustomFieldExtraFieldsProviderExtension(ViewExtension):
    """
    Add ``cf_*`` custom fields to the "Edit Details" bulk-edit form and save
    them alongside real model fields.

    ``ExtraFieldsProvider`` has no per-request state of its own (it's
    resolved fresh per call via ``get_extra_fields_provider()``), so both
    methods derive everything they need from their arguments.
    """

    _inherit_view = (
        "horilla.contrib.generics.views.helpers.edit_field.ExtraFieldsProvider"
    )

    def get_extra_fields(self, obj, request, can_update):
        """Append one bulk-edit entry per custom field defined on ``obj``'s model."""
        entries = super().get_extra_fields(obj, request, can_update)
        try:
            entries = entries + get_custom_field_entries(obj, request, can_update)
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "custom_fields: could not add custom fields to bulk-edit form"
            )
        return entries

    def apply_extra_field(self, obj, name, request):
        """Save ``name`` if it's a recognized ``cf_*`` custom field."""
        handled = save_custom_field_from_post(obj, name, request)
        if handled:
            return True
        return super().apply_extra_field(obj, name, request)


class CustomFieldMultiStepFormKwargsExtension(ViewExtension):
    """
    Keep every selected Multiple Choice custom-field value across multi-step
    wizard steps.

    Targets the shared ``HorillaMultiStepFormView`` base class — every
    concrete wizard view (``LeadCreateWizard``, etc., across every CRM app,
    present and future) inherits ``get_form_kwargs`` from it, so a
    per-concrete-view registration would need to name every wizard in
    advance. ``horilla.extension.view.resolve.resolve_view_class`` — the
    same resolver every ``_inherit_view`` registration goes through at
    ``as_view()`` time — checks an exact match for the concrete class
    first, then falls back to checking each base class in the concrete
    class's MRO, so a registration on ``HorillaMultiStepFormView`` here is
    picked up by every concrete wizard automatically. See
    ``horilla/extension/view/resolve.py``'s ``_resolve_via_base_class``.
    """

    _inherit_view = "horilla.contrib.generics.views.multi_form.HorillaMultiStepFormView"

    def get_form_kwargs(self):
        """Overlay POST multi-choice ``cf_*`` values onto wizard form data."""
        from horilla.contrib.field_management.hooks.form import (
            overlay_custom_choice_post_values,
        )

        kwargs = super().get_form_kwargs()
        if getattr(self.request, "method", "") != "POST":
            return kwargs
        form_data = kwargs.get("form_data")
        if form_data is None:
            return kwargs
        try:
            if overlay_custom_choice_post_values(self.request.POST, form_data):
                kwargs["form_data"] = form_data
                kwargs["data"] = form_data
                storage_key = getattr(self, "storage_key", None)
                if storage_key:
                    self.request.session[storage_key] = form_data
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "custom_fields: could not keep multi-select POST values"
            )
        return kwargs


class CustomFieldScheduleExportProviderExtension(ViewExtension):
    """
    Offer custom fields in Schedule Export and write them into the emailed file.

    Scheduled exports are built by plain functions, so ``ScheduleExportProvider``
    is their extension seam (same pattern as ``ExtraFieldsProvider``).
    """

    _inherit_view = "horilla.contrib.core.views.export_data.ScheduleExportProvider"

    def get_extra_fields(self, model):
        """Append the model's custom fields to the schedule column picker."""
        extras = list(super().get_extra_fields(model))
        try:
            extras += [tuple(item) for item in custom_field_selector_items(model)]
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "custom_fields: could not add schedule export columns"
            )
        return extras

    def export_model_data(
        self, model, export_format, user=None, queryset=None, selected_fields=None
    ):
        """Write selected ``cf_*`` columns alongside the model columns."""
        from horilla.contrib.field_management.hooks.export import (
            _append_custom_field_columns,
            _custom_fields_only_export,
            _MaterializedObjectList,
        )

        extras = custom_field_selector_items(model)
        extra_names = {name for _label, name in extras}
        extra_pairs = [
            (label, name)
            for label, name in extras
            if not selected_fields or name in selected_fields
        ]
        if not extra_pairs or export_format not in ("csv", "xlsx"):
            return super().export_model_data(
                model, export_format, user, queryset, selected_fields
            )

        objects = _MaterializedObjectList(
            model.objects.all() if queryset is None else queryset
        )
        attach_custom_field_values_to_objects(model, objects, extras=extras)

        model_selected = None
        if selected_fields:
            model_selected = [n for n in selected_fields if n not in extra_names]
            if not model_selected:

                class _Namer:
                    @staticmethod
                    def get_export_filename(model, fmt):
                        return f"{model.__name__}_export.{fmt}"

                return _custom_fields_only_export(
                    _Namer, model, export_format, objects, extra_pairs
                )

        filename, data = super().export_model_data(
            model, export_format, user, objects, model_selected
        )
        return filename, _append_custom_field_columns(
            data, export_format, objects, extra_pairs
        )


def _model_from_request(request):
    """Model named by a field-selection request (``content_type`` / ``model_name``)."""
    from django.apps import apps as django_apps

    from horilla.contrib.core.models import HorillaContentType

    content_type_id = request.GET.get("content_type")
    model_name = request.GET.get("model_name")
    try:
        if content_type_id:
            content_type = HorillaContentType.objects.get(id=content_type_id)
        elif model_name:
            content_type = HorillaContentType.objects.get(model=model_name.lower())
        else:
            return None
        return django_apps.get_model(content_type.app_label, content_type.model)
    except Exception:
        return None


def _add_template_custom_fields(view, context):
    """Add custom fields to the "Insert Fields" picker of mail / notification templates."""
    if context.get("tab_type") != "instance" or "model_fields" not in context:
        return context
    model = _model_from_request(view.request)
    if model is None:
        return context
    fields = list(context["model_fields"])
    for label, name in custom_field_selector_items(model):
        fields.append(
            {
                "name": name,
                "verbose_name": label,
                "field_type": "CustomField",
                "template_syntax": f'{{{{ instance|extension_field:"{name}" }}}}',
                "is_foreign_key": False,
                "is_relation": False,
            }
        )
    context["model_fields"] = fields
    return context


class CustomFieldFieldSelectionExtension(ViewExtension):
    """Offer custom fields in the "Insert Fields" modal (mail and notification templates)."""

    _inherit_view = (
        "horilla.contrib.generics.views.field_selection.HorillaFieldSelectionView"
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            return _add_template_custom_fields(self, context)
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "custom_fields: could not add template fields"
            )
            return context


class CustomFieldPermissionFieldsExtension(ViewExtension):
    """List custom fields in the field-level permission modal."""

    _inherit_view = (
        "horilla.contrib.core.views.groups_and_permissions.base.ModelFieldsModalView"
    )

    def get_extra_permission_fields(self, model, existing_permissions):
        entries = list(super().get_extra_permission_fields(model, existing_permissions))
        for label, name in custom_field_selector_items(model):
            entries.append(
                {
                    "name": name,
                    "verbose_name": label,
                    "field_type": "CustomField",
                    "current_permission": existing_permissions.get(name, "readwrite"),
                    "is_mandatory": False,
                }
            )
        return entries


class CustomFieldNavbarAppliedFilterExtension(ViewExtension):
    """Show a custom field's real name on the navbar's applied-filter chip."""

    _inherit_view = "horilla.contrib.generics.views.navbar.HorillaNavView"

    def get_context_data(self, **kwargs):
        """Relabel ``cf_*`` applied-filter rows after the navbar builds them."""
        context = super().get_context_data(**kwargs)
        # Navbars without a model (e.g. non-list pages) have no custom fields
        if not (self.model_app_label and self.model_name):
            return context
        try:
            from horilla.apps import apps

            model = apps.get_model(self.model_app_label, self.model_name)
            relabel_applied_filter_slot_rows(self.request, model, context)
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "custom_fields: could not relabel applied filters"
            )
        return context
