"""Models for Horilla Mail App"""

# Standard library imports
import mimetypes
import re
import uuid
from datetime import timedelta

# Third-party imports (Django)
from django.conf import settings
from django.template import engines

from horilla.contrib.core.models import HorillaContentType, HorillaCoreModel
from horilla.contrib.utils.methods import (
    render_template,
    sanitize_html,
    sanitize_plain_text,
)
from horilla.contrib.utils.middlewares import _thread_local
from horilla.core.exceptions import ValidationError

# First-party imports (Horilla)
from horilla.db import models
from horilla.registry.limiters import limit_content_types
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _
from horilla.utils.upload import upload_path

from .encryption_utils import decrypt_password

# Local imports
from .fields import EncryptedCharField


class HorillaMailConfiguration(HorillaCoreModel):
    """
    SingletonModel to keep the mail server configurations
    """

    TYPE_CHOICES = [
        ("mail", _("Mail")),
        ("outlook", _("Outlook")),
    ]

    MAIL_CHANNELS = [
        ("incoming", _("Incoming")),
        ("outgoing", _("Outgoing")),
    ]

    type = models.CharField(
        max_length=255, choices=TYPE_CHOICES, verbose_name=_("Type")
    )
    mail_channel = models.CharField(
        max_length=20,
        choices=MAIL_CHANNELS,
        db_index=True,
        verbose_name=_("Mail Channel"),
        help_text=_(
            _(
                "Specifies whether this configuration handles incoming,"
                "outgoing, or both types of emails."
            )
        ),
    )

    host = models.CharField(
        null=True,
        max_length=256,
        verbose_name=_("Host"),
        blank=True,
        help_text=_("Your mail provider's SMTP server, e.g. smtp.gmail.com."),
    )
    port = models.SmallIntegerField(
        null=True,
        verbose_name=_("Port"),
        blank=True,
        help_text=_("Usually 587 (with TLS) or 465 (with SSL)."),
    )
    from_email = models.EmailField(
        null=True,
        max_length=256,
        verbose_name=_("Default From Mail"),
        help_text=_(
            "The email address people see as the sender. For Gmail or Outlook, "
            "use the address you log in with, or an alias you have added and verified."
        ),
    )

    username = models.CharField(
        null=True,
        max_length=256,
        verbose_name=_("Email Host Username"),
        blank=True,
        help_text=_(
            "The account used to log in to the mail server, usually your full "
            "email address."
        ),
    )

    display_name = models.CharField(
        blank=True,
        null=True,
        max_length=256,
        verbose_name=_("Display Name"),
        help_text=_("The sender name people see, e.g. Acme HR."),
    )
    password = EncryptedCharField(
        null=True,
        max_length=512,
        verbose_name=_("Email Authentication Password"),
        blank=True,
    )

    use_tls = models.BooleanField(
        default=True,
        verbose_name=_("Use TLS"),
        blank=True,
        null=True,
        help_text=_("Encrypts the connection. Choose Yes for port 587."),
    )

    use_ssl = models.BooleanField(
        default=False,
        verbose_name=_("Use SSL"),
        blank=True,
        null=True,
        help_text=_(
            "Encrypts the connection from the start. Choose Yes for port 465, "
            "and keep Use TLS on No."
        ),
    )

    fail_silently = models.BooleanField(
        default=False,
        verbose_name=_("Fail Silently"),
        blank=True,
        null=True,
        help_text=_(
            "No (recommended): you see an error when an email can't be sent. "
            "Yes: errors are hidden so users aren't interrupted, but failed emails "
            "go unnoticed."
        ),
    )

    is_primary = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_("Primary Mail Server"),
        help_text=_("Use this server by default when sending emails."),
    )
    use_dynamic_display_name = models.BooleanField(
        default=True,
        verbose_name=_("Dynamic Display Name"),
        help_text=_(
            "On: emails show the Display Name below as the sender name. "
            "Off: emails show the name of the person who triggered them."
        ),
    )

    timeout = models.SmallIntegerField(
        null=True,
        verbose_name=_("Email Send Timeout (seconds)"),
        help_text=_("How long to wait for the mail server before giving up."),
    )

    outlook_client_id = models.CharField(
        max_length=200,
        verbose_name=_("Client ID"),
        blank=True,
        null=True,
        help_text=_("The Application (client) ID from your Azure app registration."),
    )
    outlook_client_secret = EncryptedCharField(
        max_length=512,
        verbose_name=_("Client Secret"),
        blank=True,
        null=True,
        help_text=_("The secret value created for your Azure app."),
    )
    outlook_tenant_id = models.CharField(
        max_length=200,
        verbose_name=_("Tenant ID"),
        blank=True,
        null=True,
        help_text=_("The Directory (tenant) ID of your Microsoft organisation."),
    )
    outlook_redirect_uri = models.URLField(
        verbose_name=_("Redirect URI"),
        blank=True,
        null=True,
        help_text=_("Must match the redirect URI set in your Azure app."),
    )
    outlook_authorization_url = models.URLField(
        verbose_name=_("OAuth Authorization Endpoint"),
        blank=True,
        null=True,
        help_text=_("Microsoft's sign-in page address. Leave the default."),
    )
    outlook_token_url = models.URLField(
        verbose_name=_("OAuth Token Endpoint"),
        blank=True,
        null=True,
        help_text=_("Microsoft's token address. Leave the default."),
    )
    outlook_api_endpoint = models.URLField(
        verbose_name=_("Microsoft Graph API Endpoint"),
        blank=True,
        null=True,
        help_text=_("Microsoft's mail API address. Leave the default."),
    )
    token = models.JSONField(default=dict, blank=True, null=True)
    oauth_state = models.CharField(
        editable=False, max_length=100, null=True, blank=True
    )
    last_refreshed = models.DateTimeField(
        null=True, editable=False, blank=True, verbose_name=_("Token Last Refreshed")
    )

    def __init__(self, *args, **kwargs):
        """Initialize the model instance."""
        super().__init__(*args, **kwargs)
        self._saving = False

    def custom_actions(self):
        """Return custom action buttons for the admin interface."""
        return render_template(path="mail_actions.html", context={"instance": self})

    def get_detail_url(self):
        """Return the detail modal URL for this mail configuration."""
        return reverse_lazy("mail:mail_config_detail_view", kwargs={"pk": self.pk})

    def get_edit_url(self):
        """Return the edit URL based on channel and type."""
        if self.type == "outlook":
            return reverse_lazy(
                "mail:outlook_mail_server_update_view", kwargs={"pk": self.pk}
            )
        if self.mail_channel == "incoming":
            return reverse_lazy(
                "mail:incoming_mail_server_update_view", kwargs={"pk": self.pk}
            )
        return reverse_lazy("mail:mail_server_update_view", kwargs={"pk": self.pk})

    def get_delete_url(self):
        """Return the delete URL for this mail configuration."""
        return reverse_lazy("mail:mail_server_delete_view", kwargs={"pk": self.pk})

    def clean(self):
        """Validate that company is set when the configuration is not primary."""
        if not self.company and not self.is_primary:
            raise ValidationError({"company": _("This field is required")})

    def __str__(self):
        return str(self.username)

    def get_decrypted_password(self):
        """
        Get decrypted password.
        """
        if self.password:
            return decrypt_password(self.password)
        return None

    def get_decrypted_client_secret(self):
        """
        Get decrypted Outlook client secret - ONLY for OAuth operations.
        """
        if self.outlook_client_secret:
            return decrypt_password(self.outlook_client_secret)
        return None

    def save(self, *args, **kwargs):
        """
        Enforce only one primary mail configuration across the system.
        Automatically makes the first entry primary.
        """
        if self._saving:
            return super().save(*args, **kwargs)

        self._saving = True
        try:
            if self.type == "outlook" and not self.from_email and self.username:
                self.from_email = self.username
            if not HorillaMailConfiguration.objects.exclude(pk=self.pk).exists():
                self.is_primary = True
            elif self.is_primary:
                HorillaMailConfiguration.objects.exclude(pk=self.pk).filter(
                    is_primary=True
                ).update(is_primary=False)
            return super().save(*args, **kwargs)
        finally:
            self._saving = False

    class Meta:
        """Meta options for the mail configuration model."""

        verbose_name = _("Mail Configuration")
        verbose_name_plural = _("Mail Configurations")


