"""
Models for the whatsapp app.
"""

# Standard library imports
import re
from datetime import timedelta

# Third-party imports (Django)
from django.conf import settings

from horilla.contrib.core.models import HorillaContentType, HorillaCoreModel
from horilla.contrib.mail.encryption_utils import decrypt_password
from horilla.contrib.mail.fields import EncryptedCharField

# First party imports (Horilla)
from horilla.db import models
from horilla.registry.limiters import limit_content_types
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _
from horilla.utils.upload import upload_path

CONVERSATION_STATUS_CHOICES = [
    ("open", _("Open")),
    ("closed", _("Closed")),
]

MESSAGE_DIRECTION_IN = "in"
MESSAGE_DIRECTION_OUT = "out"

MESSAGE_DIRECTION_CHOICES = [
    (MESSAGE_DIRECTION_IN, _("Incoming")),
    (MESSAGE_DIRECTION_OUT, _("Outgoing")),
]

MESSAGE_TYPE_CHOICES = [
    ("text", _("Text")),
    ("template", _("Template")),
    ("image", _("Image")),
    ("document", _("Document")),
    ("video", _("Video")),
    ("audio", _("Audio")),
    ("location", _("Location")),
    ("interactive", _("Interactive")),
]

BOT_MESSAGE_TYPE_TEXT = "text"
BOT_MESSAGE_TYPE_BUTTONS = "buttons"
BOT_MESSAGE_TYPE_LIST = "list"

BOT_MESSAGE_TYPE_CHOICES = [
    (BOT_MESSAGE_TYPE_TEXT, _("Text")),
    (BOT_MESSAGE_TYPE_BUTTONS, _("Reply Buttons")),
    (BOT_MESSAGE_TYPE_LIST, _("List")),
]

MESSAGE_STATUS_PENDING = "pending"
MESSAGE_STATUS_SENT = "sent"
MESSAGE_STATUS_DELIVERED = "delivered"
MESSAGE_STATUS_READ = "read"
MESSAGE_STATUS_FAILED = "failed"
MESSAGE_STATUS_RECEIVED = "received"

MESSAGE_STATUS_CHOICES = [
    (MESSAGE_STATUS_PENDING, _("Pending")),
    (MESSAGE_STATUS_SENT, _("Sent")),
    (MESSAGE_STATUS_DELIVERED, _("Delivered")),
    (MESSAGE_STATUS_READ, _("Read")),
    (MESSAGE_STATUS_FAILED, _("Failed")),
    (MESSAGE_STATUS_RECEIVED, _("Received")),
]

TEMPLATE_CATEGORY_CHOICES = [
    ("marketing", _("Marketing")),
    ("utility", _("Utility")),
    ("authentication", _("Authentication")),
]


class WhatsAppAccount(HorillaCoreModel):
    """
    A connected WhatsApp Business (Cloud API) account/phone number.
    """

    display_name = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_("Display Name")
    )
    phone_number_id = models.CharField(
        max_length=100,
        verbose_name=_("Phone Number ID"),
        help_text=_("Phone number ID from the Meta WhatsApp Cloud API."),
    )
    display_phone_number = models.CharField(
        max_length=32, blank=True, null=True, verbose_name=_("Whatsapp Number")
    )
    business_account_id = models.CharField(
        max_length=100, blank=True, null=True, verbose_name=_("Business Account ID")
    )
    access_token = EncryptedCharField(
        max_length=1024,
        verbose_name=_("Access Token"),
        help_text=_("Permanent access token generated from the Meta app."),
    )
    webhook_verify_token = EncryptedCharField(
        max_length=512,
        blank=True,
        null=True,
        verbose_name=_("Webhook Verify Token"),
    )
    api_version = models.CharField(
        max_length=10, default="v21.0", verbose_name=_("Graph API Version")
    )
    is_primary = models.BooleanField(default=False, verbose_name=_("Primary Account"))
    bot_enabled = models.BooleanField(
        default=False,
        verbose_name=_("Enable Bot"),
        help_text=_("Automatically reply using the configurable Bot Rule builder."),
    )
    default_bot_rule = models.ForeignKey(
        "whatsapp.WhatsAppBotRule",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Default Bot Rule"),
        help_text=_(
            "Bot Rule started for new conversations when no keyword-triggered "
            "rule matches the inbound message. Must be a General rule (no "
            "Related Model set), since it applies account-wide across every "
            "linked model."
        ),
    )

    class Meta:
        """Meta options for WhatsAppAccount."""

        verbose_name = _("Account")
        verbose_name_plural = _("Accounts")

    def __str__(self):
        return self.display_name or self.display_phone_number or self.phone_number_id

    def get_decrypted_access_token(self):
        """Return the decrypted Meta Cloud API access token."""
        if self.access_token:
            return decrypt_password(self.access_token)
        return None

    def get_decrypted_webhook_verify_token(self):
        """Return the decrypted webhook verify token."""
        if self.webhook_verify_token:
            return decrypt_password(self.webhook_verify_token)
        return None

    def get_edit_url(self):
        """Return the edit URL for this account."""
        return reverse_lazy(
            "whatsapp:whatsapp_account_update_view", kwargs={"pk": self.pk}
        )

    def get_delete_url(self):
        """Return the delete URL for this account."""
        return reverse_lazy(
            "whatsapp:whatsapp_account_delete_view", kwargs={"pk": self.pk}
        )

    def get_test_connection_url(self):
        """Return the URL that tests this account's connection to Meta."""
        return reverse_lazy(
            "whatsapp:whatsapp_account_test_connection_view", kwargs={"pk": self.pk}
        )

    def save(self, *args, **kwargs):
        """Enforce only one primary WhatsApp account per company."""
        if getattr(self, "_saving", False):
            return super().save(*args, **kwargs)

        self._saving = True
        try:
            if (
                not WhatsAppAccount.objects.exclude(pk=self.pk)
                .filter(company=self.company)
                .exists()
            ):
                self.is_primary = True
            elif self.is_primary:
                WhatsAppAccount.objects.exclude(pk=self.pk).filter(
                    company=self.company, is_primary=True
                ).update(is_primary=False)
            return super().save(*args, **kwargs)
        finally:
            self._saving = False


