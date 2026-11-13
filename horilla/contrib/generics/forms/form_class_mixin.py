"""
Shared base and mixins for Horilla model forms.

Provides common field-permission removal, readonly enforcement, and
widget/initial configuration used by both HorillaModelForm and HorillaMultiStepForm.
"""

# Third-party imports (Django)
from django import forms

from horilla.core.exceptions import ImproperlyConfigured, ValidationError

# First party imports (Horilla)
from horilla.db import models
from horilla.urls import reverse_lazy
from horilla.utils.text import select_placeholder
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .constants import HORILLA_FORM_EXCLUDE

# Shared widget CSS classes (single-step and multi-step use the same styling)
WIDGET_INPUT_CSS_CLASS = (
    "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 "
    "rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm "
    "[transition:.3s] focus:border-primary-600"
)
WIDGET_INPUT_CSS_CLASS_NO_PR = (
    "text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 rounded-md "
    "mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] "
    "focus:border-primary-600"
)
WIDGET_TIME_CSS_CLASS = (
    "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 "
    "rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm "
    "transition duration-300 focus:border-primary-600"
)
SELECT_READONLY_CLASS_SUFFIX = " bg-gray-100 cursor-not-allowed opacity-60"


def apply_horilla_form_meta_exclude(meta) -> None:
    """
    Merge ``HORILLA_FORM_EXCLUDE`` into ``Meta.exclude``, honoring ``keep_on_form``.

    Used by ``HorillaFormMixin.__init_subclass__`` and composed form extensions
    (``new_class`` runs ``__init_subclass__`` before extension ``Meta`` is attached).
    """
    if meta is None:
        return
    keep_on_form = set(getattr(meta, "keep_on_form", ()) or ())
    child_exclude = list(getattr(meta, "exclude", None) or [])
    # Parent forms may already have core fields in exclude; re-apply from scratch.
    child_exclude = [f for f in child_exclude if f not in HORILLA_FORM_EXCLUDE]
    base_exclude = [f for f in HORILLA_FORM_EXCLUDE if f not in keep_on_form]
    merged = child_exclude + [f for f in base_exclude if f not in child_exclude]
    meta.exclude = merged


