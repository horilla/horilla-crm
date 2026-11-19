"""
Reflect field requirements and custom fields in the import wizard, through
``ViewExtension``/``_inherit_view`` on the concrete import views.

``get_model_fields`` on the import views only reads model columns and the
model-level ``null``/``blank`` flags, so it ignores per-company field
requirement overrides and custom fields.

- Field requirement overrides are applied to the ``required`` flag in every
  import step and in the Download Template modal.
- Custom fields are listed in the Download Template modal and their header is
  rewritten from ``cf_<id>`` to the field label in the downloaded file.
"""

import csv
import io
import logging

from django.apps import apps
from openpyxl import load_workbook

from horilla.contrib.field_management.utils.custom_fields import (
    custom_field_form_name,
    get_custom_field_definitions,
    safe_custom_field_label,
)
from horilla.contrib.field_management.utils.field_requirements import (
    get_field_requirements_for_model,
)
from horilla.extension.view import ViewExtension

logger = logging.getLogger(__name__)

_IMPORT = "horilla.contrib.core.views.import_data"


def _apply_requirements(fields, module_name, app_label):
    """Override ``required`` from the active company's field requirements."""
    try:
        model = apps.get_model(app_label, module_name)
        overrides = get_field_requirements_for_model(model)
    except Exception:
        logger.exception("field_requirements: could not load import overrides")
        return fields
    for info in fields:
        if info["name"] in overrides:
            info["required"] = overrides[info["name"]]
    return fields


class ImportStep1RequirementsExtension(ViewExtension):
    """Apply field requirements to the step 1 field list."""

    _inherit_view = f"{_IMPORT}.step1.ImportStep1View"

    def get_model_fields(self, module_name, app_label):
        """Step 1 fields, with the field-requirement overrides applied."""
        fields = super().get_model_fields(module_name, app_label)
        return _apply_requirements(fields, module_name, app_label)


class ImportStep2RequirementsExtension(ViewExtension):
    """Apply field requirements to the step 2 field list."""

    _inherit_view = f"{_IMPORT}.step2.ImportStep2View"

    def get_model_fields(self, module_name, app_label):
        """Step 2 fields, with the field-requirement overrides applied."""
        fields = super().get_model_fields(module_name, app_label)
        return _apply_requirements(fields, module_name, app_label)


class ImportStep3RequirementsExtension(ViewExtension):
    """Apply field requirements to the step 3 field list."""

    _inherit_view = f"{_IMPORT}.step3.ImportStep3View"

    def get_model_fields(self, module_name, app_label):
        """Step 3 fields, with the field-requirement overrides applied."""
        fields = super().get_model_fields(module_name, app_label)
        return _apply_requirements(fields, module_name, app_label)


class DownloadTemplateModalFieldsExtension(ViewExtension):
    """Apply field requirements and add custom fields to the template modal."""

    _inherit_view = f"{_IMPORT}.aux_views.DownloadTemplateModalView"

    def get_model_fields(self, module_name, app_label):
        """Template fields, with requirements applied and custom fields added."""
        fields = _apply_requirements(
            super().get_model_fields(module_name, app_label), module_name, app_label
        )
        try:
            model = apps.get_model(app_label, module_name)
            for defn in get_custom_field_definitions(model):
                fields.append(
                    {
                        "name": custom_field_form_name(defn),
                        "verbose_name": safe_custom_field_label(defn),
                        "required": False,
                    }
                )
        except Exception:
            logger.exception("custom_fields: could not add template fields")
        return fields


class DownloadTemplateHeadersExtension(ViewExtension):
    """Replace ``cf_<id>`` headers in the template file with field labels."""

    _inherit_view = f"{_IMPORT}.aux_views.DownloadTemplateView"

    def post(self, request, *args, **kwargs):
        """Template download, with custom-field headers shown as labels."""
        response = super().post(request, *args, **kwargs)
        selected = [
            n for n in request.POST.getlist("selected_fields") if n.startswith("cf_")
        ]
        if not selected or response.status_code != 200:
            return response
        try:
            model = apps.get_model(
                request.POST.get("app_label"), request.POST.get("module")
            )
            labels = {
                custom_field_form_name(d): str(safe_custom_field_label(d))
                for d in get_custom_field_definitions(model)
            }
            if request.POST.get("file_format", "xlsx") == "csv":
                rows = list(csv.reader(io.StringIO(response.content.decode())))
                rows[0] = [labels.get(h, h) for h in rows[0]]
                buffer = io.StringIO()
                csv.writer(buffer).writerows(rows)
                response.content = buffer.getvalue().encode()
            else:
                wb = load_workbook(io.BytesIO(response.content))
                for cell in wb.active[1]:
                    cell.value = labels.get(cell.value, cell.value)
                buffer = io.BytesIO()
                wb.save(buffer)
                response.content = buffer.getvalue()
        except Exception:
            logger.exception("custom_fields: could not relabel template headers")
        return response
