"""
Models for the utilities module.

This file defines the database models used in the application.
These models represent the structure of the data and include any
relationships, constraints, and behaviors.
"""

# Third-party imports (Django)
from django.conf import settings

from horilla.contrib.core.models import HorillaContentType, HorillaCoreModel
from horilla.contrib.mail.models import HorillaMailConfiguration
from horilla.contrib.utils.methods import render_template
from horilla.core.exceptions import ValidationError

# First party imports (Horilla)
from horilla.db import models
from horilla.registry.limiters import limit_content_types
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _


class Activity(HorillaCoreModel):
    """
    Model representing various types of activities such as events, meetings, tasks, and log calls.
    """

    # Lets the generic history/audit log display (history_display.py) label a
    # CREATE entry as e.g. "Task added" via get_activity_type_display(), instead
    # of hardcoding Activity's type values there.
    HISTORY_CREATE_TYPE_FIELD = "activity_type"

    ACTIVITY_TYPES = [
        ("event", _("Event")),
        ("meeting", _("Meeting")),
        ("task", _("Task")),
        ("log_call", _("Log Call")),
    ]
    STATUS_CHOICES = [
        ("not_started", _("Not Started")),
        ("scheduled", _("Scheduled")),
        ("in_progress", _("In Progress")),
        ("waiting", _("Waiting on Someone")),
        ("completed", _("Completed")),
        ("cancelled", _("Cancelled")),
        ("deferred", _("Deferred")),
    ]
    TASK_PRIORITY_CHOICES = [
        ("high", _("High")),
        ("medium", _("Medium")),
        ("low", _("Low")),
    ]
    CALL_TYPE_CHOICES = [
        ("inbound", _("Inbound")),
        ("outbound", _("Outbound")),
    ]
    MEETING_PROVIDER_CHOICES = [
        ("zoom", _("Zoom")),
        ("google_meet", _("Google Meet")),
        ("ms_teams", _("Microsoft Teams")),
    ]

    # Common fields from GeneralActivity
    subject = models.CharField(max_length=100, verbose_name=_("Subject"))
    description = models.TextField(blank=True, null=True, verbose_name=_("Description"))
    activity_type = models.CharField(
        max_length=20, choices=ACTIVITY_TYPES, verbose_name=_("Activity Type")
    )
    content_type = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        limit_choices_to=limit_content_types("activity_related_models"),
        verbose_name=_("Related Content Type"),
        null=True,
        blank=True,
    )

    object_id = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_("Related To")
    )
    related_object = models.GenericForeignKey("content_type", "object_id")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
        verbose_name=_("Status"),
    )

    title = models.CharField(
        max_length=255, null=True, blank=True, verbose_name=_("Title")
    )
    start_datetime = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Start Date")
    )
    end_datetime = models.DateTimeField(
        null=True, blank=True, verbose_name=_("End Date")
    )
    location = models.CharField(
        max_length=100, null=True, blank=True, verbose_name=_("Location")
    )
    is_online = models.BooleanField(default=False, verbose_name=_("Online Meeting"))
    meeting_provider = models.CharField(
        max_length=30,
        choices=MEETING_PROVIDER_CHOICES,
        null=True,
        blank=True,
        verbose_name=_("Meeting Provider"),
    )
    meeting_url = models.URLField(
        max_length=2000, null=True, blank=True, verbose_name=_("Meeting Link")
    )
    is_all_day = models.BooleanField(default=False, verbose_name=_("All Day"))
    assigned_to = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="assigned_activities",
        blank=True,
        verbose_name=_("Assigned To"),
    )
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="activity_participants",
        blank=True,
        verbose_name=_("Participants"),
    )
    meeting_host = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="hosted_activities",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Meeting Host"),
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="owned_activities",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Activity Owner"),
    )
    # Task-specific
    task_priority = models.CharField(
        max_length=50,
        choices=TASK_PRIORITY_CHOICES,
        null=True,
        blank=True,
        verbose_name=_("Priority"),
    )
    due_datetime = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Due Date")
    )
    recipient_email = models.EmailField(
        null=True, blank=True, verbose_name=_("Recipient Email")
    )

    # LogCall-specific
    call_duration_display = models.CharField(
        max_length=20, null=True, blank=True, verbose_name=_("Call Duration")
    )
    call_duration_seconds = models.IntegerField(
        null=True, blank=True, verbose_name=_("Call Duration (seconds)")
    )
    call_type = models.CharField(
        max_length=50,
        choices=CALL_TYPE_CHOICES,
        null=True,
        blank=True,
        verbose_name=_("Call Type"),
    )
    notes = models.TextField(null=True, blank=True, verbose_name=_("Notes"))
    google_event_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Google Calendar Event ID"),
    )
    call_purpose = models.CharField(
        max_length=100, null=True, blank=True, verbose_name=_("Call Purpose")
    )

    # Meeting extras
    external_participants = models.JSONField(
        default=list, blank=True, verbose_name=_("External Participants")
    )
    REMINDER_CHOICES = [
        ("", _("No Reminder")),
        ("5", _("5 minutes before")),
        ("10", _("10 minutes before")),
        ("15", _("15 minutes before")),
        ("30", _("30 minutes before")),
        ("60", _("1 hour before")),
        ("1440", _("1 day before")),
    ]
    reminder = models.CharField(
        max_length=10,
        choices=REMINDER_CHOICES,
        blank=True,
        null=True,
        verbose_name=_("Reminder"),
    )
    mail_template = models.ForeignKey(
        "mail.HorillaMailTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_activities",
        verbose_name=_("Invitation Email Template"),
    )

    OWNER_FIELDS = ["owner", "assigned_to"]
    SORT_FIELD_MAPPING = {"related_object_col": "related_object"}

    class Meta:
        """
        Meta class for Activity model
        """

        verbose_name = _("Activity")
        verbose_name_plural = _("Activities")
        indexes = [
            models.Index(fields=["activity_type"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["start_datetime"]),
            models.Index(fields=["due_datetime"]),
        ]

    def __str__(self):
        return self.subject or self.title or f"{self.activity_type} {self.pk}"

    def clean(self):
        """Ensure a mail server is configured when an invitation email template is set."""
        super().clean()
        if (
            self.mail_template_id
            and not HorillaMailConfiguration.objects.filter(
                mail_channel="outgoing"
            ).exists()
        ):
            raise ValidationError(
                {
                    "mail_template": _(
                        "No outgoing mail configuration is set up. "
                        "Please configure a mail server before selecting an "
                        "invitation email template."
                    )
                }
            )

    def save(self, *args, **kwargs):
        if self.activity_type == "log_call" and self.call_duration_display:
            try:
                h, m, s = map(int, self.call_duration_display.split(":"))
                self.call_duration_seconds = h * 3600 + m * 60 + s
            except Exception:
                self.call_duration_seconds = None
        super().save(*args, **kwargs)

    def get_detail_url(self):
        """
        This method to get detail url
        """
        return reverse_lazy("activity:activity_detail", kwargs={"pk": self.pk})

    def get_edit_url(self):
        """
        Return the URL for editing the activity based on its type.
        """
        url_map = {
            "event": "activity:event_update_form",
            "meeting": "activity:meeting_update_form",
            "task": "activity:task_update_form",
            # "email": "activity:event_update_form",
            "log_call": "activity:call_update_form",
        }
        return reverse_lazy(url_map[self.activity_type], kwargs={"pk": self.pk})

    def get_activity_edit_url(self):
        """
        Return the URL for editing the activity using the generic activity edit form.
        """
        return reverse_lazy("activity:activity_edit_form", kwargs={"pk": self.pk})

    def get_delete_url(self):
        """
        Return the URL for deleting the activity.
        """
        return reverse_lazy("activity:delete_activity", kwargs={"pk": self.pk})

    def get_start_date(self):
        """
        Return the start date or due date or created at date based on activity type.
        """
        if self.activity_type in ["event", "meeting"] and self.is_all_day:
            return _("All Day Event")
        return self.start_datetime or self.due_datetime or self.created_at

    def get_end_date(self):
        """
        Return the end date or due date or created at date based on activity type.
        """
        if self.activity_type in ["event", "meeting"] and self.is_all_day:
            return _("All Day Event")
        return self.end_datetime or self.due_datetime or self.created_at

    def meeting_link_col(self):
        """Return a clickable Join link if this is an online meeting with a URL."""
        if self.is_online and self.meeting_url:
            return render_template(
                path="meeting_link_col.html",
                context={"meeting_url": self.meeting_url},
            )
        return "—"

    def related_object_col(self):
        """Return the related record for list views, linked when the viewer may open it."""
        from horilla.contrib.utils.middlewares import get_current_request

        from .methods import get_related_record_url

        related = self.related_object
        if related is None:
            return ""
        request = get_current_request()
        return render_template(
            path="related_object_col.html",
            context={
                "name": str(related),
                "detail_url": get_related_record_url(
                    related, getattr(request, "user", None)
                ),
            },
        )

    def get_meeting_url_display(self):
        """Return plain-text meeting URL for kanban cards (no HTML)."""
        if self.is_online and self.meeting_url:
            return self.meeting_url
        return "—"

    def status_col(self):
        """
        Return an inline status select dropdown for the all-activity list view.
        """
        return render_template(
            path="activity_status_col.html",
            context={
                "instance": self,
                "status_choices": self.STATUS_CHOICES,
            },
        )

    def get_status_update_html(self):
        """
        Return an inline status dropdown for list views.
        Callers must set _status_update_url on the instance before rendering.
        """
        url = getattr(self, "_status_update_url", None)
        if not url:
            return self.get_status_display()
        return render_template(
            path="history_task_status_col.html",
            context={
                "instance": self,
                "url": url,
                "status_choices": self.STATUS_CHOICES,
            },
        )