def normalize_whatsapp_number(contact_number):
    """
    Normalize a phone number to bare digits (as sent by Meta's wa_id) so
    numbers stored in different formats (+91 xxx, dashes, spaces, ...)
    still match the format used by inbound webhook payloads.
    """
    if not contact_number:
        return contact_number
    return re.sub(r"\D", "", contact_number)


class WhatsAppConversation(HorillaCoreModel):
    """
    A single WhatsApp conversation thread with a contact number, optionally
    linked to a CRM record (Lead, Contact, Account, ...) via a generic relation.
    """

    contact_number = models.CharField(max_length=32, verbose_name=_("Contact Number"))
    contact_name = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_("Contact Name")
    )
    content_type = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    related_to = models.GenericForeignKey("content_type", "object_id")
    status = models.CharField(
        max_length=10, choices=CONVERSATION_STATUS_CHOICES, default="open"
    )
    is_bot_active = models.BooleanField(
        default=True,
        verbose_name=_("Bot Active"),
        help_text=_("Disabled once a human agent takes over the conversation."),
    )
    last_message_at = models.DateTimeField(
        blank=True, null=True, verbose_name=_("Last Message At")
    )
    account = models.ForeignKey(
        WhatsAppAccount,
        on_delete=models.SET_NULL,
        null=True,
        related_name="conversations",
        verbose_name=_("Account"),
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="whatsapp_conversations",
        verbose_name=_("Assigned To"),
    )

    class Meta:
        """Meta options for WhatsAppConversation."""

        verbose_name = _("Conversation")
        verbose_name_plural = _("Conversations")
        unique_together = (("account", "contact_number"),)

    def __str__(self):
        return self.contact_name or self.contact_number

    def get_detail_url(self):
        """Return the URL of the conversation panel."""
        return reverse_lazy(
            "whatsapp:whatsapp_conversation_panel_view", kwargs={"pk": self.pk}
        )

    @classmethod
    def get_or_create_for(cls, account, contact_number, contact_name=None):
        """
        Get or create the conversation for the given account/contact_number
        pair. Returns a (conversation, created) tuple, matching Django's own
        get_or_create convention, so callers can react to a brand-new contact.
        """
        contact_number = normalize_whatsapp_number(contact_number)
        conversation, created = cls.objects.get_or_create(
            account=account,
            contact_number=contact_number,
            defaults={
                "contact_name": contact_name,
                "company": account.company,
            },
        )
        if created is False and contact_name and not conversation.contact_name:
            conversation.contact_name = contact_name
            conversation.save(update_fields=["contact_name"])
        return conversation, created