class HorillaMail(HorillaCoreModel):
    """
    Model to store each email details
    """

    # Lets the generic history/audit log display (history_display.py) label a
    # CREATE entry as e.g. "Draft added"/"Sent added" via get_mail_status_display(),
    # instead of hardcoding HorillaMail's status values there.
    HISTORY_CREATE_TYPE_FIELD = "mail_status"
    # The create row reads only "New Draft created ... by <user>", without the
    # sender, tracking uid etc.
    HISTORY_CREATE_HIDE_FIELDS = True
    # A mail is created as a draft and then sent/delivered/bounced, so show
    # those status changes in the parent's history instead of leaving it
    # reading "Draft" forever.
    HISTORY_LINKED_UPDATE_FIELDS = ("mail_status",)
    # The draft is only a placeholder created when the compose window opens;
    # once it is sent/failed/bounced the history shows just that outcome.
    HISTORY_TRANSIENT_CREATE = ("mail_status", "draft")
    # "delivered" is what the mail is set to once it has been sent.
    HISTORY_STATUS_LABELS = {"delivered": _("Sent")}

    MAIL_STATUS_CHOICES = [
        ("draft", _("Draft")),
        ("scheduled", _("Scheduled")),
        ("sent", _("Sent")),
        ("delivered", _("Delivered")),
        ("bounced", _("Bounced")),
        ("opened", _("Opened")),
        ("failed", _("Failed")),
    ]

    sender = models.ForeignKey(
        HorillaMailConfiguration,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sent_mails",
        verbose_name=_("From"),
    )

    to = models.TextField(
        help_text=_("Comma separated recipient email addresses"),
        verbose_name=_("Send To"),
        blank=True,  # Allow blank for drafts, validate when sending
    )
    cc = models.TextField(blank=True, null=True, verbose_name=_("Cc"))
    bcc = models.TextField(blank=True, null=True, verbose_name=_("Bcc"))
    subject = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_("Subject")
    )
    body = models.TextField(blank=True, null=True, verbose_name=_("Body"))
    rendered_subject = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text=_("Rendered subject saved at send time."),
    )
    rendered_body = models.TextField(
        blank=True,
        null=True,
        help_text=_("Rendered body saved at send time."),
    )
    content_type = models.ForeignKey(HorillaContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    related_to = models.GenericForeignKey("content_type", "object_id")
    mail_status = models.CharField(
        max_length=20,
        choices=MAIL_STATUS_CHOICES,
        default="draft",
        db_index=True,
        verbose_name=_("Mail Status"),
    )
    mail_status_message = models.TextField(blank=True, null=True)
    sent_at = models.DateTimeField(blank=True, null=True, verbose_name=_("Sent At"))
    delivered_at = models.DateTimeField(blank=True, null=True)
    bounced_at = models.DateTimeField(blank=True, null=True)
    opened_at = models.DateTimeField(blank=True, null=True)
    tracking_uid = models.UUIDField(
        default=uuid.uuid4, unique=True, editable=False, null=True, blank=True
    )
    scheduled_at = models.DateTimeField(
        blank=True,
        null=True,
        db_index=True,
        help_text=_("When the mail should be sent (for scheduled mails)."),
    )
    send_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_mails_by",
        verbose_name=_("Sent By"),
    )

    def history_source_col(self):
        """ "Related To" cell: Self for the listed record's own rows, else a link to the source record."""
        from horilla.contrib.generics.history import history_source_pill

        return history_source_pill(self)

    def __str__(self):
        return f"[{self.mail_status}] {self.subject}"

    def render_subject(self, context=None):
        """
        Render the subject template with the given context.
        Sanitizes output to remove newlines/carriage returns (RFC 5322 prohibits
        these in email header values).
        """

        if not context:
            request = getattr(_thread_local, "request", None)
            context = {
                "instance": self.related_to,
                "user": getattr(request, "user", None),
                "active_company": request.active_company,
                "request": request,
            }
        django_engine = engines["django"]
        template_str = (self.subject or "").strip()
        if template_str:
            template_str = "{% load horilla_tags %}\n" + template_str
        rendered = django_engine.from_string(template_str).render(context)
        # Remove newlines/carriage returns - RFC 5322 forbids them in headers
        return re.sub(r"\s+", " ", rendered).strip()

    def render_body(self, context=None):
        """
        Render the body template with the given context.
        """

        if not context:
            request = getattr(_thread_local, "request", None)
            context = {
                "instance": self.related_to,
                "user": getattr(request, "user", None),
                "active_company": request.active_company,
                "request": request,
            }
        django_engine = engines["django"]
        template_str = (self.body or "").strip()
        if template_str:
            template_str = "{% load horilla_tags %}\n" + template_str
        return django_engine.from_string(template_str).render(context)

    def clean(self):
        """Sanitize XSS content from mail fields."""
        if self.subject:
            self.subject = sanitize_plain_text(self.subject)
        if self.body:
            self.body = sanitize_html(self.body)

    def save(self, *args, **kwargs):
        """Override save to ensure clean() is called for validation."""
        # Set updated_by before validation (parent save will also set it, but we need it for validation)
        request = getattr(_thread_local, "request", None)
        if request:
            user = getattr(request, "user", None)
            if user and not user.is_anonymous:
                if not self.pk:
                    # New object - set both created_by and updated_by
                    if not self.created_by:
                        self.created_by = user
                    self.updated_by = user
                else:
                    # Existing object - only update updated_by
                    self.updated_by = user

        # Only validate if required fields are set (to avoid validation errors for drafts)
        # For drafts, to field might be empty, so we skip full_clean for drafts
        if self.mail_status != "draft" or self.to:
            # created_by/updated_by (no request user, e.g. system-triggered mail
            # like assignment-rule notifications) and sender (no mail configuration
            # set up for the company) are legitimately nullable here, so they're
            # excluded from full_clean() rather than made required on the model.
            self.full_clean(exclude=["created_by", "updated_by", "sender"])
        else:
            # For drafts with empty to, just call clean() for XSS validation
            self.clean()

        return super().save(*args, **kwargs)

    def get_edit_url(self):
        """
        Get the URL to edit this mail.
        """
        return reverse_lazy("mail:send_mail_draft_view", kwargs={"pk": self.pk})

    def get_view_url(self):
        """
        Get the URL to view this mail.
        """
        return reverse_lazy("mail:sent_preview_mail", kwargs={"pk": self.pk})

    def get_delete_url(self):
        """
        Get the URL to delete this mail.
        """
        return reverse_lazy("mail:mail_delete", kwargs={"pk": self.pk})

    def get_reschedule_url(self):
        """
        Get the URL to reschedule this mail.
        """
        return reverse_lazy("mail:reschedule_mail_form", kwargs={"pk": self.pk})

    class Meta:
        """Meta options for the mail model."""

        verbose_name = _("Mail")
        verbose_name_plural = _("Mails")


