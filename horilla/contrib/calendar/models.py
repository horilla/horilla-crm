"""Models for user calendar preferences and availability in Horilla"""

# Third-party imports (Django)
from django.conf import settings

from horilla.apps import apps
from horilla.contrib.core.models import HorillaContentType, HorillaCoreModel, Role
from horilla.contrib.utils.middlewares import _thread_local
from horilla.db import models
from horilla.registry.limiters import limit_content_types
from horilla.registry.permission_registry import permission_exempt_model
from horilla.urls import reverse_lazy

# First party imports (Horilla)
from horilla.utils import timezone
from horilla.utils.choices import OPERATOR_CHOICES
from horilla.utils.translation import gettext_lazy as _

# Activity types the calendar shows (the same ones as its standard calendars).
CALENDAR_ACTIVITY_TYPES = ("event", "meeting", "task")


def calendar_activity_type_choices():
    """The (value, label) activity types a custom calendar can show."""
    activity_model = apps.get_model("activity", "Activity")
    return [
        (value, label)
        for value, label in activity_model.ACTIVITY_TYPES
        if value in CALENDAR_ACTIVITY_TYPES
    ]


def default_activity_types():
    """Every calendar activity type, comma-separated: the default for a custom calendar."""
    return ",".join(value for value, _label in calendar_activity_type_choices())


class UserCalendarPreference(HorillaCoreModel):
    """Model to store user calendar preferences."""

    CALENDAR_TYPES = (
        ("task", _("Task")),
        ("event", _("Event")),
        ("meeting", _("Meeting")),
        ("unavailability", _("Un Availability")),
        # Colors for the "Color by: Status" mode; these rows only hold a color.
        ("status_completed", _("Completed")),
        ("status_pending", _("Not completed")),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="calendar_preferences",
        verbose_name=_("User"),
    )
    calendar_type = models.CharField(
        max_length=20, choices=CALENDAR_TYPES, verbose_name=_("Calendar Type")
    )
    color = models.CharField(max_length=10, verbose_name=_("Color"))
    is_selected = models.BooleanField(default=True, verbose_name=_("Is Selected"))

    class Meta:
        """Meta class for UserCalendarPreference model."""

        unique_together = (
            "user",
            "calendar_type",
            "company",
        )  # One preference per user per calendar type
        verbose_name = _("User Calendar Preference")
        verbose_name_plural = _("User Calendar Preferences")

    def __str__(self):
        return f"{self.user.username} - {self.calendar_type}\
            - {self.color} (Selected: {self.is_selected})"


class UserAvailability(HorillaCoreModel):
    """Model to store user availability periods."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="unavailable_periods",
        verbose_name=_("User"),
    )
    from_datetime = models.DateTimeField(verbose_name=_("From"))
    to_datetime = models.DateTimeField(verbose_name=_("To"))
    reason = models.CharField(max_length=255, verbose_name=_("Reason"))

    class Meta:
        """Meta class for UserAvailability model."""

        verbose_name = _("User Unavailability")
        verbose_name_plural = _("User Unavailabilities")
        ordering = ["-from_datetime"]
        indexes = [
            models.Index(fields=["user", "from_datetime", "to_datetime"]),
        ]

    def __str__(self):
        return (
            f"{self.user} unavailable from {self.from_datetime} to {self.to_datetime}"
        )

    def is_currently_unavailable(self):
        """Check if the user is currently unavailable."""

        now = timezone.now()
        return self.from_datetime <= now <= self.to_datetime

    def update_mark_unavailability_url(self):
        """Generate URL for updating this unavailability record."""
        return reverse_lazy(
            "calendar:update_mark_unavailability", kwargs={"pk": self.pk}
        )

    def delete_mark_unavailability_url(self):
        """Generate URL for deleting this unavailability record."""
        return reverse_lazy(
            "calendar:delete_mark_unavailability", kwargs={"pk": self.pk}
        )

    google_event_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Google Calendar Event ID"),
    )


class CustomCalendar(HorillaCoreModel):
    """User-defined calendar showing the activities of a module's records (optionally filtered)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="custom_calendars",
        verbose_name=_("User"),
    )
    name = models.CharField(max_length=255, verbose_name=_("Calendar Name"))
    color = models.CharField(max_length=20, default="#E74C3C", verbose_name=_("Color"))
    module = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        limit_choices_to=limit_content_types("custom_calendar_models"),
        verbose_name=_("Module"),
    )
    # Comma-separated activity types to show for the records of ``module``,
    # e.g. "task,meeting".
    activity_types = models.TextField(
        default=default_activity_types,
        verbose_name=_("Activity Types"),
    )
    is_selected = models.BooleanField(default=True, verbose_name=_("Is Selected"))

    OWNER_FIELDS = ["user"]

    class Meta:
        """Ordering and verbose names for :class:`CustomCalendar`."""

        verbose_name = _("Custom Calendar")
        verbose_name_plural = _("Custom Calendars")
        ordering = ["name"]

    def __str__(self):
        return str(self.name)

    def get_activity_types_list(self):
        """Return the saved activity types as a list."""
        return [t.strip() for t in (self.activity_types or "").split(",") if t.strip()]