class WhatsAppTemplate(HorillaCoreModel):
    """
    A locally stored WhatsApp message template, matching one approved in
    Meta Business Manager.
    """

    title = models.CharField(max_length=100, verbose_name=_("Template Title"))
    name = models.CharField(
        max_length=255,
        verbose_name=_("Template Name"),
        help_text=_("Must match the template name approved in Meta Business Manager."),
    )
    language = models.CharField(
        max_length=10, default="en_US", verbose_name=_("Language Code")
    )
    category = models.CharField(
        max_length=20,
        choices=TEMPLATE_CATEGORY_CHOICES,
        default="utility",
        verbose_name=_("Category"),
    )
    sample_body = models.TextField(
        blank=True,
        verbose_name=_("Sample Body"),
        help_text=_("Auto-filled from the approved template in Meta Business Manager."),
    )
    components = models.JSONField(
        blank=True,
        null=True,
        verbose_name=_("Components"),
        help_text=_(
            "Raw component structure (header/body/buttons/carousel) fetched "
            "from Meta Business Manager."
        ),
    )
    content_type = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        limit_choices_to=limit_content_types("whatsapp_template_models"),
        verbose_name=_("Related Model"),
    )
    variable_fields = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Variable Fields"),
        help_text=_(
            "For each {{1}}, {{2}}... in the template text, the record field whose "
            "value fills it, in order, comma separated (for example "
            "instance.first_name,instance.company). Used when an automation sends "
            "this template."
        ),
    )
    account = models.ForeignKey(
        "WhatsAppAccount",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="templates",
        verbose_name=_("Account"),
        help_text=_(
            "The WhatsApp account this template is approved under. Leave "
            "blank to make it available to every account."
        ),
    )

    class Meta:
        """Meta options for WhatsAppTemplate."""

        verbose_name = _("Template")
        verbose_name_plural = _("Templates")
        unique_together = (("name", "language", "company", "account"),)

    def __str__(self):
        return f"{self.title} ({self.language})"

    def get_related_model(self):
        """Return the display name of the model this template is restricted to, if any."""
        if self.content_type:
            model_cls = self.content_type.model_class()
            if model_cls:
                return model_cls._meta.verbose_name.title()
        return None

    def get_edit_url(self):
        """Return the edit URL for this template."""
        return reverse_lazy(
            "whatsapp:whatsapp_template_update_view", kwargs={"pk": self.pk}
        )

    def get_delete_url(self):
        """Return the delete URL for this template."""
        return reverse_lazy(
            "whatsapp:whatsapp_template_delete_view", kwargs={"pk": self.pk}
        )

    @staticmethod
    def _count_variables(text):
        """Return the highest {{n}} placeholder index found in text, or 0."""
        numbers = [int(n) for n in re.findall(r"\{\{(\d+)\}\}", text or "")]
        return max(numbers) if numbers else 0

    @classmethod
    def _describe_body(cls, components):
        """Return the {text, variables, variable_range} description for a BODY component."""
        for component in components:
            if component.get("type") == "BODY":
                text = component.get("text", "")
                count = cls._count_variables(text)
                return {
                    "text": text,
                    "variables": count,
                    "variable_range": list(range(1, count + 1)),
                }
        return {"text": "", "variables": 0, "variable_range": []}

    @classmethod
    def _describe_header(cls, components):
        """Return the {format, variables} description for a HEADER component, if any."""
        for component in components:
            if component.get("type") == "HEADER":
                fmt = component.get("format", "TEXT")
                variables = (
                    cls._count_variables(component.get("text", ""))
                    if fmt == "TEXT"
                    else (1 if fmt in ("IMAGE", "VIDEO", "DOCUMENT") else 0)
                )
                return {"format": fmt, "variables": variables}
        return None

    @classmethod
    def _describe_buttons(cls, components):
        """Return a list of {index, type, text, url_has_variable} for BUTTONS components."""
        buttons = []
        for component in components:
            if component.get("type") != "BUTTONS":
                continue
            for index, button in enumerate(component.get("buttons", [])):
                buttons.append(
                    {
                        "index": index,
                        "type": button.get("type"),
                        "text": button.get("text", ""),
                        "url_has_variable": bool(
                            cls._count_variables(button.get("url", ""))
                        ),
                    }
                )
        return buttons

    def get_send_schema(self):
        """
        Return a description of what parameters must be supplied to send this
        template: header (media/text variables), body variable count, dynamic
        button URLs, and carousel cards. Used to render the send form and to
        validate/build the Cloud API payload.
        """
        components = self.components or []
        schema = {
            "header": self._describe_header(components),
            "body": self._describe_body(components),
            "buttons": self._describe_buttons(components),
            "carousel": None,
        }
        for component in components:
            if component.get("type") == "CAROUSEL":
                cards = []
                for card_index, card in enumerate(component.get("cards", [])):
                    card_components = card.get("components", [])
                    cards.append(
                        {
                            "index": card_index,
                            "field_id": f"whatsapp-card-media-{card_index}",
                            "field_name": f"card_{card_index}_header_media",
                            "header": self._describe_header(card_components),
                            "body": self._describe_body(card_components),
                            "buttons": self._describe_buttons(card_components),
                        }
                    )
                schema["carousel"] = {"cards": cards}
        return schema


class WhatsAppFlow(HorillaCoreModel):
    """
    A locally stored reference to a static WhatsApp Flow configured in Meta
    Flow Builder / WhatsApp Manager. Only supports sending a published,
    static (no data-exchange/dynamic screens) Flow and receiving its
    completed submission.
    """

    title = models.CharField(max_length=100, verbose_name=_("Flow Title"))
    flow_id = models.CharField(
        max_length=100,
        verbose_name=_("Flow"),
        help_text=_("Flow ID from Meta Flow Builder / WhatsApp Manager."),
    )
    flow_name = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_("Flow Name")
    )
    cta_text = models.CharField(
        max_length=50,
        default="Start",
        verbose_name=_("Button Text"),
        help_text=_("Text shown on the button that opens the Flow."),
    )
    account = models.ForeignKey(
        WhatsAppAccount,
        on_delete=models.CASCADE,
        related_name="flows",
        verbose_name=_("Account"),
    )
    content_type = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        limit_choices_to=limit_content_types("whatsapp_template_models"),
        verbose_name=_("Related Model"),
        help_text=_(
            "Restrict this Flow to conversations linked to this model. Leave "
            "blank to make it available for any model (General)."
        ),
    )

    class Meta:
        """Meta options for WhatsAppFlow."""

        verbose_name = _("Flow")
        verbose_name_plural = _("Flows")
        unique_together = (("flow_id", "company"),)

    def __str__(self):
        return self.title

    def get_related_model(self):
        """Return the display name of the model this flow is restricted to, if any."""
        if self.content_type:
            model_cls = self.content_type.model_class()
            if model_cls:
                return model_cls._meta.verbose_name.title()
        return None

    def get_edit_url(self):
        """Return the edit URL for this flow."""
        return reverse_lazy(
            "whatsapp:whatsapp_flow_update_view", kwargs={"pk": self.pk}
        )

    def get_delete_url(self):
        """Return the delete URL for this flow."""
        return reverse_lazy(
            "whatsapp:whatsapp_flow_delete_view", kwargs={"pk": self.pk}
        )


