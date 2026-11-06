"""
Cadence follow-up types: the built-ins plus the registered delivery channels.

``CadenceFollowUp.followup_type`` holds one key and has no fixed choices.
The key is either a built-in (``task``, ``call``, ``email``), which creates
an activity or a mail, or the key of a channel registered in
``horilla.registry.delivery`` (``notification``, ``sms``, ``bale``, ...),
which sends through that channel. One follow-up is one channel.

Mail is a registered channel too, but the ``email`` follow-up already sends
mail (and tracks the mail it creates), so the ``mail`` channel is not listed
a second time. Notifications have no built-in follow-up, so the
``notification`` channel is offered like any other channel.
"""

from horilla.registry.delivery import get_delivery_channel, get_delivery_channels
from horilla.utils.translation import gettext_lazy as _

#: The built-in follow-up types, in the order the type picker lists them.
BUILTIN_FOLLOWUP_TYPES = (
    ("task", _("Task")),
    ("call", _("Call")),
    ("email", _("Email")),
)

#: Channel keys a built-in follow-up already sends through (``email`` sends
#: mail); they are not offered as channels.
BUILTIN_CHANNEL_KEYS = frozenset({"mail"})

#: Longest stored key (``horilla.registry.delivery.KEY_MAX_LENGTH``).
FOLLOWUP_TYPE_MAX_LENGTH = 50

#: The status a channel follow-up reaches once its message is handed to the
#: channel; follow-ups after it wait for this status.
CHANNEL_SENT_STATUS = "completed"

TEMPLATE_MAIL = "mail"
TEMPLATE_NOTIFICATION = "notification"

BUILTIN_KEYS = frozenset(key for key, _label in BUILTIN_FOLLOWUP_TYPES)


def is_builtin_followup_type(followup_type):
    """Whether ``followup_type`` is a task, a call or an email."""
    return followup_type in BUILTIN_KEYS


def get_followup_channel(followup_type):
    """
    The registered delivery channel ``followup_type`` names, or ``None``.

    ``None`` for a built-in, for ``mail`` and for a key no app registers
    (any more).
    """
    if not followup_type or is_builtin_followup_type(followup_type):
        return None
    if followup_type in BUILTIN_CHANNEL_KEYS:
        return None
    return get_delivery_channel(followup_type)


def get_followup_type_choices(company=None):
    """
    ``(key, label)`` for the type picker: the built-ins, then the channels
    available to ``company`` in ``get_delivery_channels()`` order.
    """
    choices = list(BUILTIN_FOLLOWUP_TYPES)
    for channel in get_delivery_channels(company):
        if channel.key in BUILTIN_CHANNEL_KEYS or is_builtin_followup_type(channel.key):
            continue
        choices.append((channel.key, channel.label))
    return choices


def get_followup_type_label(followup_type):
    """
    The label of ``followup_type``: the built-in's, the channel's, or the key
    itself when the channel's app is gone.
    """
    for key, label in BUILTIN_FOLLOWUP_TYPES:
        if key == followup_type:
            return label
    channel = get_followup_channel(followup_type)
    if channel is not None:
        return channel.label
    return followup_type or ""


def get_channel_template_kind(channel):
    """
    Which template a channel follow-up's ``template_id`` points to:
    ``"notification"`` (a ``NotificationTemplate``) when the channel shows the
    notification template, else ``"mail"`` (a ``HorillaMailTemplate``) when it
    shows the mail fields, else ``None`` (the channel takes no template).
    """
    if channel is None:
        return None
    if channel.shows_notification_fields():
        return TEMPLATE_NOTIFICATION
    if channel.shows_mail_fields():
        return TEMPLATE_MAIL
    return None
