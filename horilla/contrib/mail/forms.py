"""
Forms for Horilla Mail module.

This module contains Django forms for managing email templates,
mail configurations, and mail-related functionality.
"""

# Third-party imports (Django)
from django import forms
from django.core.validators import validate_email

# First party imports (Horilla)
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.forms import HorillaModelForm, PasswordInputWithEye
from horilla.contrib.generics.forms.rich_text import HorillaSummernoteWidget
from horilla.core.exceptions import ValidationError

# First-party (Horilla)
from horilla.db.models import Q
from horilla.urls import reverse_lazy
from horilla.utils.html import strip_tags
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import HorillaMailConfiguration, HorillaMailTemplate


# Define your mail forms here
class DynamicMailTestForm(forms.Form):
    """
    Form for testing email configuration
    """

    to_email = forms.EmailField(
        label=_("To Email"),
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "placeholder": _("Enter email address to send test email"),
                "required": True,
            }
        ),
        help_text=_("Enter the email address where you want to send the test email."),
    )

    def clean_to_email(self):
        """
        Validate the email address
        """
        email = self.cleaned_data.get("to_email")
        if email:
            try:
                validate_email(email)
            except ValidationError as exc:
                raise ValidationError(_("Please enter a valid email address.")) from exc
        return email

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add Bootstrap classes or custom styling if needed
        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control"})


class HorillaMailTemplateForm(forms.ModelForm):
    """Form for creating and editing Horilla Mail Templates"""

    field_order = [
        "title",
        "subject",
        "content_type",
        "body",
        "company",
    ]

    class Meta:
        """Meta class for HorillaMailTemplateForm."""

        model = HorillaMailTemplate
        fields = "__all__"
        widgets = {"body": HorillaSummernoteWidget(preset="full")}
        exclude = [
            "is_active",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "additional_info",
        ]

    def clean_title(self):
        """
        Clean and validate the title field.

        Returns:
            str: The cleaned and stripped title.

        Raises:
            ValidationError: If the title is empty or contains only whitespace.
        """
        title = self.cleaned_data.get("title")
        if not title or title.strip() == "":
            raise ValidationError(_("Template title is required."))
        return title.strip()

    def clean_body(self):
        """
        Clean and validate the body field.

        Returns:
            str: The cleaned body content.

        Raises:
            ValidationError: If the body is empty or contains only whitespace.
        """
        body = self.cleaned_data.get("body")
        if not body or body.strip() == "":
            raise ValidationError(_("Template body is required."))
        return body


class MailTemplateSelectForm(forms.Form):
    """
    Form for selecting a mail template.

    This form allows users to select a mail template filtered by model name.
    The template queryset is dynamically filtered based on the content type
    associated with the provided model name.
    """

    template = forms.ModelChoiceField(
        queryset=HorillaMailTemplate.objects.none(),
        label=_("Select Mail Template"),
        empty_label=_("Choose a template"),
        required=True,
        widget=forms.Select(attrs={"class": "js-example-basic-single headselect"}),
    )

    def __init__(self, *args, model_name=None, **kwargs):
        super().__init__(*args, **kwargs)
        if model_name:
            try:
                content_type = HorillaContentType.objects.get(model=model_name.lower())
                self.fields["template"].queryset = HorillaMailTemplate.objects.filter(
                    Q(content_type=content_type) | Q(content_type__isnull=True)
                )
            except HorillaContentType.DoesNotExist:
                self.fields["template"].queryset = HorillaMailTemplate.objects.none()

        else:
            self.fields["template"].queryset = HorillaMailTemplate.objects.filter(
                content_type__isnull=True
            )


class SaveAsMailTemplateForm(forms.ModelForm):
    """
    Form for saving email content as a mail template.

    This form allows users to save existing email content as a reusable
    mail template for future use.
    """

    class Meta:
        """Meta class for SaveAsMailTemplateForm."""

        model = HorillaMailTemplate
        fields = ["title", "body", "company", "content_type"]

    def clean_body(self):
        """
        Clean and validate the body field.

        Ensures the body contains actual content and is not empty
        (even after stripping HTML tags).

        Returns:
            str: The cleaned body content.

        Raises:
            ValidationError: If the body is empty or contains only empty HTML tags.
        """
        body = self.cleaned_data.get("body")
        if not body or strip_tags(body).strip() == "" or body == "<p><br></p>":
            raise ValidationError(_("Body content cannot be empty."))

        return body


def apply_dynamic_display_name_toggle(form):
    """
    Toggle the "display_name" field's required/visible state based on the
    current value of "use_dynamic_display_name", wiring the checkbox to
    live-update the field via HTMX.
    """
    if (
        "display_name" not in form.fields
        or "use_dynamic_display_name" not in form.fields
    ):
        return

    form.fields["use_dynamic_display_name"].widget.attrs.update(
        {
            "hx-get": reverse_lazy("mail:mail_display_name_field"),
            "hx-trigger": "change",
            "hx-include": "closest form",
            "hx-target": "#display_name_container",
            "hx-swap": "outerHTML",
            "hx-sync": "this:replace",
        }
    )
    if form.is_bound:
        dynamic_display_name = "use_dynamic_display_name" in form.data
    else:
        dynamic_display_name = form.initial.get(
            "use_dynamic_display_name",
            getattr(form.instance, "use_dynamic_display_name", False),
        )
    form.fields["display_name"].required = dynamic_display_name
    # The generic form template doesn't hide the field on first render, so hide
    # it up front when the dynamic display name is off (the HTMX toggle handles
    # later changes).
    if not dynamic_display_name:
        form.fields["display_name"].widget.attrs["container_style"] = "display: none;"
    else:
        form.fields["display_name"].widget.attrs.pop("container_style", None)