@permission_exempt_model
class CustomCalendarCondition(HorillaCoreModel):
    """Filter rows for a custom calendar (same shape as dashboard component criteria)."""

    custom_calendar = models.ForeignKey(
        CustomCalendar,
        on_delete=models.CASCADE,
        related_name="conditions",
        verbose_name=_("Custom Calendar"),
    )
    field = models.CharField(max_length=100, verbose_name=_("Field Name"))
    operator = models.CharField(
        max_length=50, choices=OPERATOR_CHOICES, verbose_name=_("Operator")
    )
    value = models.CharField(max_length=255, blank=True, verbose_name=_("Value"))
    sequence = models.PositiveIntegerField(default=1, verbose_name=_("Sequence"))

    class Meta:
        """Default ordering for condition rows belonging to one custom calendar."""

        ordering = ["sequence"]
        verbose_name = _("Custom Calendar Condition")
        verbose_name_plural = _("Custom Calendar Conditions")

    def __str__(self):
        return f"{self.custom_calendar_id} - {self.field} {self.operator} {self.value}"


ACCESS_ALL = "all"
ACCESS_ROLES = "roles"
ACCESS_USERS = "users"

ACCESS_CHOICES = [
    (ACCESS_ALL, _("All Users")),
    (ACCESS_ROLES, _("Specific Roles")),
    (ACCESS_USERS, _("Specific Users")),
]


class GoogleIntegrationSetting(HorillaCoreModel):
    """Per-company admin toggle to enable/disable Google Calendar integration for users."""

    CACHE_NAMESPACE = "calendar.google_integration"

    is_google_calendar_enabled = models.BooleanField(
        default=False,
        verbose_name=_("Enable Google Calendar Integration"),
        help_text=_(
            "When enabled, users in this company can connect their Google Calendar."
        ),
    )
    access_type = models.CharField(
        max_length=10,
        choices=ACCESS_CHOICES,
        default=ACCESS_ALL,
        verbose_name=_("Access Type"),
        help_text=_("Who can connect Google Calendar."),
    )
    allowed_roles = models.ManyToManyField(
        Role,
        blank=True,
        verbose_name=_("Allowed Roles"),
        related_name="google_integrations",
    )
    allowed_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        verbose_name=_("Allowed Users"),
        related_name="google_integrations",
    )

    class Meta:
        """Company-scoped singleton metadata for enabling Google Calendar."""

        verbose_name = _("Google Integration Setting")
        verbose_name_plural = _("Google Integration Settings")

    def user_has_access(self, user):
        """Return True if *user* is allowed to use Google Calendar integration."""
        if not self.is_google_calendar_enabled:
            return False
        if self.access_type == ACCESS_ALL:
            return True
        if self.access_type == ACCESS_ROLES:
            user_role_id = getattr(user, "role_id", None)
            if not user_role_id:
                return False
            return self.allowed_roles.filter(pk=user_role_id).exists()
        if self.access_type == ACCESS_USERS:
            return self.allowed_users.filter(pk=user.pk).exists()
        return False

    @classmethod
    def get_for_company(cls, company):
        """Return the setting row for ``company``, creating it if missing."""
        if not company:
            return None
        setting, _created = cls.all_objects.get_or_create(company=company)
        return setting

    @classmethod
    def user_can_access(cls, user, company, request=None):
        """Return True if integration is enabled and ``user`` is allowed for ``company``."""
        setting = cls._get_cached_setting(request, company)
        return bool(setting and setting.user_has_access(user))

    @classmethod
    def user_has_menu_access(cls, request=None):
        """Menu condition: integration enabled AND the current user has access."""
        if request is None:
            request = getattr(_thread_local, "request", None)
        if request is None:
            return False
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        company = getattr(user, "company", None)
        if not company:
            return False
        return cls.user_can_access(user, company, request=request)

    @classmethod
    def _get_cached_setting(cls, request, company):
        """
        Resolve the setting row for ``company``.

        Uses request-local cache (same request) then Django cache
        (``cache.get_or_set``, per company) so menu conditions do not
        hit the DB on every page render.
        """
        from horilla.contrib.utils.company_settings_cache import (
            get_or_set_company_setting,
        )

        if not company:
            return None

        company_id = company.pk
        cache_attr = "_google_integration_setting_cache"
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
    def google_calendar_enabled(cls, request=None):
        """Quick check if Google Calendar integration is enabled for a company.

        Accepts a request object (called by the menu system as condition(request))
        or falls back to thread-local request.
        """
        if request is None:
            request = getattr(_thread_local, "request", None)
        if request is None:
            return False
        company = getattr(request.user, "company", None)
        if not company:
            return False
        settings = cls._get_cached_setting(request, company)
        return settings.is_google_calendar_enabled if settings else False

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

    def __str__(self):
        status = _("enabled") if self.is_google_calendar_enabled else _("disabled")
        return f"Google Integration ({status})"