class WhatsAppMessage(HorillaCoreModel):
    """
    A single inbound or outbound WhatsApp message within a conversation.
    """

    direction = models.CharField(max_length=3, choices=MESSAGE_DIRECTION_CHOICES)
    message_type = models.CharField(
        max_length=20, choices=MESSAGE_TYPE_CHOICES, default="text"
    )
    body = models.TextField(blank=True, null=True, verbose_name=_("Message"))
    wa_message_id = models.CharField(
        max_length=128, unique=True, blank=True, null=True, editable=False
    )
    status = models.CharField(
        max_length=20, choices=MESSAGE_STATUS_CHOICES, default=MESSAGE_STATUS_PENDING
    )
    status_message = models.TextField(blank=True, null=True)
    sent_by_bot = models.BooleanField(default=False, verbose_name=_("Sent By Bot"))
    sent_at = models.DateTimeField(blank=True, null=True)
    delivered_at = models.DateTimeField(blank=True, null=True)
    read_at = models.DateTimeField(blank=True, null=True)

    conversation = models.ForeignKey(
        WhatsAppConversation,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name=_("Conversation"),
    )
    template = models.ForeignKey(
        WhatsAppTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
    )
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="whatsapp_sent_messages",
        verbose_name=_("Sent By"),
    )

    class Meta:
        """Meta options for WhatsAppMessage."""

        verbose_name = _("Message")
        verbose_name_plural = _("Messages")
        ordering = ["created_at"]

    def __str__(self):
        return f"[{self.direction}] {(self.body or '')[:50]}"

    @staticmethod
    def humanize_flow_field(key):
        """'screen_0_Full_Name_0' -> 'Full Name' (Meta's generated field ids)."""
        import re

        label = re.sub(r"^screen_\d+_", "", str(key))
        label = re.sub(r"_\d+$", "", label)
        return label.replace("_", " ").strip().title() or str(key)

    @property
    def flow_sent_info(self):
        """{'title','cta'} for an outbound Flow message, else None."""
        info = self.additional_info or {}
        if self.direction == "out" and info.get("flow_token"):
            return {
                "title": info.get("flow_title")
                or (self.body or "").replace("Flow sent:", "").strip(),
                "cta": info.get("flow_cta"),
            }
        return None

    @property
    def flow_answer_items(self):
        """[(label, value)] for an inbound Flow submission, else []."""
        info = self.additional_info or {}
        answers = info.get("flow_answers")
        if self.direction != "in" or not isinstance(answers, dict):
            return []
        labels = info.get("flow_labels") or {}
        return [
            (labels.get(k) or self.humanize_flow_field(k), v)
            for k, v in answers.items()
            if k != "flow_token"
        ]

    def save(self, *args, **kwargs):
        """Keep the parent conversation's last_message_at in sync."""
        super().save(*args, **kwargs)
        WhatsAppConversation.objects.filter(pk=self.conversation_id).update(
            last_message_at=self.created_at
        )


class WhatsAppAttachment(HorillaCoreModel):
    """
    A file/image/document attached to a WhatsApp message.
    """

    file = models.FileField(upload_to=upload_path)
    file_size = models.PositiveIntegerField(blank=True, null=True)
    mime_type = models.CharField(max_length=100, blank=True, null=True)
    media_id = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        help_text=_("Media ID returned by the WhatsApp Cloud API."),
    )
    message = models.ForeignKey(
        WhatsAppMessage,
        on_delete=models.CASCADE,
        related_name="attachments",
    )

    class Meta:
        """Meta options for WhatsAppAttachment."""

        verbose_name = _("Attachment")
        verbose_name_plural = _("Attachments")

    def __str__(self):
        return self.file.name if self.file else str(self.pk)


BOT_RULE_TRIGGER_CHOICES = [
    ("inbound_message", _("Inbound Message")),
    ("keyword", _("Keyword")),
    ("manual", _("Manual")),
]

#: Values double as datetime.timedelta kwargs (see
#: WhatsAppBotRule.retrigger_cooldown_timedelta), so only include units
#: timedelta itself accepts - no "months" (not a fixed duration).
RETRIGGER_COOLDOWN_UNIT_CHOICES = [
    ("minutes", _("Minutes")),
    ("hours", _("Hours")),
    ("days", _("Days")),
    ("weeks", _("Weeks")),
]

BOT_RULE_NODE_TYPE_CHOICES = [
    ("message", _("Message")),
    ("question", _("Question")),
    ("buttons", _("Buttons")),
    ("list", _("List")),
    ("condition", _("Condition")),
    ("create_record", _("Create Record")),
    ("update_record", _("Update Record")),
    ("search_record", _("Search Record")),
    ("assign_owner", _("Assign Owner")),
    ("add_note", _("Add Note")),
    ("send_template", _("Send Template")),
    ("send_meta_flow", _("Send Meta Flow")),
    ("wait", _("Wait")),
    ("end", _("End Flow")),
]