class IncomingMail(HorillaCoreModel):
    """
    A single message fetched from an incoming mailbox (IMAP or Outlook).

    This is generic mail infrastructure and must stay free of any dependency
    on CRM models (Lead/Contact) - see horilla/contrib/mail/actions.py for
    how other apps contribute "what can be done with this email" actions
    without this app importing them. Which actions have already been run
    against a row is tracked in the inherited additional_info field under the
    "converted_actions" key (a list of action keys), not a dedicated column.
    """

    mail = models.ForeignKey(
        HorillaMailConfiguration,
        on_delete=models.SET_NULL,
        null=True,
        related_name="incoming_mails",
        verbose_name=_("Mailbox"),
    )
    sender_email = models.EmailField(verbose_name=_("Sender Email"))
    sender_name = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_("Sender Name")
    )
    subject = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_("Subject")
    )
    body = models.TextField(blank=True, null=True, verbose_name=_("Body"))
    is_html_body = models.BooleanField(
        default=False,
        verbose_name=_("Is HTML Body"),
        help_text=_(
            "True if body holds sanitized HTML (rendered as-is in the "
            "preview); False if it is plain text (rendered with line "
            "breaks preserved)."
        ),
    )
    cc = models.TextField(blank=True, null=True, verbose_name=_("Cc"))
    message_id = models.CharField(max_length=998, unique=True, db_index=True)
    in_reply_to = models.CharField(max_length=998, blank=True, null=True)
    references = models.TextField(blank=True, null=True)
    received_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Received At"))

    def __str__(self):
        return f"{self.sender_email}: {self.subject}"

    def get_delete_url(self):
        """
        Return the delete URL for this incoming mail, for
        HorillaSingleDeleteView's generic delete-confirm flow.

        Deleting an IncomingMail is a genuine hard delete (no permanent
        clutter kept around) - its attachments cascade-delete with it.
        DeletedIncomingMessageId.message_id is what actually prevents the
        fetch task from recreating it later; see that model and
        signals.py's pre_delete receiver for how that's preserved
        independently of this row's own lifetime.
        """
        return reverse_lazy("mail:inbox_delete_view", kwargs={"pk": self.pk})

    def clean(self):
        """
        Sanitize XSS content from mail fields. This is a model-level backstop
        on top of the Celery fetch task's own sanitize_html() call - any
        future code path that creates/edits an IncomingMail row (an admin
        action, a management command, a migration) gets the same protection
        without having to remember to sanitize first. Safe to call more than
        once since sanitize_html is idempotent.

        Only the HTML body needs active sanitization here: a plain-text body
        is never marked |safe in the preview template, so Django's default
        autoescaping already neutralizes any markup in it without needing to
        strip characters out of what may be genuine plain-text content (e.g.
        a quoted "<noreply@example.com>" address).
        """
        if self.subject:
            self.subject = sanitize_plain_text(self.subject)
        if self.body and self.is_html_body:
            self.body = sanitize_html(self.body)

    def save(self, *args, **kwargs):
        """Override save to ensure clean() always runs, like HorillaMail does."""
        self.clean()
        return super().save(*args, **kwargs)

    def get_view_url(self):
        """Return the detail/preview modal URL for this incoming mail."""
        return reverse_lazy("mail:inbox_preview_view", kwargs={"pk": self.pk})

    def get_converted_actions(self):
        """Return the list of action keys already run against this message."""
        return (self.additional_info or {}).get("converted_actions", [])

    def mark_action_converted(self, key):
        """Record that the given action key has been run, if not already."""
        info = dict(self.additional_info or {})
        actions = list(info.get("converted_actions", []))
        if key not in actions:
            actions.append(key)
        info["converted_actions"] = actions
        self.additional_info = info
        self.save(update_fields=["additional_info"])

    class Meta:
        """Meta options for the incoming mail model."""

        verbose_name = _("Incoming Mail")
        verbose_name_plural = _("Incoming Mails")
        ordering = ["-received_at"]


