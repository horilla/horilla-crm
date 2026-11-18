"""Views for handling notification-related operations."""

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.shortcuts import render
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import HttpResponse, ScriptResponse

# Local imports
from ..methods import get_user_notifications
from ..models import Notification, NotificationSoundPreference


class MarkNotificationReadView(LoginRequiredMixin, View):
    """View to mark a single notification as read."""

    def post(self, request, pk, *args, **kwargs):
        """
        Mark a specific notification as read.

        Args:
            request: The HTTP request object.
            pk: Primary key of the notification to mark as read.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Returns:
            HttpResponse: HTTP 200 response on success.
        """
        try:
            notif = get_user_notifications(request.user).get(pk=pk)
            notif.read = True
            notif.save()
        except Notification.DoesNotExist:
            # The row is swapped out by the response; the script shows the message.
            messages.error(request, _("The requested record does not exist."))
            return ScriptResponse(msgs=True)
        return HttpResponse("", status=200)


class MarkAllNotificationsReadView(LoginRequiredMixin, View):
    """View to mark all notifications as read for the current user."""

    def post(self, request, *args, **kwargs):
        """
        Mark all unread notifications as read for the current user.

        Args:
            request: The HTTP request object.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Returns:
            HttpResponse: Rendered notification list template.
        """
        get_user_notifications(request.user).filter(read=False).update(read=True)
        messages.success(request, _("All notifications marked as read."))
        unread_notifications = get_user_notifications(request.user).filter(read=False)
        return render(
            request,
            "notification_list.html",
            {
                "unread_notifications": unread_notifications,
                "keep_open": True,
            },
        )


class DeleteNotification(LoginRequiredMixin, View):
    """View to delete a single notification."""

    def post(self, request, pk, *args, **kwargs):
        """
        Delete a specific notification.

        Args:
            request: The HTTP request object.
            pk: Primary key of the notification to delete.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Returns:
            HttpResponse: HTTP 200 response on success.
        """
        try:
            notif = get_user_notifications(request.user).get(pk=pk)
            notif.delete()
        except Notification.DoesNotExist:
            # The delete button reloads the messages after its click, which shows this.
            messages.error(request, _("The requested record does not exist."))
            return HttpResponse(status=200)
        messages.success(request, _("Notification Deleted."))
        response = HttpResponse(status=200)
        return response


class DeleteAllNotification(LoginRequiredMixin, View):
    """View to delete all notifications for the current user."""

    def post(self, request, *args, **kwargs):
        """
        Delete all notifications for the current user.

        Args:
            request: The HTTP request object.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Returns:
            HttpResponse: Rendered sidebar list template.
        """
        get_user_notifications(request.user).delete()
        messages.success(request, f"All notifications cleared.")
        return render(request, "sidebar_list.html", {"request": request})


@method_decorator(htmx_required, name="dispatch")
class OpenNotificationView(LoginRequiredMixin, View):
    """View to open a notification: redirect to URL if present, else show detail popup."""

    def get(self, request, pk, *args, **kwargs):
        """
        Mark a notification as read. If it has a URL, redirect. Otherwise show a
        detail popup with the related object's details (or notification message only).
        """
        try:
            notif = get_user_notifications(request.user).get(pk=pk)
            notif.read = True
            notif.save()

            url = (notif.url or "").strip()
            response = HttpResponse()
            response["HX-Redirect"] = url
            return response

        except Notification.DoesNotExist:
            return render(request, "403.html", status=404)


class ToggleNotificationSoundView(LoginRequiredMixin, View):
    """Toggle the notification sound mute preference for the current user."""

    def post(self, request, *args, **kwargs):
        """Invert ``sound_muted`` and return the refreshed notification list partial."""
        pref, _ = NotificationSoundPreference.objects.get_or_create(user=request.user)
        pref.sound_muted = not pref.sound_muted
        pref.save()
        unread = get_user_notifications(request.user).filter(read=False)
        return render(
            request,
            "notification_list.html",
            {
                "unread_notifications": unread,
                "notification_sound_muted": pref.sound_muted,
                "keep_open": True,
            },
        )
