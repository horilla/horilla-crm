"""Models for the Horilla Calls Integration app."""

# Third-party imports (Django)
from django.conf import settings

# First party imports (Horilla)
from horilla.apps import apps
from horilla.contrib.core.models import HorillaCoreModel, Role
from horilla.contrib.mail.fields import EncryptedCharField
from horilla.contrib.utils.methods import render_template
from horilla.db import models
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _


class CallIntegrationSetting(HorillaCoreModel):
    """
    Company-level toggle for the calls integration.
    One row per company — controls whether any call provider is available
    and who can initiate calls.
    """

    CACHE_NAMESPACE = "calls.integration"

    ACCESS_ALL = "all"
    ACCESS_ROLES = "roles"
    ACCESS_USERS = "users"

    ACCESS_CHOICES = [
        (ACCESS_ALL, _("All Users")),
        (ACCESS_ROLES, _("Specific Roles")),
        (ACCESS_USERS, _("Specific Users")),
    ]

    is_enabled = models.BooleanField(
        default=False,
        verbose_name=_("Enabled"),
    )
    access_type = models.CharField(
        max_length=10,
        choices=ACCESS_CHOICES,
        default=ACCESS_ALL,
        verbose_name=_("Access Type"),
        help_text=_("Who can initiate calls."),
    )
    allowed_roles = models.ManyToManyField(
        Role,
        blank=True,
        verbose_name=_("Allowed Roles"),
        related_name="call_integrations",
    )
    allowed_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        verbose_name=_("Allowed Users"),
        related_name="call_integrations",
    )

    class Meta:
        """Meta options for CallIntegrationSetting model."""

        verbose_name = _("Call Integration Setting")
        verbose_name_plural = _("Call Integration Settings")

    def __str__(self):
        return f"Call Integration – {'on' if self.is_enabled else 'off'}"

    def user_has_access(self, user):
        """Return True if the given user has access to the calls integration based on the access_type setting."""
        if not self.is_enabled:
            return False
        if self.access_type == self.ACCESS_ALL:
            return True
        if self.access_type == self.ACCESS_ROLES:
            user_role_id = getattr(user, "role_id", None)
            if not user_role_id:
                return False
            return self.allowed_roles.filter(pk=user_role_id).exists()
        if self.access_type == self.ACCESS_USERS:
            return self.allowed_users.filter(pk=user.pk).exists()
        return False

    @classmethod
    def _get_cached_setting(cls, request, company):
        """
        Resolve the setting row for ``company``.

        Uses request-local cache then Django ``cache.get_or_set`` (per
        company) so menu conditions avoid a DB hit on every page render.
        """
        from horilla.contrib.utils.company_settings_cache import (
            get_or_set_company_setting,
        )

        if not company:
            return None

        company_id = company.pk
        cache_attr = "_call_integration_setting_cache"
        if request is not None:
            cached = getattr(request, cache_attr, None)
            if cached is None:
                cached = {}
                setattr(request, cache_attr, cached)
            if company_id in cached:
                return cached[company_id]

        setting = get_or_set_company_setting(
            cls.CACHE_NAMESPACE,
            company_id,
            lambda: cls.all_objects.filter(company_id=company_id).first(),
        )
        if request is not None:
            cached[company_id] = setting
        return setting

    @classmethod
    def calls_enabled(cls, request=None):
        """Menu condition — True when calls integration is enabled for the company."""
        from horilla.contrib.utils.middlewares import _thread_local

        if request is None:
            request = getattr(_thread_local, "request", None)
        if request is None:
            return False
        company = getattr(request, "active_company", None) or getattr(
            request.user, "company", None
        )
        if not company:
            return False
        setting = cls._get_cached_setting(request, company)
        return bool(setting and setting.is_enabled)

    @classmethod
    def user_has_menu_access(cls, request=None):
        """Menu condition — True only when integration is enabled AND current user has access."""
        from horilla.contrib.utils.middlewares import _thread_local

        if request is None:
            request = getattr(_thread_local, "request", None)
        if request is None:
            return False
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        company = getattr(request, "active_company", None) or getattr(
            user, "company", None
        )
        if not company:
            return False
        return cls.user_can_access(user, company, request=request)

    @classmethod
    def get_for_company(cls, company):
        """Utility method to get or create the CallIntegrationSetting for a given company."""
        from horilla.contrib.utils.company_settings_cache import (
            invalidate_company_setting,
        )

        if not company:
            return None
        setting, created = cls.all_objects.get_or_create(company=company)
        if created:
            invalidate_company_setting(cls.CACHE_NAMESPACE, company.pk)
        return setting

    @classmethod
    def user_can_access(cls, user, company, request=None):
        """Utility method to check if a given user has access to the calls integration for a given company."""
        setting = cls._get_cached_setting(request, company)
        return bool(setting and setting.user_has_access(user))

    def save(self, *args, **kwargs):
        """Persist and drop the per-company Django cache entry."""
        from horilla.contrib.utils.company_settings_cache import (
            invalidate_company_setting,
        )

        super().save(*args, **kwargs)
        invalidate_company_setting(self.CACHE_NAMESPACE, self.company_id)

    def delete(self, *args, **kwargs):
        """Delete and drop the per-company Django cache entry."""
        from horilla.contrib.utils.company_settings_cache import (
            invalidate_company_setting,
        )

        company_id = self.company_id
        super().delete(*args, **kwargs)
        invalidate_company_setting(self.CACHE_NAMESPACE, company_id)


