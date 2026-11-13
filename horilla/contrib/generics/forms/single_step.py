"""
Single-step form classes for horilla.contrib.generics.

Provides HorillaModelForm and related base classes for standard (single-page)
model forms with field configuration, permissions, condition fields, and HTMX support.
"""

# Standard library imports
import logging

# Third-party imports (Django)
from django import forms
from django.templatetags.static import static

from horilla.auth.models import User

# First party imports (Horilla)
from horilla.db import models
from horilla.db.models import Q
from horilla.utils.translation import gettext_lazy as _

# Local imports
from . import condition_fields as condition_fields_module
from .form_class_mixin import WIDGET_INPUT_CSS_CLASS, HorillaFormMixin

logger = logging.getLogger(__name__)


class HorillaModelForm(HorillaFormMixin, forms.ModelForm):
    """Base model form class with enhanced field configuration and validation.

    Subclasses automatically inherit ``HORILLA_FORM_EXCLUDE`` on their
    ``Meta.exclude``.  Two escape hatches are available on ``Meta``:

    * ``keep_on_form`` — iterable of field names that should be removed from
      the base exclude list (i.e. shown on this form).
    * ``exclude`` — any extra fields listed here are *added* to the merged
      list; the base core fields are still excluded unless listed in
      ``keep_on_form``.

    Examples::

        class MyForm(HorillaModelForm):
            class Meta:
                model = MyModel
                fields = "__all__"
                # core fields excluded automatically — nothing extra needed

        class AdminForm(HorillaModelForm):
            class Meta:
                model = MyModel
                fields = "__all__"
                keep_on_form = ("company",)   # show company, still hide rest

        class RestrictedForm(HorillaModelForm):
            class Meta:
                model = MyModel
                fields = "__all__"
                exclude = ("internal_notes",)  # hides internal_notes + core fields
    """

    fieldsets = ()

    def get_fieldsets(self):
        """
        Return fieldsets as dicts with bound fields for template rendering.

        Only fields present on the form instance are included, so extension
        apps can inject fields via ``fieldsets_insert`` without editing HTML.
        When ``fieldsets`` is empty, all visible form fields are returned in
        a single untitled group.
        """
        fieldsets = getattr(self, "fieldsets", None) or ()
        if not fieldsets:
            bound_fields = [
                self[name]
                for name, field in self.fields.items()
                if not isinstance(field.widget, forms.HiddenInput)
            ]
            return (
                [{"name": "", "fields": bound_fields, "description": None}]
                if bound_fields
                else []
            )

        result = []
        for name, options in fieldsets:
            bound_fields = [
                self[field_name]
                for field_name in options.get("fields", ())
                if field_name in self.fields
            ]
            if bound_fields:
                result.append(
                    {
                        "name": name,
                        "fields": bound_fields,
                        "description": options.get("description"),
                    }
                )
        return result

    def __init__(self, *args, **kwargs):
        self._pop_form_options(kwargs)
        super().__init__(*args, **kwargs)
        self._setup_file_and_initial()
        self._apply_default_time_zone()
        if self.condition_fields:
            if self.condition_model:
                condition_fields_module.add_condition_fields(self)
                if (
                    hasattr(self, "instance_obj")
                    and self.instance_obj
                    and self.instance_obj.pk
                ):
                    condition_fields_module.set_initial_condition_values(self)
            else:
                condition_fields_module.add_condition_fields(self)

        condition_fields_module.add_generic_htmx_to_field(self)
        self._apply_phone_fields()

        for field_name, field in self.fields.items():
            if getattr(field, "is_custom_field", False):
                continue
            # Condition fields are already fully built by add_condition_fields
            # (including any company/permission-scoped choices); skip the
            # generic widget rebuild below so it doesn't overwrite them with
            # an unfiltered queryset.
            if self.condition_fields and field_name in self.condition_fields:
                continue
            if field_name in self.hidden_fields or isinstance(
                field.widget, forms.HiddenInput
            ):
                field.widget = forms.HiddenInput()
                field.widget.attrs.update({"class": "hidden-input"})
                continue

            existing_attrs = getattr(field.widget, "attrs", {}).copy()

            is_readonly = False
            if hasattr(self, "field_permissions") and self.field_permissions:
                permission = self.field_permissions.get(field_name, "readwrite")
                is_readonly = permission == "readonly"

            if not is_readonly:
                is_readonly = (
                    existing_attrs.get("readonly") == "readonly"
                    or existing_attrs.get("readOnly") == "readOnly"
                )

            if is_readonly:
                is_create_mode = not (self.instance and self.instance.pk)
                is_duplicate_mode = self.duplicate_mode

                is_mandatory = False
                try:
                    model_field = self._meta.model._meta.get_field(field_name)
                    is_mandatory = not model_field.null and not model_field.blank
                except Exception:
                    is_mandatory = field.required

                if (is_create_mode or is_duplicate_mode) and is_mandatory:
                    is_readonly = (
                        False  # Don't make it readonly - user needs to fill it
                    )

            readonly_attrs = {}
            if is_readonly:
                readonly_attrs = {"readonly": "readonly"}

            is_color_input = existing_attrs.get("type") == "color"
            if not isinstance(field.widget, forms.CheckboxInput) and not is_color_input:
                existing_placeholder = existing_attrs.get("placeholder", "")
                default_placeholder = (
                    _("Enter %(field)s") % {"field": field.label}
                    if not isinstance(field.widget, forms.Select)
                    else ""
                )

                field.widget.attrs.update(
                    {
                        "class": WIDGET_INPUT_CSS_CLASS,
                        "placeholder": existing_placeholder or default_placeholder,
                    }
                )

                if is_readonly:
                    field.widget.attrs.update(readonly_attrs)
                else:
                    if "readonly" in field.widget.attrs:
                        del field.widget.attrs["readonly"]
                    if "readOnly" in field.widget.attrs:
                        del field.widget.attrs["readOnly"]

            try:
                model_field = None
                model = self._meta.model
                try:
                    model_field = model._meta.get_field(field_name)
                except Exception:
                    if self.condition_model and field_name in self.condition_fields:
                        try:
                            model_field = self.condition_model._meta.get_field(
                                field_name
                            )
                        except Exception:
                            pass

                if model_field:
                    if isinstance(
                        model_field,
                        (models.DateTimeField, models.DateField, models.TimeField),
                    ):
                        if not isinstance(field.widget, forms.HiddenInput):
                            self._apply_datetime_like_widget(
                                field, field_name, model_field, existing_attrs
                            )

                    elif isinstance(model_field, models.ManyToManyField):
                        if not isinstance(field.widget, forms.HiddenInput):
                            related_model = model_field.related_model
                            initial_value = []
                            if self.instance and self.instance.pk:
                                initial_value = list(
                                    getattr(self.instance, field_name).values_list(
                                        "pk", flat=True
                                    )
                                )
                            elif field_name in self.initial:
                                initial_data = self.initial[field_name]
                                if isinstance(initial_data, list):
                                    initial_value = [
                                        item.pk if hasattr(item, "pk") else item
                                        for item in initial_data
                                    ]
                                else:
                                    initial_value = [
                                        (
                                            initial_data.pk
                                            if hasattr(initial_data, "pk")
                                            else initial_data
                                        )
                                    ]
                            submitted_values = (
                                self.data.getlist(field_name, [])
                                if field_name in self.data
                                else []
                            )
                            submitted_values = [v for v in submitted_values if v]
                            all_values = list(
                                set(v for v in (initial_value + submitted_values) if v)
                            )
                            initial_choices = []
                            if all_values:
                                selected_objects = related_model.objects.filter(
                                    pk__in=all_values
                                )
                                initial_choices = [
                                    (obj.pk, str(obj)) for obj in selected_objects
                                ]
                            display_value = submitted_values or initial_value
                            object_id = (
                                self.instance.pk
                                if self.instance and self.instance.pk
                                else None
                            )
                            widget_attrs = self._build_select2_m2m_attrs(
                                field_name,
                                model_field,
                                display_value,
                                object_id=object_id,
                                existing_attrs=existing_attrs,
                            )
                            if self._should_disable_select_for_permission(
                                field_name, model_field
                            ):
                                self._apply_readonly_to_select_attrs(widget_attrs)
                                field.disabled = True
                            field.widget = forms.SelectMultiple(
                                choices=initial_choices, attrs=widget_attrs
                            )

                    elif isinstance(model_field, models.ForeignKey):
                        if not isinstance(field.widget, forms.HiddenInput):
                            related_model = model_field.related_model
                            initial_value = None
                            if self.instance and self.instance.pk:
                                related_obj = getattr(self.instance, field_name, None)
                                initial_value = related_obj.pk if related_obj else None
                            elif field_name in self.initial:
                                initial_data = self.initial[field_name]
                                initial_value = (
                                    initial_data.pk
                                    if hasattr(initial_data, "pk")
                                    else initial_data
                                )
                            submitted_value = (
                                self.data.get(field_name)
                                if field_name in self.data
                                else None
                            )
                            all_values = [
                                v for v in [initial_value, submitted_value] if v
                            ]
                            initial_choices = []
                            try:
                                base_queryset = getattr(field, "queryset", None)
                                if base_queryset is None:
                                    base_queryset = related_model.objects.all()
                                    base_queryset = self._scope_fk_queryset_to_company(
                                        base_queryset, related_model
                                    )
                                excluded_hook = getattr(
                                    self.instance, "get_select2_excluded_pks", None
                                )
                                if excluded_hook and self.instance.pk:
                                    base_queryset = base_queryset.exclude(
                                        pk__in=excluded_hook(field_name)
                                    )
                                queryset = base_queryset[:100]
                                initial_choices = [
                                    (obj.pk, str(obj)) for obj in queryset
                                ]
                                if all_values:
                                    selected_objects = base_queryset.filter(
                                        pk__in=all_values
                                    )
                                    initial_choices = [
                                        (obj.pk, str(obj)) for obj in selected_objects
                                    ] + [
                                        (obj.pk, str(obj))
                                        for obj in queryset
                                        if obj.pk not in all_values
                                    ]
                            except Exception as e:
                                logger.error(
                                    "Error fetching choices for %s: %s",
                                    field_name,
                                    str(e),
                                )
                            display_value = submitted_value or initial_value
                            object_id = (
                                self.instance.pk
                                if self.instance and self.instance.pk
                                else None
                            )
                            widget_attrs = self._build_select2_fk_attrs(
                                field_name,
                                model_field,
                                display_value,
                                object_id=object_id,
                                existing_attrs=existing_attrs,
                            )
                            if self._should_disable_select_for_permission(
                                field_name, model_field
                            ):
                                self._apply_readonly_to_select_attrs(widget_attrs)
                                field.disabled = True
                            field.widget = forms.Select(
                                choices=[("", "---------")] + initial_choices,
                                attrs=widget_attrs,
                            )

                    elif isinstance(field.widget, forms.Select):
                        field.widget.attrs.update(
                            {"class": "js-example-basic-single headselect"}
                        )
                        if model_field and self._should_disable_select_for_permission(
                            field_name, model_field
                        ):
                            self._apply_readonly_to_select_attrs(field.widget.attrs)
                            field.disabled = True

            except Exception as e:
                logger.error("Error processing field %s: %s", field_name, str(e))

            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({"class": "sr-only peer"})
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs.update(
                    {
                        "rows": 4,
                        "placeholder": _("Enter %(field)s here...")
                        % {"field": field.label},
                    }
                )

        self._apply_boolean_labels()

        skip_for_permission = tuple(
            set((self.condition_fields or []) + (self.hidden_fields or []))
        )
        self._remove_fields_by_permission(
            skip_field_names=skip_for_permission,
            duplicate_mode=self.duplicate_mode,
        )

    def _pop_form_options(self, kwargs):
        """Pop form options from kwargs and set on self; resolve model_name and condition_field_choices."""
        self.full_width_fields = kwargs.pop("full_width_fields", [])
        self.dynamic_create_fields = kwargs.pop("dynamic_create_fields", [])
        self.hidden_fields = kwargs.pop("hidden_fields", [])
        self.condition_fields = kwargs.pop("condition_fields", [])
        self.condition_model = kwargs.pop("condition_model", None)
        self.condition_related_name = kwargs.pop("condition_related_name", None)
        self.condition_related_name_candidates = kwargs.pop(
            "condition_related_name_candidates", None
        )
        self.condition_hx_include = kwargs.pop("condition_hx_include", "")
        self.request = kwargs.pop("request", None)
        self.field_permissions = kwargs.pop("field_permissions", {})
        self.save_and_new = kwargs.pop("save_and_new", "")
        self.duplicate_mode = kwargs.pop("duplicate_mode", False)
        self.row_id = kwargs.pop("row_id", "0")
        self.instance_obj = kwargs.get("instance")
        self.model_name = kwargs.pop("model_name", None)
        if not self.model_name:
            self.model_name = (
                condition_fields_module.get_model_name_from_request_or_instance(
                    self, kwargs
                )
            )
        condition_field_choices = kwargs.pop("condition_field_choices", None)
        if (
            not condition_field_choices
            and self.condition_model
            and self.condition_fields
        ):
            condition_field_choices = (
                condition_fields_module.build_condition_field_choices(
                    self, self.model_name
                )
            )
        self.condition_field_choices = condition_field_choices or {}

    def _extract_condition_rows(self):
        """Extract condition rows from form data. Override in subclasses if needed."""
        return condition_fields_module.extract_condition_rows(self)

    def _setup_file_and_initial(self):
        """Set initial and widget attrs for file/image fields (existing, cleared, uploaded)."""
        if self.instance and self.instance.pk:
            for field_name, field in self.fields.items():
                if isinstance(field, (forms.FileField, forms.ImageField)):
                    if self.data and self.data.get(f"id_{field_name}_clear") == "true":
                        self.initial[field_name] = None
                        field.widget.attrs["data_cleared"] = "true"
                    elif self.files and field_name in self.files:
                        uploaded_file = self.files[field_name]
                        field.widget.attrs["data_uploaded_filename"] = (
                            uploaded_file.name
                        )
                        field.widget.attrs["data_cleared"] = "false"
                    else:
                        existing_file = getattr(self.instance, field_name, None)
                        if existing_file:
                            self.initial[field_name] = existing_file
                            field.widget.attrs["data_existing_filename"] = (
                                existing_file.name
                            )
                            field.widget.attrs["data_cleared"] = "false"
        if self.request and self.request.method == "POST" and self.request.FILES:
            for field_name in self.request.FILES:
                if field_name in self.fields:
                    if not self.initial.get(field_name):
                        self.initial[field_name] = self.request.FILES[field_name].name
                    field = self.fields[field_name]
                    field.widget.attrs["data_uploaded_filename"] = self.request.FILES[
                        field_name
                    ].name
                    field.widget.attrs["data_cleared"] = "false"

    def _readonly_for_datetime_like_field(
        self, field_name, model_field, existing_attrs
    ):
        """Compute readonly flag for datetime/date/time fields (permission + create/duplicate mandatory)."""
        is_field_readonly = (
            hasattr(self, "field_permissions")
            and self.field_permissions.get(field_name, "readwrite") == "readonly"
        )
        if is_field_readonly:
            is_create_mode = not (self.instance and self.instance.pk)
            is_duplicate_mode = getattr(self, "duplicate_mode", False)
            is_mandatory = not model_field.null and not model_field.blank
            if (is_create_mode or is_duplicate_mode) and is_mandatory:
                is_field_readonly = False
        return is_field_readonly or existing_attrs.get("readonly") == "readonly"

    def _apply_datetime_like_widget(
        self, field, field_name, model_field, existing_attrs
    ):
        """Set widget and input_formats for DateTimeField, DateField, or TimeField."""
        readonly = self._readonly_for_datetime_like_field(
            field_name, model_field, existing_attrs
        )
        if isinstance(model_field, models.DateTimeField):
            attrs = self._build_datetime_widget_attrs(existing_attrs, readonly=readonly)
            field.widget = forms.DateTimeInput(attrs=attrs, format="%Y-%m-%dT%H:%M")
            field.input_formats = ["%Y-%m-%dT%H:%M"]
        elif isinstance(model_field, models.DateField):
            attrs = self._build_date_widget_attrs(existing_attrs, readonly=readonly)
            field.widget = forms.DateInput(attrs=attrs, format="%Y-%m-%d")
            field.input_formats = ["%Y-%m-%d"]
        else:
            time_style = (
                f'background-image: url("{static("assets/icons/clock_icon.svg")}"); '
                "background-repeat: no-repeat; background-position: right 12px center; background-size: 18px;"
            )
            attrs = self._build_time_widget_attrs(
                existing_attrs, readonly=readonly, extra_style=time_style
            )
            field.widget = forms.TimeInput(attrs=attrs)

    def clean(self):
        """Validate and normalize condition fields; strip condition data when no condition_model."""
        cleaned_data = super().clean()

        if self.condition_fields and not self.condition_model:
            for field_name in self.condition_fields:
                if field_name in cleaned_data:
                    del cleaned_data[field_name]

        for field_name, field in self.fields.items():
            if field_name not in cleaned_data:
                continue

            value = cleaned_data[field_name]
            if not value:
                continue

            if self.condition_fields and field_name in self.condition_fields:
                continue

            try:
                model = self._meta.model
                try:
                    model_field = model._meta.get_field(field_name)
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
                            "Invalid selection. You don't have permission to select this option.",
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
                                "Invalid selection. You don't have permission to select some options.",
                            )

                elif isinstance(field, forms.ChoiceField) and not isinstance(
                    field, forms.ModelChoiceField
                ):
                    if hasattr(field, "choices") and field.choices:
                        valid_choices = [choice[0] for choice in field.choices]
                        if value not in valid_choices:
                            self.add_error(
                                field_name,
                                "Invalid choice. Please select a valid option.",
                            )

            except Exception as e:
                logger.error("Error validating field %s: %s", field_name, str(e))

        self._enforce_readonly_in_cleaned_data(cleaned_data)
        condition_fields_module.clean_condition_fields(self, cleaned_data)
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

    def _scope_fk_queryset_to_company(self, queryset, related_model):
        """Narrow a plain (auto-built) FK queryset to the active company.

        Only applies when the related model is company-scoped and no
        explicit ``queryset`` was already set on the field (e.g. by
        ``OwnerQuerysetMixin`` or a custom form), so a deliberately chosen
        queryset is never second-guessed here.
        """
        try:
            related_model._meta.get_field("company")
        except Exception:
            return queryset

        instance = getattr(self, "instance", None)
        company = None
        if (
            instance
            and getattr(instance, "pk", None)
            and getattr(instance, "company", None)
        ):
            company = instance.company
        elif self.request:
            company = getattr(self.request, "active_company", None)
            if not company:
                company = getattr(self.request.user, "company", None)

        if company:
            queryset = queryset.filter(company=company)
        return queryset
