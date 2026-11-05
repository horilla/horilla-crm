"""Forms for custom calendars and Google Calendar integration."""

# Standard library imports
import json

# Third-party imports (Django)
from django import forms

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.models import HorillaContentType, Role
from horilla.contrib.generics.forms import HorillaModelForm
from horilla.core.exceptions import ValidationError
from horilla.urls import reverse, reverse_lazy
from horilla.utils import timezone
from horilla.utils.translation import gettext_lazy as _

from .models import CustomCalendar, UserAvailability, calendar_activity_type_choices

# Local imports
from .module_registry import get_custom_calendar_models


class CustomCalendarForm(HorillaModelForm):
    """Single-step form: module, activity types, color, and generic conditions."""

    htmx_field_choices_url = "generics:get_model_field_choices"

    field_order = [
        "name",
        "color",
        "module",
        "activity_types",
        "is_selected",
    ]

    class Meta:
        """Field list and widgets for creating or editing a custom calendar."""

        model = CustomCalendar
        fields = "__all__"
        exclude = ["user"]
        widgets = {
            "color": forms.TextInput(
                attrs={
                    "type": "color",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        # HTMX reload after changing module must NOT use ``data=GET`` - that binds the form and
        # triggers validation, showing "required" on empty fields before Save. Merge GET into
        # ``initial`` instead so the form stays unbound until POST.
        request = kwargs.get("request")
        if (
            request
            and request.method == "GET"
            and request.GET
            and request.headers.get("HX-Request")
        ):
            initial = kwargs.get("initial")
            if initial is None:
                initial = {}
            elif not isinstance(initial, dict):
                initial = dict(initial)
            q = request.GET
            for key in q.keys():
                # A multi-select posts several values under one key.
                initial[key] = q.getlist(key) if key == "activity_types" else q.get(key)
            kwargs["initial"] = initial
        super().__init__(*args, **kwargs)

        if "module" in self.fields and self.request and hasattr(self.request, "user"):
            user = self.request.user
            allowed_pks = []
            for _key, model_cls in get_custom_calendar_models():
                app_label = model_cls._meta.app_label
                meta_model_name = model_cls._meta.model_name
                view_perm = f"{app_label}.view_{meta_model_name}"
                view_own_perm = f"{app_label}.view_own_{meta_model_name}"
                if user.has_perm(view_perm) or user.has_perm(view_own_perm):
                    ct = HorillaContentType.objects.filter(
                        app_label=app_label,
                        model=model_cls._meta.model_name,
                    ).first()
                    if ct:
                        allowed_pks.append(ct.pk)
            self.fields["module"].queryset = HorillaContentType.objects.filter(
                pk__in=allowed_pks
            )
            self.fields["module"].required = False
            self.fields["module"].empty_label = "---------"
            # Refresh this single-form view when module changes,
            # so the condition rows are rebuilt from the selected model.
            reload_path = self.request.path
            pk = getattr(getattr(self, "instance", None), "pk", None)
            if pk:
                reload_path = reverse(
                    "calendar:custom_calendar_update", kwargs={"pk": pk}
                )
            self.fields["module"].widget.attrs.update(
                {
                    "hx-get": reload_path,
                    "hx-target": "#customcalendar-form-view-container",
                    "hx-swap": "outerHTML",
                    "hx-include": "#customcalendar-form-view",
                    "hx-trigger": "change",
                }
            )

        # Stored as a comma-separated string; the widget needs a list to show
        # the saved types selected (every type on a new calendar).
        self.activity_type_choices = calendar_activity_type_choices()
        self.fields["activity_types"].widget = forms.SelectMultiple(
            choices=self.activity_type_choices,
            attrs={
                "class": "js-example-basic-multiple headselect w-full",
                "id": "id_activity_types",
                "data-placeholder": _("Select Activity Types"),
                "multiple": "multiple",
            },
        )
        saved_types = self.initial.get("activity_types")
        if isinstance(saved_types, str):
            self.initial["activity_types"] = [
                t.strip() for t in saved_types.split(",") if t.strip()
            ]
        elif not saved_types:
            self.initial["activity_types"] = [
                value for value, _label in self.activity_type_choices
            ]
        self.fields["name"].label = CustomCalendar._meta.get_field("name").verbose_name
        self.fields["color"].label = CustomCalendar._meta.get_field(
            "color"
        ).verbose_name
        self.fields["module"].label = CustomCalendar._meta.get_field(
            "module"
        ).verbose_name
        self.fields["is_selected"].label = CustomCalendar._meta.get_field(
            "is_selected"
        ).verbose_name
        # Keep native color swatch appearance with compact boxed styling.
        self.fields["color"].widget.attrs.pop("placeholder", None)
        self.fields["color"].widget.attrs[
            "class"
        ] = "w-full h-8 p-1 cursor-pointer bg-white border border-dark-50 rounded-md"

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("module"):
            self.add_error("module", _("Please select a module."))
        return cleaned_data

    def clean_activity_types(self):
        """Store the selected types as a comma-separated string."""
        selected = self.data.getlist("activity_types")
        valid = {value for value, _label in self.activity_type_choices}
        if any(item not in valid for item in selected):
            raise ValidationError(_("Select a valid activity type."))
        return ",".join(selected)


class UserAvailabilityForm(HorillaModelForm):
    """Mark Unavailability form: the period cannot be in the past."""

    class Meta:
        """Every field; the view hides user, company and the like."""

        model = UserAvailability
        fields = "__all__"

    def clean(self):
        """
        Reject unavailability in the past, like activities.

        The start may be any time today (a whole-day block starts at 00:00) but
        not an earlier day, and the end must not have passed. A value left
        unchanged on an existing record is skipped, so an old one can still be
        edited.
        """
        cleaned_data = super().clean()
        from_datetime = cleaned_data.get("from_datetime")
        to_datetime = cleaned_data.get("to_datetime")
        if (
            from_datetime
            and timezone.localtime(from_datetime).date() < timezone.localdate()
            and not self._unchanged("from_datetime", from_datetime)
        ):
            self.add_error("from_datetime", _("From cannot be in the past."))
        if (
            to_datetime
            and to_datetime < timezone.now()
            and not self._unchanged("to_datetime", to_datetime)
        ):
            self.add_error("to_datetime", _("To cannot be in the past."))
        return cleaned_data

    def _unchanged(self, field_name, value):
        """True when editing a saved record and the field keeps its saved value."""
        return bool(self.instance.pk) and value == self.initial.get(field_name)


class TeamMembersForm(forms.Form):
    """
    The members the Team calendar can be narrowed to.

    Not rendered: the calendar's members filter opens the generic user picker
    with this form so the picker lists only these users.
    """

    members = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(), required=False
    )

    def __init__(self, *args, request=None, **kwargs):
        kwargs.pop("instance", None)
        super().__init__(*args, **kwargs)
        if request is not None:
            # Imported here: views imports this module.
            from .views import _team_members

            self.fields["members"].queryset = _team_members(request)


class GoogleSyncDirectionForm(forms.ModelForm):
    """Form for the user to choose one-way or two-way sync direction."""

    class Meta:
        """Expose only ``sync_direction`` on :class:`~.models.GoogleCalendarConfig`."""

        from .models import GoogleCalendarConfig

        model = GoogleCalendarConfig
        fields = ["sync_direction"]
        widgets = {
            "sync_direction": forms.RadioSelect(),
        }


class GoogleCredentialsUploadForm(forms.Form):
    """
    Form for users to upload their Google OAuth2 client_secret_*.json file
    and set the redirect URI, stored per-user in GoogleCalendarConfig.
    """

    credentials_file = forms.FileField(
        label=_("Google OAuth JSON file"),
        help_text=_(
            "Upload the client_secret_*.json file downloaded from Google Cloud Console."
        ),
        widget=forms.ClearableFileInput(attrs={"accept": ".json"}),
    )
    redirect_uri = forms.URLField(
        label=_("Redirect URI"),
        help_text=_(
            "Must match exactly what you registered in Google Cloud Console. "
            "E.g. https://yourdomain.com/calendar/google-calendar/callback/"
        ),
        widget=forms.URLInput(
            attrs={
                "class": "w-full text-xs border border-dark-50 rounded-md p-3 focus:outline-none focus:border-primary-400 mt-1",
                "placeholder": "https://yourdomain.com/calendar/google-calendar/callback/",
            }
        ),
    )

    def clean_credentials_file(self):
        """Validate uploaded JSON is a Google OAuth client secret / installed app file."""
        f = self.cleaned_data["credentials_file"]
        try:
            data = json.loads(f.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValidationError(_("Invalid JSON file.")) from exc
        if "web" not in data and "installed" not in data:
            raise ValidationError(
                _(
                    "Not a valid Google OAuth2 credentials file. "
                    "Expected a JSON with a 'web' or 'installed' key."
                )
            )
        return data  # Returns parsed dict, not the raw file


_SINGLE_FORM_VIEW_KWARGS = (
    "full_width_fields",
    "dynamic_create_fields",
    "hidden_fields",
    "condition_fields",
    "condition_model",
    "condition_field_choices",
    "condition_hx_include",
    "condition_related_name",
    "condition_related_name_candidates",
    "field_permissions",
    "duplicate_mode",
    "request",
)


def _pop_single_form_view_kwargs(form_instance, kwargs):
    """Remove all extra kwargs injected by HorillaSingleFormView.get_form_kwargs()."""
    for key in _SINGLE_FORM_VIEW_KWARGS:
        val = kwargs.pop(key, None)
        if val is not None:
            setattr(form_instance, key, val)


class GoogleAccessRolesForm(forms.Form):
    """Select roles that can connect Google Calendar."""

    allowed_roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.none(),
        label=_("Roles"),
        widget=forms.SelectMultiple(
            attrs={
                "class": "select2-pagination w-full",
                "data-url": reverse_lazy(
                    "generics:model_select2",
                    kwargs={"app_label": "core", "model_name": "role"},
                ),
                "data-placeholder": _("Select Roles"),
                "multiple": "multiple",
                "data-field-name": "allowed_roles",
                "id": "id_allowed_roles",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        _pop_single_form_view_kwargs(self, kwargs)
        super().__init__(*args, **kwargs)


class GoogleAccessUsersForm(forms.Form):
    """Select users that can connect Google Calendar."""

    allowed_users = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        label=_("Users"),
        widget=forms.SelectMultiple(
            attrs={
                "class": "select2-pagination w-full",
                "data-url": reverse_lazy(
                    "generics:model_select2",
                    kwargs={
                        "app_label": User._meta.app_label,
                        "model_name": User._meta.model_name,
                    },
                ),
                "data-placeholder": _("Select Users"),
                "multiple": "multiple",
                "data-field-name": "allowed_users",
                "id": "id_allowed_users",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        request = kwargs.pop("request", None)
        _pop_single_form_view_kwargs(self, kwargs)
        super().__init__(*args, **kwargs)
        if request is not None:
            company = getattr(request, "active_company", None) or request.user.company
            self.fields["allowed_users"].queryset = User.objects.filter(
                company=company, is_active=True
            )
