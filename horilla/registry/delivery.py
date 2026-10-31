"""
Delivery channel registry.

A delivery channel is one way Automations can send a message: mail, an
in-app notification, or a channel another app adds (an SMS gateway, a
messenger). Each channel is a ``DeliveryChannel`` subclass that its own app
defines in its ``delivery.py`` and registers from its ``registration.py``
(imported at startup through the app's ``auto_import_modules``)::

    from horilla.registry.delivery import register_delivery_channel

    from .delivery import SmsChannel

    register_delivery_channel(SmsChannel())

One key is one channel. Automations lets the user pick several of the
registered channels and stores their keys in
``HorillaAutomation.delivery_channel`` joined by a comma (``mail``,
``mail,notification``, ``mail,sms``), then calls ``channel.send(...)`` for each.
Credentials and provider calls stay in the channel's own app.

This module does not import Automations, mail or notifications, and knows
nothing about ``"both"`` or about comma-separated values.
"""

import abc
import logging

from django.contrib.auth import get_user_model
from django.db import models

from horilla.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

#: Longest key. Automations joins several keys in a 255-character column.
KEY_MAX_LENGTH = 50

ADDRESS_EMAIL = "email"
ADDRESS_USER = "user"
ADDRESS_PHONE = "phone"

#: Keys a plugin must not take, and the app each one belongs to. ``"both"``
#: belongs to no channel: it is reserved only so the value Automations used
#: to store for mail and notification together cannot come back as a key.
RESERVED_KEYS = {
    "both": None,
    "mail": "horilla.contrib.mail",
    "notification": "horilla.contrib.notifications",
}

#: Parts of a field name that mark a phone number field.
PHONE_FIELD_HINTS = ("phone", "mobile", "contact_number")

_channels = {}