TOMBSTONE_RELEVANCE_WINDOW = timedelta(days=7)


class DeletedIncomingMessageId(models.Model):
    """
    A permanent, minimal record of a Message-ID the user explicitly deleted
    from the Inbox, independent of the full IncomingMail row's lifetime.

    Deleting an IncomingMail is a genuine hard delete (no indefinitely
    accumulating "soft-deleted" rows cluttering the table - see
    get_delete_url() above), so nothing would otherwise stop the fetch task
    from recreating it the next time it polls the same still-intact mailbox.
    This tiny table (just the Message-ID string) is intentionally decoupled
    from IncomingMail's own storage/attachments/body so deleting the real
    content never has to be weighed against "but then it'll just come back" -
    the two concerns (storage cost vs. never-refetch) are solved separately.

    Rows older than TOMBSTONE_RELEVANCE_WINDOW are pruned by a daily task
    (see tasks.py's prune_expired_deleted_message_ids) since a tombstone that
    old can no longer protect against anything - the fetch task's own search
    window is far shorter.
    """

    message_id = models.CharField(max_length=998, unique=True, db_index=True)
    deleted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.message_id

    class Meta:
        """Meta options for the deleted-message tombstone model."""

        verbose_name = _("Deleted Incoming Message ID")
        verbose_name_plural = _("Deleted Incoming Message IDs")


