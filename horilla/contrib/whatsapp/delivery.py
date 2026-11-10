"""
The WhatsApp delivery channel: an automation that sends an approved WhatsApp
template to the record's phone number.

Registered from ``registration.py`` through the delivery channel registry
(``horilla.registry.delivery``). Automations does not know about WhatsApp: the
WhatsApp account to send from and the template are columns this app injects onto
``HorillaAutomation`` (see ``AutomationWhatsAppExtension`` in models.py), and the
form fields are added by ``automation_extensions.py``. The record fields that fill
the template's variables are set on the template (``WhatsAppTemplate.variable_fields``).
"""

# Standard library imports
import logging
import threading

# First party imports (Horilla)
from horilla.registry.delivery import ADDRESS_PHONE, DeliveryChannel
from horilla.utils import timezone
from horilla.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)


def split_variable_fields(raw):
    """The stored comma separated variable fields as a list (empty entries kept as ``""``)."""
    return (
        [part.strip() for part in (raw or "").split(",")] if (raw or "").strip() else []
    )


def body_variable_count(template):
    """How many {{n}} variables the template's text has."""
    return template.get_send_schema()["body"]["variables"]


def resolve_variable(spec, instance, user):
    """
    The text for one template variable: ``instance`` (the record itself, as its
    name), ``instance.<field path>`` (a field of the record, or of a record it
    points to) or ``self`` (the user who triggered the automation). A value
    that is empty gives ``-``, because WhatsApp rejects an empty variable.
    """
    spec = (spec or "").strip()
    if spec == "self":
        value = user
    elif spec == "instance":
        value = instance
    elif spec.startswith("instance."):
        value = instance
        for attr in spec[len("instance.") :].split("."):
            value = getattr(value, attr, None)
            if value is None:
                break
    else:
        value = spec
    if value is None or value == "":
        return "-"
    if hasattr(value, "get_full_name") and callable(value.get_full_name):
        value = value.get_full_name() or str(value)
    text = str(value).strip()
    return text or "-"


def describe_variable_fields(template, model=None):
    """A template's saved variable mapping as text, e.g. "{{1}} First Name, {{2}} Company"."""
    specs = split_variable_fields(template.variable_fields if template else "")
    if not specs:
        return "-"
    labels = dict(variable_field_choices(model))
    return ", ".join(
        "{{%d}} %s" % (index, labels.get(spec, spec) if spec else "?")
        for index, spec in enumerate(specs, 1)
    )


def variable_field_choices(model):
    """
    ``(spec, label)`` choices for the record's fields a variable can come from:
    the record itself (its name), its text / number / date fields, the users it
    points to (shown by their name), and the user who triggered the automation.
    """
    from django.db import models as dj_models

    from horilla.auth.models import User
    from horilla.registry.delivery import (
        SKIPPED_RELATED_MODELS,
        get_recipient_relations,
    )

    choices = [("instance", _("Record name"))]
    if model is None:
        return choices + [("self", _("Self (User who triggered)"))]
    # Technical fields nobody would put in a message.
    skipped = {
        "password",
        "id",
        "pk",
        "is_active",
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
        "additional_info",
        "company",
    }
    text_fields = (
        dj_models.CharField,
        dj_models.TextField,
        dj_models.EmailField,
        dj_models.IntegerField,
        dj_models.DecimalField,
        dj_models.FloatField,
        dj_models.DateField,
        dj_models.DateTimeField,
        dj_models.BooleanField,
    )

    def label_of(field):
        return (
            getattr(field, "verbose_name", None) or field.name.replace("_", " ").title()
        )

    for field in model._meta.get_fields():
        if not getattr(field, "concrete", False) or field.name in skipped:
            continue
        if isinstance(field, dj_models.ForeignKey):
            related = field.related_model
            if isinstance(related, type) and issubclass(related, User):
                choices.append((f"instance.{field.name}", label_of(field)))
        elif isinstance(field, text_fields):
            choices.append((f"instance.{field.name}", label_of(field)))
    # Records the model declares in RECIPIENT_RELATIONS (e.g. an opportunity's
    # primary contact), read through the attribute; empty when the record has none.
    for name, related, label in get_recipient_relations(model):
        if (
            not isinstance(related, type)
            or issubclass(related, User)
            or related._meta.label_lower in SKIPPED_RELATED_MODELS
        ):
            continue
        for field in related._meta.get_fields():
            if (
                getattr(field, "concrete", False)
                and not field.is_relation
                and field.name not in skipped
                and isinstance(field, text_fields)
            ):
                choices.append(
                    (f"instance.{name}.{field.name}", f"{label} - {label_of(field)}")
                )
    choices.append(("self", _("Self (User who triggered)")))
    return choices


def unsupported_reason(template):
    """
    Why Automations cannot send ``template``, or ``None`` when it can. Every
    variable in the template's text must be linked to a record field on the
    template itself (``variable_fields``), and it can't have a header that
    needs a value or media, a carousel, or a button link with a value.
    """
    schema = template.get_send_schema()
    needed = schema["body"]["variables"]
    if needed:
        mapped = split_variable_fields(template.variable_fields)
        if len(mapped) < needed or not all(mapped[:needed]):
            return _(
                "its variables aren't linked to record fields yet (edit the template "
                "and choose a field for each variable)"
            )
    header = schema.get("header")
    if header and (header.get("format") != "TEXT" or header.get("variables")):
        return _("it has a header that needs a value or media")
    if schema.get("carousel"):
        return _("it is a carousel")
    if any(button.get("url_has_variable") for button in schema.get("buttons", [])):
        return _("it has a button link that needs a value")
    return None


