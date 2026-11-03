"""
A generic multi-step form view for Horilla that supports dynamic field handling, file uploads, and permission checks.
This view can be extended to create complex multi-step forms for any model, with features.
"""

# Standard library imports
import base64
import logging
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

# Third-party imports (Django)
from django import forms
from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils.dateparse import parse_date, parse_datetime

from horilla.contrib.utils.middlewares import _thread_local

# First party imports (Horilla)
from horilla.db import models
from horilla.urls import reverse
from horilla.utils.text import title_words
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import FormView
from horilla.web import HttpResponse, ScriptResponse

# Local imports
from ..forms import HorillaMultiStepForm
from .toolkit.form_mixin import FormViewCommonMixin

logger = logging.getLogger(__name__)


class HorillaMultiStepFormView(FormViewCommonMixin, FormView):
    """View for handling multi-step form workflows."""

    template_name = "form_view.html"
    form_class = None
    model = None
    success_url = None
    step_titles = {}
    total_steps = 4
    form_url_name = None
    form_title = None
    fullwidth_fields = []
    dynamic_create_fields = []
    dynamic_create_field_mapping = {}
    pk_url_kwarg = "pk"
    permission_required = None
    check_object_permission = True
    permission_denied_template = "403.html"
    skip_permission_check = False
    view_id = ""
    detail_url_name = None
    save_and_new = True

    def get_create_url(self):
        """Get the create URL for the form"""
        # Use form_url_name to get create URL
        if self.form_url_name:
            if isinstance(self.form_url_name, dict):
                url_name = self.form_url_name.get("create")
                if url_name:
                    return reverse(url_name)
            else:
                return reverse(self.form_url_name)
        # Fallback: use request path
        return self.request.path

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.storage_key = f"{self.__class__.__name__}_form_data"
        self.object = None

    def dispatch(self, request, *args, **kwargs):
        """Check permission and resolve object when pk given; then dispatch."""
        if not self.skip_permission_check and not self.has_permission():
            return self.get_permission_denied_response(request)
        obj, error_response = self.get_object_or_error_response(request)
        if error_response is not None:
            return error_response
        if obj is not None:
            self.object = obj
            self.storage_key = f"{self.__class__.__name__}_form_data_{self.kwargs.get(self.pk_url_kwarg)}"
        return super().dispatch(request, *args, **kwargs)

    def cleanup_session_data(self):
        """Clean up session data"""
        keys_to_remove = [self.storage_key, f"{self.storage_key}_files"]
        for key in keys_to_remove:
            if key in self.request.session:
                del self.request.session[key]
        self.request.session.modified = True

    def get_form_class(self):
        """Return DynamicMultiStepForm for the model when form_class is not set."""
        if self.form_class is None and self.model is not None:

            class DynamicMultiStepForm(HorillaMultiStepForm):
                """Dynamically generated multi-step form based on model."""

                class Meta:
                    """Meta options for DynamicMultiStepForm."""

                    model = self.model
                    fields = "__all__"
                    exclude = [
                        "created_at",
                        "updated_at",
                        "created_by",
                        "updated_by",
                        "additional_info",
                    ]
                    widgets = {
                        field.name: forms.DateInput(attrs={"type": "date"})
                        for field in self.model._meta.fields
                        if isinstance(field, models.DateField)
                    }

            return DynamicMultiStepForm

        # Concrete form from the view (form_class=UserFormClass, etc.), not the dynamic branch above.
        base = super().get_form_class()
        # No registered form on this view — nothing to compose; do not call resolve_form_class.
        if base is None:
            return base
        # Import here (not at module top): extension forms bootstrap in CoreConfig.ready()
        # after apps are loaded; a top-level import can run too early or create cycles.
        from horilla.extension.forms.resolve import resolve_form_class

        # Views keep form_class = Horilla module form at import time; resolve to composed subclass
        # (e.g. UserFormClassExtended) when an extension app registered _inherit_form.
        return resolve_form_class(base)

    def _multiwidget_step_map(self, all_step_fields, form_class):
        """Expand a ``{field_name: step}`` map with PhoneWidget's sub-keys.

        HorillaMultiStepForm keeps MultiValueField-based fields (e.g.
        PhoneField) as real MultiWidgets even when hidden on later steps, so
        the browser always posts ``{name}_0``/``{name}_1`` sub-keys rather
        than a single flattened value. PhoneField is only swapped in on the
        form instance (not in ``base_fields``), so phone-field names are
        resolved the same way ``_apply_phone_fields`` does, rather than by
        inspecting an instantiated field's widget.
        """
        phone_fields_attr = form_class.__dict__.get("phone_fields", None)
        if phone_fields_attr is None:
            phone_fields_attr = getattr(form_class, "phone_fields", None)
        if phone_fields_attr is not None and len(phone_fields_attr) == 0:
            active_names = set()
        else:
            active_names = form_class._DEFAULT_PHONE_FIELD_NAMES | set(
                phone_fields_attr or []
            )

        expanded = dict(all_step_fields)
        for field_name, step_num in all_step_fields.items():
            if field_name in active_names:
                expanded[f"{field_name}_0"] = step_num
                expanded[f"{field_name}_1"] = step_num
        return expanded

    def get_initial_step(self):
        """Get the initial step, ensuring it's valid and within bounds."""
        try:
            step = int(self.request.POST.get("step", 1))
            if step < 1 or step > self.total_steps:
                return 1
            return step
        except (ValueError, TypeError):
            return 1

    def encode_file_for_session(self, uploaded_file):
        """Encode file to store in session"""
        try:
            content = uploaded_file.read()
            uploaded_file.seek(0)
            return {
                "name": uploaded_file.name,
                "content": base64.b64encode(content).decode("utf-8"),
                "content_type": uploaded_file.content_type,
                "size": uploaded_file.size,
            }
        except Exception as e:
            logger.error("Error encoding file: %s", e)
            return None

    def decode_file_from_session(self, file_data):
        """Decode file from session storage"""
        try:
            if not file_data or "content" not in file_data:
                return None
            content = base64.b64decode(file_data["content"])
            return SimpleUploadedFile(
                name=file_data["name"],
                content=content,
                content_type=file_data["content_type"],
            )
        except Exception as e:
            logger.error("Error decoding file: %s", e)
            return None

    def get_form_kwargs(self):
        """Pass request, step, instance, session form_data/files, and field_permissions to the form."""
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        step = getattr(self, "current_step", self.get_initial_step())
        kwargs["step"] = step
        kwargs["full_width_fields"] = self.fullwidth_fields
        kwargs["dynamic_create_fields"] = self.get_filtered_dynamic_create_fields()

        kwargs["field_permissions"] = self.get_field_permissions()

        if self.object:
            kwargs["instance"] = self.object

        form_data = self.request.session.get(self.storage_key, {})
        files_data = self.request.session.get(f"{self.storage_key}_files", {})

        form_class = self.get_form_class()
        step_fields = getattr(form_class, "step_fields", {}).get(step, [])

        # Build a map of field_name -> step_number to identify fields from earlier steps
        all_step_fields_map = {}
        if hasattr(form_class, "step_fields") and form_class.step_fields:
            for step_num, fields_list in form_class.step_fields.items():
                for field_name in fields_list:
                    all_step_fields_map[field_name] = step_num

        # Clean up form_data: fix any ManyToMany fields that were stored as string representations
        # This can happen when session serializes lists incorrectly
        # Only process fields that are in at least one step
        many_to_many_fields = [
            field.name
            for field in self.model._meta.get_fields()
            if isinstance(field, models.ManyToManyField)
        ]
        for key in list(form_data.keys()):
            if key in many_to_many_fields and key in all_step_fields_map:
                value = form_data[key]
                # Check if value is a list containing a string representation of a list
                if isinstance(value, list) and len(value) == 1:
                    first_item = value[0]
                    if isinstance(first_item, str) and (
                        first_item.startswith("[") and first_item.endswith("]")
                    ):
                        try:
                            import ast

                            parsed_list = ast.literal_eval(first_item)
                            if isinstance(parsed_list, list):
                                form_data[key] = parsed_list
                        except (ValueError, SyntaxError):
                            # If parsing fails, set to empty list
                            form_data[key] = []
            elif key in many_to_many_fields and key not in all_step_fields_map:
                # Remove ManyToMany fields that aren't in any step from form_data
                # They shouldn't be processed
                form_data.pop(key, None)

        # Build a map of field_name -> step_number to identify fields from earlier steps
        all_step_fields = {}
        if hasattr(form_class, "step_fields") and form_class.step_fields:
            for step_num, fields_list in form_class.step_fields.items():
                for field_name in fields_list:
                    all_step_fields[field_name] = step_num
        all_step_fields = self._multiwidget_step_map(all_step_fields, form_class)

        if self.request.method == "POST" and "reset" not in self.request.GET:
            post_data = self.request.POST.copy()
            boolean_fields = [
                field.name
                for field in self.model._meta.fields
                if isinstance(field, models.BooleanField)
            ]
            many_to_many_fields = [
                field.name
                for field in self.model._meta.get_fields()
                if isinstance(field, models.ManyToManyField)
            ]
            file_fields = [
                field.name
                for field in self.model._meta.fields
                if isinstance(field, (models.FileField, models.ImageField))
            ]

            for key in post_data:
                if key not in ["csrfmiddlewaretoken", "step", "previous"]:
                    if key in many_to_many_fields:
                        # Skip ManyToMany fields that are not in any step
                        # (like groups, user_permissions in User form)
                        if key not in all_step_fields:
                            # Field not in any step - skip processing it
                            continue

                        # Check if this field belongs to the current step or earlier steps
                        field_step = all_step_fields.get(key)
                        is_in_current_step = field_step == step
                        is_from_earlier_step = field_step and field_step < step

                        # Check if key actually exists in POST (getlist returns [] even if key doesn't exist)
                        has_key_in_post = key in post_data
                        values = post_data.getlist(key) if has_key_in_post else []

                        # Convert values to integers (they come as strings from POST)
                        if values:
                            try:
                                values = [
                                    int(v) for v in values if v and str(v).strip()
                                ]
                            except (ValueError, TypeError):
                                values = []

                        # Only update form_data if field is in current step or has values
                        # If editing and field not in current step, preserve existing values
                        if values:
                            # POST has values, update form_data
                            form_data[key] = values
                        elif has_key_in_post and is_in_current_step:
                            # Field is in current step and explicitly in POST with no values - set empty list
                            form_data[key] = []
                        elif self.object:
                            # Editing existing instance - preserve or initialize from instance
                            if is_from_earlier_step:
                                # Field from earlier step - preserve existing values if not set or empty
                                if key not in form_data or (
                                    isinstance(form_data.get(key), list)
                                    and not form_data[key]
                                ):
                                    # Initialize from instance if available
                                    try:
                                        instance_values = list(
                                            getattr(self.object, key).values_list(
                                                "pk", flat=True
                                            )
                                        )
                                        form_data[key] = (
                                            instance_values if instance_values else []
                                        )
                                    except Exception:
                                        form_data[key] = []
                            else:
                                # Field not in any step (or step not defined) - preserve or initialize from instance
                                if key not in form_data or (
                                    isinstance(form_data.get(key), list)
                                    and not form_data[key]
                                ):
                                    try:
                                        instance_values = list(
                                            getattr(self.object, key).values_list(
                                                "pk", flat=True
                                            )
                                        )
                                        form_data[key] = (
                                            instance_values if instance_values else []
                                        )
                                    except Exception:
                                        form_data[key] = []
                        # If creating new instance and field not in current step, don't set anything
                        # (will be handled by form initialization)
                        continue

                    # Check if this field belongs to an earlier step
                    field_step = all_step_fields.get(key)
                    is_from_earlier_step = field_step and field_step < step
                    post_value = post_data[key]

                    # For fields from earlier steps: preserve session values if POST is empty
                    if is_from_earlier_step:
                        # Field is from an earlier step - preserve session value if POST is empty
                        if post_value and str(post_value).strip():
                            # POST has a value, update it (user might be changing it)
                            form_data[key] = post_value
                        # Otherwise, keep the existing session value (don't overwrite with empty)
                        # Only update if session doesn't have a value
                        elif key not in form_data or not form_data.get(key):
                            form_data[key] = post_value
                        # If session has a value and POST is empty, preserve session value
                        continue

                    try:
                        model_field = self.model._meta.get_field(key)
                        if isinstance(model_field, models.DateField) and not isinstance(
                            model_field, models.DateTimeField
                        ):
                            parsed_date = parse_date(
                                post_data[key].split("T")[0]
                                if "T" in post_data[key]
                                else post_data[key]
                            )
                            if parsed_date:
                                form_data[key] = parsed_date.isoformat()
                                continue
                        parsed_datetime = parse_datetime(post_data[key])
                        if parsed_datetime:
                            form_data[key] = parsed_datetime.isoformat()
                            continue
                        parsed_date = parse_date(post_data[key])
                        if parsed_date:
                            form_data[key] = parsed_date.isoformat()
                            continue
                        try:
                            decimal_value = Decimal(post_data[key])
                            form_data[key] = str(decimal_value)
                            continue
                        except (ValueError, TypeError, InvalidOperation):
                            pass
                    except Exception:
                        pass
                    form_data[key] = post_data[key]

            for field_name in boolean_fields:
                if (
                    field_name in step_fields
                    and field_name not in post_data
                    and step == int(post_data.get("step", 1))
                ):
                    form_data[field_name] = False
            for field_name in file_fields:
                if field_name in self.request.FILES:
                    uploaded_file = self.request.FILES[field_name]
                    encoded_file = self.encode_file_for_session(uploaded_file)
                    if encoded_file:
                        files_data[field_name] = encoded_file
                        form_data[f"{field_name}_filename"] = uploaded_file.name
                        form_data[f"{field_name}_new_file"] = True
                        # Remove cleared flag if new file uploaded
                        form_data.pop(f"{field_name}_cleared", None)
                # Check if file was cleared
                elif (
                    f"{field_name}-clear" in post_data
                    and post_data[f"{field_name}-clear"] == "true"
                ):
                    # Mark file as cleared
                    form_data[f"{field_name}_cleared"] = True
                    # Remove file from session
                    files_data.pop(field_name, None)
                    form_data.pop(f"{field_name}_filename", None)
                    form_data.pop(f"{field_name}_new_file", None)

            self.request.session[self.storage_key] = form_data
            self.request.session[f"{self.storage_key}_files"] = files_data
            self.request.session.modified = True

        if form_data:
            if (
                self.request.method == "GET"
                and step == 1
                and "previous" not in self.request.POST
                and "new" in self.request.GET
                and not self.object
            ):
                pass
            else:
                kwargs["form_data"] = form_data
                kwargs["data"] = form_data

        files_dict = {}

        if self.request.FILES:
            files_dict.update(self.request.FILES)

        for field_name, file_data in files_data.items():
            if field_name not in files_dict:
                decoded_file = self.decode_file_from_session(file_data)
                if decoded_file:
                    files_dict[field_name] = decoded_file

        if files_dict:
            kwargs["files"] = files_dict

        # Updated here

        if self.request.method == "POST" and (
            "previous" in self.request.POST
            or (
                self.get_initial_step() < self.total_steps
                and "step" in self.request.POST
            )
        ):
            if "data" in kwargs:
                kwargs["data"] = None

        return kwargs

    def get_form_title(self):
        """Return a human-friendly form title based on create/update state."""
        if self.model:
            action = _("Update") if self.object else _("Create")
            verbose = self.model._meta.verbose_name
            return f"{action} {title_words(verbose)}"
        return ""

    def get_context_data(self, **kwargs):
        """Provide context for multi-step forms including navigation and titles."""
        context = super().get_context_data(**kwargs)
        self.current_step = getattr(self, "current_step", self.get_initial_step())
        context["step_titles"] = self.step_titles
        context["save_and_new"] = self.save_and_new
        context["total_steps"] = self.total_steps
        context["current_step"] = self.current_step
        context["form_title"] = self.form_title or self.get_form_title()
        context["object"] = self.object
        context["is_edit"] = bool(self.object)
        context["full_width_fields"] = self.fullwidth_fields
        context["dynamic_create_fields"] = self.get_filtered_dynamic_create_fields()
        context["dynamic_create_field_mapping"] = self.dynamic_create_field_mapping

        if self.form_url_name:
            if self.object:
                context["form_url"] = reverse(
                    self.form_url_name, kwargs={self.pk_url_kwarg: self.object.pk}
                )
            else:
                context["form_url"] = reverse(self.form_url_name)
        else:
            context["form_url"] = self.request.path

        context["related_models_info"] = self.get_related_models_info()
        context["m2m_picker_info"] = self._get_m2m_picker_info()

        context["stored_form_data"] = self.request.session.get(self.storage_key, {})
        context["stored_files_data"] = self.request.session.get(
            f"{self.storage_key}_files", {}
        )

        form_data = self.request.session.get(self.storage_key, {})
        files_data = self.request.session.get(f"{self.storage_key}_files", {})
        file_field_states = {}

        for field in self.model._meta.fields:
            if isinstance(field, (models.FileField, models.ImageField)):
                field_name = field.name
                is_image = isinstance(field, models.ImageField)
                # Check if file was cleared
                if form_data.get(f"{field_name}_cleared"):
                    file_field_states[field_name] = {
                        "has_file": False,
                        "filename": None,
                        "is_cleared": True,
                        "url": "",
                    }
                elif field_name in files_data or form_data.get(
                    f"{field_name}_new_file"
                ):
                    filename = form_data.get(f"{field_name}_filename")
                    url = ""
                    if is_image and field_name in files_data:
                        file_data = files_data[field_name]
                        content_type = file_data.get("content_type", "")
                        content = file_data.get("content", "")
                        if content_type and content:
                            url = f"data:{content_type};base64,{content}"
                    file_field_states[field_name] = {
                        "has_file": True,
                        "filename": filename,
                        "is_new": True,
                        "url": url,
                    }
                # Use instance file if exists and not modified
                elif self.object and hasattr(self.object, field_name):
                    instance_file = getattr(self.object, field_name, None)
                    if instance_file and instance_file.name:
                        file_field_states[field_name] = {
                            "has_file": True,
                            "filename": instance_file.name.split("/")[-1],
                            "is_existing": True,
                            "url": instance_file.url if is_image else "",
                        }

        context["file_field_states"] = file_field_states

        form = context.get("form")
        if form and hasattr(self, "fullwidth_fields"):
            for field_name, field in form.fields.items():
                if field_name in self.fullwidth_fields:
                    field.widget.attrs["fullwidth"] = True

        context["form_mode"] = self.resolve_form_mode()
        context["view_id"] = self.view_id or f"{self.model._meta.model_name}-form-view"

        context["field_permissions"] = self.get_field_permissions()

        return context

    def form_valid(self, form):
        """Advance step and re-render form, or save on last step and redirect/cleanup."""
        step = self.get_initial_step()

        if step < self.total_steps:
            self.current_step = step + 1
            form_kwargs = self.get_form_kwargs()

            files_data = self.request.session.get(f"{self.storage_key}_files", {})
            final_files = {}

            if self.request.FILES:
                final_files.update(self.request.FILES)

            for field_name, file_data in files_data.items():
                if field_name not in final_files:
                    decoded_file = self.decode_file_from_session(file_data)
                    if decoded_file:
                        final_files[field_name] = decoded_file

            next_step_form_kwargs = {
                "step": self.current_step,
                "form_data": form_kwargs.get("form_data", {}),
                "instance": self.object if self.object else None,
                "full_width_fields": self.fullwidth_fields,
                "dynamic_create_fields": self.dynamic_create_fields,
                "request": self.request,
            }

            next_step_form_kwargs["field_permissions"] = self.get_field_permissions()

            if final_files:
                next_step_form_kwargs["files"] = final_files

            next_step_form = self.get_form_class()(**next_step_form_kwargs)

            try:
                next_step_form = self.get_form_class()(**next_step_form_kwargs)
                next_step_form.errors.clear()
                next_step_form.is_bound = False
            except Exception as e:
                logger.error("Error creating next step form: %s", e)
                next_step_form = self.get_form_class()(**next_step_form_kwargs)

            return self.render_to_response(self.get_context_data(form=next_step_form))

        try:
            form_data = self.request.session.get(self.storage_key, {})
            files_data = self.request.session.get(f"{self.storage_key}_files", {})

            # Build a map of field_name -> step_number to identify fields from earlier steps
            form_class = self.get_form_class()
            all_step_fields = {}
            if hasattr(form_class, "step_fields") and form_class.step_fields:
                for step_num, fields_list in form_class.step_fields.items():
                    for field_name in fields_list:
                        all_step_fields[field_name] = step_num
            all_step_fields = self._multiwidget_step_map(all_step_fields, form_class)

            for key, value in self.request.POST.items():
                if key not in ["csrfmiddlewaretoken", "step", "previous"]:
                    if key in [
                        field.name
                        for field in self.model._meta.get_fields()
                        if isinstance(field, models.ManyToManyField)
                    ]:
                        form_data[key] = self.request.POST.getlist(key)
                    else:
                        # Check if this field belongs to an earlier step
                        field_step = all_step_fields.get(key)
                        is_from_earlier_step = (
                            field_step and field_step < self.total_steps
                        )

                        # For fields from earlier steps: preserve session values if POST is empty
                        if is_from_earlier_step:
                            # Field is from an earlier step - preserve session value if POST is empty
                            if value and str(value).strip():
                                # POST has a value, update it (user might be changing it)
                                form_data[key] = value
                            # Otherwise, keep the existing session value (don't overwrite with empty)
                            # Only update if session doesn't have a value
                            elif key not in form_data or not form_data.get(key):
                                form_data[key] = value
                            # If session has a value and POST is empty, preserve session value
                        else:
                            # Field is in current step or not in any step - update normally
                            form_data[key] = value

            final_files = {}

            if self.request.FILES:
                final_files.update(self.request.FILES)

            for field_name, file_data in files_data.items():
                if field_name not in final_files:
                    decoded_file = self.decode_file_from_session(file_data)
                    if decoded_file:
                        final_files[field_name] = decoded_file

            # Save updated form_data to session before validation
            # This ensures data is preserved if validation fails
            self.request.session[self.storage_key] = form_data
            self.request.session.modified = True

            final_form_kwargs = {
                "data": form_data,
                "step": self.total_steps,
                "form_data": form_data,
                "full_width_fields": self.fullwidth_fields,
                "dynamic_create_fields": self.dynamic_create_fields,
                "request": self.request,
            }

            final_form_kwargs["field_permissions"] = self.get_field_permissions()

            if final_files:
                final_form_kwargs["files"] = final_files

            if self.object:
                final_form_kwargs["instance"] = self.object

            final_form = self.get_form_class()(**final_form_kwargs)

            if final_form.is_valid():
                try:
                    instance = final_form.save(commit=False)
                    instance.company = final_form.cleaned_data.get("company") or (
                        getattr(_thread_local, "request", None).active_company
                        if hasattr(_thread_local, "request")
                        else self.request.user.company
                    )

                    # Handle file fields - Django's save(commit=False) doesn't set files on instance
                    # We need to explicitly set them from cleaned_data or final_files
                    for field in self.model._meta.get_fields():
                        if isinstance(field, (models.FileField, models.ImageField)):
                            field_name = field.name
                            if form_data.get(f"{field_name}_cleared"):
                                setattr(instance, field_name, None)
                            elif field_name in final_form.cleaned_data:
                                # File is in cleaned_data (from form.save()), use it
                                file_value = final_form.cleaned_data[field_name]
                                if file_value:
                                    setattr(instance, field_name, file_value)
                            elif field_name in final_files:
                                # File from earlier step - set it explicitly
                                file_obj = final_files[field_name]
                                if file_obj:
                                    setattr(instance, field_name, file_obj)

                    with transaction.atomic():
                        instance.save()
                        # Call save_m2m to ensure ManyToMany fields are saved
                        final_form.save_m2m()
                        self.object = instance

                        for field in self.model._meta.get_fields():
                            if (
                                isinstance(field, models.ManyToManyField)
                                and field.name in form_data
                            ):
                                values = form_data[field.name]
                                if values:
                                    getattr(instance, field.name).set(values)
                                else:
                                    getattr(instance, field.name).clear()

                    self.cleanup_session_data()

                    action = (
                        "updated" if self.kwargs.get(self.pk_url_kwarg) else "created"
                    )
                    messages.success(
                        self.request,
                        f"{self.model._meta.verbose_name} was successfully {action}.",
                    )

                    # Check if "save_and_new" button was clicked (only in create mode, last step)
                    if "save_and_new" in self.request.POST and not self.kwargs.get(
                        self.pk_url_kwarg
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
                    if self.detail_url_name and not self.kwargs.get(self.pk_url_kwarg):
                        detail_url = reverse(
                            self.detail_url_name,
                            kwargs={self.pk_url_kwarg: self.object.pk},
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

                    return ScriptResponse(reload=True, close=True)
                except Exception as e:
                    final_form.add_error(None, e)

                    error_form_kwargs = {
                        "data": form_data,
                        "step": self.total_steps,
                        "form_data": form_data,
                        "full_width_fields": self.fullwidth_fields,
                        "dynamic_create_fields": self.dynamic_create_fields,
                        "request": self.request,
                    }

                    error_form_kwargs["field_permissions"] = (
                        self.get_field_permissions()
                    )

                    if final_files:
                        error_form_kwargs["files"] = final_files

                    if self.object:
                        error_form_kwargs["instance"] = self.object

                    error_form = self.get_form_class()(**error_form_kwargs)

                    # copy over the error into the form
                    for field_name, errors in final_form.errors.items():
                        if field_name == "__all__":
                            for error in errors:
                                error_form.add_error(None, error)
                        else:
                            for error in errors:
                                error_form.add_error(field_name, error)

                    self.current_step = self.total_steps
                    return self.render_to_response(
                        self.get_context_data(form=error_form)
                    )
            else:
                # Set current_step to total_steps when form is invalid on last step
                self.current_step = self.total_steps
                return self.render_to_response(self.get_context_data(form=final_form))

        except Exception as e:
            action = "updating" if self.object else "creating"
            messages.error(
                self.request, f"Error {action} {self.model.__name__}: {str(e)}"
            )
            logger.error("Exception in form_valid: %s", str(e))
            import traceback

            traceback.print_exc()
            return self.render_to_response(self.get_context_data(form=form))

    def form_invalid(self, form):
        """Re-render the current step form with validation errors."""
        return self.render_to_response(self.get_context_data(form=form))

    def post(self, request, *args, **kwargs):
        """Handle previous/next step or submit; delegate to parent post for normal submit."""
        if "previous" in request.POST:
            step = self.get_initial_step()
            if step > 1:
                self.current_step = step - 1

                files_data = self.request.session.get(f"{self.storage_key}_files", {})
                form_data = self.request.session.get(self.storage_key, {})

                final_files = {}
                for field_name, file_data in files_data.items():
                    decoded_file = self.decode_file_from_session(file_data)
                    if decoded_file:
                        final_files[field_name] = decoded_file

                form_kwargs = {
                    "step": self.current_step,
                    "form_data": form_data,
                    "instance": self.object if self.object else None,
                    "full_width_fields": self.fullwidth_fields,
                    "dynamic_create_fields": self.dynamic_create_fields,
                    "request": self.request,
                    "data": form_data,
                }

                form_kwargs["field_permissions"] = self.get_field_permissions()

                if final_files:
                    form_kwargs["files"] = final_files

                form = self.get_form_class()(**form_kwargs)

                form.errors.clear()

                return self.render_to_response(self.get_context_data(form=form))

        return super().post(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        """Reset session when requested; set current_step to 1 and render form."""
        if "reset" in request.GET or ("new" in request.GET and not self.object):
            self.cleanup_session_data()
        elif self.object:
            step = int(request.GET.get("step", 1))
            if step == 1 and "previous" not in request.POST:
                self.cleanup_session_data()
        self.current_step = 1
        form = self.get_form()
        return self.render_to_response(self.get_context_data(form=form))