class HorillaMailAttachment(HorillaCoreModel):
    """
    Each email can have multiple attachments.

    An attachment belongs to exactly one of mail (an outgoing HorillaMail) or
    incoming_mail (a fetched IncomingMail) - never both.
    """

    mail = models.ForeignKey(
        HorillaMail,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
    )
    incoming_mail = models.ForeignKey(
        "IncomingMail",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
    )
    file = models.FileField(upload_to=upload_path)
    file_size = models.PositiveIntegerField(blank=True, null=True)
    mime_type = models.CharField(max_length=100, blank=True, null=True)
    is_inline = models.BooleanField(default=False)
    content_id = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        owner = self.mail_id or self.incoming_mail_id
        return f"Attachment for Mail {owner}: {self.file.name}"

    def file_name(self):
        """Return the name of the file."""
        return self.file.name.split("/")[-1]

    def clean(self):
        """
        Enforce "exactly one of mail/incoming_mail is set" at the
        application level too, so a form/admin save gets a clear
        ValidationError instead of only failing on the DB CheckConstraint
        below with an opaque IntegrityError.
        """
        if bool(self.mail_id) == bool(self.incoming_mail_id):
            raise ValidationError(
                _(
                    "An attachment must belong to exactly one of an outgoing "
                    "mail or an incoming mail, not both or neither."
                )
            )

    def save(self, *args, **kwargs):
        """Automatically populate file_size and mime_type on save."""
        if self.file:
            self.file_size = self.file.size
            mime, _ = mimetypes.guess_type(self.file.name)
            self.mime_type = mime or "application/octet-stream"
        self.clean()
        super().save(*args, **kwargs)

    class Meta:
        """Meta options for the mail attachment model."""

        verbose_name = _("Mail Attachment")
        verbose_name_plural = _("Mail Attachments")
        constraints = [
            # DB-level backstop for the same "exactly one of mail/
            # incoming_mail" rule enforced in clean() above - catches any
            # row created by raw SQL, a bulk_create() (which skips
            # save()/clean()), or a future code path that forgets to call
            # either.
            models.CheckConstraint(
                condition=(
                    models.Q(mail__isnull=False, incoming_mail__isnull=True)
                    | models.Q(mail__isnull=True, incoming_mail__isnull=False)
                ),
                name="mail_attachment_exactly_one_parent",
            ),
        ]