class DeliveryChannel(abc.ABC):
    """
    An outbound channel Automations can send through.

    ``key`` is stored on ``HorillaAutomation.delivery_channel``, joined by a
    comma with the other selected keys, so it has no comma and no space
    (at most 50 characters; ``mail``, ``notification`` and ``both`` are
    reserved).
    ``label`` is shown in the automation form. ``address_kind`` is what the
    channel sends to: ``"email"``, ``"user"`` or ``"phone"``; the default
    recipient methods below follow it.

    Subclasses implement ``send()``. The other methods have defaults.
    """

    key = ""
    label = ""
    address_kind = ADDRESS_EMAIL

    def is_available(self, company=None):
        """Whether the channel can be chosen for ``company``."""
        return True

    def get_recipient_choices(self, model):
        """
        Options for the automation's recipient picker (``mail_to``).

        ``"self"`` (the user who triggered the automation), the model's
        foreign keys to users, and its fields that hold an address of
        ``address_kind``, as ``("instance.<field>", label)``.
        """
        choices = [("self", _("Self (User who triggered)"))]
        if model is None:
            return choices
        user_model = get_user_model()
        for field in model._meta.get_fields():
            if not hasattr(field, "name"):
                continue
            if isinstance(field, models.ForeignKey):
                related = field.related_model
                if not (isinstance(related, type) and issubclass(related, user_model)):
                    continue
            elif not self.is_address_field(field):
                continue
            label = (
                getattr(field, "verbose_name", None)
                or field.name.replace("_", " ").title()
            )
            choices.append((f"instance.{field.name}", label))
        return choices

    def is_address_field(self, field):
        """Whether a (non foreign key) model field holds an ``address_kind`` address."""
        name = field.name.lower()
        if self.address_kind == ADDRESS_PHONE:
            return isinstance(field, models.CharField) and any(
                hint in name for hint in PHONE_FIELD_HINTS
            )
        return isinstance(field, (models.EmailField, models.CharField)) and (
            "email" in name
        )

    def resolve_recipients(self, spec, instance, user):
        """
        Turn the saved ``mail_to`` string into this channel's addresses.

        ``spec`` is comma separated: ``self``, ``instance.<field path>`` or a
        literal address. Each target goes through ``get_address()``; repeats
        and empty results are dropped.
        """
        addresses = []
        for part in (spec or "").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                if part == "self":
                    target = user
                elif part.startswith("instance."):
                    target = instance
                    for attr in part[len("instance.") :].split("."):
                        target = getattr(target, attr, None)
                        if target is None:
                            break
                else:
                    target = part
                address = self.get_address(target)
            except Exception as e:
                logger.error("Error resolving recipient '%s': %s", part, str(e))
                continue
            if address and address not in addresses:
                addresses.append(address)
        return addresses

    def get_address(self, target):
        """
        This channel's address for ``target``, or ``None``.

        ``target`` is a raw value, used as it is when it fits
        ``address_kind``, or an object (usually a user) whose own field is
        used: ``email`` for ``"email"``, the user itself for ``"user"``,
        ``contact_number`` for ``"phone"``.
        """
        if target is None or target == "":
            return None
        user_model = get_user_model()
        if isinstance(target, str):
            value = target.strip()
            if self.address_kind == ADDRESS_PHONE:
                return value or None
            if "@" not in value:
                return None
            if self.address_kind == ADDRESS_USER:
                return user_model.objects.filter(email=value).first()
            return value
        if self.address_kind == ADDRESS_USER:
            if isinstance(target, user_model):
                return target
            email = getattr(target, "email", None)
            return user_model.objects.filter(email=email).first() if email else None
        field = "contact_number" if self.address_kind == ADDRESS_PHONE else "email"
        value = getattr(target, field, None)
        return (str(value).strip() or None) if value else None

    def add_also_sent_to(self, recipients, users):
        """``recipients`` plus the address of each of ``users`` not already in it."""
        recipients = list(recipients)
        for user in users:
            address = self.get_address(user)
            if address and address not in recipients:
                recipients.append(address)
        return recipients

    def shows_mail_fields(self):
        """Whether the automation form shows the mail template and mail server."""
        return False

    def shows_notification_fields(self):
        """Whether the automation form shows the notification template."""
        return False

    @abc.abstractmethod
    def send(self, automation, instance, recipients, context, user):
        """
        Send the automation's message to ``recipients``.

        Must not block: ``execute_automation()`` runs inside ``post_save``.
        Hand slow work (a provider call) to a thread or a task.
        """


def register_delivery_channel(channel):
    """
    Register ``channel`` (a ``DeliveryChannel`` instance) under its key.

    Raises ValueError if the key is empty, contains a comma or a space, is
    too long, is reserved for another app, or is already registered.
    Returns ``channel``.
    """
    if not isinstance(channel, DeliveryChannel):
        raise TypeError(f"{channel!r} is not a DeliveryChannel instance.")
    key = channel.key
    if not isinstance(key, str) or not key:
        raise ValueError(f"{type(channel).__name__} needs a key.")
    if "," in key or any(char.isspace() for char in key):
        # Automations stores several keys in one column, joined by a comma.
        raise ValueError(
            f"Delivery channel key {key!r} must not contain a comma or a space."
        )
    if len(key) > KEY_MAX_LENGTH:
        raise ValueError(
            f"Delivery channel key {key!r} is longer than {KEY_MAX_LENGTH} characters."
        )
    if key in RESERVED_KEYS:
        owner = RESERVED_KEYS[key]
        module = type(channel).__module__
        if owner is None or not (module == owner or module.startswith(owner + ".")):
            raise ValueError(f"Delivery channel key {key!r} is reserved.")
    if key in _channels:
        raise ValueError(f"A delivery channel with key {key!r} is already registered.")
    _channels[key] = channel
    return channel


def unregister_delivery_channel(key):
    """Remove the channel registered under ``key`` (for tests); unknown keys are ignored."""
    _channels.pop(key, None)


def get_delivery_channel(key):
    """The channel registered under ``key``, or ``None``."""
    return _channels.get(key)


def get_delivery_channels(company=None):
    """A copy of the registered channels available to ``company``, in registration order."""
    return [channel for channel in _channels.values() if channel.is_available(company)]
