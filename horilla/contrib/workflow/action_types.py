"""
Workflow action types: the built-ins plus the registered delivery channels.

``WorkflowAction.action_type`` and ``WorkflowTimeTriggerAction.action_type``
hold one key and have no fixed choices. The key is either a built-in
(``update_field``, ``assign_task``, ``email``, ``notification``), run by
``methods.py``, or the key of a channel registered in
``horilla.registry.delivery`` (``sms``, ``bale``, ...), run by calling that
channel. One action is one channel: a workflow that mails and then sends an
SMS has two actions.

Mail and notification are registered channels too, but Workflow already has
its own ``email`` and ``notification`` actions for them (with their own
``action_config``), so the ``mail`` and ``notification`` channels are not
listed a second time.
"""

from horilla.registry.delivery import get_delivery_channel, get_delivery_channels
from horilla.utils.translation import gettext_lazy as _

#: The built-in action types, in the order the action picker lists them.
BUILTIN_ACTION_TYPES = (
    ("update_field", _("Edit Field")),
    ("assign_task", _("Assign Task")),
    ("email", _("Mail")),
    ("notification", _("Notification")),
)

#: Channel keys a built-in action already sends through (``email`` sends
#: mail, ``notification`` notifications); they are not offered as channels.
BUILTIN_CHANNEL_KEYS = frozenset({"mail", "notification"})

#: Longest stored key (``horilla.registry.delivery.KEY_MAX_LENGTH``).
ACTION_TYPE_MAX_LENGTH = 50

TEMPLATE_MAIL = "mail"
TEMPLATE_NOTIFICATION = "notification"

_BUILTIN_KEYS = frozenset(key for key, _label in BUILTIN_ACTION_TYPES)


def is_builtin_action_type(action_type):
    """Whether ``action_type`` is run by Workflow itself."""
    return action_type in _BUILTIN_KEYS


def get_action_channel(action_type):
    """
    The registered delivery channel ``action_type`` names, or ``None``.

    ``None`` for a built-in (including ``notification``, which is also a
    channel key) and for a key no app registers (any more).
    """
    if not action_type or is_builtin_action_type(action_type):
        return None
    if action_type in BUILTIN_CHANNEL_KEYS:
        return None
    return get_delivery_channel(action_type)


def get_action_type_choices(company=None):
    """
    ``(key, label)`` for the action picker: the built-ins, then the channels
    available to ``company`` in ``get_delivery_channels()`` order.
    """
    choices = list(BUILTIN_ACTION_TYPES)
    for channel in get_delivery_channels(company):
        if channel.key in BUILTIN_CHANNEL_KEYS or is_builtin_action_type(channel.key):
            continue
        choices.append((channel.key, channel.label))
    return choices


def get_action_type_label(action_type):
    """
    The label of ``action_type``: the built-in's, the channel's, or the key
    itself when the channel's app is gone.
    """
    for key, label in BUILTIN_ACTION_TYPES:
        if key == action_type:
            return label
    channel = get_action_channel(action_type)
    if channel is not None:
        return channel.label
    return action_type or ""


def get_channel_template_kind(channel):
    """
    Which template a channel action's ``template_id`` points to:
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
