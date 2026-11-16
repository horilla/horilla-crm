"""Step 3 of import: import options (create/update/both, match fields)."""

# Standard library imports
import logging
import traceback

# First party imports (Horilla)
from horilla.apps import apps
from horilla.db.models import CharField, ForeignKey
from horilla.shortcuts import redirect, render
from horilla.utils.decorators import method_decorator, permission_required_or_denied
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View

# Local imports
from .base import (
    IMPORT_EXCLUDED_FIELDS,
    get_import_excluded_fields,
    get_model_verbose_name,
)

# Third-party imports (Django)


logger = logging.getLogger(__name__)


@method_decorator(
    permission_required_or_denied("core.can_view_horilla_import"),
    name="dispatch",
)
class ImportStep3View(View):
    """Handle import options"""

    def get(self, request, *args, **kwargs):
        """Handle navigation back to step 3"""
        import_data = request.session.get("import_data", {})
        import_config = request.session.get("import_config", {})
        single_import = import_config.get("single_import", False)
        if not import_data:
            return redirect("core:import_data")

        module = import_data.get("module")
        app_label = import_data.get("app_label")

        if not module or not app_label:
            return redirect("core:import_data")

        model_fields = self.get_model_fields(module, app_label)

        # Get existing selections from session
        selected_import_option = import_data.get("import_option", "1")
        selected_match_fields = import_data.get("match_fields", [])

        return render(
            request,
            "import/import_step3.html",
            {
                "module": module,
                "app_label": app_label,
                "model_fields": model_fields,
                "selected_import_option": selected_import_option,
                "selected_match_fields": selected_match_fields,
                "single_import": single_import,
            },
        )

    def post(self, request, *args, **kwargs):
        """Handle import options submission"""
        import_data = request.session.get("import_data", {})
        module = import_data.get("module")
        app_label = import_data.get("app_label")
        import_config = request.session.get("import_config", {})
        single_import = import_config.get("single_import", False)

        if not module or not app_label:
            return render(
                request,
                "common/message_fragment.html",
                {
                    "message": _("Missing module or app_label in session"),
                    "variant": "sm",
                },
            )

        try:
            import_option = request.POST.get(
                "import_option"
            )  # 1=create, 2=update, 3=both
            match_fields = request.POST.getlist("match_fields")

            if import_option in ["2", "3"] and not match_fields:
                model_fields = self.get_model_fields(module, app_label)
                return render(
                    request,
                    "import/import_step3.html",
                    {
                        "module": module,
                        "app_label": app_label,
                        "model_fields": model_fields,
                        "error_message": "Please select at least one field to match records for update operations.",
                        "selected_import_option": import_option,
                        "selected_match_fields": match_fields,
                    },
                )

            import_data["import_option"] = import_option
            import_data["match_fields"] = match_fields
            request.session["import_data"] = import_data

            # Calculate mapped and unmapped fields
            field_mappings = import_data.get("field_mappings", {})
            headers = import_data.get("headers", [])

            mapped_count = len(field_mappings)
            unmapped_count = len(headers) - mapped_count

            # Get the verbose name for the module
            module_verbose_name = get_model_verbose_name(module, app_label)

            try:
                return render(
                    request,
                    "import/import_step4.html",
                    {
                        "import_data": import_data,
                        "mapped_count": mapped_count,
                        "unmapped_count": unmapped_count,
                        "module": module,
                        "module_verbose_name": module_verbose_name,
                        "app_label": app_label,
                        "single_import": single_import,
                    },
                )
            except Exception as e:
                logger.error("Template rendering error in ImportStep3View: %s", e)
                tb = traceback.format_exc()
                logger.error(tb)
                return render(
                    request,
                    "common/message_fragment.html",
                    {
                        "message": f"Template rendering error: {e!s}",
                        "variant": "sm",
                    },
                )

        except Exception as e:
            logger.error("Error in ImportStep3View.post: %s", e)
            tb = traceback.format_exc()
            logger.error(tb)
            return render(
                request,
                "common/message_fragment.html",
                {
                    "message": f"Error processing import options: {e!s}",
                    "variant": "sm",
                },
            )

    def get_model_fields(self, module_name, app_label):
        """Get fields from the selected model with choice and foreign key info"""

        try:
            model = apps.get_model(app_label, module_name)
            fields = []
            for field in model._meta.fields:
                if field.name in get_import_excluded_fields(model):
                    continue
                if not getattr(field, "editable", True):
                    continue
                field_info = {
                    "name": field.name,
                    "verbose_name": field.verbose_name,
                    "required": not field.null and not field.blank,
                    "field_type": field.get_internal_type(),
                    "is_choice_field": False,
                    "is_foreign_key": False,
                    "choices": [],
                    "foreign_key_model": None,
                    "foreign_key_choices": [],
                }
                # Handle ChoiceField
                if isinstance(field, CharField) and field.choices:
                    field_info["is_choice_field"] = True
                    field_info["choices"] = [
                        {"value": value, "label": label}
                        for value, label in field.choices
                    ]
                # Handle ForeignKey
                elif isinstance(field, ForeignKey):
                    field_info["is_foreign_key"] = True
                    field_info["foreign_key_model"] = field.related_model
                    related_instances = field.related_model.objects.all()
                    field_info["foreign_key_choices"] = [
                        {"id": instance.pk, "display": str(instance)}
                        for instance in related_instances
                    ]
                fields.append(field_info)
            return fields
        except Exception as e:
            logger.error(
                "Error in get_model_fields (app_label: %s, module: %s): %s",
                app_label,
                module_name,
                e,
            )
            return []
