"""
The notification delivery channel: automations that send an in-app notification.

Registered from ``registration.py``. Automations calls
``NotificationChannel.send`` through the delivery channel registry
(``horilla.registry.delivery``); this module does not import Automations.
"""

# Standard library imports
import logging
from urllib.parse import urlencode, urlparse

# Third-party imports (Django)
from django.template import engines

from horilla.auth.models import User
from horilla.contrib.utils.methods import get_section_info_for_model
from horilla.contrib.utils.middlewares import _thread_local
from horilla.db import transaction
from horilla.registry.delivery import ADDRESS_USER, DeliveryChannel

# First party imports (Horilla)
from horilla.utils import timezone
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .methods import create_notification

logger = logging.getLogger(__name__)


class _RenderRequest:
    """
    Stands in for the request while a notification is rendered for one
    recipient, outside a real request (scheduled or background triggers).

    Template filters such as ``user_datetime_format`` read the user and the
    company from ``_thread_local.request``.
    """

    def __init__(self, user, company):
        self.user = user
        self.active_company = company
        self.META = {}
        self._host = ""
        self.scheme = "https"
        self.is_anonymous = user is None

    def get_host(self):
        """Get host for use in templates"""
        return self._host

    def build_absolute_uri(self, location=None):
        """Build absolute URI for use in templates"""
        if location is None:
            return f"{self.scheme}://{self._host}/"
        if location.startswith("http"):
            return location
        return f"{self.scheme}://{self._host}{location}"