BOT_RULE_SESSION_STATUS_CHOICES = [
    ("running", _("Running")),
    ("waiting_input", _("Waiting For Input")),
    ("completed", _("Completed")),
    ("failed", _("Failed")),
]

SCHEDULED_RESUME_STATUS_CHOICES = [
    ("pending", _("Pending")),
    ("resumed", _("Resumed")),
    ("failed", _("Failed")),
    ("cancelled", _("Cancelled")),
]


class WhatsAppBotRule(HorillaCoreModel):
    """
    A configurable, no-code conversation flow: a graph of WhatsAppBotRuleNode
    connected by WhatsAppBotRuleEdge, interpreted at runtime by the bot rule
    engine. An account opts in via WhatsAppAccount.bot_enabled.
    """

    name = models.CharField(max_length=255, verbose_name=_("Flow Name"))
    description = models.TextField(blank=True, verbose_name=_("Description"))
    trigger_type = models.CharField(
        max_length=20,
        choices=BOT_RULE_TRIGGER_CHOICES,
        default="inbound_message",
        verbose_name=_("Trigger Type"),
    )
    trigger_keywords = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name=_("Trigger Keywords"),
        help_text=_(
            "Comma separated keywords that start this flow when Trigger "
            "Type is Keyword."
        ),
    )
    version = models.PositiveIntegerField(
        default=1,
        verbose_name=_("Version"),
        help_text=_(
            "Incremented when the flow's structure changes, so in-flight "
            "sessions keep running against the version they started on."
        ),
    )
    retrigger_cooldown_value = models.PositiveIntegerField(
        default=5,
        verbose_name=_("Retrigger Cooldown"),
        help_text=_(
            "After this flow finishes for a conversation, don't restart it "
            "for that same conversation again until this much time has "
            "passed. Set to 0 to allow immediate retriggering."
        ),
    )
    retrigger_cooldown_unit = models.CharField(
        max_length=10,
        choices=RETRIGGER_COOLDOWN_UNIT_CHOICES,
        default="minutes",
        verbose_name=_("Cooldown Unit"),
    )
    account = models.ForeignKey(
        WhatsAppAccount,
        on_delete=models.CASCADE,
        related_name="bot_rules",
        verbose_name=_("Account"),
    )
    content_type = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        limit_choices_to=limit_content_types("whatsapp_template_models"),
        verbose_name=_("Related Model"),
        help_text=_(
            "Restrict this flow to conversations linked to this model. Leave "
            "blank to make it available for any model (General)."
        ),
    )

    class Meta:
        """Meta options for WhatsAppBotRule."""

        verbose_name = _("Bot Rule")
        verbose_name_plural = _("Bot Rules")
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_related_model(self):
        """Return the display name of the model this rule is restricted to, if any."""
        if self.content_type:
            model_cls = self.content_type.model_class()
            if model_cls:
                return model_cls._meta.verbose_name.title()
        return None

    def get_start_node(self):
        """Return this flow's entry node, if one is marked."""
        return self.nodes.filter(is_start=True).first()

    def bump_version(self):
        """Increment the flow's version (call after structural edits)."""
        self.version = (self.version or 1) + 1
        self.save(update_fields=["version"])

    def retrigger_cooldown_timedelta(self):
        """Return the configured retrigger cooldown as a timedelta (or None if disabled)."""
        if not self.retrigger_cooldown_value:
            return None
        return timedelta(
            **{self.retrigger_cooldown_unit: self.retrigger_cooldown_value}
        )

    @property
    def running_session_count(self):
        """Number of sessions currently in progress for this flow."""
        return self.sessions.filter(status__in=["running", "waiting_input"]).count()

    def get_edit_url(self):
        """Return the edit URL for this bot flow."""
        return reverse_lazy(
            "whatsapp:whatsapp_bot_rule_update_view", kwargs={"pk": self.pk}
        )

    def get_delete_url(self):
        """Return the delete URL for this bot flow."""
        return reverse_lazy(
            "whatsapp:whatsapp_bot_rule_delete_view", kwargs={"pk": self.pk}
        )

    def get_builder_url(self):
        """Return the node/edge builder URL for this bot flow."""
        return reverse_lazy(
            "whatsapp:whatsapp_bot_rule_builder_view", kwargs={"pk": self.pk}
        )