def _fill(text, values):
    """Replace {{1}}, {{2}}... in ``text`` with the 1-indexed ``values``."""
    for index, value in enumerate(values, start=1):
        text = text.replace("{{%d}}" % index, value or "")
    return text


def _pick_account(automation, template, company):
    """The account to send from: the one chosen on the automation, else a fallback."""
    from .models import WhatsAppAccount

    if automation.whatsapp_account_id and automation.whatsapp_account.is_active:
        return automation.whatsapp_account
    if template.account_id and template.account.is_active:
        return template.account
    accounts = WhatsAppAccount.objects.filter(is_active=True)
    if company:
        accounts = accounts.filter(company=company)
    return accounts.order_by("-is_primary", "pk").first()


def _send_all(account_id, template_id, jobs, automation_id):
    """Background worker: send to every number and record each message."""
    from django.db import connection

    from .models import (
        MESSAGE_DIRECTION_OUT,
        MESSAGE_STATUS_FAILED,
        MESSAGE_STATUS_SENT,
        WhatsAppAccount,
        WhatsAppConversation,
        WhatsAppMessage,
        WhatsAppTemplate,
    )
    from .services import WhatsAppAPIError, WhatsAppCloudAPIClient

    try:
        account = WhatsAppAccount.objects.get(pk=account_id)
        template = WhatsAppTemplate.objects.get(pk=template_id)
        client = WhatsAppCloudAPIClient(account)
        body_text = template.sample_body or ""
        for job in jobs:
            conversation, _created = WhatsAppConversation.get_or_create_for(
                account, job["number"], job["contact_name"]
            )
            if job["content_type_id"] and not conversation.content_type_id:
                conversation.content_type_id = job["content_type_id"]
                conversation.object_id = job["object_id"]
                conversation.save(update_fields=["content_type", "object_id"])
            message = WhatsAppMessage.objects.create(
                conversation=conversation,
                direction=MESSAGE_DIRECTION_OUT,
                message_type="template",
                body=_fill(body_text, job["values"]),
                template=template,
                company=conversation.company,
                additional_info={"automation": automation_id},
            )
            components = (
                [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": v} for v in job["values"]
                        ],
                    }
                ]
                if job["values"]
                else None
            )
            try:
                result = client.send_template(
                    job["number"],
                    template.name,
                    template.language,
                    components=components,
                )
                message.wa_message_id = result.get("messages", [{}])[0].get("id")
                message.status = MESSAGE_STATUS_SENT
                message.sent_at = timezone.now()
                message.save(update_fields=["wa_message_id", "status", "sent_at"])
            except WhatsAppAPIError as exc:
                message.status = MESSAGE_STATUS_FAILED
                message.status_message = str(exc)
                message.save(update_fields=["status", "status_message"])
                logger.error(
                    "Automation %s: WhatsApp template %s to %s failed: %s",
                    automation_id,
                    template.name,
                    job["number"],
                    exc,
                )
    except Exception:  # pylint: disable=broad-except
        logger.exception("Automation %s: WhatsApp send failed", automation_id)
    finally:
        connection.close()


class WhatsAppChannel(DeliveryChannel):
    """Send the automation's WhatsApp template to the record's phone number."""

    key = "whatsapp"
    label = _("Send as WhatsApp Message")
    address_kind = ADDRESS_PHONE
    # After mail (10) and notification (20).
    order = 30

    def is_available(self, company=None):
        """Offer the channel only when a WhatsApp account is connected."""
        from .models import WhatsAppAccount

        accounts = WhatsAppAccount.objects.filter(is_active=True)
        if company:
            accounts = accounts.filter(company=company)
        return accounts.exists()

    def get_detail_fields(self):
        """Show the account and the template on the automation's detail view."""
        return [
            "whatsapp_account",
            "whatsapp_template",
            "get_whatsapp_variables_display",
        ]

    def send(self, automation, instance, recipients, context, user):
        """
        Send the template to each phone number in ``recipients``.

        The numbers are worked out here, while the record is at hand, and the
        provider calls run in a background thread so the save that triggered
        the automation is not held up.
        """
        from horilla.contrib.core.models import HorillaContentType

        from .models import normalize_whatsapp_number

        template = automation.whatsapp_template
        if not template:
            logger.warning("Automation %s has no WhatsApp template", automation.title)
            return
        reason = unsupported_reason(template)
        if reason:
            logger.error(
                "Automation %s: template %s can't be sent from an automation (%s)",
                automation.title,
                template.name,
                reason,
            )
            return

        needed = body_variable_count(template)
        specs = split_variable_fields(template.variable_fields)
        if len(specs) < needed or not all(specs[:needed]):
            logger.error(
                "Automation %s: template %s needs %s variable(s) linked to record fields, %s linked",
                automation.title,
                template.name,
                needed,
                len([spec for spec in specs if spec]),
            )
            return
        values = [resolve_variable(spec, instance, user) for spec in specs[:needed]]

        company = getattr(instance, "company", None) or automation.company
        account = _pick_account(automation, template, company)
        if not account:
            logger.error("Automation %s: no active WhatsApp account", automation.title)
            return

        content_type = HorillaContentType.objects.get_for_model(instance)
        contact_name = str(instance)
        jobs = []
        for recipient in recipients:
            number = normalize_whatsapp_number(recipient)
            if number:
                jobs.append(
                    {
                        "number": number,
                        "values": values,
                        "contact_name": contact_name,
                        "content_type_id": content_type.pk,
                        "object_id": instance.pk,
                    }
                )
        if not jobs:
            return

        threading.Thread(
            target=_send_all,
            args=(account.pk, template.pk, jobs, automation.pk),
            daemon=True,
        ).start()
