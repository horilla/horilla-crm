"""
Celery tasks for horilla_booking — booking reminder emails.
"""

# Standard library imports
import logging
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from celery import shared_task

# Third-party imports (Django)
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection

# First party imports (Horilla)
from horilla.contrib.mail.models import HorillaMailConfiguration
from horilla.urls import reverse_lazy
from horilla.utils import timezone
from horilla.utils.branding import load_branding


def _format_for_booker(booking):
    """Return formatted start/end strings in the booker's own timezone."""
    try:
        tz = (
            ZoneInfo(booking.booker_timezone)
            if booking.booker_timezone
            else timezone.get_current_timezone()
        )
    except (ZoneInfoNotFoundError, KeyError):
        tz = timezone.get_current_timezone()
    local_start = booking.start_datetime.astimezone(tz)
    local_end = booking.end_datetime.astimezone(tz)
    tz_label = str(tz)
    start_str = local_start.strftime("%A, %B %d, %Y at %I:%M %p")
    end_str = local_end.strftime("%I:%M %p")
    return f"{start_str} – {end_str} ({tz_label})"


def _format_for_host(booking):
    """Return formatted start/end strings in the server/host timezone."""
    local_start = timezone.localtime(booking.start_datetime)
    local_end = timezone.localtime(booking.end_datetime)
    tz_label = str(timezone.get_current_timezone())
    start_str = local_start.strftime("%A, %B %d, %Y at %I:%M %p")
    end_str = local_end.strftime("%I:%M %p")
    return f"{start_str} – {end_str} ({tz_label})"


logger = logging.getLogger(__name__)


@shared_task
def send_booking_reminders():
    """
    Runs every 15 minutes via Celery Beat.
    Sends reminder emails for bookings whose reminder_at falls within
    the current 15-minute window.
    """
    from .models import Booking  # lazy — Celery imports tasks before apps are ready

    now = timezone.now()
    window_end = now + timedelta(minutes=15)

    bookings = Booking.all_objects.filter(
        status__in=["pending", "confirmed"],
        booking_page__reminder_hours__isnull=False,
        start_datetime__gt=now,
    ).select_related("booking_page", "booking_page__host")

    sent = 0
    for booking in bookings:
        remind_at = booking.start_datetime - timedelta(
            hours=booking.booking_page.reminder_hours
        )
        if now <= remind_at < window_end:
            try:
                _send_reminder_email(booking)
                sent += 1
            except Exception:
                logger.exception(
                    "Failed to send reminder for booking pk=%s", booking.pk
                )

    logger.info("send_booking_reminders: sent %d reminder(s)", sent)
    return sent


def _get_mail_config(company):
    return (
        HorillaMailConfiguration.objects.filter(
            company=company, mail_channel="outgoing", is_primary=True
        ).first()
        or HorillaMailConfiguration.objects.filter(
            company=company, mail_channel="outgoing"
        ).first()
    )


def _get_connection(mail_config):
    if mail_config:
        return get_connection("horilla.contrib.mail.backends.HorillaDefaultMailBackend")
    return get_connection()