class WhatsAppBotRuleNode(HorillaCoreModel):
    """
    A single step in a WhatsAppBotRule: a message, question, condition, CRM
    action, or other operation. Type-specific configuration lives in `config`
    (JSON), its shape depending on `node_type`.
    """

    flow = models.ForeignKey(
        WhatsAppBotRule,
        on_delete=models.CASCADE,
        related_name="nodes",
        verbose_name=_("Flow"),
    )
    node_key = models.SlugField(
        max_length=100,
        verbose_name=_("Node Key"),
        help_text=_("Stable id for this node, unique within the flow."),
    )
    node_type = models.CharField(
        max_length=20,
        choices=BOT_RULE_NODE_TYPE_CHOICES,
        verbose_name=_("Node Type"),
    )
    config = models.JSONField(
        blank=True,
        default=dict,
        verbose_name=_("Config"),
        help_text=_("Type-specific configuration; schema depends on node_type."),
    )
    order = models.PositiveIntegerField(default=0, verbose_name=_("Order"))
    is_start = models.BooleanField(
        default=False,
        verbose_name=_("Is Start Node"),
        help_text=_("Marks the entry node the engine begins execution from."),
    )

    class Meta:
        """Meta options for WhatsAppBotRuleNode."""

        verbose_name = _("Bot Rule Node")
        verbose_name_plural = _("Bot Rule Nodes")
        ordering = ["order"]
        unique_together = (("flow", "node_key"),)

    def __str__(self):
        return f"{self.node_key} ({self.node_type})"

    _NODE_TYPE_ICONS = {
        "message": "fa-comment-dots",
        "question": "fa-circle-question",
        "buttons": "fa-list-check",
        "list": "fa-bars",
        "condition": "fa-code-branch",
        "create_record": "fa-square-plus",
        "update_record": "fa-pen-to-square",
        "search_record": "fa-magnifying-glass",
        "assign_owner": "fa-user-plus",
        "add_note": "fa-note-sticky",
        "send_template": "fa-envelope",
        "send_meta_flow": "fa-diagram-project",
        "wait": "fa-clock",
        "end": "fa-flag-checkered",
    }

    def get_icon_class(self):
        """Return a FontAwesome icon class representing this node's type."""
        return self._NODE_TYPE_ICONS.get(self.node_type, "fa-circle")

    _NODE_TYPE_CATEGORIES = {
        "message": "messaging",
        "question": "messaging",
        "buttons": "messaging",
        "list": "messaging",
        "send_template": "messaging",
        "send_meta_flow": "messaging",
        "condition": "control",
        "wait": "control",
        "create_record": "record",
        "update_record": "record",
        "search_record": "record",
        "assign_owner": "record",
        "add_note": "record",
        "end": "terminal",
    }

    def get_category(self):
        """Return a coarse category for this node's type, used for accent color grouping."""
        return self._NODE_TYPE_CATEGORIES.get(self.node_type, "messaging")

    def get_outgoing_edge(self, source_handle=""):
        """Return the outgoing edge for the given branch/option handle, if any."""
        return self.outgoing_edges.filter(source_handle=source_handle).first()

    @staticmethod
    def _keyed_handles(node_type, config):
        """
        Return {position_key: handle_value} for every handle-producing slot
        in `config` for `node_type` - keyed by role/position (not by value),
        so a caller can tell "the found-branch handle" apart from "the
        not-found-branch handle" even when diffing an old vs. new config to
        detect a rename (an unordered set of old/new values alone can't
        disambiguate which old handle became which new one). Shared by
        get_available_handles() (below) and the node form's rename-cascade
        diffing (WhatsAppBotRuleNodeForm) so the two never drift apart.
        """
        config = config or {}
        handles = {}

        if node_type == "condition":
            for index, branch in enumerate(config.get("branches", [])):
                if isinstance(branch, dict) and branch.get("handle"):
                    handles[("branch", index)] = branch["handle"]
            if config.get("default_handle"):
                handles[("default",)] = config["default_handle"]

        elif node_type == "search_record":
            if config.get("found_branch_handle"):
                handles[("found",)] = config["found_branch_handle"]
            if config.get("not_found_branch_handle"):
                handles[("not_found",)] = config["not_found_branch_handle"]

        elif node_type in ("buttons", "list"):
            for index, option in enumerate(config.get("options", [])):
                if isinstance(option, dict) and option.get("id"):
                    handles[("option", index)] = option["id"]

        return handles

    def get_available_handles(self):
        """
        Return the [(handle, label), ...] choices valid for this node's
        outgoing edges, so the edge form can offer a dropdown instead of a
        free-text field the admin has to retype without a typo. Empty for
        node types with a single, unconditional outgoing path.
        """
        config = self.config or {}
        keyed = self._keyed_handles(self.node_type, config)

        if self.node_type == "condition":
            handles = [
                (handle, handle) for key, handle in keyed.items() if key[0] == "branch"
            ]
            default_handle = keyed.get(("default",))
            if default_handle:
                handles.append(
                    (
                        default_handle,
                        _("%(handle)s (default)") % {"handle": default_handle},
                    )
                )
            return handles

        if self.node_type == "search_record":
            handles = []
            found_handle = keyed.get(("found",))
            not_found_handle = keyed.get(("not_found",))
            if found_handle:
                handles.append(
                    (found_handle, _("%(handle)s (found)") % {"handle": found_handle})
                )
            if not_found_handle:
                handles.append(
                    (
                        not_found_handle,
                        _("%(handle)s (not found)") % {"handle": not_found_handle},
                    )
                )
            return handles

        if self.node_type in ("buttons", "list"):
            options_by_index = {
                index: option for index, option in enumerate(config.get("options", []))
            }
            return [
                (handle, options_by_index[key[1]].get("label") or handle)
                for key, handle in keyed.items()
                if key[0] == "option"
            ]

        return []

    def _config_target_model(self):
        """Return the model class of this node's config content_type, if any."""
        content_type_id = self.config.get("content_type_id") or self.config.get(
            "_ui_hint_content_type_id"
        )
        if not content_type_id:
            return None
        from horilla.contrib.core.models import HorillaContentType

        content_type = HorillaContentType.objects.filter(pk=content_type_id).first()
        return content_type.model_class() if content_type else None

    @staticmethod
    def _resolve_model_field(model_class, field_name):
        """Return the model field for field_name, unwrapping a trailing '_id' FK suffix."""
        if not model_class:
            return None
        try:
            return model_class._meta.get_field(field_name)
        except Exception:
            if field_name.endswith("_id"):
                try:
                    return model_class._meta.get_field(field_name[: -len("_id")])
                except Exception:
                    return None
            return None

    @staticmethod
    def _describe_field_value(model_class, field_name, value):
        """Return 'Label: display value' for one field_mapping/filters entry."""
        field = WhatsAppBotRuleNode._resolve_model_field(model_class, field_name)
        if not field:
            return f"{field_name}: {value}"

        label = str(field.verbose_name).title()
        display_value = value
        is_variable_token = isinstance(value, str) and "{{" in value
        if not is_variable_token:
            from django.db import models as dj_models

            if isinstance(field, dj_models.ForeignKey) and value not in (None, ""):
                related = field.related_model.objects.filter(pk=value).first()
                display_value = str(related) if related else value
            elif getattr(field, "choices", None):
                display_value = dict(field.choices).get(value, value)
        return f"{label}: {display_value}"

    @staticmethod
    def _describe_fields(model_class, mapping):
        """Return 'Label: display value' parts for a field_mapping/filters dict."""
        return [
            WhatsAppBotRuleNode._describe_field_value(model_class, name, value)
            for name, value in mapping.items()
        ]

    def get_config_summary(self):
        """
        Return a short human-readable preview of this node's config, shown on
        the flow builder card so an admin can see what a node does/says
        without opening its edit form.
        """
        config = self.config or {}

        if self.node_type in ("message", "add_note"):
            text = config.get("body") or config.get("text") or ""
            return text

        if self.node_type == "question":
            prompt = config.get("prompt") or ""
            variable_name = config.get("variable_name")
            if variable_name:
                return _("%(prompt)s (saved as %(variable)s)") % {
                    "prompt": prompt,
                    "variable": variable_name,
                }
            return prompt

        if self.node_type in ("buttons", "list"):
            body = config.get("body") or ""
            options = config.get("options") or []
            if options:
                labels = ", ".join(
                    option.get("label") or option.get("id") or ""
                    for option in options
                    if isinstance(option, dict)
                )
                return _("%(body)s — options: %(labels)s") % {
                    "body": body,
                    "labels": labels,
                }
            return body

        if self.node_type == "condition":
            branches = config.get("branches") or []
            handles = ", ".join(
                branch.get("handle") or ""
                for branch in branches
                if isinstance(branch, dict) and branch.get("handle")
            )
            return (
                _("Branches: %(handles)s") % {"handles": handles} if handles else None
            )

        if self.node_type in ("create_record", "update_record", "search_record"):
            model_class = self._config_target_model()
            model_label = (
                model_class._meta.verbose_name.title() if model_class else None
            )
            field_mapping = config.get("field_mapping") or {}
            filters = config.get("filters") or {}
            parts = []
            if model_label:
                parts.append(model_label)
            if self.node_type == "search_record" and filters:
                parts.append(
                    _("filter by %(fields)s")
                    % {"fields": ", ".join(self._describe_fields(model_class, filters))}
                )
            elif field_mapping:
                parts.append(
                    _("sets %(fields)s")
                    % {
                        "fields": ", ".join(
                            self._describe_fields(model_class, field_mapping)
                        )
                    }
                )
            return " — ".join(parts) if parts else None

        if self.node_type == "send_template":
            template_id = config.get("template_id")
            if not template_id:
                return None
            template = WhatsAppTemplate.objects.filter(pk=template_id).first()
            return str(template) if template else None

        if self.node_type == "send_meta_flow":
            meta_flow_pk = config.get("flow_id")
            if not meta_flow_pk:
                return None
            meta_flow = WhatsAppFlow.objects.filter(pk=meta_flow_pk).first()
            return str(meta_flow) if meta_flow else None

        if self.node_type == "wait":
            seconds = config.get("duration_seconds")
            return _("Wait %(seconds)ss") % {"seconds": seconds} if seconds else None

        return None

    def save(self, *args, **kwargs):
        """Auto-slugify node_key from node_type + pk-less order if left blank."""
        if not self.node_key:
            from django.utils.text import slugify

            base = slugify(f"{self.node_type}-{self.order}") or slugify(self.node_type)
            candidate = base
            suffix = 1
            while (
                WhatsAppBotRuleNode.objects.filter(flow=self.flow, node_key=candidate)
                .exclude(pk=self.pk)
                .exists()
            ):
                suffix += 1
                candidate = f"{base}-{suffix}"
            self.node_key = candidate
        super().save(*args, **kwargs)