class HorillaFormMixin:
    """
    Mixin with shared logic for HorillaModelForm and HorillaMultiStepForm:
    - Auto-excluding HorillaCoreModel audit fields via __init_subclass__
    - Removing fields based on field_permissions (hidden/readonly)
    - Enforcing readonly in clean() by restoring original values and adding errors

    Meta escape hatches (on any subclass):
    * ``keep_on_form`` — fields to remove from the base exclude list (shown on form).
    * ``exclude`` — extra fields added to the merged list; core fields still excluded
      unless listed in ``keep_on_form``.

    Boolean fields render as a two-segment control. Set the segment labels per
    field on the form class as ``{field_name: (true_label, false_label)}``;
    fields not listed use Yes / No. An entry for a field that is not on the form, is not a
    boolean, or is not a (true_label, false_label) pair raises ImproperlyConfigured::

        boolean_labels = {"is_final": (_("Closed"), _("Open"))}
    """

    boolean_labels = {}

    @classmethod
    def _boolean_label_errors(cls):
        """Return a list of problems in the ``boolean_labels`` this class declares.

        Only entries written on the class itself are checked. Entries inherited
        from a parent form may name fields the subclass does not show, which is
        fine and is skipped when the labels are applied.
        """
        errors = []
        base_fields = getattr(cls, "base_fields", None)
        if base_fields is None:
            return errors
        for name, labels in (cls.__dict__.get("boolean_labels") or {}).items():
            base_field = base_fields.get(name)
            if base_field is None:
                errors.append(
                    f"{cls.__name__}.boolean_labels: '{name}' is not a field of this form."
                )
            elif not isinstance(base_field.widget, forms.CheckboxInput):
                errors.append(
                    f"{cls.__name__}.boolean_labels: '{name}' is not a boolean field."
                )
            elif not isinstance(labels, (list, tuple)) or len(labels) != 2:
                errors.append(
                    f"{cls.__name__}.boolean_labels: '{name}' needs exactly two "
                    "labels (true_label, false_label)."
                )
        return errors

    def _apply_boolean_labels(self):
        """Validate ``boolean_labels`` and copy it onto each boolean widget.

        Mistakes are also reported at startup by the system check in
        ``horilla.contrib.generics.checks``; this guards forms built at runtime.
        """
        errors = self._boolean_label_errors()
        if errors:
            raise ImproperlyConfigured(" ".join(errors))
        for name, labels in (self.boolean_labels or {}).items():
            field = self.fields.get(name)
            if field is not None and isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["data_true_label"] = labels[0]
                field.widget.attrs["data_false_label"] = labels[1]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        meta = cls.__dict__.get("Meta")
        if meta is None:
            return
        apply_horilla_form_meta_exclude(meta)

    def _remove_fields_by_permission(
        self,
        skip_field_names=(),
        duplicate_mode=False,
        skip_hidden_widget=False,
    ):
        """
        Remove form fields based on field_permissions (hidden, readonly).
        In create/duplicate mode, mandatory fields are never removed.

        Args:
            skip_field_names: Field names to never remove (e.g. condition_fields, hidden_fields).
            duplicate_mode: If True, treat like create mode for mandatory checks (HorillaModelForm).
            skip_hidden_widget: If True, skip fields that already use HiddenInput (HorillaMultiStepForm).
        """
        field_permissions = getattr(self, "field_permissions", None) or {}
        if not field_permissions:
            return

        is_create_mode = not (self.instance and self.instance.pk)
        is_duplicate_mode = getattr(self, "duplicate_mode", False) or duplicate_mode
        fields_to_remove = []

        for field_name, field in list(self.fields.items()):
            if field_name in skip_field_names:
                continue
            if skip_hidden_widget and isinstance(field.widget, forms.HiddenInput):
                continue

            permission = field_permissions.get(field_name, "readwrite")

            if permission == "hidden":
                if is_create_mode or is_duplicate_mode:
                    is_mandatory = self._is_field_mandatory(field_name, field)
                    if not is_mandatory:
                        fields_to_remove.append(field_name)
                else:
                    fields_to_remove.append(field_name)
            elif permission == "readonly" and (is_create_mode or is_duplicate_mode):
                is_mandatory = self._is_field_mandatory(field_name, field)
                if not is_mandatory:
                    fields_to_remove.append(field_name)

        for field_name in fields_to_remove:
            if field_name in self.fields:
                del self.fields[field_name]

    def _is_field_mandatory(self, field_name, field):
        """Return True if the field is required (not null and not blank on model, or field.required)."""
        try:
            model_field = self._meta.model._meta.get_field(field_name)
            return not model_field.null and not model_field.blank
        except Exception:
            return getattr(field, "_original_required", field.required)

    def _enforce_readonly_in_cleaned_data(self, cleaned_data):
        """
        Enforce readonly field permissions in edit mode: restore original values
        for readonly fields and add validation errors if the user changed them.
        Modifies cleaned_data in place and adds errors to self.
        """
        field_permissions = getattr(self, "field_permissions", None) or {}
        if not field_permissions or not (self.instance and self.instance.pk):
            return

        for field_name, permission in field_permissions.items():
            if permission != "readonly" or field_name not in self.fields:
                continue
            try:
                model_field = self._meta.model._meta.get_field(field_name)
            except Exception:
                continue

            if isinstance(model_field, models.ManyToManyField):
                original_value = list(getattr(self.instance, field_name).all())
            elif isinstance(model_field, models.ForeignKey):
                original_value = getattr(self.instance, field_name, None)
            else:
                original_value = getattr(self.instance, field_name, None)

            submitted_value = cleaned_data.get(field_name)
            value_changed = False

            if isinstance(model_field, models.ManyToManyField):
                original_pks = (
                    set(obj.pk for obj in original_value) if original_value else set()
                )
                submitted_pks = (
                    set(obj.pk for obj in submitted_value) if submitted_value else set()
                )
                value_changed = original_pks != submitted_pks
            elif isinstance(model_field, models.ForeignKey):
                original_pk = original_value.pk if original_value else None
                submitted_pk = submitted_value.pk if submitted_value else None
                value_changed = original_pk != submitted_pk
            else:
                value_changed = original_value != submitted_value

            if value_changed:
                cleaned_data[field_name] = original_value
                self.add_error(
                    field_name,
                    ValidationError(
                        _("This field is read-only and cannot be modified."),
                        code="readonly_field",
                    ),
                )
            else:
                cleaned_data[field_name] = original_value

    # Default phone field names — automatically get PhoneField widget.
    # Subclasses can extend with extra names:
    #   phone_fields = ["work_phone", "home_phone"]
    # Or disable entirely:
    #   phone_fields = []
    _DEFAULT_PHONE_FIELD_NAMES = {
        "phone",
        "mobile",
        "contact_number",
        "phone_number",
        "mobile_number",
        "secondary_phone",
        "assistant_phone",
        "secondary_contact_number",
        "assistant_contact_number",
        "fax",
        "whatsapp",
        "telephone",
        "cell",
        "cell_number",
        "alt_phone",
        "alternate_phone",
    }

    def _apply_default_time_zone(self):
        """Default a blank ``time_zone`` field to the requesting user's/company's
        configured time zone instead of the model's hardcoded "UTC" default.

        Only applies when creating a new record (no instance pk) and no explicit
        initial/submitted value is already present for the field.
        """
        field = self.fields.get("time_zone")
        if not field or (self.instance and self.instance.pk):
            return
        if self.initial.get("time_zone") or (self.data and self.data.get("time_zone")):
            return

        request = getattr(self, "request", None)
        user = getattr(request, "user", None) if request else None
        if not user or not getattr(user, "is_authenticated", False):
            return

        time_zone = getattr(user, "time_zone", None) or getattr(
            getattr(user, "company", None), "time_zone", None
        )
        if time_zone:
            self.initial["time_zone"] = time_zone

    def _apply_phone_fields(self):
        """Replace CharFields whose names are in the phone field set with PhoneField.

        Subclass override examples::

            # Add extra field names on top of defaults
            phone_fields = ["work_phone", "home_phone"]

            # Opt out entirely
            phone_fields = []
        """
        from horilla.contrib.generics.forms.generics import PhoneField

        phone_fields_attr = self.__class__.__dict__.get("phone_fields", None)
        if phone_fields_attr is None:
            # Not declared on this class — check MRO for any parent override
            phone_fields_attr = getattr(self.__class__, "phone_fields", None)

        if phone_fields_attr is None:
            active_names = self._DEFAULT_PHONE_FIELD_NAMES
        elif len(phone_fields_attr) == 0:
            return  # opted out
        else:
            active_names = self._DEFAULT_PHONE_FIELD_NAMES | set(phone_fields_attr)

        for field_name, field in list(self.fields.items()):
            if field_name not in active_names:
                continue
            if isinstance(field, PhoneField):
                continue
            if not isinstance(field, forms.CharField):
                continue
            current_value = (
                getattr(self.instance, field_name, None)
                if hasattr(self, "instance")
                and self.instance
                and getattr(self.instance, "pk", None)
                else None
            )
            phone_field = PhoneField(label=field.label, required=field.required)
            if current_value:
                phone_field.initial = current_value
            self.fields[field_name] = phone_field

    # --- Shared widget / initial helpers (each form gets initials its own way, same attrs) ---

    def _should_disable_select_for_permission(self, field_name, model_field):
        """Return True if this FK/M2M/Select should be disabled (readonly and not mandatory in create/duplicate)."""
        field_permissions = getattr(self, "field_permissions", None) or {}
        permission = field_permissions.get(field_name, "readwrite")
        if permission != "readonly":
            return False
        is_create_mode = not (self.instance and self.instance.pk)
        is_duplicate_mode = getattr(self, "duplicate_mode", False)
        try:
            is_mandatory = not model_field.null and not model_field.blank
        except Exception:
            return True
        return not ((is_create_mode or is_duplicate_mode) and is_mandatory)

    def _apply_readonly_to_select_attrs(self, attrs):
        """Mutate attrs to add disabled and readonly styling for select widgets."""
        attrs["disabled"] = "disabled"
        attrs["data-disabled"] = "true"
        existing = attrs.get("class", "")
        if SELECT_READONLY_CLASS_SUFFIX.strip() not in existing:
            attrs["class"] = f"{existing}{SELECT_READONLY_CLASS_SUFFIX}".strip()

    def _build_select2_m2m_attrs(
        self,
        field_name,
        model_field,
        initial_value,
        object_id=None,
        existing_attrs=None,
    ):
        """Build widget attrs for a ManyToManyField with select2-pagination. Caller sets initial_value source."""
        related_model = model_field.related_model
        app_label = related_model._meta.app_label
        model_name = related_model._meta.model_name
        data_initial = ",".join(map(str, initial_value)) if initial_value else ""
        attrs = {
            "class": "select2-pagination w-full text-sm",
            "data-url": reverse_lazy(
                "generics:model_select2",
                kwargs={"app_label": app_label, "model_name": model_name},
            ),
            "data-placeholder": select_placeholder(model_field.verbose_name),
            "multiple": "multiple",
            "data-initial": data_initial,
            "data-field-name": field_name,
            "id": f"id_{field_name}",
            "data-form-class": getattr(
                self.__class__,
                "__horilla_form_path__",
                f"{self.__module__}.{self.__class__.__name__}",
            ),
            **(existing_attrs or {}),
        }
        if object_id is not None:
            attrs["data-object-id"] = str(object_id)
        if self.__class__.__name__ == "DynamicForm":
            attrs["data-parent-model"] = (
                f"{self._meta.model._meta.app_label}.{self._meta.model._meta.model_name}"
            )
        return attrs

    def _build_select2_fk_attrs(
        self,
        field_name,
        model_field,
        initial_value,
        object_id=None,
        existing_attrs=None,
    ):
        """Build widget attrs for a ForeignKey with select2-pagination. Caller sets initial_value source."""
        related_model = model_field.related_model
        app_label = related_model._meta.app_label
        model_name = related_model._meta.model_name
        attrs = {
            "class": "select2-pagination w-full",
            "data-url": reverse_lazy(
                "generics:model_select2",
                kwargs={"app_label": app_label, "model_name": model_name},
            ),
            "data-placeholder": select_placeholder(model_field.verbose_name),
            "data-initial": str(initial_value) if initial_value is not None else "",
            "data-field-name": field_name,
            "id": f"id_{field_name}",
            "data-form-class": getattr(
                self.__class__,
                "__horilla_form_path__",
                f"{self.__module__}.{self.__class__.__name__}",
            ),
            **(existing_attrs or {}),
        }
        if object_id is not None:
            attrs["data-object-id"] = str(object_id)
        if self.__class__.__name__ == "DynamicForm":
            attrs["data-parent-model"] = (
                f"{self._meta.model._meta.app_label}.{self._meta.model._meta.model_name}"
            )
        return attrs

    def _build_datetime_widget_attrs(self, existing_attrs=None, readonly=False):
        """Build attrs for DateTimeInput (type=datetime-local)."""
        base = {
            "type": "datetime-local",
            "class": WIDGET_INPUT_CSS_CLASS_NO_PR,
            **(existing_attrs or {}),
        }
        if readonly:
            base["readonly"] = "readonly"
        return base

    def _build_date_widget_attrs(self, existing_attrs=None, readonly=False):
        """Build attrs for DateInput (type=date)."""
        base = {
            "type": "date",
            "class": WIDGET_INPUT_CSS_CLASS_NO_PR,
            **(existing_attrs or {}),
        }
        if readonly:
            base["readonly"] = "readonly"
        return base

    def _build_time_widget_attrs(
        self, existing_attrs=None, readonly=False, extra_style=None
    ):
        """Build attrs for TimeInput (type=time). extra_style for e.g. clock icon (single-step)."""
        base = {
            "type": "time",
            "class": WIDGET_TIME_CSS_CLASS,
            **(existing_attrs or {}),
        }
        if extra_style:
            base["style"] = extra_style
        if readonly:
            base["readonly"] = "readonly"
        return base