class CallProvider(HorillaCoreModel):
    """
    Registry of telephony provider configurations per company.
    Each row represents one configured provider (e.g. a Twilio account,
    an Exotel SID, or an Asterisk server).
    """

    PROVIDER_TWILIO = "twilio"
    PROVIDER_SIGNALWIRE = "signalwire"
    PROVIDER_TELNYX = "telnyx"
    PROVIDER_SINCH = "sinch"
    PROVIDER_EXOTEL = "exotel"
    PROVIDER_MOCK = "mock"

    PROVIDER_CHOICES = [
        (PROVIDER_TWILIO, _("Twilio")),
        (PROVIDER_SIGNALWIRE, _("SignalWire (Beta)")),
        (PROVIDER_TELNYX, _("Telnyx (Beta)")),
        (PROVIDER_SINCH, _("Sinch (Beta)")),
        (PROVIDER_EXOTEL, _("Exotel (Beta)")),
        (PROVIDER_MOCK, _("Mock (Testing)")),
    ]

    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_TESTING = "testing"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, _("Active")),
        (STATUS_INACTIVE, _("Inactive")),
        (STATUS_TESTING, _("Testing")),
    ]

    name = models.CharField(
        max_length=100,
        verbose_name=_("Name"),
    )
    provider_type = models.CharField(
        max_length=20,
        choices=PROVIDER_CHOICES,
        verbose_name=_("Provider"),
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_INACTIVE,
        verbose_name=_("Status"),
    )
    account_sid = EncryptedCharField(
        max_length=512,
        blank=True,
        verbose_name=_("Account SID / App ID"),
        help_text=_(
            "Twilio AccountSID, Plivo Auth ID, Ozonetel username, or equivalent identifier."
        ),
    )
    api_key = EncryptedCharField(
        max_length=512,
        blank=True,
        verbose_name=_("API Key"),
    )
    api_secret = EncryptedCharField(
        max_length=512,
        blank=True,
        verbose_name=_("API Secret / Auth Token"),
    )
    api_base_url = models.URLField(
        max_length=500,
        blank=True,
        verbose_name=_("API Base URL"),
        help_text=_("Optional override for Ozonetel or custom API endpoints."),
    )
    caller_id = models.CharField(
        max_length=40,
        blank=True,
        verbose_name=_("Default Caller ID"),
        help_text=_("Default outbound phone number or SIP caller ID."),
    )
    recording_enabled = models.BooleanField(
        default=False,
        verbose_name=_("Enable Call Recording"),
        help_text=_(
            "Record calls via this provider. Requires recording support on the provider side."
        ),
    )
    webhook_secret = EncryptedCharField(
        max_length=255,
        blank=True,
        verbose_name=_("Webhook Secret"),
        help_text=_("Used to validate incoming webhook signatures."),
    )
    extra_config = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Extra Configuration"),
    )

    class Meta:
        """Meta options for CallProvider model."""

        verbose_name = _("Call Provider")
        verbose_name_plural = _("Call Providers")
        ordering = ["name"]

    def __str__(self):
        return f"{self.get_provider_type_display()}"

    def webhook_secret_error(self):
        """
        Return a user-facing message when this provider cannot verify its webhooks.

        Without the key every provider callback is rejected, so active providers must have one.
        """
        from .adapters.factory import get_adapter_class

        adapter_cls = get_adapter_class(self.provider_type)
        field_name = adapter_cls.WEBHOOK_SECRET_FIELD if adapter_cls else None
        if not field_name or getattr(self, field_name, ""):
            return None
        label = self._meta.get_field(field_name).verbose_name
        return _(
            "%(label)s is required for %(provider)s so that call status "
            "callbacks can be verified. Callbacks are rejected without it."
        ) % {"label": label, "provider": self.get_provider_type_display()}

    def get_edit_url(self):
        """Return the URL for editing this provider."""
        return reverse_lazy("calls:provider_update", kwargs={"pk": self.pk})

    def get_delete_url(self):
        """Return the URL for deleting this provider."""
        return reverse_lazy("calls:provider_delete", kwargs={"pk": self.pk})

    def get_test_url(self):
        """Return the URL for testing this provider's configuration."""
        return reverse_lazy("calls:provider_test", kwargs={"pk": self.pk})

    def status_col(self):
        """Inline status dropdown for the provider list view."""
        return render_template(
            path="calls/call_provider_status_col.html",
            context={
                "instance": self,
                "status_choices": self.STATUS_CHOICES,
            },
        )