class HorillaMailConfigurationForm(HorillaModelForm):
    """
    Form for configuring outgoing mail server settings.

    This form allows users to configure SMTP settings for sending emails,
    including host, port, authentication credentials, and security options.
    """

    password = forms.CharField(
        widget=PasswordInputWithEye(attrs={"placeholder": _("Enter App Password")}),
        help_text=_("Enter the app-specific password for your mail account."),
        required=True,
    )

    field_order = [
        "host",
        "port",
        "from_email",
        "username",
        "use_dynamic_display_name",
        "display_name",
        "password",
        "use_tls",
        "use_ssl",
        "fail_silently",
        "is_primary",
        "timeout",
        "company",
        "type",
        "mail_channel",
    ]

    class Meta:
        """Meta class for HorillaMailConfigurationForm."""

        model = HorillaMailConfiguration
        fields = "__all__"
        keep_on_form = ("company",)
        exclude = [
            "outlook_client_id",
            "outlook_client_secret",
            "outlook_tenant_id",
            "outlook_redirect_uri",
            "outlook_authorization_url",
            "outlook_token_url",
            "outlook_api_endpoint",
            "token",
            "oauth_state",
            "last_refreshed",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        required_fields = [
            "host",
            "port",
            "from_email",
            "username",
            "password",
        ]

        # Set fields as required
        for field_name in required_fields:
            if field_name in self.fields:
                self.fields[field_name].required = True

        apply_dynamic_display_name_toggle(self)

    def clean(self):
        """TLS and SSL are mutually exclusive; the mail backend rejects both."""
        cleaned_data = super().clean()
        if cleaned_data.get("use_tls") and cleaned_data.get("use_ssl"):
            self.add_error(
                "use_ssl",
                _(
                    "Use TLS and Use SSL can't both be Yes. "
                    "Choose one (TLS for port 587, SSL for port 465)."
                ),
            )
        return cleaned_data


class IncomingHorillaMailConfigurationForm(HorillaModelForm):
    """
    Form for configuring incoming mail server settings.

    This form allows users to configure IMAP/POP3 settings for receiving emails,
    including host, port, and authentication credentials.
    """

    password = forms.CharField(
        widget=PasswordInputWithEye(attrs={"placeholder": _("Enter App Password")}),
        help_text=_("Enter the app-specific password  for your mail account."),
        required=True,
    )

    field_order = [
        "host",
        "port",
        "username",
        "password",
        "is_primary",
        "company",
        "type",
        "mail_channel",
    ]

    class Meta:
        """Meta class for IncomingHorillaMailConfigurationForm."""

        model = HorillaMailConfiguration
        fields = "__all__"
        keep_on_form = ("company",)
        exclude = [
            "from_email",
            "display_name",
            "use_tls",
            "use_ssl",
            "fail_silently",
            "use_dynamic_display_name",
            "timeout",
            "outlook_client_id",
            "outlook_client_secret",
            "outlook_tenant_id",
            "outlook_redirect_uri",
            "outlook_authorization_url",
            "outlook_token_url",
            "outlook_api_endpoint",
            "token",
            "oauth_state",
            "last_refreshed",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        required_fields = [
            "host",
            "port",
            "username",
            "password",
        ]

        # Set fields as required
        for field_name in required_fields:
            if field_name in self.fields:
                self.fields[field_name].required = True

    def save(self, commit=True):
        """Pick the transport from the port, since the form has no SSL/TLS option.

        Port 993 is IMAP over SSL; any other port uses plaintext + STARTTLS.
        """
        instance = self.instance
        port = self.cleaned_data.get("port")
        instance.use_ssl = port == 993
        instance.use_tls = not instance.use_ssl
        self.instance = instance
        return super().save(commit=commit)


class OutlookMailConfigurationForm(HorillaModelForm):
    """
    Form for configuring Outlook/Microsoft 365 mail integration.

    This form allows users to configure Microsoft Azure app registration
    details and OAuth settings for Outlook email integration.
    """

    outlook_client_secret = forms.CharField(
        widget=PasswordInputWithEye(attrs={"placeholder": _("Enter Client Secret")}),
        help_text=_(
            "Enter the client secret generated from your Microsoft Azure app registration. "
            "This secret is used to authenticate your Outlook integration securely."
        ),
        required=True,
    )

    field_order = [
        "mail_channel",
        "outlook_client_id",
        "outlook_client_secret",
        "outlook_tenant_id",
        "username",
        "use_dynamic_display_name",
        "display_name",
        "outlook_redirect_uri",
        "outlook_authorization_url",
        "outlook_token_url",
        "outlook_api_endpoint",
        "is_primary",
        "company",
        "type",
    ]

    class Meta:
        """Meta class for OutlookMailConfigurationForm."""

        model = HorillaMailConfiguration
        fields = "__all__"
        keep_on_form = ("company",)
        exclude = [
            "host",
            "port",
            "from_email",
            "password",
            "use_tls",
            "use_ssl",
            "fail_silently",
            "timeout",
            "token",
            "oauth_state",
            "last_refreshed",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # For Outlook, these fields are mandatory
        outlook_required_fields = [
            "outlook_client_id",
            "outlook_client_secret",
            "outlook_tenant_id",
            "username",
            "outlook_redirect_uri",
            "outlook_authorization_url",
            "outlook_token_url",
            "outlook_api_endpoint",
        ]

        # Set fields as required
        for field_name in outlook_required_fields:
            if field_name in self.fields:
                self.fields[field_name].required = True

        apply_dynamic_display_name_toggle(self)
