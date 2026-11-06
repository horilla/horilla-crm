"""Version and metadata for the booking app."""

from horilla.utils.translation import gettext_lazy as _

__version__ = "1.11.12"
__module_name__ = _("Booking")
__release_date__ = ""
__description__ = _(
    "Public scheduling pages with slot availability, online meeting links "
    "(Zoom, Google Meet, Microsoft Teams), CRM lead integration, and "
    "confirmation, reminder, reschedule, and cancellation emails."
)
__icon__ = "/assets/icons/calendar.svg"

__1_11_12__ = _(
    "Booking page modals use Create and Update titles. Select and Enter "
    "placeholders are built from the field label."
)

__1_11_11__ = _(
    "Public booking pages can be embedded on any site. Blocked dates and "
    "slots say why. Reschedule uses the booking page in the booker's "
    "timezone. A honeypot, a per-IP limit and a cap on active bookings per "
    "email cut off scripted bookings."
)

__1_11_10__ = _(
    "Show My Bookings and the linked meeting activities to users who only "
    "have view-own booking access."
)

__1_11_9__ = _(
    "Honor ShiftHour break windows in slot generation; fix public date-strip "
    "navigation; show Join actions for meeting links."
)

__1_11_8__ = _(
    "Build public booking links from SITE_URL, matching web-to-lead and "
    "password-reset link generation."
)

__1_11_7__ = _(
    "Restrict meeting provider choices to connected integrations. Validate outgoing "
    "mail configuration before enabling email-dependent booking features."
)

__1_11_6__ = _(
    "Adopt shared empty_state gate when Business Hours are missing. Derive list column "
    "labels from model verbose_name; add cursor-pointer on clickable controls."
)

__1_11_5__ = _(
    "Use shared WEEK_ORDER / weekday choices and the Horilla generic View base. "
    "Apply runtime viewport fit on booking settings list and detail pages."
)

__1_11_4__ = _(
    "Resolve public booking slots in the booker's timezone instead of the server's. "
    "New booking pages pick up the shared theme accent color instead of a hardcoded default."
)

__1_11_3__ = _("Registered Booking for export_data.")

__1_11_2__ = _(
    "Added ModalDetailView with clickable rows, prev/next navigation, and status "
    "change actions; replaced hardcoded modal colors with theme variables. Split "
    "booking/views.py into booking_page, booking_list, and public modules. Use load_branding() "
    "TITLE as the fallback company name in reminder and confirmation emails."
)

__1_11_1__ = _(
    "Improved booking calendar UX with timezone-aware slot display and confirmation "
    "rendering. Fixed the public date-strip to read date-object properties instead of "
    "stale outer-scope month/day variables. Adopted the utils.timezone shim and "
    "standardized first-party import groups across booking models, tasks, utils, and views."
)

__1_11_0__ = _(
    "Select2 timezone picker and clearer public scheduling layout. "
    "HTMX toggles for allow_cancel, allow_reschedule, and is_online with "
    "better online/offline location controls and brand-color widget rendering. "
    "Per-booking-page mail templates for confirmation, cancellation, and reschedule — "
    "plus Celery reminder emails aligned with CRM lead/contact/activity hooks."
)

__1_10_0__ = _(
    "Initial release: booking pages with business-hour or shift-hour availability, "
    "public booking forms, embed URLs, custom questions and brand colors, "
    "My Bookings under My Jobs, settings under General Settings, optional mail "
    "templates for confirmation/cancellation/reschedule, Celery reminder tasks, "
    "and automatic lead and activity creation on booking submission."
)