class GoogleCalendarConfig(HorillaCoreModel):
    """Stores per-user Google OAuth2 credentials and access token."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="google_calendar_config",
        verbose_name=_("User"),
    )
    # Parsed client_secret_*.json uploaded by the user
    credentials_json = models.JSONField(
        null=True,
        blank=True,
        verbose_name=_("Credentials JSON"),
    )
    redirect_uri = models.URLField(
        null=True,
        blank=True,
        verbose_name=_("Redirect URI"),
    )
    # Set after OAuth2 flow completes
    google_email = models.EmailField(
        null=True,
        blank=True,
        verbose_name=_("Connected Google Account"),
    )
    token = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_("OAuth Token"),
    )
    # Stored during OAuth dance for CSRF protection; cleared after callback
    oauth_state = models.CharField(
        editable=False,
        max_length=200,
        null=True,
        blank=True,
        verbose_name=_("OAuth State"),
    )
    SYNC_DIRECTION_CHOICES = [
        ("horilla_to_google", _("One-way: App → Google Calendar")),
        ("both", _("Two-way: App ↔ Google Calendar")),
    ]
    sync_direction = models.CharField(
        max_length=20,
        choices=SYNC_DIRECTION_CHOICES,
        default="both",
        verbose_name=_("Sync Direction"),
    )
    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Last Synced At"),
    )
    # Google incremental sync token — avoids full re-fetch on every pull
    google_sync_token = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        verbose_name=_("Google Sync Token"),
    )
    # Google Calendar Push Notification (watch channel) fields
    watch_channel_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("Watch Channel ID"),
    )
    watch_resource_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("Watch Resource ID"),
    )
    watch_expiration = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Watch Channel Expiration"),
    )
    watch_token = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name=_("Watch Channel Token"),
    )

    class Meta:
        """Verbose names for the per-user Google Calendar OAuth row."""

        verbose_name = _("Google Calendar Configuration")
        verbose_name_plural = _("Google Calendar Configurations")

    def __str__(self):
        return f"{self.user} — {self.google_email or 'not connected'}"

    def is_configured(self):
        """True if the user has uploaded their credentials JSON."""
        return bool(self.credentials_json)

    def is_connected(self):
        """True if the user has completed OAuth and holds an access token."""
        return bool(self.token and self.token.get("access_token"))

    def _web_block(self):
        creds = self.credentials_json or {}
        return creds.get("web") or creds.get("installed") or {}

    def get_client_id(self):
        """OAuth client identifier from uploaded credentials."""
        return self._web_block().get("client_id", "")

    def get_client_secret(self):
        """OAuth client secret from uploaded credentials."""
        return self._web_block().get("client_secret", "")

    def get_auth_uri(self):
        """Authorization endpoint URL from credentials, or Google's default."""
        return self._web_block().get(
            "auth_uri", "https://accounts.google.com/o/oauth2/v2/auth"
        )

    def get_token_uri(self):
        """Token endpoint URL from credentials, or Google's default."""
        return self._web_block().get("token_uri", "https://oauth2.googleapis.com/token")
