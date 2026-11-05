"""Forms for the Horilla Meeting Integration app."""

# Third-party imports (Django)
from django import forms

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.models import Role
from horilla.contrib.generics.forms import HorillaModelForm
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import MeetingIntegrationSetting, UserMeetingConfig


class MeetingIntegrationSettingForm(HorillaModelForm):
    """Admin form to configure the global meeting integration."""

    class Meta:
        """Fields shown when editing company-wide meeting integration access."""

        model = MeetingIntegrationSetting
        fields = [
            "access_type",
            "allowed_roles",
            "allowed_users",
        ]
        widgets = {
            "allowed_roles": forms.CheckboxSelectMultiple(),
            "allowed_users": forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["allowed_roles"].required = False
        self.fields["allowed_users"].required = False


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


class MeetingAccessRolesForm(forms.Form):
    """Select roles that can access meeting integration."""

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


class MeetingAccessUsersForm(forms.Form):
    """Select users that can access meeting integration."""

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
            from horilla.contrib.meeting.views import _get_active_company

            company = _get_active_company(request)
            self.fields["allowed_users"].queryset = User.objects.filter(
                company=company, is_active=True
            )


class UserMeetingConfigForm(HorillaModelForm):
    """Per-user form to save a personal meeting room URL for a provider."""

    class Meta:
        """Fields for configuring a user's personal meeting URL per provider."""

        model = UserMeetingConfig
        fields = ["provider", "personal_meeting_url"]

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