def _send_reminder_email(booking):
    """Send an HTML reminder email to the booker."""
    from .models import build_public_booking_url  # lazy — see send_booking_reminders

    page = booking.booking_page
    company = booking.company
    mail_config = _get_mail_config(company)

    start_str = _format_for_booker(booking)
    host_label = page.host.get_full_name() or page.host.username

    if page.is_online and booking.meeting_url:
        location_line = (
            f"<p>&#128279; <strong>Join:</strong> "
            f'<a href="{booking.meeting_url}">{booking.meeting_url}</a></p>'
        )
    elif page.location:
        location_line = f"<p>&#128205; <strong>Location:</strong> {page.location}</p>"
    else:
        location_line = ""

    cancel_url = build_public_booking_url(
        reverse_lazy(
            "booking:booking_cancel", kwargs={"token": booking.cancellation_token}
        )
    )
    reschedule_url = build_public_booking_url(
        reverse_lazy(
            "booking:booking_reschedule", kwargs={"token": booking.cancellation_token}
        )
    )

    html_body = f"""
<div style="max-width:600px;margin:auto;background:white;border-radius:12px;padding:32px;font-family:sans-serif">
  <h2 style="color:#111;margin-bottom:6px">&#128337; Meeting Reminder</h2>
  <p style="color:#555;margin-bottom:20px">This is a reminder for your upcoming meeting.</p>
  <div style="background:#f9fafb;border-left:4px solid #e54f38;border-radius:6px;padding:16px;margin-bottom:20px">
    <p style="margin:4px 0"><strong>{page.title}</strong></p>
    <p style="margin:4px 0;color:#555">&#128197; {start_str}</p>
    <p style="margin:4px 0;color:#555">&#128100; Host: {host_label}</p>
    {location_line}
  </div>
  <p style="font-size:12px;color:#999">
    <a href="{reschedule_url}" style="color:#e54f38">Reschedule</a> &nbsp;|&nbsp;
    <a href="{cancel_url}" style="color:#999">Cancel</a>
  </p>
</div>"""

    plain_body = (
        f"Reminder: {page.title}\n"
        f"When: {start_str}\n"
        f"Host: {page.host.get_full_name() or page.host.username}\n"
    )

    from_email = getattr(mail_config, "from_email", None) or getattr(
        settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"
    )

    try:
        msg = EmailMultiAlternatives(
            subject=f"Reminder: {page.title}",
            body=plain_body,
            from_email=from_email,
            to=[booking.booker_email],
            connection=_get_connection(mail_config),
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send()
        logger.info(
            "Sent reminder to %s for booking pk=%s", booking.booker_email, booking.pk
        )
    except Exception:
        logger.exception("Email send error for booking pk=%s", booking.pk)


def send_booking_confirmation_email(booking, cancel_url="", reschedule_url=""):
    """Send a meeting-invitation-style confirmation email to the booker."""
    page = booking.booking_page
    company = booking.company
    mail_config = _get_mail_config(company)

    time_line = _format_for_booker(booking)

    host_name = page.host.get_full_name() or page.host.username
    meeting_url = booking.meeting_url or ""
    company_name = str(company) if company else str(load_branding()["TITLE"])

    template_context = {
        "booking": booking,
        "page": page,
        "host_name": host_name,
        "time_line": time_line,
        "meeting_url": meeting_url,
        "company_name": company_name,
        "cancel_url": cancel_url,
        "reschedule_url": reschedule_url,
    }

    subject_line = f"Booking Confirmed: {page.title}"
    mail_template = getattr(page, "confirmation_mail_template", None)
    if mail_template:
        try:
            rendered = mail_template.render_subject(context=template_context)
            if rendered:
                subject_line = rendered
        except Exception:
            pass

    if meeting_url:
        join_link_row = (
            f'<p style="margin:6px 0;font-size:14px;color:#333">'
            f"&#128279; <strong>Join Link:</strong> "
            f'<a href="{meeting_url}" style="color:#e54f38;">{meeting_url}</a></p>'
        )
        join_button = (
            f'<div style="text-align:center;margin-top:25px">'
            f'<a href="{meeting_url}" style="display:inline-block;padding:10px 20px;'
            f"background-color:#e54f38;color:white;text-decoration:none;border-radius:6px;"
            f'font-weight:500;margin:5px">Join Meeting</a></div>'
        )
    elif page.location:
        join_link_row = (
            f'<p style="margin:6px 0;font-size:14px;color:#333">'
            f"&#128205; <strong>Location:</strong> {page.location}</p>"
        )
        join_button = ""
    else:
        join_link_row = ""
        join_button = ""

    reschedule_cancel_row = ""
    if reschedule_url or cancel_url:
        links = []
        if reschedule_url:
            links.append(
                f'<a href="{reschedule_url}" '
                f'style="color:#e54f38;text-decoration:none;">Reschedule</a>'
            )
        if cancel_url:
            links.append(
                f'<a href="{cancel_url}" style="color:#888;text-decoration:none;">Cancel</a>'
            )
        reschedule_cancel_row = (
            '<p style="text-align:center;font-size:12px;color:#888;margin-top:16px">'
            + " &nbsp;|&nbsp; ".join(links)
            + "</p>"
        )

    html_body = f"""
<div style="max-width:650px;margin:auto;background:white;border-radius:12px;padding:35px;box-shadow:0 4px 12px rgba(0,0,0,0.08)">
  <h2 style="color:#000000;text-align:center;font-size:24px;margin-bottom:25px">
    Meeting Invitation
  </h2>
  <p style="font-size:14px;color:#333;line-height:1.6">
    Your booking with <strong>{host_name}</strong> has been confirmed.
  </p>
  <div style="margin:20px 0;padding:15px;background:#fdf2f1;border-left:4px solid #e54f38;border-radius:6px">
    <p style="margin:6px 0;font-size:14px;color:#333">
      &#128197; <strong>Title:</strong> {page.title}
    </p>
    <p style="margin:6px 0;font-size:14px;color:#333">
      &#128336; <strong>When:</strong> {time_line}
    </p>
    <p style="margin:6px 0;font-size:14px;color:#333">
      &#128100; <strong>Host:</strong> {host_name}
    </p>
    {join_link_row}
  </div>
  {join_button}
  {reschedule_cancel_row}
  <hr style="margin:30px 0;border:none;border-top:1px solid #eee">
  <p style="font-size:12px;color:#888;text-align:center;line-height:1.5">
    This confirmation was sent via <strong>{company_name}</strong>.<br>
    If you were not expecting this, please ignore this email.
  </p>
</div>"""

    plain_body = (
        f"Your booking with {host_name} has been confirmed.\n\n"
        f"Title: {page.title}\nWhen: {time_line}\nHost: {host_name}\n"
        + (f"Join: {meeting_url}\n" if meeting_url else "")
        + (f"Reschedule: {reschedule_url}\n" if reschedule_url else "")
        + (f"Cancel: {cancel_url}\n" if cancel_url else "")
    )

    from_email = getattr(mail_config, "from_email", None) or getattr(
        settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"
    )

    try:
        msg = EmailMultiAlternatives(
            subject=subject_line,
            body=plain_body,
            from_email=from_email,
            to=[booking.booker_email],
            connection=_get_connection(mail_config),
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send()
        logger.info(
            "Sent confirmation to %s for booking pk=%s",
            booking.booker_email,
            booking.pk,
        )
    except Exception:
        logger.exception("Confirmation email failed for booking pk=%s", booking.pk)


def send_status_change_email(booking, new_status):
    """Send email to booker when host changes booking status."""
    page = booking.booking_page
    company = booking.company
    mail_config = _get_mail_config(company)

    status_labels = {
        "confirmed": "Confirmed ✓",
        "cancelled": "Cancelled",
        "completed": "Completed",
        "no_show": "Marked as No-Show",
        "pending": "Rescheduled",
    }
    label = status_labels.get(new_status, new_status.title())
    start_str = _format_for_booker(booking)
    company_name = str(company) if company else str(load_branding()["TITLE"])

    # Pick the right template based on status
    if new_status == "cancelled":
        mail_template = getattr(page, "cancellation_mail_template", None)
    elif new_status == "pending":
        mail_template = getattr(page, "reschedule_mail_template", None)
    else:
        mail_template = None

    template_context = {
        "booking": booking,
        "page": page,
        "label": label,
        "start_str": start_str,
        "company_name": company_name,
        "new_status": new_status,
    }

    subject_line = f"Your booking has been {label.lower()} — {page.title}"
    if mail_template:
        try:
            rendered = mail_template.render_subject(context=template_context)
            if rendered:
                subject_line = rendered
        except Exception:
            pass

    html_body = f"""
<div style="max-width:600px;margin:auto;background:white;border-radius:12px;padding:32px;font-family:sans-serif">
  <h2 style="color:#111">Booking {label}</h2>
  <p style="color:#555">
    Your booking for <strong>{page.title}</strong> on {start_str} has been
    <strong>{label.lower()}</strong>.
  </p>
</div>"""
    plain_body = (
        f"Your booking for {page.title} on {start_str} has been {label.lower()}."
    )

    from_email = getattr(mail_config, "from_email", None) or getattr(
        settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"
    )

    try:
        msg = EmailMultiAlternatives(
            subject=subject_line,
            body=plain_body,
            from_email=from_email,
            to=[booking.booker_email],
            connection=_get_connection(mail_config),
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send()
    except Exception:
        logger.exception("Status change email failed for booking pk=%s", booking.pk)
