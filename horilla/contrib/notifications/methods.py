"""
This module provides helper methods for creating notifications and limiting content types for notifications in the Horilla framework. It includes a function to create notifications with optional linking to related objects, and a function to limit
"""

# Notification helper methods
# First party imports (Horilla)
from horilla.contrib.core.models import HorillaContentType

# Local imports
from .models import Notification


def create_notification(
    user, message, sender=None, url=None, instance=None, read=False
):
    """
    Create and save a Notification, optionally linking it to a related object.

    When ``instance`` is provided, sets content_type and object_id so the
    notification detail popup can show that object's details when no URL is given.

    Args:
        user: User to notify (required).
        message: Notification message text (required).
        sender: User who triggered the notification (optional).
        url: Optional URL to redirect to when the notification is opened.
        read: Whether the notification is read (default False).

    Returns:
        The created Notification instance, or None if creation failed.
    """
    content_type = None
    object_id = None
    if instance is not None:
        try:
            content_type = HorillaContentType.objects.get_for_model(instance)
            object_id = instance.pk
        except Exception:
            pass

    try:
        # Lazy import to avoid circular import

        notification = Notification(
            user=user,
            message=message,
            sender=sender,
            url=url or None,
            read=read,
            content_type=content_type,
            object_id=object_id,
        )
        notification.save()
        return notification
    except Exception:
        return None


def get_user_notifications(user):
    """
    Return the user's notifications, leaving out those whose related record is
    not visible in the active company (the default manager is company-scoped).
    """
    queryset = Notification.objects.filter(user=user)
    linked = queryset.filter(content_type__isnull=False, object_id__isnull=False)
    hidden = []
    for content_type_id in linked.values_list("content_type_id", flat=True).distinct():
        model = HorillaContentType.objects.get(pk=content_type_id).model_class()
        if model is None:
            continue
        rows = list(
            linked.filter(content_type_id=content_type_id).values_list(
                "pk", "object_id"
            )
        )
        visible = set(
            model._default_manager.filter(
                pk__in={object_id for _, object_id in rows}
            ).values_list("pk", flat=True)
        )
        hidden.extend(pk for pk, object_id in rows if object_id not in visible)
    return queryset.exclude(pk__in=hidden)
