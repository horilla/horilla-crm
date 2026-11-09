"""
A generic single form view for creating and editing objects in Horilla, with dynamic form generation based on the model and view configuration.
This view supports dynamic condition rows, field-level permissions.
"""

# Standard library imports
import base64
import inspect
import logging
import re
from urllib.parse import urlencode

# Third-party imports (Django)
from django import forms
from django.contrib import messages
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import IntegrityError, transaction

from horilla.contrib.utils.middlewares import _thread_local
from horilla.core.exceptions import FieldDoesNotExist

# First party imports (Horilla)
from horilla.db import models
from horilla.urls import reverse, reverse_lazy
from horilla.utils.choices import TABLE_FALLBACK_FIELD_TYPES
from horilla.utils.text import title_words
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import FormView
from horilla.web import HttpResponse, ScriptResponse

# Local imports
from .toolkit import single_form_builder
from .toolkit.form_mixin import FormViewCommonMixin
from .toolkit.single_form_builder import fill_mandatory_condition_defaults

logger = logging.getLogger(__name__)


class HorillaSingleFormView(FormViewCommonMixin, FormView):
    """View for handling single-step form submissions."""

    template_name = "single_form_view.html"
    model = None
    form_class = None
    success_url = None
    object = None
    fields = None
    exclude = None
    full_width_fields = None
    form_url = None
    dynamic_create_fields = None
    modal_height = True
    form_title = None
    hidden_fields = []
    view_id = ""
    condition_fields = None
    condition_model = None
    condition_field_choices = None
    condition_field_title = None
    condition_hx_include = None
    condition_related_name = None
    condition_related_name_candidates = []
    condition_order_by = ["created_at"]
    content_type_field = None
    header = True
    modal_height_class = None
    hx_attrs: dict = {}
    permission_required = None
    check_object_permission = True
    permission_denied_template = "403.html"
    skip_permission_check = False

    duplicate_mode = False
    detail_url_name = None
    save_and_new = True
    return_response = ""

    def dispatch(self, request, *args, **kwargs):
        """Set duplicate_mode from GET; check permission; handle add_condition_row; resolve object."""
        if "pk" in self.kwargs:
            self.duplicate_mode = (
                request.GET.get("duplicate", "false").lower() == "true"
            )

        if not self.skip_permission_check and not self.has_permission():
            return self.get_permission_denied_response(request)

        if request.headers.get("HX-Request") and "add_condition_row" in request.GET:
            return single_form_builder.add_condition_row(self, request)

        obj, error_response = self.get_object_or_error_response(request)
        if error_response is not None:
            return error_response
        if obj is not None:
            self.object = obj
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        """Clear session keys on edit and set condition_row_count; then delegate to parent get."""
        if self.kwargs.get("pk"):
            for key in self.session_keys_to_clear_on_edit:
                if key in request.session:
                    del request.session[key]
            if (
                "new" in request.GET
                and self.pending_files_session_key in request.session
            ):
                del request.session[self.pending_files_session_key]
            request.session.modified = True

            existing_conditions = single_form_builder.get_existing_conditions(self)
            if existing_conditions is not None:
                request.session["condition_row_count"] = len(existing_conditions)
                request.session.modified = True
        return super().get(request, *args, **kwargs)

    def get_existing_conditions(self):
        """Retrieve existing conditions for the current object in edit mode."""
        return single_form_builder.get_existing_conditions(self)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_keys_to_clear_on_edit = ["condition_row_count"]

    @property
    def pending_files_session_key(self):
        """Session key used to bridge an uploaded file across a same-request validation failure."""
        pk = self.kwargs.get("pk", "new")
        return f"{self.__class__.__name__}_pending_files_{pk}"

    def get_model_name_from_content_type(self, request=None):
        """Extract model_name from content_type field (POST or GET)."""
        return single_form_builder.get_model_name_from_content_type(self, request)

    def get_submitted_condition_data(self):
        """Extract condition field data from submitted form data (POST)."""
        return single_form_builder.get_submitted_condition_data(self)

    def get_form_class(self):
        """Return dynamic form class with condition fields and readonly handling when form_class is None."""
        if self.form_class is None and self.model is not None:
            return single_form_builder.get_dynamic_form_class(self)
        # Concrete form from the view (form_class=UserFormSingle, etc.), not the dynamic branch above.
        base = super().get_form_class()
        # No registered form on this view — nothing to compose; do not call resolve_form_class.
        if base is None:
            return base
        # Import here (not at module top): extension forms bootstrap in CoreConfig.ready()
        # after apps are loaded; a top-level import can run too early or create cycles.
        from horilla.extension.forms.resolve import resolve_form_class

        # Views keep form_class = Horilla module form at import time; resolve to composed subclass
        # (e.g. UserFormSingleExtended) when an extension app registered _inherit_form.
        return resolve_form_class(base)

    def get_form_kwargs(self):
        """Pass full_width_fields, conditions, request, instance/initial, and field_permissions to the form."""
        kwargs = super().get_form_kwargs()

        kwargs["full_width_fields"] = self.full_width_fields or []
        kwargs["dynamic_create_fields"] = self.get_filtered_dynamic_create_fields()
        kwargs["condition_fields"] = self.condition_fields or []
        kwargs["condition_model"] = self.condition_model
        kwargs["condition_field_choices"] = self.condition_field_choices or {}
        if self.condition_fields:
            kwargs["condition_related_name"] = self.condition_related_name
            kwargs["condition_related_name_candidates"] = getattr(
                self,
                "condition_related_name_candidates",
                ["conditions", "criteria", "team_members"],
            )
        kwargs["hidden_fields"] = getattr(self, "hidden_fields", [])
        kwargs["condition_hx_include"] = self.condition_hx_include

        # Auto-add request if form accepts it
        form_class = self.get_form_class()
        if (
            form_class
            and "request" in inspect.signature(form_class.__init__).parameters
        ):
            kwargs["request"] = self.request

        # Auto-extract model_name if content_type_field is set
        if self.content_type_field:
            model_name = self.get_model_name_from_content_type()
            if model_name:
                if "initial" not in kwargs:
                    kwargs["initial"] = {}
                kwargs["initial"]["model_name"] = model_name

        kwargs["field_permissions"] = self.get_field_permissions()

        # Pass duplicate_mode to form so it can check if readonly fields should be hidden
        kwargs["duplicate_mode"] = self.duplicate_mode

        if self.object and not self.duplicate_mode:
            kwargs["instance"] = self.object
        elif self.object and self.duplicate_mode:
            # In duplicate mode, populate initial data from the object
            from horilla.contrib.generics.forms.form_class_mixin import HorillaFormMixin

            phone_field_names = HorillaFormMixin._DEFAULT_PHONE_FIELD_NAMES
            phone_fields_attr = getattr(form_class, "phone_fields", None)
            if phone_fields_attr:
                phone_field_names = phone_field_names | set(phone_fields_attr)

            initial = kwargs.get("initial", {})
            for field in self.object._meta.fields:
                if field.name not in [
                    "id",
                    "pk",
                    "created_at",
                    "updated_at",
                    "created_by",
                    "updated_by",
                ]:
                    field_value = getattr(self.object, field.name)
                    if field_value is not None:
                        if (
                            field_value
                            and field.get_internal_type()
                            in TABLE_FALLBACK_FIELD_TYPES[:2]  # [CharField, TextField]
                            and not isinstance(
                                field,
                                (models.EmailField, models.URLField, models.SlugField),
                            )
                            and not field.choices
                            and field.name not in phone_field_names
                        ):
                            initial[field.name] = f"{field_value} (Copy)"
                        else:
                            initial[field.name] = field_value

            # Handle ManyToMany fields
            for field in self.object._meta.many_to_many:
                m2m_value = getattr(self.object, field.name).all()
                if m2m_value.exists():
                    initial[field.name] = list(m2m_value)

            kwargs["initial"] = initial
        kwargs["request"] = self.request

        if self.request.method == "POST":
            pending_files = self.request.session.get(self.pending_files_session_key, {})
            if pending_files:
                files = kwargs.get("files")
                # kwargs["files"] is a QueryDict/MultiValueDict from request.FILES;
                # only fall back to a pending file when this submission didn't
                # include a fresh one for that field, and the user hasn't
                # explicitly cleared it in this same submission.
                merged = dict(files.items()) if files else {}
                for field_name, file_data in pending_files.items():
                    if self.request.POST.get(f"id_{field_name}_clear") == "true":
                        continue
                    if field_name not in merged or not merged[field_name]:
                        decoded = self.decode_file_from_session(file_data)
                        if decoded:
                            merged[field_name] = decoded
                if merged:
                    kwargs["files"] = merged
        return kwargs

    def get_form_title(self):
        """Return a human-friendly form title based on create/update/duplicate state."""
        if not self.model:
            return ""
        verbose = self.model._meta.verbose_name
        if self.duplicate_mode:
            action = _("Duplicate")
        elif self.kwargs.get("pk"):
            action = _("Update")
        else:
            action = _("Create")
        return f"{action} {title_words(verbose)}"

    def get_reuploaded_image_previews(self):
        """Return {field_name: data_uri} for image fields re-submitted on a failed POST.

        Django's ClearableFileInput can't redisplay an uploaded-but-unsaved
        file (FileField.bound_data always returns the initial value), so
        without this the preview silently reverts to the old image whenever
        validation fails on the same request that included a new upload.
        Includes files carried over from a prior failed submission via the
        session (see save_pending_files_to_session), not just this request's.
        """
        previews = {}
        if self.request.method != "POST":
            return previews

        candidates = {}
        pending_files = self.request.session.get(self.pending_files_session_key, {})
        for field_name, file_data in pending_files.items():
            if self.request.POST.get(f"id_{field_name}_clear") == "true":
                continue
            decoded = self.decode_file_from_session(file_data)
            if decoded:
                candidates[field_name] = decoded
        # A file freshly attached to this exact request always wins. Iterate
        # via .items(), not dict()/.update() - MultiValueDict wraps values in
        # a list under those, which breaks the .seek()/.read() calls below.
        for field_name, uploaded_file in self.request.FILES.items():
            candidates[field_name] = uploaded_file

        for field_name, uploaded_file in candidates.items():
            try:
                model_field = self.model._meta.get_field(field_name)
            except Exception:
                continue
            if not isinstance(model_field, models.ImageField):
                continue
            try:
                uploaded_file.seek(0)
                content = uploaded_file.read()
                uploaded_file.seek(0)
                encoded = base64.b64encode(content).decode("ascii")
                content_type = getattr(uploaded_file, "content_type", "") or "image/*"
                previews[field_name] = f"data:{content_type};base64,{encoded}"
            except Exception as e:
                logger.warning("Could not build preview for %s: %s", field_name, e)
        return previews

    def encode_file_for_session(self, uploaded_file):
        """Encode an uploaded file so it can round-trip through the session."""
        try:
            uploaded_file.seek(0)
            content = uploaded_file.read()
            uploaded_file.seek(0)
            return {
                "name": uploaded_file.name,
                "content": base64.b64encode(content).decode("ascii"),
                "content_type": getattr(uploaded_file, "content_type", None),
            }
        except Exception as e:
            logger.warning("Could not encode file for session: %s", e)
            return None

    def decode_file_from_session(self, file_data):
        """Decode a file previously stored via encode_file_for_session."""
        from django.core.files.uploadedfile import SimpleUploadedFile

        try:
            if not file_data or "content" not in file_data:
                return None
            content = base64.b64decode(file_data["content"])
            return SimpleUploadedFile(
                name=file_data["name"],
                content=content,
                content_type=file_data.get("content_type"),
            )
        except Exception as e:
            logger.warning("Could not decode pending file from session: %s", e)
            return None

    def save_pending_files_to_session(self):
        """Persist newly uploaded image files so a same-request validation
        failure doesn't lose the selection on the next submit attempt.

        Django never repopulates a file input's ``files`` on redisplay
        (``FileField.bound_data`` always returns ``initial``), so without
        this, fixing an unrelated field error and resubmitting silently
        keeps the old file instead of saving the one the user picked.
        """
        if self.request.method != "POST":
            return
        if self.model is None:
            return
        pending = dict(self.request.session.get(self.pending_files_session_key, {}))
        for field in self.model._meta.fields:
            if not isinstance(field, (models.FileField, models.ImageField)):
                continue
            field_name = field.name
            # User clicked "Remove photo" for this field in this submission -
            # don't let a stale pending file resurrect it.
            if self.request.POST.get(f"id_{field_name}_clear") == "true":
                pending.pop(field_name, None)
                continue
            uploaded_file = self.request.FILES.get(field_name)
            if uploaded_file:
                encoded = self.encode_file_for_session(uploaded_file)
                if encoded:
                    pending[field_name] = encoded
        if pending:
            self.request.session[self.pending_files_session_key] = pending
        elif self.pending_files_session_key in self.request.session:
            del self.request.session[self.pending_files_session_key]
        self.request.session.modified = True

    def clear_pending_files_session(self):
        """Drop any pending-file state once the form has been saved successfully."""
        if self.pending_files_session_key in self.request.session:
            del self.request.session[self.pending_files_session_key]
            self.request.session.modified = True

    def get_context_data(self, **kwargs):
        """Add form_title, duplicate_mode, condition fields, and form options to context."""
        context = super().get_context_data(**kwargs)
        context["reuploaded_image_previews"] = self.get_reuploaded_image_previews()
        context["form_title"] = self.form_title or self.get_form_title()
        context["duplicate_mode"] = self.duplicate_mode
        context["save_and_new"] = self.save_and_new
        context["full_width_fields"] = self.full_width_fields or []
        context["condition_fields"] = self.condition_fields or []
        context["condition_fields_tiltle"] = self.condition_field_title
        context["condition_model_str"] = ""
        if getattr(self, "condition_model", None):
            context["condition_model_str"] = (
                f"{self.condition_model._meta.app_label}."
                f"{self.condition_model._meta.model_name}"
            )
        context["form_url"] = self.get_form_url()
        context["add_condition_url"] = (
            self.get_add_condition_url() if self.condition_fields else None
        )
        context["dynamic_create_fields"] = self.get_filtered_dynamic_create_fields()
        context["dynamic_create_field_mapping"] = getattr(
            self, "dynamic_create_field_mapping", {}
        )
        context["modal_height"] = self.modal_height
        self.view_id = self.view_id or f"{self.model._meta.model_name}-form-view"
        context["view_id"] = self.view_id
        context["form_class_name"] = self.get_form_class().__name__
        context["model_name"] = (
            self.model._meta.model_name if self.model is not None else ""
        )
        context["app_label"] = (
            self.model._meta.app_label if self.model is not None else ""
        )
        context["submitted_condition_data"] = self.get_submitted_condition_data()

        single_form_builder.build_condition_context(self, context)

        context["field_permissions"] = self.get_field_permissions()

        context["related_models_info"] = self.get_related_models_info()
        context["m2m_picker_info"] = self._get_m2m_picker_info()

        query_string = ""
        if self.request.GET:
            query_string = f"?{self.request.GET.urlencode()}"

        default_hx_attrs = {
            "hx-post": f"{self.form_url}{query_string}",
            "hx-swap": "outerHTML",
            "hx-target": f"#{self.view_id}-container",
            "enctype": "multipart/form-data",
        }
        context["header"] = self.header
        context["modal_height_class"] = self.modal_height_class
        context["hx_attrs"] = {**default_hx_attrs, **(self.hx_attrs or {})}
        context["form_mode"] = self.resolve_form_mode()
        context["condition_hx_include"] = self.condition_hx_include
        return context

    def get_form_url(self):
        """Return the configured form URL or fall back to the current request path."""
        return self.form_url or self.request.path

    def save_conditions(self, form=None):
        """Save conditions from form.cleaned_data or POST; delete existing and create from submitted data."""
        return single_form_builder.save_conditions(self, form)

    def save_multiple_main_instances(self, form=None):
        """Generic method to create multiple instances of the main model from condition rows.

        Used when condition_fields exist but no condition_model is specified.
        Creates multiple instances of self.model directly from condition rows.

        Returns:
            list: List of created instances, or False if validation errors occurred
        """
        if not (self.condition_fields and self.model):
            return []

        # Validate form has required fields (can be overridden in child classes)
        if form and hasattr(self, "validate_form_for_multiple_instances"):
            validation_result = self.validate_form_for_multiple_instances(form)
            if validation_result is False:
                return False

        # Get condition data from form.cleaned_data or POST
        condition_rows = None
        if (
            form
            and hasattr(form, "cleaned_data")
            and "condition_rows" in form.cleaned_data
        ):
            condition_rows = form.cleaned_data["condition_rows"]

        if condition_rows:
            # Use condition_rows from cleaned_data (already extracted and validated)
            condition_data = {}
            for order, row_data in enumerate(condition_rows):
                row_id = str(order)
                condition_data[row_id] = row_data
        else:
            # Extract condition data from POST
            condition_data = self.get_submitted_condition_data()

        if not condition_data:
            if form:
                form.add_error(None, _("At least one instance must be added."))
            return []

        created_instances = []
        validation_errors = []
        unique_check_cache = set()  # For duplicate checking (can be overridden)

        # Sort by row_id to maintain order
        def sort_key(x):
            try:
                return int(x)
            except ValueError:
                return 999

        for row_id in sorted(condition_data.keys(), key=sort_key):
            row_data = condition_data[row_id]
            # Fill mandatory condition fields that are missing (e.g. not shown in form)
            row_data = fill_mandatory_condition_defaults(
                self.model, self.condition_fields, row_data
            )

            # Skip empty rows
            if not any(row_data.get(field) for field in self.condition_fields):
                continue

            # Process row_data (can be customized in child classes for "same" checkbox logic, etc.)
            if hasattr(self, "process_row_data_before_create"):
                processed_result = self.process_row_data_before_create(
                    row_data, row_id, form
                )
                if processed_result is False:  # Explicit False means validation failed
                    return False
                if processed_result is None:  # None means skip this row
                    continue
                if isinstance(processed_result, dict):  # Returned processed row_data
                    row_data = processed_result
                # If True or no return, continue with original row_data

            # Check for duplicates (can be customized in child classes)
            if hasattr(self, "check_duplicate_instance"):
                duplicate_result = self.check_duplicate_instance(
                    row_data, unique_check_cache, form
                )
                if duplicate_result:
                    if isinstance(duplicate_result, str):
                        validation_errors.append(duplicate_result)
                    continue
                if duplicate_result is False:  # Explicit False means validation failed
                    return False

            try:
                # Build create kwargs for main model instance
                create_kwargs = {}

                # Add main form fields (non-condition fields) from form.cleaned_data
                if form and hasattr(form, "cleaned_data"):
                    for field_name, value in form.cleaned_data.items():
                        if field_name not in (
                            self.condition_fields or []
                        ) and field_name not in ["condition_rows"]:
                            try:
                                model_field = self.model._meta.get_field(field_name)
                                if isinstance(model_field, models.ForeignKey):
                                    create_kwargs[f"{field_name}_id"] = (
                                        value.id if hasattr(value, "id") else value
                                    )
                                else:
                                    create_kwargs[field_name] = value
                            except (FieldDoesNotExist, Exception):
                                pass

                # Add condition field values
                for field_name in self.condition_fields:
                    if field_name in row_data and row_data[field_name]:
                        try:
                            model_field = self.model._meta.get_field(field_name)
                            if isinstance(model_field, models.ForeignKey):
                                create_kwargs[f"{field_name}_id"] = row_data[field_name]
                            else:
                                create_kwargs[field_name] = row_data[field_name]
                        except (FieldDoesNotExist, Exception):
                            pass

                # Add standard fields if they exist
                if hasattr(self.model, "company"):
                    create_kwargs["company"] = (
                        getattr(_thread_local, "request", None).active_company
                        if hasattr(_thread_local, "request")
                        else self.request.user.company
                    )

                if hasattr(self.model, "created_by"):
                    create_kwargs["created_by"] = self.request.user
                if hasattr(self.model, "updated_by"):
                    create_kwargs["updated_by"] = self.request.user

                # Allow child classes to modify create_kwargs before creating instance
                if hasattr(self, "modify_create_kwargs"):
                    modify_result = self.modify_create_kwargs(
                        create_kwargs, row_data, row_id, form
                    )
                    if modify_result is False:  # Explicit False means validation failed
                        return False
                    if modify_result is None:  # None means skip this row
                        continue
                    if isinstance(
                        modify_result, dict
                    ):  # Returned modified create_kwargs
                        create_kwargs = modify_result

                # Create the instance
                instance = self.model.objects.create(**create_kwargs)
                created_instances.append(instance)

                # Update unique check cache if method exists
                if hasattr(self, "update_unique_check_cache"):
                    self.update_unique_check_cache(
                        row_data, unique_check_cache, instance
                    )

            except Exception as e:
                error_msg = str(e)
                if "UNIQUE constraint failed" in error_msg:
                    # Try to get a better error message
                    if hasattr(self, "get_duplicate_error_message"):
                        error_msg = self.get_duplicate_error_message(
                            row_data, error_msg
                        )
                validation_errors.append(f"Row {row_id}: {error_msg}")

        # If there are validation errors, add them to form
        if validation_errors and form:
            for error in validation_errors:
                form.add_error(None, error)
            return False

        return created_instances

    def get_add_condition_url(self):
        """Return URL that adds a new condition row (with content_type_field if set)."""
        return single_form_builder.get_add_condition_url(self)

    def get_create_url(self):
        """Get the create URL for the form"""
        form_url_value = self.form_url
        if hasattr(form_url_value, "url"):
            return form_url_value.url
        return str(form_url_value)

    def form_valid(self, form):
        """Save single or multiple instances; redirect or show errors."""

        # Handle multiple main model instances pattern (no condition_model)
        if self.condition_fields and not self.condition_model:
            created_instances = self.save_multiple_main_instances(form)
            # If save_multiple_main_instances returned False or None, form had errors
            if created_instances is False:
                return self.form_invalid(form)
            # If we have created instances, show success and return
            if created_instances:
                self.request.session["condition_row_count"] = 0
                messages.success(
                    self.request,
                    f"Created {len(created_instances)} {self.model._meta.verbose_name.lower()}(s) successfully.",
                )
                return ScriptResponse(reload=True, close=True)
            # If no instances created but no errors, show error
            if created_instances == []:
                form.add_error(
                    None,
                    "At least one instance must be created with all required fields.",
                )
                return self.form_invalid(form)

        # Standard pattern: save main object
        self.object = form.save(commit=False)

        for field_name, field in form.fields.items():
            if isinstance(field, (forms.FileField, forms.ImageField)):
                clear_flag = self.request.POST.get(f"id_{field_name}_clear", "false")
                if clear_flag == "true":
                    setattr(self.object, field_name, None)

        if self.kwargs.get("pk") and not self.duplicate_mode:
            self.object.updated_by = self.request.user
        else:
            self.object.created_by = self.request.user
            self.object.updated_by = self.request.user
        self.object.company = form.cleaned_data.get("company") or (
            getattr(_thread_local, "request", None).active_company
            if hasattr(_thread_local, "request")
            else self.request.user.company
        )
        try:
            with transaction.atomic():
                self.object.save()
                form.save_m2m()

                # Save conditions if condition_fields and condition_model are set
                if self.condition_fields and self.condition_model:
                    condition_errors = self.save_conditions(form)
                    if condition_errors:
                        self.object.delete()
                        return self.form_invalid(form)

            self.clear_pending_files_session()
            self.request.session["condition_row_count"] = 0
            self.request.session.modified = True
            action = (
                _("duplicated")
                if self.duplicate_mode
                else (
                    _("updated")
                    if self.kwargs.get("pk") and not self.duplicate_mode
                    else _("created")
                )
            )

            messages.success(
                self.request,
                _("%(model)s %(action)s successfully.")
                % {
                    "model": self.model._meta.verbose_name,
                    "action": action,
                },
            )

            # Check if "save_and_new" button was clicked (only in create mode)
            if (
                "save_and_new" in self.request.POST
                and not self.kwargs.get("pk")
                and not self.duplicate_mode
            ):
                create_url = self.get_create_url()
                return HttpResponse(
                    f"<div hx-get='{create_url}' "
                    f"hx-target='#modalBox' "
                    f"hx-swap='innerHTML' "
                    f"hx-trigger='load'>"
                    f"</div>"
                    f"<script>$('#reloadButton').click();</script>"
                )

            # Check if detail_url_name is provided and this is a create operation
            if (
                self.detail_url_name
                and not self.kwargs.get("pk")
                and not self.duplicate_mode
            ):
                detail_url = reverse(
                    self.detail_url_name, kwargs={"pk": self.object.pk}
                )
                # Preserve section parameter from the request
                if "section" in self.request.GET:
                    query_string = urlencode(
                        {"section": self.request.GET.get("section")}
                    )
                    detail_url = f"{detail_url}?{query_string}"
                response = HttpResponse()
                response["HX-Redirect"] = detail_url
                return response

            if self.return_response:
                return self.return_response
            return ScriptResponse(close=True, reload=True)

        except IntegrityError as e:
            error_message = str(e)

            field_error_added = False

            if "UNIQUE constraint failed" in error_message:
                constraint_match = re.search(
                    r"UNIQUE constraint failed: (.+)", error_message
                )
                if constraint_match:
                    fields_str = constraint_match.group(1)
                    # Extract field names (remove table prefix)
                    field_names = [f.split(".")[-1] for f in fields_str.split(", ")]

                    # Try to find which fields are involved
                    unique_fields = []
                    for field_name in field_names:
                        # Remove _id suffix for ForeignKey fields
                        clean_field_name = field_name.replace("_id", "")
                        if clean_field_name in form.fields:
                            unique_fields.append(clean_field_name)

                    if unique_fields:
                        # Add error to the first field involved
                        primary_field = unique_fields[0]

                        # Build human-readable message
                        if len(unique_fields) == 1:
                            field_label = (
                                form.fields[primary_field].label or primary_field
                            )
                            user_message = _(
                                "A %(model)s with this %(field)s already exists."
                            ) % {
                                "model": self.model._meta.verbose_name,
                                "field": str(field_label),
                            }
                        else:
                            field_labels = [
                                str(form.fields[f].label or f) for f in unique_fields
                            ]
                            user_message = _(
                                "A %(model)s with this combination of %(fields)s already exists."
                            ) % {
                                "model": self.model._meta.verbose_name,
                                "fields": ", ".join(field_labels),
                            }

                        form.add_error(primary_field, user_message)
                        field_error_added = True

            # If we couldn't parse the error, add a generic error
            if not field_error_added:
                form.add_error(
                    None,
                    _(
                        "This %(model)s could not be saved due to a duplicate entry. "
                        "Please check your input and try again."
                    )
                    % {"model": self.model._meta.verbose_name},
                )

            # Return form with errors
            return self.form_invalid(form)

        except ValidationError as e:
            # Raised deliberately by model/signal-level business rules (e.g.
            # the approval process blocking edits to a pending record) -
            # these already carry a precise, user-facing reason, so show it
            # instead of folding it into the generic "contact support"
            # message below.
            if hasattr(e, "error_dict"):
                # Model validation (full_clean in save) names the field at
                # fault: show it under that field when the form displays it,
                # else as a non-field error prefixed with the field's label.
                for field_name, errors in e.error_dict.items():
                    msg_error = [m for err in errors for m in err.messages]
                    form_field = form.fields.get(field_name)
                    if form_field is not None and not form_field.widget.is_hidden:
                        for message in msg_error:
                            form.add_error(field_name, message)
                        continue
                    label = None
                    if form_field is not None:
                        label = form_field.label
                    elif field_name != NON_FIELD_ERRORS:
                        try:
                            label = self.model._meta.get_field(field_name).verbose_name
                        except Exception:  # pylint: disable=broad-except
                            label = field_name
                    for message in msg_error:
                        form.add_error(
                            None, f"{label}: {message}" if label else message
                        )
            else:
                for message in e.messages:
                    form.add_error(None, message)
            return self.form_invalid(form)

        except Exception as e:
            # Handle any other database errors
            logger.error(
                "Error saving %s: %s",
                self.model._meta.verbose_name,
                str(e),
                exc_info=True,
            )
            form.add_error(
                None,
                _(
                    "An error occurred while saving. Please try again or contact support."
                ),
            )
            return self.form_invalid(form)

    def form_invalid(self, form):
        """Re-render form with validation errors."""
        print(form.errors)
        self.save_pending_files_to_session()
        return super().form_invalid(form)

    def get_success_url(self):
        """Return success_url or default list URL for the model."""
        return self.success_url or reverse_lazy(f"{self.model._meta.model_name}-list")