class HorillaMailTemplate(HorillaCoreModel):
    """Model to store mail templates."""

    title = models.CharField(max_length=100, verbose_name=_("Template Title"))
    subject = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("Subject"),
    )
    body = models.TextField(verbose_name=_("Body"))
    content_type = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        limit_choices_to=limit_content_types("mail_template_models"),
        verbose_name=_("Related Model"),
    )

    # Extra controls rendered beside a field in the dynamic create popup
    dynamic_create_field_tools = {
        "body": [
            {"tool": "insert_field", "include": "#id_content_type"},
            {
                "tool": "preview",
                "url_name": "mail:mail_template_preview_view",
                "include": "#id_body, #id_subject",
            },
        ]
    }

    def __str__(self) -> str:
        return f"{self.title}"

    class Meta:
        """Meta options for the mail template model."""

        verbose_name = _("Mail Template")
        verbose_name_plural = _("Mail Templates")
        unique_together = ["title", "company"]

    def get_edit_url(self):
        """Get the URL to edit this mail template."""
        return reverse_lazy("mail:mail_template_update_view", kwargs={"pk": self.pk})

    def get_delete_url(self):
        """Get the URL to delete this mail template."""
        return reverse_lazy("mail:mail_template_delete_view", kwargs={"pk": self.pk})

    def get_detail_view_url(self):
        """Get the URL to view this mail template."""
        return reverse_lazy("mail:mail_template_detail_view", kwargs={"pk": self.pk})

    def get_related_model(self):
        """Return the related model's verbose name."""
        if self.content_type:
            return self.content_type.model_class()._meta.verbose_name
        return _("General")

    def clean(self):
        """Sanitize XSS content from mail fields."""
        if self.subject:
            self.subject = sanitize_plain_text(self.subject)
        if self.body:
            self.body = sanitize_html(self.body)

    def save(self, *args, **kwargs):
        """Override save to ensure clean() is called for validation."""
        self.full_clean()
        return super().save(*args, **kwargs)