class WhatsAppBotRuleEdge(HorillaCoreModel):
    """
    A directed connection between two WhatsAppBotRuleNodes. `source_handle`
    selects which branch/button/list-option/condition-branch this edge fires
    for; blank for nodes with a single, unconditional outgoing path.
    """

    flow = models.ForeignKey(
        WhatsAppBotRule,
        on_delete=models.CASCADE,
        related_name="edges",
        verbose_name=_("Flow"),
    )
    source_node = models.ForeignKey(
        WhatsAppBotRuleNode,
        on_delete=models.CASCADE,
        related_name="outgoing_edges",
        verbose_name=_("Source Node"),
    )
    target_node = models.ForeignKey(
        WhatsAppBotRuleNode,
        on_delete=models.CASCADE,
        related_name="incoming_edges",
        verbose_name=_("Target Node"),
    )
    source_handle = models.CharField(
        max_length=100, blank=True, default="", verbose_name=_("Source Handle")
    )

    class Meta:
        """Meta options for WhatsAppBotRuleEdge."""

        verbose_name = _("Bot Rule Edge")
        verbose_name_plural = _("Bot Rule Edges")
        ordering = ["pk"]
        unique_together = (("source_node", "source_handle"),)

    def __str__(self):
        handle = f" [{self.source_handle}]" if self.source_handle else ""
        return f"{self.source_node.node_key}{handle} -> {self.target_node.node_key}"