def _get_model_list_view_url(model_class):
    """
    Resolve the list/view URL for a model by finding a settings menu item
    whose permission matches the model's view permission (e.g. department -> department_view).
    Returns a path string or None if not found.
    """
    try:
        app_label = model_class._meta.app_label
        model_name = model_class._meta.model_name
        view_perm = f"{app_label}.view_{model_name}"
        from horilla.menu.settings_menu import settings_registry

        for cls in settings_registry:
            items = getattr(cls(), "items", [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                perm = item.get("perm")
                if perm != view_perm:
                    continue
                url = item.get("url")
                if url is None:
                    continue
                path = str(url).strip()
                if path and path != "#":
                    if not path.startswith("/"):
                        parsed = urlparse(path)
                        path = parsed.path or path
                    return path
        return None
    except Exception as e:
        logger.debug("_get_model_list_view_url(%s): %s", model_class.__name__, str(e))
        return None


class NotificationChannel(DeliveryChannel):
    """Send the automation's notification template as an in-app notification."""

    key = "notification"
    label = _("Send as Notification")
    address_kind = ADDRESS_USER
    # After mail (10), before channels that keep the default 100.
    order = 20

    def shows_notification_fields(self):
        """Notifications need the notification template."""
        return True

    def get_detail_fields(self):
        """Notifications show their template."""
        return ["notification_template"]

    def resolve_recipients(self, spec, instance, user):
        """
        Resolve users for notifications from the mail_to field.
        Supports both email addresses and direct user field references.

        Args:
            spec: String containing recipient specification
            instance: Model instance
            user: User who triggered the automation

        Returns:
            list: List of User objects
        """
        users = []

        # Split by comma to handle multiple recipients
        for recipient_spec in spec.split(","):
            recipient_spec = recipient_spec.strip()
            if not recipient_spec:
                continue

            try:
                # Handle 'self' keyword - the user who triggered the automation
                if recipient_spec == "self":
                    if user:
                        users.append(user)
                    continue

                # Handle field paths like 'instance.owner' or 'instance.created_by'
                if recipient_spec.startswith("instance."):
                    field_path = recipient_spec.replace("instance.", "")
                    value = instance
                    for attr in field_path.split("."):
                        value = getattr(value, attr, None)
                        if value is None:
                            break

                    # If value is a User object, use it directly
                    if value and hasattr(value, "email") and hasattr(value, "pk"):
                        # Check if it's a User model instance
                        if isinstance(value, User):
                            users.append(value)
                        elif hasattr(value, "email"):
                            # It's an object with email, try to find the user
                            try:
                                user_obj = User.objects.filter(
                                    email=value.email
                                ).first()
                                if user_obj:
                                    users.append(user_obj)
                            except Exception:
                                pass
                else:
                    # Direct email address - find user by email
                    if "@" in recipient_spec:
                        try:
                            user_obj = User.objects.filter(email=recipient_spec).first()
                            if user_obj:
                                users.append(user_obj)
                        except Exception:
                            pass
            except Exception as e:
                logger.error(
                    "Error resolving notification user '%s': %s",
                    recipient_spec,
                    str(e),
                    exc_info=True,
                )
                continue

        return users

    def send(self, automation, instance, recipients, context, user):
        """
        Send notification for an automation.

        Args:
            automation: HorillaAutomation instance
            instance: Model instance
            recipients: List of User objects to notify (``resolve_recipients``
                plus the automation's "Also Send To" users)
            context: Template context
            user: User who triggered the automation
        """
        try:
            # Use notification_template if available, otherwise fall back to mail_template for backward compatibility
            notification_template = automation.notification_template
            if not notification_template and automation.mail_template:
                # Fallback to mail_template for backward compatibility
                logger.warning(
                    "Automation %s has no notification template, using mail template as fallback",
                    automation.title,
                )
                notification_template = None  # Will use mail_template below

            if not notification_template and not automation.mail_template:
                logger.warning(
                    "Automation %s  has no notification template or mail template",
                    automation.title,
                )
                return

            users_to_notify = list(recipients)

            if not users_to_notify:
                logger.warning(
                    "Automation %s has no valid users for notification",
                    automation.title,
                )
                return

            django_engine = engines["django"]

            message_template = ""
            subject_template = ""
            body_template = ""
            if notification_template:
                message_template = (notification_template.message or "").strip()
            else:
                # Fallback to mail_template for backward compatibility
                subject_template = (automation.mail_template.subject or "").strip()
                body_template = (automation.mail_template.body or "").strip()

            def _render_notification_message(for_user):
                """
                Render the notification message for a specific recipient.

                Bare template variables (e.g. `{{ instance.due_datetime }}`) are
                converted to local time via Django's own active timezone
                (`timezone.activate`, the same mechanism `TimezoneMiddleware` uses
                per-request), while filters such as `user_datetime_format` read
                the acting user from `_thread_local.request`. Scheduled/background
                triggers have no real request or active timezone, so both must be
                set up here per recipient, or due dates render in raw UTC instead
                of the recipient's own local time.
                """
                previous_request = getattr(_thread_local, "request", None)
                tzname = getattr(for_user, "time_zone", None) or "UTC"
                _thread_local.request = _RenderRequest(
                    for_user, context.get("active_company")
                )
                timezone.activate(tzname)
                try:
                    if notification_template:
                        rendered = ""
                        if message_template:
                            rendered = django_engine.from_string(
                                "{% load horilla_tags %}\n" + message_template
                            ).render(context)
                        return rendered[:500] if rendered else "Automation notification"

                    rendered = ""
                    if subject_template:
                        rendered = django_engine.from_string(
                            "{% load horilla_tags %}\n" + subject_template
                        ).render(context)
                    if body_template:
                        body = django_engine.from_string(
                            "{% load horilla_tags %}\n" + body_template
                        ).render(context)
                        rendered = f"{rendered}\n{body}" if rendered else body
                    return rendered[:500] if rendered else "Automation notification"
                finally:
                    timezone.deactivate()
                    if previous_request is not None:
                        _thread_local.request = previous_request
                    else:
                        delattr(_thread_local, "request")

            instance_url = None
            for attr in dir(instance):
                if attr.startswith("get_detail_"):
                    method = getattr(instance, attr)
                    if callable(method):
                        try:
                            url = method()
                            if url and str(url).strip() and str(url) != "#":
                                instance_url = str(url).strip()
                                if not instance_url.startswith("/"):
                                    parsed = urlparse(instance_url)
                                    instance_url = parsed.path or instance_url
                                break
                        except Exception as e:
                            logger.debug("get_detail_* %s: %s", attr, str(e))
                            continue

            # If no detail URL, use the model's list/view URL with filter so the instance is focused
            if not instance_url:
                try:
                    model_class = instance.__class__
                    # Prefer settings menu entry (e.g. Department -> department_view) so we get
                    # the correct list view even when there is no section in sub_section_menu
                    instance_url = _get_model_list_view_url(model_class)
                    if not instance_url:
                        section_info = get_section_info_for_model(model_class)
                        base_url = (section_info.get("url") or "").strip()
                        if base_url and base_url != "#":
                            section = section_info.get("section") or ""
                            if not base_url.startswith("/"):
                                parsed = urlparse(base_url)
                                base_url = parsed.path or base_url
                            instance_url = (
                                f"{base_url}?{urlencode({'section': section})}"
                                if section
                                else base_url
                            )
                    # Append filter so the list view shows this instance (id=exact)
                    if instance_url and getattr(instance, "pk", None) is not None:
                        filter_params = {
                            "apply_filter": "true",
                            "layout": "list",
                            "field": "id",
                            "operator": "exact",
                            "value": str(instance.pk),
                        }
                        sep = "&" if "?" in instance_url else "?"
                        instance_url = f"{instance_url}{sep}{urlencode(filter_params)}"
                except Exception as e:
                    logger.debug(
                        "Could not get list/section URL for %s: %s",
                        instance.__class__.__name__,
                        str(e),
                    )

            created_count = 0
            try:
                with transaction.atomic():
                    for notification_user in users_to_notify:
                        try:
                            notification_message = _render_notification_message(
                                notification_user
                            )
                            notification = create_notification(
                                user=notification_user,
                                message=notification_message,
                                sender=user,
                                url=instance_url,
                                instance=instance,
                                read=False,
                            )
                            if notification:
                                created_count += 1
                        except Exception as e:
                            logger.error(
                                "Error creating notification for user %s: %s",
                                notification_user.username,
                                str(e),
                                exc_info=True,
                            )
                            continue

                logger.info(
                    "Created %s notifications for automation '%s' (instance: %s, URL: %s )",
                    created_count,
                    automation.title,
                    instance,
                    instance_url or "none",
                )
            except Exception as e:
                logger.error("Error creating notifications: %s", str(e), exc_info=True)

        except Exception as e:
            logger.error(
                "Error sending automation notification for %s: %s",
                automation.title,
                str(e),
                exc_info=True,
            )
