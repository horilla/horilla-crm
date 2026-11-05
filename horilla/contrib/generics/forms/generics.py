"""
Forms for horilla.contrib.generics.

Contains form classes and helpers used across the horilla.contrib.generics app.
"""

# Standard library imports
import logging
import re
from datetime import timedelta

# Django imports
# Third-party imports (Django)
from django import forms
from django.core.exceptions import ValidationError
from django.db.models.fields import Field
from django.utils.encoding import force_str

from horilla.contrib.core.models import (
    HorillaAttachment,
    KanbanGroupBy,
    ListColumnVisibility,
    TimelineSpanBy,
)
from horilla.contrib.generics.forms.rich_text import HorillaSummernoteWidget
from horilla.contrib.utils.middlewares import _thread_local

# Horilla application imports
# First party imports (Horilla)
from horilla.utils.html import format_html
from horilla.utils.text import enter_placeholder
from horilla.utils.translation import gettext_lazy as _

# Third-party imports


logger = logging.getLogger(__name__)


# Define your horilla.contrib.generics forms here
class KanbanGroupByForm(forms.ModelForm):
    """Form for configuring group-by settings for Kanban or Group By view."""

    class Meta:
        """Meta options for KanbanGroupByForm."""

        model = KanbanGroupBy
        fields = ["model_name", "field_name", "app_label", "view_type"]
        widgets = {
            "model_name": forms.HiddenInput(),
            "app_label": forms.HiddenInput(),
            "view_type": forms.HiddenInput(),
            "field_name": forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        self.request = getattr(_thread_local, "request")
        exclude_fields = kwargs.pop("exclude_fields", [])
        include_fields = kwargs.pop("include_fields", [])
        super().__init__(*args, **kwargs)

        # Try to resolve model/app from data, then initial, then instance
        model_name = (
            self.data.get("model_name")
            or self.initial.get("model_name")
            or getattr(self.instance, "model_name", None)
        )
        app_label = (
            self.data.get("app_label")
            or self.initial.get("app_label")
            or getattr(self.instance, "app_label", None)
        )

        if model_name and app_label:
            temp_instance = KanbanGroupBy(model_name=model_name, app_label=app_label)
            user = getattr(self.request, "user", None) if self.request else None
            self.fields["field_name"].choices = temp_instance.get_model_groupby_fields(
                exclude_fields=exclude_fields,
                include_fields=include_fields,
                user=user,
            )
        else:
            self.fields["field_name"].choices = []

        view_type = (
            self.data.get("view_type")
            or self.initial.get("view_type")
            or getattr(self.instance, "view_type", "kanban")
        )
        self.fields["view_type"].initial = view_type

    def clean(self):
        """Validate group-by field and add field_name errors if invalid."""
        cleaned_data = super().clean()
        model_name = cleaned_data.get("model_name")
        app_label = cleaned_data.get("app_label")
        field_name = cleaned_data.get("field_name")

        # Only validate if field_name is filled
        view_type = cleaned_data.get("view_type") or "kanban"
        if model_name and field_name:
            temp_instance = KanbanGroupBy(
                model_name=model_name,
                field_name=field_name,
                app_label=app_label,
                view_type=view_type,
                user=self.request.user,
            )
            try:
                temp_instance.clean()
            except Exception as e:
                self.add_error("field_name", e)

        return cleaned_data


class TimelineSpanByForm(forms.ModelForm):
    """Form for persisted timeline start/end date fields (per user + model)."""

    main_url = forms.CharField(required=False, widget=forms.HiddenInput())
    preserve_qs = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        """Meta class for time line model"""

        model = TimelineSpanBy
        fields = ["model_name", "app_label", "start_field", "end_field"]
        widgets = {
            "model_name": forms.HiddenInput(),
            "app_label": forms.HiddenInput(),
            "start_field": forms.Select(),
            "end_field": forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        self.request = getattr(_thread_local, "request", None)
        super().__init__(*args, **kwargs)

        model_name = (
            self.data.get("model_name")
            or self.initial.get("model_name")
            or getattr(self.instance, "model_name", None)
        )
        app_label = (
            self.data.get("app_label")
            or self.initial.get("app_label")
            or getattr(self.instance, "app_label", None)
        )

        if model_name and app_label:
            temp = TimelineSpanBy(model_name=model_name, app_label=app_label)
            user = getattr(self.request, "user", None) if self.request else None
            choices = temp.get_model_date_fields(user=user)
            if not choices:
                choices = [("", "---------")]
            self.fields["start_field"].choices = choices
            self.fields["end_field"].choices = choices
        else:
            self.fields["start_field"].choices = [("", "---------")]
            self.fields["end_field"].choices = [("", "---------")]

    def clean(self):
        """Validate timeline start/end fields via TimelineSpanBy model clean."""
        cleaned = super().clean()
        model_name = cleaned.get("model_name")
        app_label = cleaned.get("app_label")
        start_field = cleaned.get("start_field")
        end_field = cleaned.get("end_field")
        if model_name and app_label and self.request and start_field and end_field:
            temp = TimelineSpanBy(
                model_name=model_name,
                app_label=app_label,
                start_field=start_field,
                end_field=end_field,
                user=self.request.user,
            )
            try:
                temp.clean()
            except Exception as e:
                self.add_error("start_field", e)
        return cleaned


class ColumnSelectionForm(forms.Form):
    """Form for selecting visible columns in list views."""

    visible_fields = forms.MultipleChoiceField(
        required=False, widget=forms.MultipleHiddenInput
    )

    def __init__(self, *args, **kwargs):
        """Initialize form with model and app_label; populate visible_fields choices."""
        model = kwargs.pop("model", None)
        app_label = kwargs.pop("app_label", None)
        path_context = kwargs.pop("path_context", None)
        user = kwargs.pop("user", None)
        model_name = kwargs.pop("model_name", None)
        _url_name = kwargs.pop("url_name", None)
        super().__init__(*args, **kwargs)

        if model:
            excluded_fields = ["history"]
            # Get model fields and methods as [verbose_name, field_name]
            instance = model()
            model_fields = [
                [
                    force_str(f.verbose_name or f.name.title()),
                    (
                        f.name
                        if not getattr(f, "choices", None)
                        else f"get_{f.name}_display"
                    ),
                ]
                for f in model._meta.get_fields()
                if isinstance(f, Field) and f.name not in excluded_fields
            ]

            # Use columns property if available, otherwise use model_fields
            all_fields = (
                getattr(instance, "columns", model_fields)
                if hasattr(instance, "columns")
                else model_fields
            )
            field_name_to_verbose = {f[1]: f[0] for f in all_fields}
            unique_field_names = {f[1] for f in all_fields}

            visible_field_lists = []
            removed_custom_field_lists = []
            if app_label and model_name and path_context and user:
                visibility = ListColumnVisibility.all_objects.filter(
                    user=user,
                    app_label=app_label,
                    model_name=model_name,
                    context=path_context,
                ).first()
                if visibility:
                    visible_field_lists = visibility.visible_fields
                    removed_custom_field_lists = visibility.removed_custom_fields

            choices = [(f[1], f[0]) for f in all_fields]

            for visible_field in visible_field_lists:
                if (
                    len(visible_field) >= 2
                    and visible_field[1] not in unique_field_names
                ):
                    choices.append((visible_field[1], visible_field[0]))
                    unique_field_names.add(visible_field[1])
                    field_name_to_verbose[visible_field[1]] = visible_field[0]

            for custom_field in removed_custom_field_lists:
                if len(custom_field) >= 2 and custom_field[1] not in unique_field_names:
                    choices.append((custom_field[1], custom_field[0]))
                    unique_field_names.add(custom_field[1])
                    field_name_to_verbose[custom_field[1]] = custom_field[0]

            choices.sort(key=lambda x: x[1].lower())
            self.fields["visible_fields"].choices = choices

            form_data = getattr(self, "data", None)
            if form_data:
                field_names = (
                    form_data.getlist("visible_fields")
                    if hasattr(form_data, "getlist")
                    else form_data.get("visible_fields", [])
                )
                if not isinstance(field_names, list):
                    field_names = [field_names] if field_names else []
                valid_field_names = [f for f in field_names if f in unique_field_names]
                if valid_field_names:
                    form_data = form_data.copy() if hasattr(form_data, "copy") else {}
                    if hasattr(form_data, "setlist"):
                        form_data.setlist("visible_fields", valid_field_names)
                    else:
                        form_data["visible_fields"] = valid_field_names
                    self.data = form_data


class SaveFilterListForm(forms.Form):
    """Form for saving filter configurations as reusable filter lists."""

    list_name = forms.CharField(
        max_length=100,
        required=True,
        label=_("List View Name"),
        widget=forms.TextInput(
            attrs={
                "class": "text-color-600 p-2 placeholder:text-xs  w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                "placeholder": _("Specify the list view name"),
            }
        ),
    )
    model_name = forms.CharField(
        max_length=100, required=True, widget=forms.HiddenInput()
    )
    main_url = forms.CharField(required=False, widget=forms.HiddenInput())
    saved_list_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    make_public = forms.BooleanField(
        required=False,
        initial=False,
        label=_("Make as public"),
        widget=forms.CheckboxInput(
            attrs={
                "class": "w-4 h-4 bg-[#E9EDF7] rounded-sm accent-[#e54f38]",
            }
        ),
    )

    def clean(self):
        """Validate list name is non-empty."""
        cleaned_data = super().clean()
        list_name = cleaned_data.get("list_name")
        if not list_name or not list_name.strip():
            self.add_error("list_name", _("List name cannot be empty."))
        return cleaned_data


class PasswordInputWithEye(forms.PasswordInput):
    """Password input widget with eye icon toggle for showing/hiding password."""

    def __init__(self, attrs=None):
        """Initialize widget with default styling and optional extra attrs."""
        default_attrs = {
            "class": "text-color-600 p-2 placeholder:text-xs font-normal w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm transition duration-300 focus:border-primary-600 pr-10",
        }
        if attrs:
            default_attrs.update(attrs)
        super().__init__(attrs=default_attrs)

    def render(self, name, value, attrs=None, renderer=None):
        """Render password input with eye toggle button markup."""
        password_input = super().render(name, value, attrs, renderer)

        return format_html(
            """
            <div class="relative">
                {}
                <button type="button" class="absolute inset-y-0 end-0 pe-3 flex items-center"
                        onclick="togglePassword(this)">
                    <img src="/static/assets/icons/eye-hide.svg"
                        alt="Toggle Password"
                        class="w-4 h-4 text-gray-400 hover:text-gray-600 cursor-pointer" />
                </button>
            </div>
            <script>
            function togglePassword(btn) {{
                const container = btn.closest('.relative');
                const passwordField = container.querySelector('input');
                const eyeIcon = btn.querySelector('img');
                if (passwordField.type === 'password') {{
                    passwordField.type = 'text';
                    eyeIcon.src = '/static/assets/icons/eye.svg';
                }} else {{
                    passwordField.type = 'password';
                    eyeIcon.src = '/static/assets/icons/eye-hide.svg';
                }}
            }}
            </script>
            """,
            password_input,
        )


class HorillaHistoryForm(forms.Form):
    """Base form for filtering history by a date range (same options as the dashboard)."""

    # "Last N days" presets offered in the history date-range dropdown.
    DATE_RANGE_CHOICES = [7, 30, 60, 90]

    date_range = forms.CharField(required=False)
    date_from = forms.DateField(required=False)
    date_to = forms.DateField(required=False)

    def clean_date_range(self):
        """Accept only 'all', 'custom' or one of DATE_RANGE_CHOICES."""
        value = (self.cleaned_data.get("date_range") or "").strip()
        valid = ["", "all", "custom"] + [str(days) for days in self.DATE_RANGE_CHOICES]
        if value not in valid:
            raise forms.ValidationError(_("Invalid date range"))
        return value

    def is_filtering(self):
        """Return True when the submitted values narrow the history down."""
        if not self.is_valid():
            return False
        date_range = self.cleaned_data.get("date_range")
        if date_range == "custom":
            return bool(
                self.cleaned_data.get("date_from") or self.cleaned_data.get("date_to")
            )
        return date_range not in ("", "all")

    def apply_filter(self, history_by_date, today):
        """Apply the selected date range to a sequence of (date, entries) pairs.

        ``today`` is the current day in the timezone the history days are
        grouped in. If the form is invalid or no range is selected, the
        original sequence is returned.
        """
        if not self.is_filtering():
            return history_by_date

        date_range = self.cleaned_data["date_range"]
        if date_range == "custom":
            start = self.cleaned_data.get("date_from")
            end = self.cleaned_data.get("date_to")
        else:
            start = today - timedelta(days=int(date_range))
            end = None
        return [
            (date, entries)
            for date, entries in history_by_date
            if (start is None or date >= start) and (end is None or date <= end)
        ]


class RowFieldWidget(forms.MultiWidget):
    """Multi-widget for rendering multiple fields in a single row layout."""

    template_name = "forms/widgets/row_field_widget.html"

    def __init__(self, field_configs, attrs=None):
        widgets = []
        self.field_configs = field_configs
        for config in field_configs:
            if config["type"] == "select":
                widgets.append(
                    forms.Select(
                        attrs={
                            "class": "normal-seclect headselect",
                            "choices": config.get("choices", []),
                        }
                    )
                )
            elif config["type"] == "text":
                widgets.append(
                    forms.TextInput(
                        attrs={
                            "class": "h-[35px] text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 rounded-md focus-visible:outline-0 placeholder:text-dark-100 text-sm transition focus:border-primary-600",
                            "placeholder": config.get("placeholder", "Enter Value"),
                        }
                    )
                )
        super().__init__(widgets, attrs)

    def decompress(self, value):
        """Split a combined value into one value per subwidget."""
        if isinstance(value, (list, tuple)):
            return list(value)
        return [None] * len(self.widgets)

    def get_context(self, name, value, attrs):
        """Add field_configs to the widget template context."""
        context = super().get_context(name, value, attrs)
        context["field_configs"] = self.field_configs
        return context


class RowField(forms.MultiValueField):
    """Multi-value field for handling multiple related fields in a row layout."""

    widget = RowFieldWidget

    def __init__(self, field_configs, *args, **kwargs):
        fields = []
        self.field_configs = field_configs
        for config in field_configs:
            if config["type"] == "select":
                fields.append(
                    forms.ChoiceField(
                        choices=config.get("choices", []),
                        required=config.get("required", True),
                    )
                )
            elif config["type"] == "text":
                fields.append(
                    forms.CharField(
                        required=config.get("required", True),
                        max_length=config.get("max_length", None),
                    )
                )
        super().__init__(fields, *args, **kwargs)
        self.is_row_field = True

    def compress(self, data_list):
        """Return the list of subfield values as the combined value for the row."""
        return data_list


class CustomFileInput(forms.ClearableFileInput):
    """Custom file input widget with enhanced display and preview capabilities."""

    template_name = "forms/widgets/custom_file_input.html"

    def get_context(self, name, value, attrs):
        """Add selected_filename and other display data to the widget template context."""
        context = super().get_context(name, value, attrs)

        selected_filename = None
        if value:
            # Check if it's a FieldFile object
            if hasattr(value, "name") and value.name:
                # Extract just the filename from the full path
                selected_filename = value.name.split("/")[-1]
            elif isinstance(value, str):
                selected_filename = value.split("/")[-1]

        context["selected_filename"] = selected_filename
        return context


class CheckboxGridSelectMultiple(forms.CheckboxSelectMultiple):
    """Checkbox-grid widget for any multi-choice field (weekdays, roles, etc).

    Renders options as a responsive grid of bordered checkbox+label
    pills instead of Django's default stacked ``<ul><li>`` list or the
    select2 tag-input that generic Horilla forms apply to ordinary
    ``forms.Select``-based widgets. Drop-in replacement for
    ``forms.SelectMultiple``/``forms.CheckboxSelectMultiple`` on any
    ``ModelMultipleChoiceField`` or ``MultipleChoiceField``.

    Generic form templates (e.g. single_form_view.html) key off
    ``widget.input_type == "checkbox"`` to detect a *single* boolean
    toggle field and render it as an on/off switch. That check can't
    tell a lone ``CheckboxInput`` apart from this multi-option widget,
    since Django gives both the same ``input_type`` value. ``input_type``
    is set to ``None`` here so this widget is treated as a regular field
    by those templates; ``create_option`` is overridden to still emit
    ``type="checkbox"`` on each individual option input, since Django's
    ``ChoiceWidget.create_option`` otherwise reads that type from
    ``self.input_type`` too.
    """

    template_name = "forms/widgets/checkbox_grid_select.html"
    option_template_name = "forms/widgets/checkbox_grid_option.html"
    input_type = None

    def create_option(self, *args, **kwargs):
        """Create a checkbox option for the checkbox grid select multiple widget."""
        option = super().create_option(*args, **kwargs)
        option["type"] = "checkbox"
        return option


# Phone country-dial-code data: (dial_code, country_name)
def _build_phone_country_codes():
    """Build sorted, deduplicated dial-code choices from the phonenumbers library."""
    try:
        import phonenumbers

        seen = set()
        codes = []
        for region in sorted(phonenumbers.SUPPORTED_REGIONS):
            dial = phonenumbers.country_code_for_region(region)
            label = f"+{dial}"
            if label not in seen:
                seen.add(label)
                codes.append((label, label))
        codes.sort(key=lambda x: int(x[0][1:]))
        return [("", "+")] + codes
    except ImportError:
        return [("", "+")]


PHONE_COUNTRY_CODES = _build_phone_country_codes()


class PhoneWidget(forms.MultiWidget):
    """Phone input widget combining a country-code selector and a number input.

    Stores the combined value in the underlying CharField as ``+XX NNNNNN``.
    No migration is required — the field type is unchanged.
    """

    template_name = "forms/widgets/phone_widget.html"

    def __init__(self, attrs=None, placeholder=None):
        widgets = [
            forms.Select(
                choices=PHONE_COUNTRY_CODES,
                attrs={
                    "class": "js-example-basic-single headselect phone-country-code",
                    "data-placeholder": "+",
                },
            ),
            forms.TextInput(
                attrs={
                    "class": (
                        "phone-number-input text-color-600 p-2 placeholder:text-xs "
                        "w-full border border-dark-50 rounded-md "
                        "focus-visible:outline-0 placeholder:text-dark-100 text-sm "
                        "[transition:.3s] focus:border-primary-600"
                    ),
                    "placeholder": placeholder or _("Enter Phone Number"),
                }
            ),
        ]
        super().__init__(widgets, attrs)

    def decompress(self, value):
        """Split stored ``+XX NNNNNN`` into [dial_code, number]."""
        if value:
            value = value.strip()
            if value.startswith("+"):
                # Match longest known dial code first
                for code, _ in PHONE_COUNTRY_CODES[1:]:
                    if value.startswith(code):
                        rest = value[len(code) :].strip()
                        return [code, rest]
                parts = value.split(" ", 1)
                if len(parts) == 2:
                    return parts
                return ["", value]
            return ["", value]
        return ["", ""]

    def render(self, name, value, attrs=None, renderer=None):
        """Render as a flex row: [Select2 country-code select][number input]."""
        if not isinstance(value, list):
            value = self.decompress(value)
        code_widget, number_widget = self.widgets
        final_attrs = self.build_attrs(self.attrs, attrs or {})
        id_ = final_attrs.get("id", f"id_{name}")
        select_id = f"{id_}_0"

        code_html = code_widget.render(f"{name}_0", value[0], {"id": select_id})
        number_html = number_widget.render(f"{name}_1", value[1], {"id": f"{id_}_1"})

        if isinstance(code_widget, forms.HiddenInput):
            return format_html(
                '<div class="phone-widget-wrapper">{}{}</div>',
                code_html,
                number_html,
            )

        # No per-field init script here: the country-code <select> carries
        # "js-example-basic-single" (see widgets above), so the app-wide
        # htmx:afterSwap handler in global.js already re-initialises it,
        # scoped to the swapped content. A per-field script bound its own
        # permanent document-level listener keyed by this element's id;
        # since ids are reused across wizard steps, that listener kept
        # firing select2() on later steps' hidden replacement input too.
        return format_html(
            '<div class="flex items-center gap-2 w-full phone-widget-wrapper mt-1">'
            '<div style="width:25%;flex-shrink:0">{}</div>'
            '<div style="width:75%">{}</div>'
            "</div>",
            code_html,
            number_html,
        )


class PhoneField(forms.MultiValueField):
    """Form field that pairs a country-code selector with a phone-number input.

    Compresses into a single string (``+XX NNNNNN``) saved to the CharField.
    Both sub-fields are optional so the whole field can be blank.
    """

    widget = PhoneWidget

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("required", False)
        fields = [
            forms.ChoiceField(
                choices=PHONE_COUNTRY_CODES,
                required=False,
            ),
            forms.CharField(
                required=False,
                max_length=50,
            ),
        ]
        super().__init__(fields, *args, **kwargs)
        if self.label:
            self.widget.widgets[1].attrs["placeholder"] = enter_placeholder(self.label)

    def compress(self, data_list):
        """Combine dial code and number into a single string."""
        if not data_list:
            return ""
        code = (data_list[0] or "").strip()
        number = (data_list[1] or "").strip()
        if not code and not number:
            return ""

        if number and not re.match(r"^[0-9 \-().]+$", number):
            raise ValidationError(
                _("Enter a valid phone number."), code="invalid_phone"
            )

        if number:
            import phonenumbers

            try:
                parsed = phonenumbers.parse(
                    f"{code} {number}" if code else number, None
                )
            except phonenumbers.NumberParseException as exc:
                raise ValidationError(
                    _("Enter a valid phone number."), code="invalid_phone"
                ) from exc
            if not phonenumbers.is_valid_number(parsed):
                raise ValidationError(
                    _("Enter a valid phone number."), code="invalid_phone"
                )

        if code and number:
            return f"{code} {number}"
        return number or code


class HorillaAttachmentForm(forms.ModelForm):
    """Form for creating and editing attachments with title, file, and description."""

    class Meta:
        """Meta options for HorillaAttachmentForm."""

        model = HorillaAttachment
        fields = ["title", "file", "description"]
        labels = {
            "file": "",  # hide label
        }
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                    "placeholder": _("e.g. Signed Contract"),
                }
            ),
            "file": CustomFileInput(
                attrs={
                    "class": "hidden",
                    "id": "attachmentUpload",
                }
            ),
            "description": HorillaSummernoteWidget(
                settings={
                    "height": "300px",
                    "styleTags": [
                        "p",
                        "blockquote",
                        "pre",
                        "h1",
                        "h2",
                        "h3",
                        "h4",
                        "h5",
                        "h6",
                        {
                            "title": "Bold",
                            "tag": "b",
                            "className": "font-bold",
                            "value": "b",
                        },
                        {
                            "title": "Italic",
                            "tag": "i",
                            "className": "italic",
                            "value": "i",
                        },
                    ],
                }
            ),
        }