class WhatsAppBotRuleSession(HorillaCoreModel):
    """
    Tracks one contact's progress through a WhatsAppBotRule: which node it is
    currently on, collected variables, and (optionally) which CRM record the
    flow is operating on.
    """

    flow = models.ForeignKey(
        WhatsAppBotRule,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sessions",
        verbose_name=_("Flow"),
    )
    flow_version = models.PositiveIntegerField(
        verbose_name=_("Flow Version"),
        help_text=_(
            "Snapshot of Flow.version at session start, so live edits don't "
            "corrupt an in-flight session."
        ),
    )
    conversation = models.ForeignKey(
        WhatsAppConversation,
        on_delete=models.CASCADE,
        related_name="bot_rule_sessions",
        verbose_name=_("Conversation"),
    )
    current_node_key = models.CharField(
        max_length=100, blank=True, null=True, verbose_name=_("Current Node Key")
    )
    variables = models.JSONField(blank=True, default=dict, verbose_name=_("Variables"))
    status = models.CharField(
        max_length=20,
        choices=BOT_RULE_SESSION_STATUS_CHOICES,
        default="running",
        verbose_name=_("Status"),
    )
    content_type = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    related_to = models.GenericForeignKey("content_type", "object_id")
    error_message = models.TextField(blank=True, verbose_name=_("Error"))
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Completed At"),
        help_text=_("When this session reached completed or failed status."),
    )

    class Meta:
        """Meta options for WhatsAppBotRuleSession."""

        verbose_name = _("Bot Rule Session")
        verbose_name_plural = _("Bot Rule Sessions")
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["conversation", "status"],
                name="whatsapp_bfs_conv_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.conversation} - {self.flow} ({self.status})"

    @classmethod
    def get_or_create_for(cls, flow, conversation, **defaults):
        """
        Get the active (running/waiting_input) session for this conversation,
        or start a new one for `flow`. Returns a (session, created) tuple.
        """
        session = (
            cls.objects.filter(
                conversation=conversation, status__in=["running", "waiting_input"]
            )
            .order_by("-created_at")
            .first()
        )
        if session:
            return session, False
        session = cls.objects.create(
            flow=flow,
            flow_version=flow.version,
            conversation=conversation,
            company=conversation.company,
            **defaults,
        )
        return session, True


class WhatsAppScheduledResume(HorillaCoreModel):
    """
    A scheduled resumption of a WhatsAppBotRuleSession paused at a `wait`
    node; processed periodically by a Celery beat task.
    """

    session = models.ForeignKey(
        WhatsAppBotRuleSession,
        on_delete=models.CASCADE,
        related_name="scheduled_resumes",
        verbose_name=_("Flow Session"),
    )
    resume_at = models.DateTimeField(verbose_name=_("Resume At"), db_index=True)
    status = models.CharField(
        max_length=20,
        choices=SCHEDULED_RESUME_STATUS_CHOICES,
        default="pending",
        db_index=True,
        verbose_name=_("Status"),
    )
    error_message = models.TextField(blank=True, verbose_name=_("Error"))

    class Meta:
        """Meta options for WhatsAppScheduledResume."""

        verbose_name = _("Scheduled Bot Rule Resume")
        verbose_name_plural = _("Scheduled Bot Rule Resumes")
        ordering = ["resume_at"]
        indexes = [
            models.Index(
                fields=["status", "resume_at"], name="whatsapp_sr_status_resume_idx"
            ),
        ]

    def __str__(self):
        return f"{self.session} @ {self.resume_at}"


class AutomationWhatsAppExtension(HorillaCoreModel):
    """
    Adds the WhatsApp channel's settings to ``automations.HorillaAutomation``
    (``_inherit_model``), so Automations itself is not edited. The columns
    are created by this app's own migration.
    """

    _inherit_model = "automations.HorillaAutomation"

    whatsapp_template = models.ForeignKey(
        "whatsapp.WhatsAppTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="automations",
        verbose_name=_("WhatsApp Template"),
        help_text=_("Approved template sent when the WhatsApp channel is selected."),
    )
    whatsapp_account = models.ForeignKey(
        "whatsapp.WhatsAppAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="automations",
        verbose_name=_("WhatsApp Account"),
        help_text=_("The WhatsApp account the message is sent from."),
    )

    def get_whatsapp_variables_display(self):
        """The template's variable mapping as readable text, e.g. "{{1}} First Name"."""
        from horilla.contrib.whatsapp.delivery import describe_variable_fields

        model = self.model.model_class() if self.model_id else None
        return describe_variable_fields(self.whatsapp_template, model)