class AgentMapping(HorillaCoreModel):
    """Maps a CRM user to their telephony agent credentials for a given provider."""

    provider = models.ForeignKey(
        CallProvider,
        on_delete=models.CASCADE,
        related_name="agent_mappings",
        verbose_name=_("Provider"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="call_agent_mappings",
        verbose_name=_("User"),
    )
    extension = models.CharField(
        max_length=40,
        blank=True,
        verbose_name=_("Extension / SIP Extension"),
    )
    agent_id = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Agent / Caller ID"),
        help_text=_("Provider's internal agent or caller identifier."),
    )
    OWNER_FIELDS = ["user"]

    class Meta:
        """Meta options for AgentMapping model."""

        verbose_name = _("Agent Mapping")
        verbose_name_plural = _("Agent Mappings")
        unique_together = [("provider", "user")]

    def __str__(self):
        return f"{self.user}"


class CallLog(HorillaCoreModel):
    """
    CRM-side record of every telephony call — outbound or inbound.
    Linked to a Lead or Contact via model name + object ID.
    """

    DIRECTION_INBOUND = "inbound"
    DIRECTION_OUTBOUND = "outbound"

    DIRECTION_CHOICES = [
        (DIRECTION_INBOUND, _("Inbound")),
        (DIRECTION_OUTBOUND, _("Outbound")),
    ]

    STATUS_INITIATED = "initiated"
    STATUS_RINGING = "ringing"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_NO_ANSWER = "no_answer"
    STATUS_BUSY = "busy"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_INITIATED, _("Initiated")),
        (STATUS_RINGING, _("Ringing")),
        (STATUS_IN_PROGRESS, _("In Progress")),
        (STATUS_COMPLETED, _("Completed")),
        (STATUS_NO_ANSWER, _("No Answer")),
        (STATUS_BUSY, _("Busy")),
        (STATUS_FAILED, _("Failed")),
        (STATUS_CANCELLED, _("Cancelled")),
    ]

    provider = models.ForeignKey(
        CallProvider,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="call_logs",
        verbose_name=_("Provider"),
    )
    agent = models.ForeignKey(
        AgentMapping,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="call_logs",
        verbose_name=_("Agent"),
    )
    direction = models.CharField(
        max_length=20,
        choices=DIRECTION_CHOICES,
        verbose_name=_("Direction"),
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_INITIATED,
        verbose_name=_("Status"),
    )
    from_number = models.CharField(
        max_length=40,
        verbose_name=_("From Number"),
    )
    to_number = models.CharField(
        max_length=40,
        verbose_name=_("To Number"),
    )
    duration_seconds = models.IntegerField(
        null=True,
        blank=True,
        verbose_name=_("Duration (seconds)"),
    )
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Started At"),
    )
    ended_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Ended At"),
    )
    provider_call_id = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        verbose_name=_("Provider Call ID"),
        help_text=_(
            "Twilio CallSID, Plivo RequestUUID, Vonage UUID, Ozonetel UCID, etc."
        ),
    )
    recording_url = models.URLField(
        max_length=2000,
        blank=True,
        null=True,
        verbose_name=_("Recording URL"),
    )
    related_model_name = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Related Model"),
        help_text=_("'lead' or 'contact'"),
    )
    related_object_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Related Object ID"),
    )

    class Meta:
        """Meta options for CallLog model."""

        verbose_name = _("Call Log")
        verbose_name_plural = _("Call Logs")
        ordering = ["-started_at", "-created_at"]
        indexes = [
            models.Index(fields=["provider_call_id"]),
            models.Index(fields=["status"]),
            models.Index(fields=["from_number"]),
            models.Index(fields=["to_number"]),
            models.Index(fields=["started_at"]),
            models.Index(fields=["company", "started_at"]),
            models.Index(fields=["company", "status"]),
        ]

    def __str__(self):
        return f"{self.get_direction_display()} – {self.from_number} → {self.to_number}"

    def get_duration_display(self):
        """Return 'MM:SS' string from duration_seconds."""
        if not self.duration_seconds:
            return "—"
        minutes = self.duration_seconds // 60
        seconds = self.duration_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    def get_avatar(self):
        """
        Method will retun the api to the avatar or path to the profile image
        """
        url = f"https://ui-avatars.com/api/?name={self.provider}&background=random"
        return url

    def get_delete_url(self):
        """Return the URL for deleting this call log entry."""
        return reverse_lazy("calls:call_log_delete", kwargs={"pk": self.pk})

    def get_detail_url(self):
        """Return the URL for viewing this call log entry."""
        return reverse_lazy("calls:call_log_detail", kwargs={"pk": self.pk})

    def get_related_object(self):
        """Return the related object for this call log.

        Tries the callable model registry first, then falls back to a generic
        ContentType lookup so that models not registered as callable (e.g. Opportunity)
        can still be resolved.
        """
        if not self.related_model_name or not self.related_object_id:
            return None
        try:
            from calls.registration import _CALLABLE_MODEL_REGISTRY
            from horilla.contrib.core.models import HorillaContentType

            for app_label, model_name, _phone_field in _CALLABLE_MODEL_REGISTRY:
                if model_name == self.related_model_name:
                    model_cls = apps.get_model(app_label, model_name)
                    manager = getattr(model_cls, "all_objects", model_cls.objects)
                    return manager.filter(pk=self.related_object_id).first()

            # Fallback: resolve via ContentType for any model not in the registry.
            ct = HorillaContentType.objects.filter(
                model=self.related_model_name.lower()
            ).first()
            if ct:
                model_cls = ct.model_class()
                if model_cls:
                    manager = getattr(model_cls, "all_objects", model_cls.objects)
                    return manager.filter(pk=self.related_object_id).first()
        except Exception:
            return None
        return None
