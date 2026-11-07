"""
The mail delivery channel: automations that send an email.

Registered from ``registration.py``. Automations calls ``MailChannel.send``
through the delivery channel registry (``horilla.registry.delivery``); this
module does not import Automations.
"""

# Standard library imports
import logging
import threading

from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.utils.middlewares import _thread_local
from horilla.registry.delivery import (
    ADDRESS_EMAIL,
    DeliveryChannel,
    get_delivery_channel,
)

# First party imports (Horilla)
from horilla.utils import timezone
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import HorillaMail, HorillaMailConfiguration
from .services import HorillaMailManager
from .tasks import MockRequest

logger = logging.getLogger(__name__)


class MailChannel(DeliveryChannel):
    """Send the automation's mail template as an email, through a mail server."""

    key = "mail"
    label = _("Send as Mail")
    address_kind = ADDRESS_EMAIL
    # Before notification, so mail and notification together send mail first.
    order = 10

    def shows_mail_fields(self):
        """Mail needs the mail template and the outgoing mail server."""
        return True

    def get_detail_fields(self):
        """Mail shows its template and the outgoing mail server."""
        return ["mail_template", "mail_server"]

    def resolve_recipients(self, spec, instance, user):
        """
        Resolve mail recipients from the mail_to field.
        Supports dynamic field access like 'instance.owner.email' or 'self.email'.

        Args:
            spec: String containing recipient specification
            instance: Model instance
            user: User who triggered the automation

        Returns:
            list: List of email addresses
        """
        recipients = []

        # Split by comma to handle multiple recipients
        for recipient_spec in spec.split(","):
            recipient_spec = recipient_spec.strip()
            if not recipient_spec:
                continue

            try:
                # Handle 'self' keyword
                if recipient_spec == "self":
                    if user and hasattr(user, "email") and user.email:
                        recipients.append(user.email)
                    continue

                # Handle field paths like 'instance.owner.email' or 'instance.owner'
                if recipient_spec.startswith("instance."):
                    field_path = recipient_spec.replace("instance.", "")
                    value = instance
                    for attr in field_path.split("."):
                        value = getattr(value, attr, None)
                        if value is None:
                            break

                    # If value is a User object, get its email
                    if (
                        value
                        and hasattr(value, "email")
                        and getattr(value, "email", None)
                    ):
                        recipients.append(value.email)
                    # If value is already an email string
                    elif isinstance(value, str) and "@" in value:
                        recipients.append(value)
                else:
                    # Direct email address
                    if "@" in recipient_spec:
                        recipients.append(recipient_spec)
            except Exception as e:
                logger.error(
                    "Error resolving recipient '%s': %s", recipient_spec, str(e)
                )
                continue

        # De-duplicate and drop empties
        return [
            r for r in dict.fromkeys([r.strip() for r in recipients if r and r.strip()])
        ]

    def send(self, automation, instance, recipients, context, user):
        """
        Send email for an automation.

        Args:
            automation: HorillaAutomation instance
            instance: Model instance
            recipients: List of email addresses
            context: Template context
            user: User who triggered the automation
        """
        try:
            if not automation.mail_template:
                logger.warning("Automation %s has no mail template", automation.title)
                return

            # Create HorillaMail instance

            # Reuse the actor/company execute_automation() already resolved for
            # template rendering, so the sent mail's metadata matches the
            # timezone used to format fields like due_datetime in its body.
            actor = context.get("user") or (
                user
                or getattr(instance, "updated_by", None)
                or getattr(instance, "created_by", None)
                or getattr(automation, "updated_by", None)
                or getattr(automation, "created_by", None)
            )

            company = context.get("active_company") or (
                actor.company if hasattr(actor, "company") and actor else None
            )

            # Use the primary recipient's own timezone to render date/time fields
            # in the mail body, since the mail is addressed to them, not to the
            # triggering actor. The users behind mail_to are resolved the way
            # the notification channel resolves them (looked up through the
            # registry, so mail does not import notifications).
            notification_channel = get_delivery_channel("notification")
            recipient_users = (
                notification_channel.resolve_recipients(
                    automation.mail_to, instance, user
                )
                if notification_channel is not None
                else []
            )
            timezone_user = recipient_users[0] if recipient_users else actor

            content_type = HorillaContentType.objects.get_for_model(instance)

            # Get mail server - use the one selected in automation, or fall back to default
            sender = automation.mail_server

            # If no mail server selected in automation, use default logic
            if not sender:
                if company:
                    sender = HorillaMailConfiguration.objects.filter(
                        company=company, mail_channel="outgoing", is_primary=True
                    ).first()
                    if not sender:
                        sender = HorillaMailConfiguration.objects.filter(
                            company=company, mail_channel="outgoing"
                        ).first()
                else:
                    # Fallback to primary mail server if no company
                    sender = HorillaMailConfiguration.objects.filter(
                        mail_channel="outgoing", is_primary=True
                    ).first()

            mail = HorillaMail.objects.create(
                sender=sender,
                to=",".join(recipients),
                subject=automation.mail_template.subject or "",
                body=automation.mail_template.body or "",
                content_type=content_type,
                object_id=instance.pk,
                mail_status="draft",
                created_by=actor,
                updated_by=actor,
                company=company,
                created_at=timezone.now(),
                updated_at=timezone.now(),
            )

            # Store context in mail's additional_info for async sending
            if not mail.additional_info:
                mail.additional_info = {}
            mail.additional_info["request_info"] = {
                "user_id": user.pk if user else None,
                "company_id": company.pk if company else None,
                "meta": {},
                "host": "",
                "scheme": "https",
            }
            mail.save(update_fields=["additional_info"])

            def send_email_thread():
                try:
                    if sender:
                        setattr(_thread_local, "from_mail_id", sender.pk)

                    mock_request = MockRequest(actor, company, {})
                    setattr(_thread_local, "request", mock_request)

                    # Bare template variables (e.g. `{{ instance.due_datetime }}`)
                    # are converted to local time via Django's active timezone,
                    # not via the MockRequest above (that only backs filters like
                    # `user_datetime_format`). Background threads have no active
                    # timezone, so activate the recipient's, same as
                    # TimezoneMiddleware does per-request - otherwise dates render
                    # in raw UTC.
                    tzname = getattr(timezone_user, "time_zone", None) or "UTC"
                    timezone.activate(tzname)

                    # Send the mail using HorillaMailManager (uses horilla_backends)
                    HorillaMailManager.send_mail(mail, context=context)

                    mail.refresh_from_db()
                    if mail.mail_status not in ("sent", "delivered"):
                        logger.error(
                            "Email failed to send via threading: %s (mail_id: %s), status: %s, message: %s",
                            automation.title,
                            mail.pk,
                            mail.mail_status,
                            mail.mail_status_message,
                        )
                except Exception as e:
                    logger.error(
                        "Error sending email in thread for automation %s (mail_id: %s ): %s",
                        automation.title,
                        mail.pk,
                        str(e),
                        exc_info=True,
                    )
                    # Update mail status to failed
                    try:
                        mail.refresh_from_db()
                        mail.mail_status = "failed"
                        mail.mail_status_message = str(e)
                        mail.save(update_fields=["mail_status", "mail_status_message"])
                    except Exception:
                        pass
                finally:
                    timezone.deactivate()
                    # Clean up thread local
                    if hasattr(_thread_local, "from_mail_id"):
                        delattr(_thread_local, "from_mail_id")
                    if hasattr(_thread_local, "request"):
                        delattr(_thread_local, "request")

            thread = threading.Thread(target=send_email_thread, daemon=True)
            thread.start()

        except Exception as e:
            logger.error(
                "Error sending automation email for %s: %s",
                automation.title,
                str(e),
                exc_info=True,
            )
