"""Step 4 of import: final import execution."""

# Standard library imports
import csv
import logging
import math
import time
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from io import StringIO

# Third-party imports (other)
import pandas as pd

# Third-party imports (Django)
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

# First party imports (Horilla)
from horilla.apps import apps
from horilla.contrib.utils.middlewares import get_active_company
from horilla.db import connection, transaction
from horilla.db.models import CharField, ForeignKey
from horilla.registry.feature import FEATURE_REGISTRY
from horilla.shortcuts import redirect, render
from horilla.utils import timezone
from horilla.utils.decorators import method_decorator, permission_required_or_denied
from horilla.utils.text import slugify
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View

from ...models import ImportHistory

# Local imports
from .base import get_model_verbose_name

logger = logging.getLogger(__name__)


@method_decorator(
    permission_required_or_denied("core.can_view_horilla_import"),
    name="dispatch",
)
class ImportStep4View(View):
    """Handle final import process"""

    def get(self, request, *args, **kwargs):
        """Handle navigation back to step 4 (review)"""
        import_data = request.session.get("import_data", {})
        import_config = request.session.get("import_config", {})
        single_import = import_config.get("single_import", False)

        if not import_data:
            return redirect("core:import_data")

        module = import_data.get("module")
        app_label = import_data.get("app_label")

        if not module or not app_label:
            return redirect("core:import_data")

        # Calculate mapped and unmapped fields
        field_mappings = import_data.get("field_mappings", {})
        headers = import_data.get("headers", [])

        mapped_count = len(field_mappings)
        unmapped_count = len(headers) - mapped_count

        # Get the verbose name for the module
        module_verbose_name = get_model_verbose_name(module, app_label)

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

    def post(self, request, *args, **kwargs):
        """Handle the actual import when user clicks Import button"""

        import_data = request.session.get("import_data", {})
        import_config = request.session.get("import_config", {})
        single_import = import_config.get("single_import", False)

        if not import_data:
            return render(
                request,
                "common/message_fragment.html",
                {"message": _("No import data found in session"), "variant": "sm"},
            )

        module_name = import_data.get("module", "")
        app_label_check = import_data.get("app_label", "")
        if module_name and app_label_check:
            import_models = FEATURE_REGISTRY.get("import_models", [])
            registered = next(
                (
                    m
                    for m in import_models
                    if m.__name__ == module_name
                    and m._meta.app_label == app_label_check
                ),
                None,
            )
            add_perm = f"{app_label_check}.add_{module_name.lower()}"
            if not registered or not request.user.has_perm(add_perm):
                field_mappings = import_data.get("field_mappings", {})
                headers = import_data.get("headers", [])
                return render(
                    request,
                    "import/import_step4.html",
                    {
                        "import_data": import_data,
                        "mapped_count": len(field_mappings),
                        "unmapped_count": len(headers) - len(field_mappings),
                        "module": module_name,
                        "module_verbose_name": get_model_verbose_name(
                            module_name, app_label_check
                        ),
                        "app_label": app_label_check,
                        "single_import": single_import,
                        "error_message": _(
                            "Invalid module selection. Please choose a valid module from the list."
                        ),
                    },
                )

        process_start = time.perf_counter()
        # Create import history record
        import_history = ImportHistory.objects.create(
            import_name=import_data.get("import_name", ""),
            module_name=import_data.get("module", ""),
            app_label=import_data.get("app_label", ""),
            original_filename=import_data.get("original_filename", ""),
            imported_file_path=import_data.get("file_path", ""),
            import_option=import_data.get("import_option", "1"),
            match_fields=import_data.get("match_fields", []),
            field_mappings=import_data.get("field_mappings", {}),
            created_by=request.user if request.user.is_authenticated else None,
            company=get_active_company(request),
            status="processing",
        )

        try:
            # Process the import
            result = self.process_import(import_data)
            duration = time.perf_counter() - process_start

            # Update import history with results
            import_history.total_rows = result["total_rows"]
            import_history.created_count = result["created_count"]
            import_history.updated_count = result["updated_count"]
            import_history.error_count = result["error_count"]
            import_history.success_rate = Decimal(str(result["success_rate"]))
            import_history.error_file_path = result.get("error_file_path", "")
            import_history.error_summary = result.get("errors", [])[
                :5
            ]  # Store first 5 errors
            import_history.duration_seconds = Decimal(str(duration))

            # Determine status
            if result["error_count"] == 0:
                import_history.status = "success"
            elif result["successful_rows"] > 0:
                import_history.status = "partial"
            else:
                import_history.status = "failed"

            import_history.save()

            # Render success page with results

            response = render(
                request,
                "import/import_success.html",
                {
                    "result": result,
                    "import_data": import_data,
                    "import_history": import_history,
                    "single_import": single_import,
                },
            )
            return response

        except Exception as e:
            # Update import history with error
            import_history.status = "failed"
            import_history.error_summary = [str(e)]
            import_history.duration_seconds = Decimal(
                str(time.perf_counter() - process_start)
            )
            import_history.save()

            return render(
                request,
                "common/message_fragment.html",
                {"message": f"Error during import: {e!s}", "variant": "sm"},
            )

    def generate_error_csv(self, detailed_errors, import_data):
        """Generate a CSV file with original file structure plus error column"""
        try:
            original_filename = import_data.get("original_filename", "file")

            # Extract filename without extension for error file naming
            if "." in original_filename:
                base_filename = original_filename.rsplit(".", 1)[0]
            else:
                base_filename = original_filename

            timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{base_filename}_errors_{timestamp}.csv"
            file_path = f"import_errors/{filename}"

            # Read original file to get structure
            original_file_path = import_data.get("file_path")
            original_headers = import_data.get("headers", [])

            if not original_file_path or not original_headers:
                raise ValueError("Original file path or headers not found")

            # Read all original data
            original_data = self.read_file_data(original_file_path)

            # Create error lookup by row number
            error_lookup = {
                error["row_number"]: error["errors"] for error in detailed_errors
            }

            # Create CSV content with original structure + error column
            csv_content = StringIO()
            writer = csv.writer(csv_content)

            # Write headers (original headers + Error column)
            headers_with_error = original_headers + ["Import_Error"]
            writer.writerow(headers_with_error)

            # Write data rows
            for row_index, row_data in enumerate(original_data, 1):
                # Get original row values in correct order
                row_values = []
                for header in original_headers:
                    row_values.append(row_data.get(header, ""))

                # Add error information if this row had errors
                error_info = error_lookup.get(row_index, "")
                row_values.append(error_info)

                # Only write rows that had errors
                if error_info:
                    writer.writerow(row_values)

            # Save to storage
            full_file_path = default_storage.save(
                file_path, ContentFile(csv_content.getvalue().encode("utf-8"))
            )

            return full_file_path

        except Exception as e:
            logger.error("Error generating error CSV: %s", e)

            return None

    def process_import(self, import_data):
        """Process the import based on the provided import_data"""

        # Database-specific batch size optimization
        is_postgres = connection.vendor == "postgresql"
        is_sqlite = connection.vendor == "sqlite"
        create_batch_size = 1000 if is_postgres else (500 if is_sqlite else 999)
        update_batch_size = 500 if is_postgres else (100 if is_sqlite else 200)

        module_name = import_data["module"]
        app_label = import_data["app_label"]
        file_path = import_data["file_path"]
        field_mappings = import_data.get("field_mappings", {})
        replace_values = import_data.get("replace_values", {})
        choice_mappings = import_data.get("choice_mappings", {})
        fk_mappings = import_data.get("fk_mappings", {})
        import_option = import_data["import_option"]
        match_fields = import_data.get("match_fields", [])

        model = apps.get_model(app_label, module_name)
        field_metadata = {
            f.name: {
                "type": f.get_internal_type(),
                "is_fk": isinstance(f, ForeignKey),
                "is_choice": isinstance(f, CharField) and f.choices,
                "related_model": f.related_model if isinstance(f, ForeignKey) else None,
                "choices": (
                    dict(f.choices) if isinstance(f, CharField) and f.choices else {}
                ),
                "null": f.null,
                "blank": f.blank,
                "verbose_name": f.verbose_name,
            }
            for f in model._meta.fields
        }

        # Precompute update fields for bulk operations
        base_update_fields = set()
        for field in model._meta.fields:
            if field.primary_key:
                continue
            if field.name in field_mappings or field.name in [
                "updated_at",
                "updated_by",
                "company",
            ]:
                base_update_fields.add(field.name)
        update_fields_for_update = list(
            base_update_fields - {"created_at", "created_by"}
        )

        data_rows = self.read_file_data(file_path)

        created, errors = [], []
        detailed_errors = []  # For CSV export
        created_count = updated_count = error_count = 0
        current_time = timezone.now()
        user = self.request.user if self.request.user.is_authenticated else None
        company = get_active_company(self.request)

        # Preload FK objects referenced in mappings
        fk_cache = {}
        for field, mapping in fk_mappings.items():
            related_model = field_metadata[field]["related_model"]
            fk_cache[field] = {
                k: related_model.objects.filter(pk=v).first()
                for k, v in mapping.items()
            }

        # Preload replace_values FKs
        for field, value in replace_values.items():
            if field_metadata[field]["is_fk"]:
                related_model = field_metadata[field]["related_model"]
                fk_cache.setdefault(field, {})
                fk_cache[field]["__replace__"] = related_model.objects.filter(
                    pk=value
                ).first()

        with transaction.atomic():
            existing_objs = {}
            if match_fields and import_option in ["1", "2", "3"]:
                filters = {
                    f"{f}__in": [
                        str(row.get(field_mappings.get(f, ""), "")).strip()
                        for row in data_rows
                        if f in field_mappings
                    ]
                    for f in match_fields
                }
                qset = model.objects.filter(**{k: v for k, v in filters.items() if v})
                existing_objs = {
                    tuple(getattr(obj, f) for f in match_fields): obj for obj in qset
                }

            # Group objects by changed fields for efficient updates
            updated_groups = defaultdict(list)

            for row_index, row_data in enumerate(data_rows, 1):
                row_errors = []
                try:
                    mapped = {}
                    for model_field, file_header in field_mappings.items():
                        value = str(row_data.get(file_header, "")).strip()
                        meta = field_metadata[model_field]
                        original_value = value  # Keep original for error reporting

                        if not value and model_field in replace_values:
                            value = replace_values[model_field]

                        if meta["is_fk"]:
                            slug_val = slugify(value) if value else None
                            obj = fk_cache.get(model_field, {}).get(slug_val)
                            if not obj and model_field in replace_values:
                                obj = fk_cache.get(model_field, {}).get("__replace__")

                            # Enhanced FK validation
                            if not obj and value and not meta["null"]:
                                row_errors.append(
                                    f"Foreign key '{meta['verbose_name']}': No matching record found for '{original_value}'"
                                )
                            elif (
                                not obj
                                and not value
                                and not meta["null"]
                                and not meta["blank"]
                            ):
                                row_errors.append(
                                    f"Foreign key '{meta['verbose_name']}': Required field cannot be empty"
                                )

                            mapped[model_field] = obj

                        elif meta["is_choice"]:
                            if value and model_field in choice_mappings:
                                slug_val = slugify(value)
                                if slug_val in choice_mappings[model_field]:
                                    value = choice_mappings[model_field][slug_val]
                                elif model_field in replace_values:
                                    value = replace_values[model_field]
                            elif not value and model_field in replace_values:
                                value = replace_values[model_field]

                            # Enhanced choice validation
                            if value and value not in meta["choices"]:
                                valid_choices = ", ".join(
                                    [f"'{choice}'" for choice in meta["choices"].keys()]
                                )
                                row_errors.append(
                                    f"Choice field '{meta['verbose_name']}': Invalid value '{original_value}'. Valid choices are: {valid_choices}"
                                )
                            elif not value and not meta["null"] and not meta["blank"]:
                                row_errors.append(
                                    f"Choice field '{meta['verbose_name']}': Required field cannot be empty"
                                )

                            mapped[model_field] = value

                        else:
                            if not value and model_field in replace_values:
                                value = replace_values[model_field]

                            # Enhanced type conversion with error reporting
                            if meta["type"] in ["IntegerField", "BigIntegerField"]:
                                if value:
                                    try:
                                        value = int(value)
                                    except ValueError:
                                        row_errors.append(
                                            f"Integer field '{meta['verbose_name']}': Cannot convert '{original_value}' to integer"
                                        )
                                        value = None
                                else:
                                    value = None

                            elif meta["type"] == "DecimalField":
                                if value:
                                    raw = str(value).strip().lower()
                                    if raw in (
                                        "nan",
                                        "inf",
                                        "-inf",
                                        "infinity",
                                        "-infinity",
                                    ):
                                        value = None
                                    else:
                                        try:
                                            value = float(value)
                                            if math.isnan(value) or math.isinf(value):
                                                value = None
                                            else:
                                                value = Decimal(str(value))
                                        except (ValueError, Exception):
                                            row_errors.append(
                                                f"Decimal field '{meta['verbose_name']}': Cannot convert '{original_value}' to decimal"
                                            )
                                            value = None
                                else:
                                    value = None

                            elif meta["type"] == "BooleanField":
                                if value:
                                    str_value = str(value).lower().strip()
                                    if str_value in (
                                        "true",
                                        "1",
                                        "yes",
                                        "on",
                                        "false",
                                        "0",
                                        "no",
                                        "off",
                                    ):
                                        value = str_value in ("true", "1", "yes", "on")
                                    else:
                                        row_errors.append(
                                            f"Replace value for '{meta['verbose_name']}': Invalid boolean value '{replace_value}'. Valid values are: true, false, 1, 0, yes, no, on, off"
                                        )
                                        value = None
                                else:
                                    value = False

                            elif meta["type"] in ["DateField", "DateTimeField"]:
                                if value:
                                    try:
                                        if meta["type"] == "DateField":
                                            try:
                                                value = datetime.strptime(
                                                    value, "%Y-%m-%d"
                                                ).date()
                                            except ValueError:
                                                try:
                                                    value = datetime.strptime(
                                                        value, "%m/%d/%Y"
                                                    ).date()
                                                except ValueError:
                                                    try:
                                                        value = datetime.strptime(
                                                            value, "%d/%m/%Y"
                                                        ).date()
                                                    except ValueError as exc:
                                                        raise ValueError(
                                                            f"Invalid date format for '{original_value}'. Expected YYYY-MM-DD, MM/DD/YYYY, or DD/MM/YYYY"
                                                        ) from exc
                                        else:
                                            try:
                                                value = datetime.fromisoformat(value)
                                            except ValueError as exc:
                                                # Try other common datetime formats
                                                formats = [
                                                    "%Y-%m-%d %H:%M:%S",
                                                    "%m/%d/%Y %H:%M:%S",
                                                    "%d/%m/%Y %H:%M:%S",
                                                    "%Y-%m-%d %I:%M:%S %p",
                                                    "%m/%d/%Y %I:%M:%S %p",
                                                    "%d/%m/%Y %I:%M:%S %p",
                                                ]
                                                parsed = False
                                                for fmt in formats:
                                                    try:
                                                        value = datetime.strptime(
                                                            value, fmt
                                                        )
                                                        parsed = True
                                                        break
                                                    except ValueError:
                                                        continue

                                                if not parsed:
                                                    raise ValueError(
                                                        f"Invalid datetime format for '{original_value}'"
                                                    ) from exc
                                    except ValueError as e:
                                        row_errors.append(
                                            f"Date field '{meta['verbose_name']}': {str(e)}"
                                        )
                                        value = None
                                else:
                                    value = None

                            # Check for required field violations
                            if value is None and not meta["null"] and not meta["blank"]:
                                row_errors.append(
                                    f"Required field '{meta['verbose_name']}': Cannot be empty or invalid"
                                )

                            mapped[model_field] = value

                    for field, replace_value in replace_values.items():
                        if field not in field_mappings and field in field_metadata:
                            meta = field_metadata[field]

                            if meta["is_fk"]:
                                obj = fk_cache.get(field, {}).get("__replace__")
                                mapped[field] = obj
                            elif meta["is_choice"]:
                                if replace_value in meta["choices"]:
                                    mapped[field] = replace_value
                                else:
                                    row_errors.append(
                                        f"Replace value for '{meta['verbose_name']}': Invalid choice '{replace_value}'"
                                    )
                            else:
                                value = replace_value
                                if meta["type"] in ["IntegerField", "BigIntegerField"]:
                                    try:
                                        value = int(value)
                                    except ValueError:
                                        row_errors.append(
                                            f"Replace value for '{meta['verbose_name']}': Cannot convert '{replace_value}' to integer"
                                        )
                                        value = None
                                elif meta["type"] == "DecimalField":
                                    raw = str(value).strip().lower()
                                    if raw in (
                                        "nan",
                                        "inf",
                                        "-inf",
                                        "infinity",
                                        "-infinity",
                                    ):
                                        value = None
                                    else:
                                        try:
                                            value = float(value)
                                            if math.isnan(value) or math.isinf(value):
                                                value = None
                                            else:
                                                value = Decimal(str(value))
                                        except (ValueError, Exception):
                                            row_errors.append(
                                                f"Replace value for '{meta['verbose_name']}': Cannot convert '{replace_value}' to decimal"
                                            )
                                            value = None
                                elif meta["type"] == "BooleanField":
                                    str_value = str(value).lower().strip()
                                    if str_value in (
                                        "true",
                                        "1",
                                        "yes",
                                        "on",
                                        "false",
                                        "0",
                                        "no",
                                        "off",
                                    ):
                                        value = str_value in ("true", "1", "yes", "on")
                                    else:
                                        row_errors.append(
                                            f"Replace value for '{meta['verbose_name']}': Invalid boolean value '{replace_value}'. Valid values are: true, false, 1, 0, yes, no, on, off"
                                        )
                                        value = None
                                elif meta["type"] in ["DateField", "DateTimeField"]:
                                    if value:
                                        try:
                                            if meta["type"] == "DateField":
                                                try:
                                                    value = datetime.strptime(
                                                        value, "%Y-%m-%d"
                                                    ).date()
                                                except ValueError:
                                                    try:
                                                        value = datetime.strptime(
                                                            value, "%m/%d/%Y"
                                                        ).date()
                                                    except ValueError:
                                                        try:
                                                            value = datetime.strptime(
                                                                value, "%d/%m/%Y"
                                                            ).date()
                                                        except ValueError as exc:
                                                            raise ValueError(
                                                                f"Invalid date format for '{original_value}'. Expected YYYY-MM-DD, MM/DD/YYYY, or DD/MM/YYYY"
                                                            ) from exc
                                            else:
                                                try:
                                                    value = datetime.fromisoformat(
                                                        value
                                                    )
                                                except ValueError as exc:
                                                    formats = [
                                                        "%Y-%m-%d %H:%M:%S",
                                                        "%m/%d/%Y %H:%M:%S",
                                                        "%d/%m/%Y %H:%M:%S",
                                                        "%Y-%m-%d %I:%M:%S %p",
                                                        "%m/%d/%Y %I:%M:%S %p",
                                                        "%d/%m/%Y %I:%M:%S %p",
                                                    ]
                                                    parsed = False
                                                    for fmt in formats:
                                                        try:
                                                            value = datetime.strptime(
                                                                value, fmt
                                                            )
                                                            parsed = True
                                                            break
                                                        except ValueError:
                                                            continue

                                                    if not parsed:
                                                        raise ValueError(
                                                            f"Invalid datetime format for '{original_value}'"
                                                        ) from exc
                                        except ValueError as e:
                                            row_errors.append(
                                                f"Date field '{meta['verbose_name']}': {str(e)}"
                                            )
                                            value = None
                                    else:
                                        value = None
                                mapped[field] = value

                    if row_errors:
                        error_count += 1
                        row_error_summary = f"Row {row_index}: {'; '.join(row_errors)}"
                        errors.append(row_error_summary)

                        # Add detailed error for CSV export
                        detailed_errors.append(
                            {"row_number": row_index, "errors": "; ".join(row_errors)}
                        )
                        continue

                    # Handle import_option
                    if import_option == "1":  # create only
                        if match_fields:
                            key = tuple(mapped.get(f) for f in match_fields)
                            if key in existing_objs:
                                # Add error for existing record when in create-only mode
                                error_count += 1
                                match_field_values = []
                                for field in match_fields:
                                    field_value = mapped.get(field, "N/A")
                                    if field_value is None:
                                        field_value = "N/A"
                                    match_field_values.append(
                                        f"{field}='{field_value}'"
                                    )
                                match_criteria = ", ".join(match_field_values)

                                error_msg = f"Row {row_index}: Record already exists with matching criteria: {match_criteria}. Skipped in create-only mode."
                                errors.append(error_msg)

                                # Add detailed error for CSV export
                                detailed_errors.append(
                                    {
                                        "row_number": row_index,
                                        "errors": f"Record already exists with matching criteria: {match_criteria}. Skipped in create-only mode.",
                                    }
                                )
                                continue

                        obj = model(**mapped)
                        obj.created_at = mapped.get("created_at", current_time)
                        obj.updated_at = current_time
                        if user:
                            obj.created_by = mapped.get("created_by", user)
                            obj.updated_by = user
                        obj.company = company
                        created.append(obj)

                    elif import_option == "2":  # update only
                        key = tuple(mapped.get(f) for f in match_fields)
                        instance = existing_objs.get(key)
                        if instance:
                            changed_fields = self._update_instance(
                                instance,
                                mapped,
                                field_metadata,
                                update_fields_for_update,
                                current_time,
                                user,
                                company,
                            )
                            updated_groups[frozenset(changed_fields)].append(instance)
                        else:
                            error_count += 1
                            match_field_values = []
                            for field in match_fields:
                                field_value = mapped.get(field, "N/A")
                                if field_value is None:
                                    field_value = "N/A"
                                match_field_values.append(f"{field}='{field_value}'")
                            match_criteria = ", ".join(match_field_values)

                            error_msg = f"Row {row_index}: No existing record found to update with matching criteria: {match_criteria}"
                            errors.append(error_msg)

                            # Add detailed error for CSV export
                            detailed_errors.append(
                                {
                                    "row_number": row_index,
                                    "errors": f"No existing record found to update with matching criteria: {match_criteria}",
                                }
                            )

                    elif import_option == "3":  # create + update
                        key = tuple(mapped.get(f) for f in match_fields)
                        instance = existing_objs.get(key)
                        if instance:
                            changed_fields = self._update_instance(
                                instance,
                                mapped,
                                field_metadata,
                                update_fields_for_update,
                                current_time,
                                user,
                                company,
                            )
                            updated_groups[frozenset(changed_fields)].append(instance)
                        else:
                            obj = model(**mapped)
                            obj.created_at = mapped.get("created_at", current_time)
                            obj.updated_at = current_time
                            if user:
                                obj.created_by = mapped.get("created_by", user)
                                obj.updated_by = user
                            obj.company = company
                            created.append(obj)
                            if match_fields:
                                existing_objs[key] = obj

                except Exception as e:
                    error_count += 1
                    error_msg = f"Row {row_index}: Unexpected error - {str(e)}"
                    errors.append(error_msg)
                    detailed_errors.append(
                        {
                            "row_number": row_index,
                            "errors": f"Unexpected error - {str(e)}",
                        }
                    )

            if created:
                model.objects.bulk_create(created, batch_size=create_batch_size)
                created_count = len(created)

            for fields, objs in updated_groups.items():
                if fields:
                    for i in range(0, len(objs), update_batch_size):
                        batch = objs[i : i + update_batch_size]
                        model.objects.bulk_update(
                            batch, fields=list(fields), batch_size=len(batch)
                        )
                        updated_count += len(batch)

        # Generate error CSV if there are errors
        error_file_path = None
        if detailed_errors:
            error_file_path = self.generate_error_csv(detailed_errors, import_data)

        if "import_data" in self.request.session:
            del self.request.session["import_data"]
            self.request.session.modified = True

        successful_rows = created_count + updated_count
        total_rows = len(data_rows)
        success_rate = (successful_rows / total_rows * 100) if total_rows > 0 else 0

        return {
            "created_count": created_count,
            "updated_count": updated_count,
            "error_count": error_count,
            "errors": errors[:5],
            "total_rows": total_rows,
            "successful_rows": successful_rows,
            "success_rate": round(success_rate, 1),
            "error_file_path": error_file_path,
            "has_more_errors": len(errors) > 5,
        }

    def _update_instance(
        self,
        instance,
        mapped,
        field_metadata,
        update_fields,
        current_time,
        user,
        company,
    ):
        """Update instance with change detection and return changed fields"""
        changed_fields = {"updated_at", "company"}  # System fields always change
        if user:
            changed_fields.add("updated_by")

        # Update data fields with change detection
        for field in update_fields:
            if field in ["updated_at", "updated_by", "company"]:
                continue

            new_value = mapped.get(field)
            old_value = getattr(instance, field)

            # Skip if values are the same
            if old_value == new_value:
                continue

            # Handle special field types
            meta = field_metadata.get(field, {})
            if meta.get("is_fk"):
                # Foreign keys are already resolved in mapped
                pass
            elif meta.get("is_choice"):
                # Choices are already converted in mapped
                pass
            else:
                # Type conversion already handled in mapped
                pass

            setattr(instance, field, new_value)
            changed_fields.add(field)

        # Update system fields
        instance.updated_at = current_time
        if user:
            instance.updated_by = user
        instance.company = company

        return changed_fields

    def read_file_data(self, file_path):
        """Read data from the uploaded file"""

        full_path = default_storage.path(file_path)
        data_rows = []
        if file_path.endswith(".csv"):
            with open(full_path, "r", encoding="utf-8") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    data_rows.append(dict(row))
        else:
            df = pd.read_excel(full_path)
            data_rows = df.to_dict("records")
        return data_rows
