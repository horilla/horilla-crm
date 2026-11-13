"""
Multi-step form classes for horilla.contrib.generics.

Provides HorillaMultiStepForm and related logic for wizard-style forms
that split fields across multiple steps with step-based validation and file handling.
"""

# Standard library imports
import logging
from datetime import date, datetime
from decimal import Decimal

# Django imports
# Third-party imports (Django)
from django import forms
from django.db.models.fields.files import ImageFieldFile

# Third-party imports
from django_countries.fields import Country, CountryField

from horilla.auth.models import User
from horilla.core.exceptions import ValidationError

# First party imports (Horilla)
from horilla.db import models
from horilla.db.models import Q
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .form_class_mixin import WIDGET_INPUT_CSS_CLASS, HorillaFormMixin

logger = logging.getLogger(__name__)


class HorillaMultiStepForm(HorillaFormMixin, forms.ModelForm):
    """Base form class for multi-step form workflows.

    Subclasses automatically inherit ``HORILLA_FORM_EXCLUDE`` on their
    ``Meta.exclude``.  Two escape hatches are available on ``Meta``:

    * ``keep_on_form`` — iterable of field names that should be removed from
      the base exclude list (i.e. shown on this form).
    * ``exclude`` — any extra fields listed here are *added* to the merged
      list; the base core fields are still excluded unless listed in
      ``keep_on_form``.
    """

    step_fields = {}

    def __init__(self, *args, **kwargs):
        self.current_step = int(kwargs.pop("step", 1))
        self.form_data = kwargs.pop("form_data", {}) or {}
        self.full_width_fields = kwargs.pop("full_width_fields", [])
        self.dynamic_create_fields = kwargs.pop("dynamic_create_fields", [])
        self.request = kwargs.pop("request", None)
        self.field_permissions = kwargs.pop("field_permissions", {})

        self.stored_files = {}
        self._step_hidden_fields = set()

        super().__init__(*args, **kwargs)

        # Get all step fields to identify fields that should be excluded
        all_step_fields = []
        if hasattr(self, "step_fields") and self.step_fields:
            for step_fields_list in self.step_fields.values():
                all_step_fields.extend(step_fields_list)

        # When step_fields is defined, auto-assign any form fields not in any step
        # to the last step (supports Meta.fields = "__all__" without explicit listing).
        if all_step_fields and self.step_fields:
            last_step = max(self.step_fields.keys())
            for field_name in list(self.fields.keys()):
                if field_name not in all_step_fields:
                    try:
                        model_field = self._meta.model._meta.get_field(field_name)
                        if not isinstance(model_field, models.ManyToManyField):
                            self.step_fields[last_step] = list(
                                self.step_fields[last_step]
                            ) + [field_name]
                            all_step_fields.append(field_name)
                    except models.FieldDoesNotExist:
                        pass

        # Remove ManyToMany fields that are not in any step from the form
        # (like groups, user_permissions in User form)
        if all_step_fields:
            fields_to_remove = []
            for field_name, field in list(self.fields.items()):
                if field_name not in all_step_fields:
                    try:
                        model_field = self._meta.model._meta.get_field(field_name)
                        if isinstance(model_field, models.ManyToManyField):
                            fields_to_remove.append(field_name)
                    except models.FieldDoesNotExist:
                        pass

            for field_name in fields_to_remove:
                del self.fields[field_name]

        # Store original required state before any modifications
        for field_name, field in self.fields.items():
            field._original_required = field.required
            if isinstance(field.widget, forms.CheckboxInput):
                field.required = False

        if self.request and self.request.FILES:
            self.files = self.request.FILES

        if hasattr(self, "files") and self.files:
            for field_name, file_obj in self.files.items():
                self.stored_files[field_name] = file_obj

        # Get all step fields to check if a field should be processed
        all_step_fields = []
        if hasattr(self, "step_fields") and self.step_fields:
            for step_fields_list in self.step_fields.values():
                all_step_fields.extend(step_fields_list)

        if self.instance and self.instance.pk:
            for field_name in self.fields:
                if all_step_fields and field_name not in all_step_fields:
                    try:
                        model_field = self._meta.model._meta.get_field(field_name)
                        if isinstance(model_field, models.ManyToManyField):
                            continue
                    except models.FieldDoesNotExist:
                        # If we can't determine the field type, process it to be safe
                        pass

                if field_name not in self.form_data or self.form_data[field_name] in [
                    None,
                    "",
                    [],
                ]:
                    field_value = getattr(self.instance, field_name, None)
                    if field_value is not None:
                        if hasattr(field_value, "pk"):
                            self.form_data[field_name] = field_value.pk
                        elif hasattr(field_value, "all"):
                            # Only populate ManyToMany if field is in at least one step
                            if not all_step_fields or field_name in all_step_fields:
                                self.form_data[field_name] = [
                                    obj.pk for obj in field_value.all()
                                ]
                        elif isinstance(field_value, datetime):
                            self.form_data[field_name] = field_value.strftime(
                                "%Y-%m-%dT%H:%M"
                            )
                        elif isinstance(field_value, date):
                            self.form_data[field_name] = field_value.strftime(
                                "%Y-%m-%d"
                            )
                        elif isinstance(field_value, Decimal):
                            self.form_data[field_name] = str(field_value)
                        elif isinstance(field_value, bool):
                            self.form_data[field_name] = field_value
                        elif isinstance(field_value, Country):
                            self.form_data[field_name] = str(field_value)
                        elif isinstance(field_value, (ImageFieldFile)):
                            # For existing files, we need to preserve the file info
                            if field_value.name:
                                self.form_data[field_name] = field_value.name
                                # Only set filename if not already set from session
                                if f"{field_name}_filename" not in self.form_data:
                                    self.form_data[f"{field_name}_filename"] = (
                                        field_value.name.split("/")[-1]
                                    )
                        else:
                            self.form_data[field_name] = field_value

        if self.form_data:
            # Clean up form data to ensure proper formatting for date/datetime fields
            cleaned_form_data = {}
            for field_name, field_value in self.form_data.items():
                if field_name in self.fields:
                    try:
                        model_field = self._meta.model._meta.get_field(field_name)
                        if isinstance(model_field, models.BooleanField):
                            # Convert string values to boolean
                            if isinstance(field_value, str):
                                cleaned_form_data[field_name] = field_value.lower() in (
                                    "true",
                                    "on",
                                    "1",
                                )
                            else:
                                cleaned_form_data[field_name] = bool(field_value)
                        elif isinstance(
                            model_field, models.DateField
                        ) and not isinstance(model_field, models.DateTimeField):
                            if isinstance(field_value, str) and "T" in field_value:
                                cleaned_form_data[field_name] = field_value.split("T")[
                                    0
                                ]
                            elif isinstance(field_value, (datetime, date)):
                                cleaned_form_data[field_name] = field_value.strftime(
                                    "%Y-%m-%d"
                                )
                            else:
                                cleaned_form_data[field_name] = field_value
                        elif isinstance(model_field, models.DateTimeField):
                            if isinstance(field_value, str) and "T" not in field_value:
                                cleaned_form_data[field_name] = f"{field_value}T00:00"
                            elif isinstance(field_value, datetime):
                                cleaned_form_data[field_name] = field_value.strftime(
                                    "%Y-%m-%dT%H:%M"
                                )
                            elif isinstance(field_value, date):
                                cleaned_form_data[field_name] = (
                                    f"{field_value.strftime('%Y-%m-%d')}T00:00"
                                )
                            else:
                                cleaned_form_data[field_name] = field_value
                        elif isinstance(model_field, CountryField):
                            cleaned_form_data[field_name] = str(field_value)
                        else:
                            cleaned_form_data[field_name] = field_value
                    except models.FieldDoesNotExist:
                        cleaned_form_data[field_name] = field_value
                else:
                    cleaned_form_data[field_name] = field_value

            self.data = cleaned_form_data

        self._configure_field_widgets()

        self._remove_fields_by_permission(skip_hidden_widget=True)
        self._apply_phone_fields()
        self._apply_default_time_zone()

        if self.current_step <= len(self.step_fields):
            current_fields = self.step_fields.get(self.current_step, [])
            all_step_fields = [
                f for step_fields in self.step_fields.values() for f in step_fields
            ]
            is_create_mode = not (self.instance and self.instance.pk)

            current_and_earlier_fields = []
            if hasattr(self, "step_fields") and self.step_fields:
                for step_num in range(1, self.current_step + 1):
                    if step_num in self.step_fields:
                        current_and_earlier_fields.extend(self.step_fields[step_num])

            for field_name in self.fields:
                is_mandatory_readonly = False
                if (
                    is_create_mode
                    and hasattr(self, "field_permissions")
                    and self.field_permissions
                ):
                    permission = self.field_permissions.get(field_name, "readwrite")
                    if permission in ("readonly", "hidden"):
                        if field_name in current_fields:
                            try:
                                model_field = self._meta.model._meta.get_field(
                                    field_name
                                )
                                is_mandatory_readonly = (
                                    not model_field.null and not model_field.blank
                                )
                            except Exception:
                                is_mandatory_readonly = getattr(
                                    self.fields[field_name],
                                    "_original_required",
                                    self.fields[field_name].required,
                                )

                # If field is not in any step, but it's mandatory readonly/hidden in create mode, keep it visible
                if field_name not in all_step_fields:
                    if not is_mandatory_readonly:
                        self.fields[field_name].required = False
                        self._hide_field(field_name)
                        self._step_hidden_fields.add(field_name)
                    continue

                # If field is not in current step
                if field_name not in current_fields:
                    if not is_mandatory_readonly:
                        self.fields[field_name].required = False
                        self._hide_field(field_name)
                        self._step_hidden_fields.add(field_name)
                else:
                    try:
                        original_field = self._meta.model._meta.get_field(field_name)
                        if isinstance(original_field, models.BooleanField):
                            self.fields[field_name].required = False
                        elif hasattr(original_field, "blank"):
                            if isinstance(
                                original_field, (models.FileField, models.ImageField)
                            ):
                                # Check if we have existing file, new file, or stored file
                                has_existing_file = (
                                    self.instance
                                    and self.instance.pk
                                    and getattr(self.instance, field_name, None)
                                )
                                has_new_file = field_name in self.stored_files
                                has_stored_filename = (
                                    f"{field_name}_filename" in self.form_data
                                )

                                # Only make not required if we actually have a file AND field allows blank
                                if (
                                    has_existing_file
                                    or has_new_file
                                    or has_stored_filename
                                ) and original_field.blank:
                                    self.fields[field_name].required = False
                                else:
                                    # Keep original required setting
                                    self.fields[field_name].required = (
                                        not original_field.blank
                                    )
                            else:
                                self.fields[field_name].required = (
                                    not original_field.blank
                                )
                    except models.FieldDoesNotExist:
                        pass

        if self.field_permissions:
            # Check if we're in create mode
            is_create_mode = not (self.instance and self.instance.pk)

            # Get current step fields to ensure we apply readonly to fields in current step
            current_fields = []
            if hasattr(self, "step_fields") and self.current_step in self.step_fields:
                current_fields = self.step_fields.get(self.current_step, [])

            for field_name, field in self.fields.items():
                if isinstance(field.widget, forms.HiddenInput):
                    # Only skip if it's truly hidden (not in current step)
                    if field_name not in current_fields:
                        continue
                permission = self.field_permissions.get(field_name, "readwrite")

                if permission == "readonly":
                    # Check if we should skip making it readonly in create mode for mandatory fields
                    is_mandatory = False
                    try:
                        model_field = self._meta.model._meta.get_field(field_name)
                        is_mandatory = not model_field.null and not model_field.blank
                    except Exception:
                        is_mandatory = field.required

                    # In create mode, if field is mandatory, don't make it readonly
                    if is_create_mode and is_mandatory:
                        continue  # Skip making it readonly - user needs to fill it

                    # Apply readonly/disabled based on field type
                    try:
                        model_field = self._meta.model._meta.get_field(field_name)
                    except Exception:
                        model_field = None

                    # Check if it's a select field (ForeignKey, ManyToMany, or ChoiceField)
                    is_select_field = (
                        isinstance(field.widget, (forms.Select, forms.SelectMultiple))
                        or (
                            model_field
                            and isinstance(
                                model_field, (models.ForeignKey, models.ManyToManyField)
                            )
                        )
                        or (
                            model_field
                            and hasattr(model_field, "choices")
                            and model_field.choices
                        )
                    )

                    if is_select_field:
                        # For select fields, use disabled
                        field.disabled = True
                        if not hasattr(field.widget, "attrs"):
                            field.widget.attrs = {}
                        field.widget.attrs["disabled"] = "disabled"
                        field.widget.attrs["data-disabled"] = "true"
                        # Add styling - preserve existing classes
                        existing_class = field.widget.attrs.get("class", "")
                        if "bg-gray-100" not in existing_class:
                            field.widget.attrs["class"] = (
                                f"{existing_class} bg-gray-100 cursor-not-allowed opacity-60".strip()
                            )
                    else:
                        # For text fields, use readonly
                        if not hasattr(field.widget, "attrs"):
                            field.widget.attrs = {}
                        field.widget.attrs["readonly"] = "readonly"
                        field.widget.attrs["data-readonly"] = "true"
                        field.disabled = False
                        # Add styling - preserve existing classes
                        existing_class = field.widget.attrs.get("class", "")
                        if "bg-gray-200" not in existing_class:
                            field.widget.attrs["class"] = (
                                f"{existing_class} bg-gray-200 border-gray-300 cursor-not-allowed opacity-75".strip()
                            )
                        field.widget.attrs["tabindex"] = "-1"

    def _hide_field(self, field_name):
        """Hide a field for steps where it isn't shown.

        Plain fields get a simple HiddenInput. MultiValueField-based fields
        (e.g. PhoneField) must keep their MultiWidget structure — swapping
        the whole widget for a bare HiddenInput breaks MultiValueField.clean(),
        which requires value_from_datadict() to return a list of sub-values,
        not a single flattened string. Instead, each sub-widget is replaced
        with a HiddenInput so the field still round-trips as a list.
        """
        field = self.fields[field_name]
        widget = field.widget
        if isinstance(widget, forms.MultiWidget):
            widget.widgets = [forms.HiddenInput() for _ in widget.widgets]
        else:
            field.widget = forms.HiddenInput()

    def _is_hidden_widget(self, widget):
        """Check if a widget (plain or MultiWidget) is fully hidden."""
        if isinstance(widget, forms.MultiWidget):
            return all(isinstance(w, forms.HiddenInput) for w in widget.widgets)
        return isinstance(widget, forms.HiddenInput)

    def _reassert_hidden_fields(self):
        """Re-hide fields whose widget was rebuilt visible after the initial hiding pass.

        Subclasses commonly rebuild a field (e.g. ``self.fields["state"] =
        forms.ChoiceField(...)``) in their own ``__init__`` *after* calling
        ``super().__init__()`` — which undoes the hiding this class already
        applied for steps where that field doesn't belong. Re-checking here,
        at access time, makes hiding stick regardless of what subclasses do
        to their fields afterward, without every subclass needing its own
        guard.
        """
        for field_name in self._step_hidden_fields:
            field = self.fields.get(field_name)
            if field is not None and not self._is_hidden_widget(field.widget):
                self._hide_field(field_name)

    def __iter__(self):
        self._reassert_hidden_fields()
        return super().__iter__()

    def __getitem__(self, name):
        self._reassert_hidden_fields()
        return super().__getitem__(name)

    def get_fields_for_step(self, step):
        """
        Returns form fields for the given step, including mandatory readonly/hidden fields in create mode
        Only includes mandatory readonly/hidden fields that belong to the current step or earlier steps
        """
        # Get all step fields across all steps
        all_step_fields = []
        if hasattr(self, "step_fields") and self.step_fields:
            for step_fields_list in self.step_fields.values():
                all_step_fields.extend(step_fields_list)

        current_fields = []
        if hasattr(self, "step_fields") and step in self.step_fields:
            current_fields = self.step_fields.get(step, [])

        # Get fields from current and earlier steps (for mandatory readonly fields)
        current_and_earlier_fields = []
        if hasattr(self, "step_fields") and self.step_fields:
            for step_num in range(1, step + 1):
                if step_num in self.step_fields:
                    current_and_earlier_fields.extend(self.step_fields[step_num])

        fields_list = []

        # Check if we're in create mode
        _is_create_mode = not (self.instance and self.instance.pk)

        # Add fields from current step
        for field_name in current_fields:
            if field_name in self.fields:
                field = self[field_name]
                fields_list.append(field)

        if not hasattr(self, "step_fields") or not self.step_fields:
            return self.visible_fields()

        return fields_list

    def _configure_field_widgets(self):
        """Configure widgets for all form fields with pagination support"""
        for field_name, field in self.fields.items():
            widget_attrs = {
                "class": WIDGET_INPUT_CSS_CLASS,
            }

            if field_name in self.full_width_fields:
                widget_attrs["fullwidth"] = True

            # Get the model field to determine its type
            try:
                model_field = self._meta.model._meta.get_field(field_name)
            except models.FieldDoesNotExist:
                model_field = None

            if model_field:
                if isinstance(model_field, (models.ImageField, models.FileField)):
                    # Check if we have existing file or new file
                    has_existing_file = (
                        self.instance
                        and self.instance.pk
                        and getattr(self.instance, field_name, None)
                    )
                    has_new_file = field_name in self.stored_files

                    current_fields = self.step_fields.get(self.current_step, [])
                    if field_name not in current_fields:
                        # Not in current step, make not required
                        field.required = False
                    elif (has_existing_file or has_new_file) and model_field.blank:
                        # In current step but has file and field allows blank
                        field.required = False
                    else:
                        # In current step, respect original field requirements
                        field.required = not model_field.blank

                    if isinstance(model_field, models.ImageField):
                        field.widget.attrs["accept"] = "image/*"

                    field.widget.attrs["formnovalidate"] = "formnovalidate"

                    if not field.widget.attrs.get("placeholder"):
                        field_label = (
                            field.label or field_name.replace("_", " ").title()
                        )
                        widget_attrs["placeholder"] = _("Upload %(field)s") % {
                            "field": field_label
                        }

                elif isinstance(model_field, models.DateField) and not isinstance(
                    model_field, models.DateTimeField
                ):
                    attrs = self._build_date_widget_attrs()
                    field.widget = forms.DateInput(attrs=attrs, format="%Y-%m-%d")
                    field.input_formats = ["%Y-%m-%d"]

                elif isinstance(model_field, models.DateTimeField):
                    attrs = self._build_datetime_widget_attrs()
                    field.widget = forms.DateTimeInput(
                        attrs=attrs, format="%Y-%m-%dT%H:%M"
                    )
                    field.input_formats = [
                        "%Y-%m-%dT%H:%M",
                        "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%d %H:%M",
                    ]
                elif isinstance(model_field, models.TimeField):
                    if not isinstance(field.widget, forms.HiddenInput):
                        attrs = self._build_time_widget_attrs()
                        field.widget = forms.TimeInput(attrs=attrs)

                elif isinstance(model_field, models.ManyToManyField):
                    all_step_fields = []
                    if hasattr(self, "step_fields") and self.step_fields:
                        for step_fields_list in self.step_fields.values():
                            all_step_fields.extend(step_fields_list)

                    if field_name in all_step_fields:
                        self._configure_many_to_many_field(
                            field, field_name, model_field
                        )
                    else:
                        field.required = False
                        if not isinstance(field.widget, forms.HiddenInput):
                            field.widget = forms.HiddenInput()

                elif isinstance(model_field, models.ForeignKey):
                    self._configure_foreign_key_field(field, field_name, model_field)

                elif isinstance(model_field, models.TextField):
                    field.widget = forms.Textarea()
                    if not field.widget.attrs.get("placeholder"):
                        field_label = (
                            field.label or field_name.replace("_", " ").title()
                        )
                        widget_attrs["placeholder"] = _("Enter %(field)s") % {
                            "field": field_label
                        }

                elif isinstance(model_field, models.BooleanField):
                    field.widget = forms.CheckboxInput()

                else:
                    # For all other field types, use generic placeholder
                    if not field.widget.attrs.get("placeholder"):
                        field_label = (
                            field.label or field_name.replace("_", " ").title()
                        )
                        widget_attrs["placeholder"] = _("Enter %(field)s") % {
                            "field": field_label
                        }
            else:
                # If no model field found, use generic placeholder
                if not field.widget.attrs.get("placeholder"):
                    field_label = field.label or field_name.replace("_", " ").title()
                    widget_attrs["placeholder"] = _("Enter %(field)s") % {
                        "field": field_label
                    }

            # Apply widget-specific classes and attributes
            if isinstance(field.widget, forms.Select):
                widget_attrs["class"] += " js-example-basic-single headselect"
            elif isinstance(field.widget, forms.Textarea):
                widget_attrs["class"] += " w-full"
            elif isinstance(field.widget, forms.CheckboxInput):
                widget_attrs["class"] = "sr-only peer"
            elif isinstance(field.widget, (forms.DateInput, forms.DateTimeInput)):
                # Don't add placeholder to date/datetime inputs
                if "placeholder" in widget_attrs:
                    del widget_attrs["placeholder"]

            if not hasattr(field.widget, "_pagination_configured"):
                field.widget.attrs.update(widget_attrs)

        self._apply_boolean_labels()

    def _configure_many_to_many_field(self, field, field_name, model_field):
        """Configure ManyToManyField with pagination support (initial value from instance/form_data)."""
        related_model = model_field.related_model

        initial_value = []
        if self.instance and self.instance.pk:
            # Get values from instance first
            try:
                initial_value = list(
                    getattr(self.instance, field_name).values_list("pk", flat=True)
                )
                # Only override with form_data if it has actual values (not empty list)
                if field_name in self.form_data:
                    form_data_value = self.form_data[field_name]
                    if isinstance(form_data_value, list) and len(form_data_value) == 1:
                        first_item = form_data_value[0]
                        # Check if it's a string that looks like a list representation
                        if isinstance(first_item, str) and (
                            first_item.startswith("[") and first_item.endswith("]")
                        ):
                            try:
                                import ast

                                parsed_list = ast.literal_eval(first_item)
                                if isinstance(parsed_list, list) and parsed_list:
                                    initial_value = parsed_list
                                elif isinstance(parsed_list, list) and not parsed_list:
                                    # Empty list from string '[]', keep instance values
                                    pass
                                else:
                                    initial_value = [parsed_list] if parsed_list else []
                            except (ValueError, SyntaxError):
                                # Failed to parse, keep instance values
                                pass
                        elif form_data_value:
                            # Normal list with actual values
                            initial_value = form_data_value
                    elif isinstance(form_data_value, list) and form_data_value:
                        # form_data has values, use them
                        initial_value = form_data_value
                    elif form_data_value and not isinstance(form_data_value, list):
                        initial_value = [form_data_value]
                    # If form_data_value is empty list [], keep instance values
            except Exception:
                # If instance doesn't have the field or error, fall back to form_data
                if field_name in self.form_data:
                    form_data_value = self.form_data[field_name]
                    if isinstance(form_data_value, list):
                        initial_value = form_data_value
                    elif form_data_value:
                        initial_value = [form_data_value]
        elif field_name in self.form_data:
            # Creating new instance - use form_data
            form_data_value = self.form_data[field_name]
            # Handle case where form_data contains string representation of list
            if isinstance(form_data_value, list) and len(form_data_value) == 1:
                first_item = form_data_value[0]
                # Check if it's a string that looks like a list representation
                if isinstance(first_item, str) and (
                    first_item.startswith("[") and first_item.endswith("]")
                ):
                    try:
                        import ast

                        parsed_list = ast.literal_eval(first_item)
                        if isinstance(parsed_list, list):
                            initial_value = parsed_list
                        else:
                            initial_value = [parsed_list] if parsed_list else []
                    except (ValueError, SyntaxError):
                        initial_value = []
                else:
                    initial_value = form_data_value
            elif isinstance(form_data_value, list):
                initial_value = form_data_value
            elif form_data_value:
                initial_value = [form_data_value]
            else:
                initial_value = []
        elif field_name in self.initial:
            # Fall back to initial data
            initial_data = self.initial[field_name]
            if isinstance(initial_data, list):
                initial_value = []
                for item in initial_data:
                    if hasattr(item, "pk"):
                        initial_value.append(item.pk)
                    else:
                        initial_value.append(item)
            else:
                if hasattr(initial_data, "pk"):
                    initial_value = [initial_data.pk]
                else:
                    initial_value = [initial_data]

        if initial_value:
            # If initial_value is a string that looks like a list, try to parse it
            if isinstance(initial_value, str):
                try:
                    import ast

                    initial_value = ast.literal_eval(initial_value)
                except (ValueError, SyntaxError):
                    # If parsing fails, treat as comma-separated string
                    initial_value = [
                        v.strip() for v in initial_value.split(",") if v.strip()
                    ]

            # Ensure it's a list
            if not isinstance(initial_value, list):
                initial_value = [initial_value] if initial_value else []

            # Convert all values to integers and filter out invalid ones
            cleaned_value = []
            for val in initial_value:
                if val is None or val == "" or val == []:
                    continue
                try:
                    # Convert to int if it's a string or already an int
                    int_val = int(val) if val else None
                    if int_val is not None:
                        cleaned_value.append(int_val)
                except (ValueError, TypeError):
                    # Skip invalid values
                    continue

            initial_value = cleaned_value
        else:
            initial_value = []

        # Get the selected objects for initial display
        initial_choices = []
        if initial_value:
            try:
                selected_objects = related_model.objects.filter(pk__in=initial_value)
                initial_choices = [(obj.pk, str(obj)) for obj in selected_objects]
            except Exception as e:
                logger.error(
                    "Error loading initial choices for %s: %s", field_name, str(e)
                )

        object_id = self.instance.pk if self.instance and self.instance.pk else None
        attrs = self._build_select2_m2m_attrs(
            field_name, model_field, initial_value, object_id=object_id
        )
        field.widget = forms.SelectMultiple(
            choices=initial_choices,
            attrs=attrs,
        )
        field.widget._pagination_configured = True

    def _configure_foreign_key_field(self, field, field_name, model_field):
        """Configure ForeignKey field with pagination support (initial from instance/form_data)."""
        related_model = model_field.related_model

        # Get initial value properly
        initial_value = None
        if self.instance and self.instance.pk:
            related_obj = getattr(self.instance, field_name, None)
            initial_value = related_obj.pk if related_obj else None
        elif field_name in self.initial:
            initial_data = self.initial[field_name]
            if hasattr(initial_data, "pk"):
                initial_value = initial_data.pk
            else:
                initial_value = initial_data
        elif field_name in self.form_data:
            initial_value = self.form_data[field_name]

        # Get the selected object for initial display
        initial_choices = []
        if initial_value:
            try:
                selected_object = related_model.objects.get(pk=initial_value)
                initial_choices = [(selected_object.pk, str(selected_object))]
            except related_model.DoesNotExist:
                logger.warning(
                    "Initial object not found for %s: %s (object may have been deleted)",
                    field_name,
                    initial_value,
                )
                # Clear invalid value from form_data to prevent issues
                if (
                    field_name in self.form_data
                    and self.form_data[field_name] == initial_value
                ):
                    self.form_data[field_name] = None
                initial_value = None
            except Exception as e:
                logger.error(
                    "Error loading initial choice for %s: %s", field_name, str(e)
                )
                initial_value = None

        object_id = self.instance.pk if self.instance and self.instance.pk else None
        attrs = self._build_select2_fk_attrs(
            field_name, model_field, initial_value, object_id=object_id
        )
        field.widget = forms.Select(
            choices=[("", "---------")] + initial_choices,
            attrs=attrs,
        )
        field.widget._pagination_configured = True

    def clean(self):
        """Validate form and enforce readonly field permissions (restore original values)."""
        cleaned_data = super().clean()
        self._enforce_readonly_in_cleaned_data(cleaned_data)

        current_fields = self.step_fields.get(self.current_step, [])

        errors_to_remove = []
        for field_name in list(self.errors.keys()):
            if field_name not in current_fields:
                errors_to_remove.append(field_name)

        for field_name in errors_to_remove:
            if field_name in self.errors:
                del self.errors[field_name]

        # For current step fields, handle file field validation properly
        for field_name in current_fields:
            if field_name not in self.fields:
                continue

            field = self.fields[field_name]

            try:
                model_field = self._meta.model._meta.get_field(field_name)
                if isinstance(model_field, (models.FileField, models.ImageField)):
                    has_stored_file = field_name in self.stored_files
                    has_existing_file = (
                        self.instance
                        and self.instance.pk
                        and getattr(self.instance, field_name, None)
                    )
                    has_form_data_file = (
                        field_name + "_filename" in self.form_data
                        or field_name + "_new_file" in self.form_data
                    )

                    # If field is required and no file exists, ensure error is present
                    if not model_field.blank and not (
                        has_stored_file or has_existing_file or has_form_data_file
                    ):
                        # Add required error if not already present
                        if field_name not in self.errors:
                            self.add_error(field_name, _("This field is required."))
                    elif (
                        model_field.blank
                        or has_stored_file
                        or has_existing_file
                        or has_form_data_file
                    ):
                        # Remove error if field allows blank or has file
                        if field_name in self.errors:
                            # Only remove required errors, keep format/other validation errors
                            error_messages = self.errors[field_name].as_data()
                            non_required_errors = [
                                error
                                for error in error_messages
                                if error.code != "required"
                            ]
                            if non_required_errors:
                                # Keep non-required errors
                                self.errors[field_name] = ValidationError(
                                    non_required_errors
                                )
                            else:
                                # Remove all errors if only required errors
                                del self.errors[field_name]
            except models.FieldDoesNotExist:
                pass

            value = cleaned_data.get(field_name)
            if not value:
                continue

            try:
                model_field = self._meta.model._meta.get_field(field_name)
            except Exception:
                continue

            if isinstance(field, forms.ModelChoiceField) and isinstance(
                model_field, models.ForeignKey
            ):
                fresh_queryset = self._get_fresh_queryset(
                    field_name, model_field.related_model
                )
                if (
                    fresh_queryset is not None
                    and not fresh_queryset.filter(pk=value.pk).exists()
                ):
                    self.add_error(
                        field_name,
                        _(
                            "Invalid selection. You don't have permission to select this option."
                        ),
                    )

            elif isinstance(field, forms.ModelMultipleChoiceField) and isinstance(
                model_field, models.ManyToManyField
            ):
                fresh_queryset = self._get_fresh_queryset(
                    field_name, model_field.related_model
                )
                if fresh_queryset is not None:
                    submitted_pks = {obj.pk for obj in value}
                    valid_pks = set(fresh_queryset.values_list("pk", flat=True))
                    if not submitted_pks.issubset(valid_pks):
                        self.add_error(
                            field_name,
                            _(
                                "Invalid selection. You don't have permission to select some options."
                            ),
                        )

        return cleaned_data

    def _get_fresh_queryset(self, field_name, related_model):
        """
        Get a FRESH filtered queryset by re-applying owner filtration logic.
        """
        if field_name in getattr(self, "_unrestricted_fields", set()):
            return related_model.objects.all()

        if not self.request or not self.request.user:
            return None

        try:
            user = self.request.user

            queryset = related_model.objects.all()

            if related_model is User:
                form_model = self._meta.model
                app_label = form_model._meta.app_label
                model_name = form_model._meta.model_name

                instance = getattr(self, "instance", None)
                is_edit = instance and hasattr(instance, "pk") and instance.pk
                if is_edit:
                    action_perm = f"{app_label}.change_{model_name}"
                    action_own_perm = f"{app_label}.change_own_{model_name}"
                else:
                    action_perm = f"{app_label}.add_{model_name}"
                    action_own_perm = f"{app_label}.add_own_{model_name}"

                if user.is_superuser or user.has_perm(action_perm):
                    pass  # full permission on the parent model — any user is a valid owner
                elif user.has_perm(action_own_perm):
                    allowed_user_ids = self._get_allowed_user_ids(user)
                    queryset = queryset.filter(id__in=allowed_user_ids)
                else:
                    queryset = queryset.filter(id=user.id)
            elif hasattr(related_model, "OWNER_FIELDS") and related_model.OWNER_FIELDS:
                app_label = related_model._meta.app_label
                model_name = related_model._meta.model_name
                # If user has the global view permission, they can select any record
                if user.is_superuser or user.has_perm(f"{app_label}.view_{model_name}"):
                    pass  # return unfiltered queryset
                elif user.has_perm(f"{app_label}.view_own_{model_name}"):
                    allowed_user_ids = self._get_allowed_user_ids(user)
                    if allowed_user_ids:
                        query = Q()
                        for owner_field in related_model.OWNER_FIELDS:
                            query |= Q(**{f"{owner_field}__id__in": allowed_user_ids})
                        queryset = queryset.filter(query)
                    else:
                        queryset = queryset.none()
                else:
                    # User has no view permission for this related model at all —
                    # skip ownership validation and let FK field required check handle it
                    return None

            return queryset

        except Exception as e:
            logger.error("Error getting fresh queryset for %s: %s", field_name, str(e))
            return related_model.objects.all()

    def _get_allowed_user_ids(self, user):
        """Get list of allowed user IDs (self + subordinates)"""
        from horilla.contrib.core.utils import get_allowed_user_ids

        if not user or not user.is_authenticated:
            return []

        if user.is_superuser:
            return list(User.objects.values_list("id", flat=True))

        return list(get_allowed_user_ids(user))
