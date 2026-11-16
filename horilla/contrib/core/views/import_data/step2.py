"""Step 2 of import: field mapping."""

# Standard library imports
import logging
import traceback

# First party imports (Horilla)
from horilla.apps import apps
from horilla.db.models import CharField, EmailField, ForeignKey, URLField
from horilla.shortcuts import redirect, render
from horilla.utils.choices import TABLE_FALLBACK_FIELD_TYPES
from horilla.utils.decorators import method_decorator, permission_required_or_denied
from horilla.utils.text import slugify
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View

# Local imports
from .base import IMPORT_EXCLUDED_FIELDS, get_import_excluded_fields

# Third-party imports (Django)


logger = logging.getLogger(__name__)


@method_decorator(
    permission_required_or_denied("core.can_view_horilla_import"),
    name="dispatch",
)
class ImportStep2View(View):
    """Handle field mapping"""

    def get(self, request, *args, **kwargs):
        """Handle navigation back to step 2"""
        import_data = request.session.get("import_data", {})
        import_config = request.session.get("import_config", {})
        single_import = import_config.get("single_import", False)
        model_name = import_config.get("model_name", "")
        if not import_data:
            return redirect("core:import_data")

        module = import_data.get("module")
        app_label = import_data.get("app_label")
        headers = import_data.get("headers", [])
        sample_data = import_data.get("sample_data", [])

        if not all([module, app_label, headers]):
            return redirect("core:import_data")

        # Get model fields
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

        # Get existing mappings from session
        auto_mappings = import_data.get("auto_mappings", {})
        auto_choice_mappings = import_data.get("auto_choice_mappings", {})
        auto_fk_mappings = import_data.get("auto_fk_mappings", {})
        field_mappings = import_data.get("field_mappings", {})
        replace_values = import_data.get("replace_values", {})
        choice_mappings = import_data.get("choice_mappings", {})
        fk_mappings = import_data.get("fk_mappings", {})

        # Merge auto mappings with manual mappings
        current_mappings = auto_mappings.copy()
        current_mappings.update(field_mappings)

        return render(
            request,
            "import/import_step2.html",
            {
                "headers": headers,
                "sample_data": sample_data,
                "model_fields": model_fields,
                "module": module,
                "app_label": app_label,
                "auto_mappings": current_mappings,
                "auto_choice_mappings": auto_choice_mappings,
                "auto_fk_mappings": auto_fk_mappings,
                "replace_values": replace_values,
                "choice_mappings": choice_mappings,
                "fk_mappings": fk_mappings,
                "validation_errors": {},
                "single_import": single_import,
                "selected_module": model_name,
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

                # Determine the field type - use actual class for EmailField and URLField
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

    def post(self, request, *args, **kwargs):
        """Handle field mapping submission and validation"""
        import_data = request.session.get("import_data", {})
        import_config = request.session.get("import_config", {})
        single_import = import_config.get("single_import", False)
        model_name = import_config.get("model_name", "")
        module = import_data.get("module")
        app_label = import_data.get("app_label")
        unique_values = import_data.get("unique_values", {})

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
            field_mappings = {}
            replace_values = {}
            choice_mappings = {}
            fk_mappings = {}
            validation_errors = {}

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

            model = apps.get_model(app_label, module)
            model_field_names = [field.name for field in model._meta.fields]

            field_lookup = {field["name"]: field for field in model_fields}

            for key, value in request.POST.items():
                if key.startswith("file_header_"):
                    field_name = key.replace("file_header_", "")
                    if value:
                        field_mappings[field_name] = value
                elif key.startswith("replace_"):
                    field_name = key.replace("replace_", "")
                    if value:
                        replace_values[field_name] = value
                elif key.startswith("choice_mapping_") or key.startswith("fk_mapping_"):
                    is_choice = key.startswith("choice_mapping_")
                    prefix = "choice_mapping_" if is_choice else "fk_mapping_"
                    remaining = key.replace(prefix, "")

                    field_name = None
                    slugified_value = None

                    for model_field in sorted(model_field_names, key=len, reverse=True):
                        if remaining.startswith(model_field + "_"):
                            field_name = model_field
                            slugified_value = remaining[len(model_field) + 1 :]
                            break

                    if field_name and slugified_value and value:
                        target_dict = choice_mappings if is_choice else fk_mappings
                        if field_name not in target_dict:
                            target_dict[field_name] = {}
                        target_dict[field_name][slugified_value] = value

            for field_name, file_header in field_mappings.items():
                if field_name not in field_lookup:
                    continue

                field = field_lookup[field_name]
                file_values = unique_values.get(file_header, [])

                if field_name in replace_values:
                    continue

                field_type = field["field_type"]
                if field["is_choice_field"]:
                    valid_choices = [choice["value"] for choice in field["choices"]]
                    mapped_values = choice_mappings.get(field_name, {})

                    # Check if all file values have mappings
                    unmapped_values = []
                    for file_val in file_values:
                        if file_val and slugify(file_val) not in mapped_values:
                            unmapped_values.append(file_val)

                    if unmapped_values:
                        if field_name not in validation_errors:
                            validation_errors[field_name] = []
                        ellipsis = "..." if len(unmapped_values) > 3 else ""
                        values_str = ", ".join(unmapped_values[:3])
                        validation_errors[field_name].append(
                            _("Unmapped choice values: %(values)s%(ellipsis)s")
                            % {"values": values_str, "ellipsis": ellipsis}
                        )

                    for _slug_val, mapped_choice in mapped_values.items():
                        if mapped_choice not in valid_choices:
                            if field_name not in validation_errors:
                                validation_errors[field_name] = []
                            validation_errors[field_name].append(
                                _("Invalid choice value: %(value)s")
                                % {"value": mapped_choice}
                            )

                elif field["is_foreign_key"]:
                    valid_fk_ids = [fk["id"] for fk in field["foreign_key_choices"]]
                    mapped_fks = fk_mappings.get(field_name, {})

                    unmapped_values = []
                    for file_val in file_values:
                        if file_val and slugify(file_val) not in mapped_fks:
                            unmapped_values.append(file_val)

                    if unmapped_values:
                        if field_name not in validation_errors:
                            validation_errors[field_name] = []
                        ellipsis = "..." if len(unmapped_values) > 3 else ""
                        values_str = ", ".join(unmapped_values[:3])
                        validation_errors[field_name].append(
                            _("Unmapped foreign key values: %(values)s%(ellipsis)s")
                            % {"values": values_str, "ellipsis": ellipsis}
                        )

                    # Verify all mapped FKs are valid IDs
                    for _slug_val, mapped_id in mapped_fks.items():
                        try:
                            mapped_id_int = int(mapped_id)
                            if mapped_id_int not in valid_fk_ids:
                                if field_name not in validation_errors:
                                    validation_errors[field_name] = []
                                validation_errors[field_name].append(
                                    _("Invalid foreign key ID: %(id)s")
                                    % {"id": mapped_id}
                                )
                        except (ValueError, TypeError):
                            if field_name not in validation_errors:
                                validation_errors[field_name] = []
                            validation_errors[field_name].append(
                                _("Foreign key must be a valid ID")
                            )

                elif field_type in ["DateField", "DateTimeField"]:
                    # Get non-empty sample values from file
                    sample_values = [
                        v for v in file_values[:10] if v and str(v).strip()
                    ]
                    invalid_dates = []

                    for val in sample_values:
                        if not self.is_valid_date_format(val):
                            invalid_dates.append(val)

                    if invalid_dates:
                        if field_name not in validation_errors:
                            validation_errors[field_name] = []
                        validation_errors[field_name].append(
                            _(
                                "Field type mismatch: '%(field)s' expects DATE format, but file column '%(column)s' contains invalid date: '%(value)s'"
                            )
                            % {
                                "field": field["verbose_name"],
                                "column": file_header,
                                "value": invalid_dates[0],
                            }
                        )

                elif field_type in [
                    "IntegerField",
                    "BigIntegerField",
                    "SmallIntegerField",
                    "PositiveIntegerField",
                    "PositiveSmallIntegerField",
                    "FloatField",
                    "DecimalField",
                ]:
                    sample_values = [
                        v for v in file_values[:10] if v and str(v).strip()
                    ]
                    invalid_numbers = []

                    for val in sample_values:
                        if not self.is_valid_number(val, field_type):
                            invalid_numbers.append(val)

                    if invalid_numbers:
                        if field_name not in validation_errors:
                            validation_errors[field_name] = []
                        number_type = (
                            _("INTEGER") if "Integer" in field_type else _("DECIMAL")
                        )
                        validation_errors[field_name].append(
                            _(
                                "Field type mismatch: '%(field)s' expects %(type)s format, but file column '%(column)s' contains invalid number: '%(value)s'"
                            )
                            % {
                                "field": field["verbose_name"],
                                "type": number_type,
                                "column": file_header,
                                "value": invalid_numbers[0],
                            }
                        )

                elif field_type == "BooleanField":
                    sample_values = [
                        v for v in file_values[:10] if v and str(v).strip()
                    ]
                    invalid_bools = []

                    for val in sample_values:
                        if not self.is_valid_boolean(val):
                            invalid_bools.append(val)

                    if invalid_bools:
                        if field_name not in validation_errors:
                            validation_errors[field_name] = []
                        validation_errors[field_name].append(
                            _(
                                "Field type mismatch: '%(field)s' expects BOOLEAN (true/false/yes/no/1/0), but file column '%(column)s' contains like: '%(value)s'"
                            )
                            % {
                                "field": field["verbose_name"],
                                "column": file_header,
                                "value": invalid_bools[0],
                            }
                        )

                elif field_type == "EmailField":
                    sample_values = [
                        v for v in file_values[:10] if v and str(v).strip()
                    ]
                    invalid_emails = []

                    for val in sample_values:
                        if not self.is_valid_email(val):
                            invalid_emails.append(val)

                    if invalid_emails:
                        if field_name not in validation_errors:
                            validation_errors[field_name] = []
                        validation_errors[field_name].append(
                            _(
                                "Field type mismatch: '%(field)s' expects EMAIL format, but file column '%(column)s' contains invalid email"
                            )
                            % {"field": field["verbose_name"], "column": file_header}
                        )

                elif field_type == "URLField":
                    sample_values = [
                        v for v in file_values[:10] if v and str(v).strip()
                    ]
                    invalid_urls = []

                    for val in sample_values:
                        if not self.is_valid_url(val):
                            invalid_urls.append(val)

                    if invalid_urls:
                        if field_name not in validation_errors:
                            validation_errors[field_name] = []
                        validation_errors[field_name].append(
                            _(
                                "Field type mismatch: '%(field)s' expects URL format, but file column '%(column)s' contains invalid URL: '%(value)s'"
                            )
                            % {
                                "field": field["verbose_name"],
                                "column": file_header,
                                "value": invalid_urls[0],
                            }
                        )

                elif (
                    field_type in TABLE_FALLBACK_FIELD_TYPES[:2]
                ):  # [CharField, TextField]
                    sample_values = [
                        v for v in file_values[:10] if v and str(v).strip()
                    ]

                    date_count = sum(
                        1 for val in sample_values if self.is_valid_date_format(val)
                    )
                    email_count = sum(
                        1 for val in sample_values if self.is_valid_email(val)
                    )
                    number_count = sum(
                        1
                        for val in sample_values
                        if self.is_valid_number(val, "FloatField")
                    )

                    total_samples = len(sample_values)
                    if total_samples > 0:
                        if date_count / total_samples >= 0.8:
                            if field_name not in validation_errors:
                                validation_errors[field_name] = []
                            validation_errors[field_name].append(
                                _(
                                    "Error: '%(field)s' is a TEXT field, but file column '%(column)s' appears to contain DATES. Consider mapping to a DateField instead."
                                )
                                % {
                                    "field": field["verbose_name"],
                                    "column": file_header,
                                }
                            )

                        # If 80% or more values look like emails
                        elif email_count / total_samples >= 0.8:
                            if field_name not in validation_errors:
                                validation_errors[field_name] = []
                            validation_errors[field_name].append(
                                _(
                                    "Error: '%(field)s' is a TEXT field, but file column '%(column)s' appears to contain EMAIL addresses. Consider mapping to an EmailField instead."
                                )
                                % {
                                    "field": field["verbose_name"],
                                    "column": file_header,
                                }
                            )

                        elif number_count / total_samples >= 0.8:
                            if field_name not in validation_errors:
                                validation_errors[field_name] = []
                            validation_errors[field_name].append(
                                _(
                                    "Error: '%(field)s' is a TEXT field, but file column '%(column)s' appears to contain NUMBERS. Consider mapping to a numeric field instead."
                                )
                                % {
                                    "field": field["verbose_name"],
                                    "column": file_header,
                                }
                            )

            # Validate required fields are mapped
            for field in model_fields:
                if field["required"]:
                    field_name = field["name"]

                    # Skip if replace value provided
                    if field_name in replace_values:
                        continue

                    # Check if field is mapped
                    if field_name not in field_mappings:
                        if field_name not in validation_errors:
                            validation_errors[field_name] = []
                        validation_errors[field_name].append(
                            _(
                                "Required field '%(field)s' must be mapped to a file column."
                            )
                            % {"field": field["verbose_name"]}
                        )
                        continue

            if validation_errors:
                return render(
                    request,
                    "import/import_step2.html",
                    {
                        "headers": import_data.get("headers", []),
                        "sample_data": import_data.get("sample_data", []),
                        "model_fields": model_fields,
                        "module": module,
                        "app_label": app_label,
                        "auto_mappings": field_mappings,
                        "auto_choice_mappings": import_data.get(
                            "auto_choice_mappings", {}
                        ),
                        "auto_fk_mappings": import_data.get("auto_fk_mappings", {}),
                        "replace_values": replace_values,
                        "choice_mappings": choice_mappings,
                        "fk_mappings": fk_mappings,
                        "validation_errors": validation_errors,
                        "single_import": single_import,
                        "selected_module": model_name,
                    },
                )

            auto_choice_mappings = import_data.get("auto_choice_mappings", {})
            auto_fk_mappings = import_data.get("auto_fk_mappings", {})

            for field_name, auto_mappings in auto_choice_mappings.items():
                if field_name not in choice_mappings:
                    choice_mappings[field_name] = auto_mappings.copy()

            for field_name, auto_mappings in auto_fk_mappings.items():
                if field_name not in fk_mappings:
                    fk_mappings[field_name] = auto_mappings.copy()

            import_data["field_mappings"] = field_mappings
            import_data["replace_values"] = replace_values
            import_data["choice_mappings"] = choice_mappings
            import_data["fk_mappings"] = fk_mappings
            request.session["import_data"] = import_data

            return render(
                request,
                "import/import_step3.html",
                {
                    "module": module,
                    "model_fields": model_fields,
                    "app_label": app_label,
                    "single_import": single_import,
                },
            )

        except Exception as e:
            logger.error("Error in ImportStep2View.post: %s", e)
            tb = traceback.format_exc()
            logger.error(tb)
            return render(
                request,
                "common/message_fragment.html",
                {
                    "message": f"{_('Error processing field mappings')}: {e!s}",
                    "variant": "sm",
                },
            )

    def is_valid_date_format(self, value):
        """Check if value can be parsed as a date"""
        try:
            from dateutil import parser

            parser.parse(str(value))
            return True
        except Exception:
            return False

    def is_valid_number(self, value, field_type):
        """Check if value is a valid number for the field type"""
        try:
            val_str = str(value).strip()
            if not val_str:
                return False
            if field_type in ["FloatField", "DecimalField"]:
                float(val_str)
            else:
                int(float(val_str))
            return True
        except (ValueError, TypeError):
            return False

    def is_valid_boolean(self, value):
        """Check if value is a valid boolean"""
        val_lower = str(value).lower().strip()
        return val_lower in ["true", "false", "yes", "no", "1", "0", "t", "f", "y", "n"]

    def is_valid_email(self, value):
        """Basic email validation"""
        import re

        val_str = str(value).strip()
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return re.match(email_pattern, val_str) is not None

    def is_valid_url(self, value):
        """Basic URL validation"""
        import re

        val_str = str(value).strip()
        url_pattern = r"^https?://[^\s/$.?#].[^\s]*$"
        return re.match(url_pattern, val_str, re.IGNORECASE) is not None
