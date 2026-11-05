"""Forms for the Horilla Calls Integration app."""

# Third-party imports (Django)
from django import forms

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.generics.forms import HorillaModelForm
from horilla.contrib.generics.forms.generics import PasswordInputWithEye
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import AgentMapping, CallIntegrationSetting, CallLog, CallProvider

# Keys injected by HorillaSingleFormView.get_form_kwargs() that plain forms.Form doesn't accept
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
    "instance",
    "request",
)


def _pop_single_form_view_kwargs(form_instance, kwargs):
    """Remove all extra kwargs injected by HorillaSingleFormView.get_form_kwargs()."""
    for key in _SINGLE_FORM_VIEW_KWARGS:
        val = kwargs.pop(key, None)
        if val is not None:
            setattr(form_instance, key, val)


class CallIntegrationSettingForm(HorillaModelForm):
    """Form to enable/configure the calls integration for a company."""

    class Meta:
        """Meta options for CallIntegrationSettingForm."""

        model = CallIntegrationSetting
        fields = ["is_enabled", "access_type", "allowed_roles", "allowed_users"]

    condition_fields = {
        "allowed_roles": {
            "field": "access_type",
            "value": "roles",
        },
        "allowed_users": {
            "field": "access_type",
            "value": "users",
        },
    }


class CallProviderForm(HorillaModelForm):
    """Form for creating and editing call providers."""

    # Fields whose visibility depends on the selected provider type.
    DYNAMIC_FIELDS = ["account_sid", "api_key", "api_base_url", "webhook_secret"]

    # Fields that store secrets — rendered as password inputs.
    SECRET_FIELDS = ["api_secret", "webhook_secret"]

    # Which dynamic fields each provider type shows.
    PROVIDER_FIELDS = {
        CallProvider.PROVIDER_TWILIO: ["account_sid"],
        CallProvider.PROVIDER_SIGNALWIRE: [
            "account_sid",
            "api_base_url",
            "webhook_secret",
        ],
        CallProvider.PROVIDER_TELNYX: ["api_key", "webhook_secret"],
        CallProvider.PROVIDER_SINCH: ["account_sid"],
        CallProvider.PROVIDER_EXOTEL: ["account_sid", "api_key"],
        CallProvider.PROVIDER_MOCK: [],
    }

    class Meta:
        """Meta options for CallProviderForm."""

        model = CallProvider
        fields = [
            "name",
            "provider_type",
            "status",
            "caller_id",
            # "recording_enabled",
            "api_secret",
            "account_sid",
            "api_key",
            "api_base_url",
            "webhook_secret",
        ]
        labels = {
            "account_sid": _("Account SID"),
            "api_key": _("API Key"),
            "api_secret": _("Auth Token / API Secret"),
            "api_base_url": _("API Base URL"),
            "webhook_secret": _("Webhook Secret"),
        }
        widgets = {
            "api_secret": PasswordInputWithEye(attrs={"autocomplete": "new-password"}),
            "webhook_secret": PasswordInputWithEye(
                attrs={"autocomplete": "new-password"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Hide dynamic fields — the HTMX load trigger shows the right ones. A bound form
        # (re-rendered after validation errors) shows them here instead, because the
        # load swap would replace them with an unbound copy and drop the errors.
        visible_fields = set()
        if self.is_bound:
            provider_type = self.data.get(self.add_prefix("provider_type"))
            visible_fields = set(self.PROVIDER_FIELDS.get(provider_type, []))
            if provider_type == CallProvider.PROVIDER_TELNYX:
                self.fields["api_key"].label = _("Connection ID")
        for field_name in self.DYNAMIC_FIELDS:
            if field_name in self.fields and field_name not in visible_fields:
                self.fields[field_name].widget.attrs["container_style"] = "display:none"

        # Build the provider_fields URL — include pk when editing so OOB view
        # can load the existing instance and pre-populate dynamic fields.
        pk = self.instance.pk if self.instance and self.instance.pk else None
        fields_url = str(reverse_lazy("calls:provider_fields"))
        if pk:
            fields_url = f"{fields_url}?pk={pk}"

        # HTMX: on provider_type change (and on initial load), fetch the correct field visibility.
        self.fields["provider_type"].widget.attrs.update(
            {
                "hx-get": fields_url,
                "hx-trigger": "change" if self.is_bound else "change, load",
                "hx-target": "body",
                "hx-swap": "none",
                "hx-include": "[name='provider_type']",
            }
        )

        # Secret fields: set placeholder so user knows to leave blank to keep existing value.
        if pk:
            for field_name in self.SECRET_FIELDS:
                if field_name in self.fields:
                    self.fields[field_name].required = False
                    self.fields[field_name].widget.attrs["placeholder"] = _(
                        "Leave blank to keep existing"
                    )

    def clean(self):
        cleaned_data = super().clean()
        # On edit, skip saving secret fields that were left blank (keep existing encrypted value).
        if self.instance and self.instance.pk:
            for field_name in self.SECRET_FIELDS:
                if field_name in cleaned_data and not cleaned_data[field_name]:
                    cleaned_data.pop(field_name)
        self._validate_webhook_secret(cleaned_data)
        return cleaned_data

    def _validate_webhook_secret(self, cleaned_data):
        """Require the webhook verification key on active providers that need one."""
        if cleaned_data.get("status") != CallProvider.STATUS_ACTIVE:
            return
        provider = CallProvider(provider_type=cleaned_data.get("provider_type"))
        for field_name in self.SECRET_FIELDS:
            # A value left blank on edit keeps the stored one, so fall back to it.
            value = cleaned_data.get(field_name) or getattr(
                self.instance, field_name, ""
            )
            setattr(provider, field_name, value)
        error = provider.webhook_secret_error()
        if error:
            from .adapters.factory import get_adapter_class

            field_name = get_adapter_class(provider.provider_type).WEBHOOK_SECRET_FIELD
            self.add_error(field_name, error)

    def save(self, commit=True):
        """Override save to handle secret fields left blank on edit (keep existing encrypted value)."""
        instance = super().save(commit=False)
        # Re-apply existing encrypted values for secret fields left blank on edit.
        if self.instance and self.instance.pk:
            db_row = CallProvider.objects.filter(pk=self.instance.pk).first()
            for field_name in self.SECRET_FIELDS:
                if field_name not in self.cleaned_data and db_row:
                    setattr(instance, field_name, getattr(db_row, field_name, ""))
        if commit:
            instance.save()
            self._save_m2m()
        return instance


class AgentMappingForm(HorillaModelForm):
    """Form for mapping CRM users to telephony agent credentials."""

    class Meta:
        """Meta options for AgentMappingForm."""

        model = AgentMapping
        fields = ["provider", "user", "extension", "agent_id"]


class CallAccessRolesForm(forms.Form):
    """Modal form: select which roles can access call integration (Select2)."""

    allowed_roles = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False,
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


class CallAccessUsersForm(forms.Form):
    """Modal form: select which users can access call integration (Select2)."""

    allowed_users = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False,
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
        _pop_single_form_view_kwargs(self, kwargs)
        super().__init__(*args, **kwargs)


class CallLogForm(HorillaModelForm):
    """Form for manually creating or editing a call log entry."""

    class Meta:
        """Meta options for CallLogForm."""

        model = CallLog
        fields = [
            "provider",
            "direction",
            "status",
            "from_number",
            "to_number",
            "duration_seconds",
            "started_at",
            "ended_at",
            "recording_url",
            "related_model_name",
            "related_object_id",
        ]
