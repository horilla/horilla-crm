"""
model for horilla notifications
"""

# Third-party imports (Django)
from django.conf import settings

from horilla.contrib.core.models import HorillaContentType, HorillaCoreModel
from horilla.contrib.utils.methods import has_xss, sanitize_html, sanitize_plain_text
from horilla.core.exceptions import ValidationError

# First-party (Horilla)
from horilla.db import models
from horilla.registry.limiters import limit_content_types
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _


class Notification(models.Model):
    """
    Model representing a notification for a user.

    Notifications are messages sent to users, typically triggered by system
    events or actions from other users. Each notification can be marked as
    read and may include a URL for navigation.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    message = models.TextField()
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_notifications",
    )
    url = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read = models.BooleanField(default=False, db_index=True)
    content_type = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notification_related_objects",
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    related_object = models.GenericForeignKey("content_type", "object_id")

    # Notifications are system messages, not part of a record's own story, so
    # they are kept out of the record's History tab.
    HISTORY_EXCLUDE_FROM_RELATED = True

    def __str__(self):
        return f"Notification for {self.user.username}: {self.message}"

    def clean(self):
        """Sanitize HTML fields and reject XSS in plain-text fields."""
        if self.message:
            self.message = sanitize_html(self.message)
        if self.url and has_xss(self.url):
            raise ValidationError(
                {
                    "url": _(
                        "URL contains potentially dangerous content. "
                        "Please remove any scripts or malicious code."
                    )
                }
            )

    def save(self, *args, **kwargs):
        """Override save to ensure clean() is called for validation."""
        self.full_clean()
        return super().save(*args, **kwargs)

    class Meta:
        """Meta options for the Notification model."""

        verbose_name = _("Notification")
        verbose_name_plural = _("Notifications")
        ordering = ["-created_at"]


class NotificationSoundPreference(models.Model):
    """Per-user preference for notification sound (mute/unmute)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_sound_preference",
    )
    sound_muted = models.BooleanField(default=False)

    def __str__(self):
        state = _("muted") if self.sound_muted else _("unmuted")
        return f"{self.user.username} – {state}"

    class Meta:
        """Django model options for notification sound preferences."""

        verbose_name = _("Notification Sound Preference")
        verbose_name_plural = _("Notification Sound Preferences")


class NotificationTemplate(HorillaCoreModel):
    """
    Model representing a notification template.
    """

    title = models.CharField(max_length=100, verbose_name=_("Template Title"))
    message = models.TextField(verbose_name=_("Message"))
    content_type = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        limit_choices_to=limit_content_types("notification_template_models"),
        verbose_name=_("Related Model"),
    )

    # Extra controls / editor toolbar for fields in the dynamic create popup
    dynamic_create_field_tools = {
        "message": [{"tool": "insert_field", "include": "#id_content_type"}]
    }
    dynamic_create_rich_text_presets = {"message": "basic"}

    def __str__(self) -> str:
        return f"{self.title}"

    def clean(self):
        """Sanitize HTML fields at the model level."""
        if self.title:
            self.title = sanitize_plain_text(self.title)
        if self.message:
            self.message = sanitize_html(self.message)

    def save(self, *args, **kwargs):
        """Enforce clean() on every save path (admin, API, shell, curl)."""
        self.full_clean()
        return super().save(*args, **kwargs)

    class Meta:
        """Meta options for the mail template model."""

        verbose_name = _("Notification Template")
        verbose_name_plural = _("Notification Templates")
        unique_together = ["title", "company"]

    def get_related_model(self):
        """Return the related model's verbose name."""
        if self.content_type:
            return self.content_type.model_class()._meta.verbose_name
        return _("General")

    def get_edit_url(self):
        """Get the URL to edit this notification template."""
        return reverse_lazy(
            "notifications:notification_template_update_view",
            kwargs={"pk": self.pk},
        )

    def get_delete_url(self):
        """Get the URL to delete this notification template."""
        return reverse_lazy(
            "notifications:notification_template_delete_view",
            kwargs={"pk": self.pk},
        )

    def get_detail_view_url(self):
        """Get the URL to view this notification template."""
        return reverse_lazy(
            "notifications:notification_template_detail_view",
            kwargs={"pk": self.pk},
        )
