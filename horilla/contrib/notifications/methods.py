"""
This module provides helper methods for creating notifications and limiting content types for notifications in the Horilla framework. It includes a function to create notifications with optional linking to related objects, and a function to limit
"""

# Notification helper methods
# First party imports (Horilla)
from horilla.contrib.core.models import HorillaContentType
from horilla.db.models import Q

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
    hidden = Q()
    # order_by() drops Meta.ordering (-created_at): with it, DISTINCT ran over
    # (content_type_id, created_at) and gave one row per notification.
    content_type_ids = linked.order_by().values_list("content_type_id", flat=True)
    for content_type_id in content_type_ids.distinct():
        model = HorillaContentType.objects.get_for_id(content_type_id).model_class()
        if model is None:
            continue
        # A subquery, not ids loaded here: this runs on every page through the
        # unread_notifications context processor, so it must not grow with the
        # number of notifications. The default manager is company-scoped.
        visible = model._default_manager.values("pk")
        hidden |= Q(content_type_id=content_type_id) & ~Q(object_id__in=visible)
    return queryset.exclude(hidden) if hidden else queryset
