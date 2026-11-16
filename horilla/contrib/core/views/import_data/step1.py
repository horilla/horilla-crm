"""Step 1 of import: file upload and module selection."""

# Standard library imports
import csv
import difflib
import logging
import traceback

# Third-party imports (other)
import pandas as pd

# Third-party imports (Django)
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

# First party imports (Horilla)
from horilla.apps import apps
from horilla.db.models import CharField, EmailField, ForeignKey, URLField
from horilla.registry.feature import FEATURE_REGISTRY
from horilla.shortcuts import render
from horilla.utils.decorators import method_decorator, permission_required_or_denied
from horilla.utils.text import slugify
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View

# Local imports
from .base import IMPORT_EXCLUDED_FIELDS, ImportDataView, get_import_excluded_fields

logger = logging.getLogger(__name__)


@method_decorator(
    permission_required_or_denied("core.can_view_horilla_import"),
    name="dispatch",
)
class ImportStep1View(View):
    """Handle file upload and module selection"""

    def post(self, request, *args, **kwargs):
        """Handle file upload and module selection"""
        import_config = request.session.get("import_config", {})
        single_import = import_config.get("single_import", False)
        restricted_model_name = import_config.get("model_name", "")
        restricted_app_label = import_config.get("app_label", "")

        module = request.POST.get("module")
        import_name = request.POST.get("import_name")
        uploaded_file = request.FILES.get("file")

        if not single_import and module:
            # Verify the submitted module is a registered import model
            import_models = FEATURE_REGISTRY.get("import_models", [])
            registered_names = {m.__name__ for m in import_models}
            if module not in registered_names:
                permitted_modules = self._get_permitted_modules(request)
                return render(
                    request,
                    "import/import_data.html",
                    {
                        "modules": permitted_modules,
                        "error_message": _(
                            "Invalid module selection. Please choose a valid module from the list."
                        ),
                        "single_import": False,
                    },
                )

            # Verify user has add permission for the submitted module
            submitted_app_label = self.get_app_label_for_model(module)
            if not submitted_app_label or not request.user.has_perm(
                f"{submitted_app_label}.add_{module.lower()}"
            ):
                permitted_modules = self._get_permitted_modules(request)
                return render(
                    request,
                    "import/import_data.html",
                    {
                        "modules": permitted_modules,
                        "error_message": _(
                            "Invalid module selection. Please choose a valid module from the list."
                        ),
                        "single_import": False,
                    },
                )

        if single_import:
            # Verify the session model is a registered import model and user has add permission
            if restricted_app_label and restricted_model_name:
                import_models = FEATURE_REGISTRY.get("import_models", [])
                registered_single = next(
                    (
                        m
                        for m in import_models
                        if m.__name__ == restricted_model_name
                        and m._meta.app_label == restricted_app_label
                    ),
                    None,
                )
                add_perm = f"{restricted_app_label}.add_{restricted_model_name.lower()}"
                if not registered_single or not request.user.has_perm(add_perm):
                    return render(
                        request,
                        "import/import_data.html",
                        {
                            "modules": [],
                            "error_message": _(
                                "Invalid module selection. Please choose a valid module from the list."
                            ),
                            "single_import": True,
                            "selected_module": restricted_model_name,
                        },
                    )
            if module != restricted_model_name:
                view = ImportDataView()
                view.request = request
                modules = []
                try:
                    model = apps.get_model(restricted_app_label, restricted_model_name)
                    modules = [
                        {
                            "name": model.__name__,
                            "label": model._meta.verbose_name,
                            "app_label": model._meta.app_label,
                            "module": model.__module__,
                        }
                    ]
                except LookupError:
                    logger.error(
                        "Model %s.%s not found",
                        restricted_app_label,
                        restricted_model_name,
                    )
                context = {
                    "modules": modules,
                    "error_message": "Invalid module. Choose one of the available choice",
                    "single_import": single_import,
                    "selected_module": restricted_model_name,
                    "selected_import_name": import_name,  # Preserve user input
                }
                return render(request, "import/import_data.html", context)

        # Check if we have existing import data (back navigation scenario)
        existing_import_data = request.session.get("import_data", {})

        # For back navigation, we might not have a new file upload
        if existing_import_data and not uploaded_file:
            # Use existing file data if available
            existing_file_path = existing_import_data.get("file_path")
            existing_filename = existing_import_data.get("original_filename")

            if not all([module, import_name]):
                return render(
                    request,
                    "common/message_fragment.html",
                    {
                        "message": _("Module and Import Name are required"),
                        "variant": "sm",
                    },
                )

            if existing_file_path and existing_filename:
                # Update session with new module/import_name but keep existing file
                existing_import_data.update(
                    {
                        "module": module,
                        "import_name": import_name,
                    }
                )
                request.session["import_data"] = existing_import_data

                # Get fresh data based on new module selection
                try:
                    app_label = self.get_app_label_for_model(module)
                    existing_import_data["app_label"] = app_label
                    request.session["import_data"] = existing_import_data

                    model_fields = self.get_model_fields(module, app_label)
                    if not model_fields:
                        return render(
                            request,
                            "common/message_fragment.html",
                            {
                                "message": f"{_('No valid fields found for the selected model')}: {module}",
                                "variant": "sm",
                            },
                        )

                    headers = existing_import_data.get("headers", [])
                    sample_data = existing_import_data.get("sample_data", [])
                    unique_values = existing_import_data.get("unique_values", {})

                    auto_mappings = self.auto_map_fields(headers, model_fields)
                    choice_mappings, fk_mappings = self.auto_map_values(
                        unique_values, model_fields, auto_mappings, app_label
                    )

                    if "field_mappings" not in existing_import_data:
                        existing_import_data["auto_mappings"] = auto_mappings
                    if "choice_mappings" not in existing_import_data:
                        existing_import_data["auto_choice_mappings"] = choice_mappings
                    if "fk_mappings" not in existing_import_data:
                        existing_import_data["auto_fk_mappings"] = fk_mappings

                    request.session["import_data"] = existing_import_data

                    return render(
                        request,
                        "import/import_step2.html",
                        {
                            "headers": headers,
                            "sample_data": sample_data,
                            "model_fields": model_fields,
                            "module": module,
                            "app_label": app_label,
                            "auto_mappings": existing_import_data.get(
                                "auto_mappings", {}
                            ),
                            "auto_choice_mappings": existing_import_data.get(
                                "auto_choice_mappings", {}
                            ),
                            "auto_fk_mappings": existing_import_data.get(
                                "auto_fk_mappings", {}
                            ),
                            "replace_values": existing_import_data.get(
                                "replace_values", {}
                            ),
                            "single_import": single_import,
                            "selected_module": restricted_model_name,
                        },
                    )
                except Exception as e:
                    tb = traceback.format_exc()
                    logger.error(tb)
                    return render(
                        request,
                        "common/message_fragment.html",
                        {
                            "message": f"Error processing module change: {e!s}",
                            "variant": "sm",
                        },
                    )

        # Original validation for new uploads
        if not all([module, import_name, uploaded_file]):
            return render(
                request,
                "common/message_fragment.html",
                {"message": _("All fields are required"), "variant": "sm"},
            )

        if not uploaded_file.name.endswith((".csv", ".xlsx", ".xls")):
            return render(
                request,
                "common/message_fragment.html",
                {"message": _("Please upload a CSV or Excel file"), "variant": "sm"},
            )

        try:
            app_label = self.get_app_label_for_model(module)
            file_path = default_storage.save(
                f"imports/{uploaded_file.name}", ContentFile(uploaded_file.read())
            )

            # Store minimal session data
            request.session["import_data"] = {
                "module": module,
                "import_name": import_name,
                "file_path": file_path,
                "original_filename": uploaded_file.name,
                "app_label": app_label,
            }

            # Parse file
            headers = self.get_file_headers(file_path)
            sample_data = self.get_sample_data(file_path)
            unique_values = self.get_unique_file_values(file_path, headers)

            # Store headers, sample data, and unique values in session
            request.session["import_data"]["headers"] = headers
            request.session["import_data"]["sample_data"] = sample_data[:1]
            request.session["import_data"]["unique_values"] = unique_values

            model_fields = self.get_model_fields(module, app_label)
            if not model_fields:
                return render(
                    request,
                    "common/message_fragment.html",
                    {
                        "message": f"{_('No valid fields found for the selected model')}: {module}",
                        "variant": "sm",
                    },
                )

            # Auto-map fields
            auto_mappings = self.auto_map_fields(headers, model_fields)

            # Auto-map choice and foreign key values
            choice_mappings, fk_mappings = self.auto_map_values(
                unique_values, model_fields, auto_mappings, app_label
            )

            # Store auto-mappings in session for later use
            request.session["import_data"]["auto_mappings"] = auto_mappings
            request.session["import_data"]["auto_choice_mappings"] = choice_mappings
            request.session["import_data"]["auto_fk_mappings"] = fk_mappings

            return render(
                request,
                "import/import_step2.html",
                {
                    "headers": headers,
                    "sample_data": sample_data,
                    "model_fields": model_fields,
                    "module": module,
                    "app_label": app_label,
                    "auto_mappings": auto_mappings,
                    "auto_choice_mappings": choice_mappings,
                    "auto_fk_mappings": fk_mappings,
                    "single_import": single_import,
                    "selected_module": restricted_model_name,
                },
            )
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(tb)
            return render(
                request,
                "common/message_fragment.html",
                {"message": f"Error processing file: {e!s}", "variant": "sm"},
            )

    def auto_map_fields(self, headers, model_fields):
        """Automatically map file headers to model fields using fuzzy matching"""
        auto_mappings = {}

        # Normalize headers and field names for better matching
        def normalize_text(text):
            return text.lower().replace("_", " ").replace("-", " ").strip()

        # Create normalized mappings
        normalized_headers = {normalize_text(header): header for header in headers}
        normalized_fields = {
            normalize_text(field["name"]): field["name"] for field in model_fields
        }
        normalized_verbose = {
            normalize_text(field["verbose_name"]): field["name"]
            for field in model_fields
        }

        # Direct exact matches (normalized)
        for norm_header, original_header in normalized_headers.items():
            if norm_header in normalized_fields:
                auto_mappings[normalized_fields[norm_header]] = original_header
            elif norm_header in normalized_verbose:
                auto_mappings[normalized_verbose[norm_header]] = original_header

        # Fuzzy matching for remaining fields
        mapped_headers = set(auto_mappings.values())
        unmapped_headers = [h for h in headers if h not in mapped_headers]
        mapped_fields = set(auto_mappings.keys())
        unmapped_fields = [
            f["name"] for f in model_fields if f["name"] not in mapped_fields
        ]

        for header in unmapped_headers:
            norm_header = normalize_text(header)
            best_match = None
            best_ratio = 0.6  # Minimum similarity threshold

            # Check against field names
            for field_name in unmapped_fields:
                norm_field = normalize_text(field_name)
                ratio = difflib.SequenceMatcher(None, norm_header, norm_field).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = field_name

            # Check against verbose names if no good field name match
            if not best_match:
                for field in model_fields:
                    if field["name"] in unmapped_fields:
                        norm_verbose = normalize_text(field["verbose_name"])
                        ratio = difflib.SequenceMatcher(
                            None, norm_header, norm_verbose
                        ).ratio()
                        if ratio > best_ratio:
                            best_ratio = ratio
                            best_match = field["name"]

            if best_match:
                auto_mappings[best_match] = header
                unmapped_fields.remove(best_match)

        return auto_mappings

    def auto_map_values(self, unique_values, model_fields, field_mappings, app_label):
        """Automatically map choice field and foreign key values"""
        choice_mappings = {}
        fk_mappings = {}

        for field in model_fields:
            field_name = field["name"]

            # Only process fields that are mapped
            if field_name not in field_mappings:
                continue

            file_header = field_mappings[field_name]
            file_values = unique_values.get(file_header, [])

            if not file_values:
                continue

            # Handle choice fields
            if field["is_choice_field"]:
                choice_dict = {
                    choice["value"]: choice["label"] for choice in field["choices"]
                }
                field_choice_mappings = {}

                for file_value in file_values:
                    best_match = self.find_best_choice_match(file_value, choice_dict)
                    if best_match:
                        slug_value = slugify(file_value)
                        field_choice_mappings[slug_value] = best_match

                if field_choice_mappings:
                    choice_mappings[field_name] = field_choice_mappings

            # Handle foreign key fields
            elif field["is_foreign_key"]:
                fk_objects = {
                    str(fk["display"]): fk["id"] for fk in field["foreign_key_choices"]
                }
                field_fk_mappings = {}

                for file_value in file_values:
                    best_match_id = self.find_best_fk_match(file_value, fk_objects)
                    if best_match_id:
                        slug_value = slugify(file_value)
                        field_fk_mappings[slug_value] = best_match_id

                if field_fk_mappings:
                    fk_mappings[field_name] = field_fk_mappings

        return choice_mappings, fk_mappings

    def find_best_choice_match(self, file_value, choice_dict):
        """Find the best matching choice using fuzzy string matching"""

        def normalize_text(text):
            return str(text).lower().strip().replace("_", " ").replace("-", " ")

        norm_file_value = normalize_text(file_value)

        # Try exact match first (normalized)
        for choice_value, choice_label in choice_dict.items():
            if norm_file_value == normalize_text(choice_value):
                return choice_value
            if norm_file_value == normalize_text(choice_label):
                return choice_value

        # Try fuzzy matching
        best_match = None
        best_ratio = 0.7  # Higher threshold for choices

        for choice_value, choice_label in choice_dict.items():
            # Check against choice value
            ratio = difflib.SequenceMatcher(
                None, norm_file_value, normalize_text(choice_value)
            ).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = choice_value

            # Check against choice label
            ratio = difflib.SequenceMatcher(
                None, norm_file_value, normalize_text(choice_label)
            ).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = choice_value

        return best_match

    def find_best_fk_match(self, file_value, fk_objects):
        """Find the best matching foreign key object using fuzzy string matching"""

        def normalize_text(text):
            return str(text).lower().strip().replace("_", " ").replace("-", " ")

        norm_file_value = normalize_text(file_value)

        # Try exact match first (normalized)
        for display_name, obj_id in fk_objects.items():
            if norm_file_value == normalize_text(display_name):
                return obj_id

        # Try fuzzy matching
        best_match_id = None
        best_ratio = 0.7  # Higher threshold for FK matches

        for display_name, obj_id in fk_objects.items():
            ratio = difflib.SequenceMatcher(
                None, norm_file_value, normalize_text(display_name)
            ).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match_id = obj_id

        return best_match_id

    def _get_permitted_modules(self, request):
        """Return registered import models the user has add permission for."""
        permitted = []
        try:
            for model in FEATURE_REGISTRY.get("import_models", []):
                add_perm = f"{model._meta.app_label}.add_{model._meta.model_name}"
                if request.user.has_perm(add_perm):
                    permitted.append(
                        {
                            "name": model.__name__,
                            "label": model._meta.verbose_name,
                            "app_label": model._meta.app_label,
                            "module": model.__module__,
                        }
                    )
        except Exception as e:
            logger.error("Error building permitted modules list: %s", e)
        return permitted

    def get_app_label_for_model(self, model_name):
        """Find the app_label for a given model name"""

        for app_config in apps.get_app_configs():
            try:
                _model = apps.get_model(app_config.label, model_name)
                return app_config.label
            except LookupError:
                continue
        return None

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

                if isinstance(field, EmailField):
                    field_type = "EmailField"
                elif isinstance(field, URLField):
                    field_type = "URLField"
                else:
                    field_type = field.get_internal_type()

                field_info = {
                    "name": field.name,
                    "verbose_name": field.verbose_name,
                    "required": not field.null and not field.blank,
                    "field_type": field_type,
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

    def get_file_headers(self, file_path):
        """Extract headers from uploaded file"""
        full_path = default_storage.path(file_path)
        if file_path.endswith(".csv"):
            with open(full_path, "r", encoding="utf-8") as file:
                reader = csv.reader(file)
                headers = next(reader)
        else:
            df = pd.read_excel(full_path, nrows=0)
            headers = list(df.columns)
        return headers

    def get_sample_data(self, file_path):
        """Get sample data from file"""
        full_path = default_storage.path(file_path)
        sample_data = []

        if file_path.endswith(".csv"):
            with open(full_path, "r", encoding="utf-8") as file:
                reader = csv.DictReader(file)
                for i, row in enumerate(reader):
                    if i >= 3:
                        break
                    sample_data.append(dict(row))
        else:
            df = pd.read_excel(full_path, nrows=3)
            # Convert all columns to string to avoid Timestamp serialization issues
            df = df.astype(str)
            sample_data = df.to_dict("records")

        return sample_data

    def get_unique_file_values(self, file_path, headers):
        """Extract unique values for each column in the file"""
        full_path = default_storage.path(file_path)
        unique_values = {header: set() for header in headers}

        if file_path.endswith(".csv"):
            with open(full_path, "r", encoding="utf-8") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    for header in headers:
                        value = str(row.get(header, "")).strip()
                        if value and value.lower() != "nan":
                            unique_values[header].add(value)
        else:
            df = pd.read_excel(full_path)
            for header in headers:
                if header in df.columns:
                    # Convert entire column to string before processing
                    str_values = df[header].astype(str).str.strip()
                    # Filter out NaN and empty strings
                    unique_values[header].update(
                        v
                        for v in str_values.tolist()
                        if isinstance(v, str) and v and v.lower() != "nan"
                    )

        return {
            header: sorted(list(values)) for header, values in unique_values.items()
        }
