"""
Version and metadata for the calendar app.

Contains the module's version string and descriptive metadata used in the
application registry and UI.
"""

# First party imports (Horilla)
from horilla.utils.translation import gettext_lazy as _

__version__ = "1.11.11"
__module_name__ = "Calendar"
__release_date__ = ""
__description__ = _("Module for managing calendar events and schedules.")
__icon__ = "assets/icons/calendar-red.svg"

__1_11_11__ = _(
    "Choose who can use Google Calendar: all users, specific roles or "
    "specific users."
)

__1_11_10__ = _(
    "Rebuild the calendar grid after a reload swap. Warn when Google "
    "Calendar sync is toggled to the state it is already in. Keep long "
    "event-popup text inside the card and hide the reload buttons."
)

__1_11_9__ = _(
    "Show multi-day events in the all-day row and block past unavailability. "
    "Activity assignees modal with user pills and search (hidden on short "
    "lists). Keep the detail URL and menu section on refresh; require change "
    "permission to mark complete and view permission to open assignees."
)

__1_11_8__ = _(
    "Team calendar: members filter (user picker), status filter, unavailability for "
    "filtered members, applied members first; rebuild custom calendars around module "
    "activities with event text colors; fix duplicate custom/standard events and "
    "all-day date spanning/creation; action-button layout."
)

__1_11_7__ = _(
    "Color by Type/Status sidebar toggle; Open Related Record on activity events; "
    "show Google credentials validation errors; harden OAuth callback state; skip "
    "Google push enqueue under manage.py test."
)

__1_11_6__ = _(
    "Reduce preference and assignee queries. Cache Google Calendar integration "
    "settings per company. Refresh the sub-sidebar when switching main sections."
)

__1_11_5__ = _("Close cross-tenant and privilege-escalation gaps in the Calendar API.")

__1_11_4__ = _(
    "Harden Google Calendar sync (service, sync, and views) and surface meeting links "
    "more reliably when events are created or updated."
)

__1_11_3__ = _(
    "Google Calendar sync uses max() to ensure end datetime is never before start. "
    "Standardized exception chaining in calendar forms."
)

__1_11_2__ = _(
    "Resolve Google Calendar integration settings from the user's company with all_objects. "
    "Use all_objects for GoogleCalendarConfig lookups to prevent missing config and UNIQUE "
    "constraint errors when admins switch company context. Scope disconnect to active company "
    "when admin disables integration."
)

__1_11_1__ = _(
    "Restored CSRF protection on SaveCalendarPreferencesView (removed @csrf_exempt). "
    "Migrated signal and timezone imports to the horilla shims and standardized "
    "first-party import groups; behavior unchanged."
)

__1_10_2__ = _(
    "Custom calendar form aligned with HorillaModelForm layout: field_order, "
    'Meta.fields = "__all__", and Meta.exclude; save logic and HTMX behavior unchanged.'
)

__1_10_1__ = _(
    "Google Calendar integration settings now pass the full request on POST so "
    "get_or_create uses the active company consistently with GET."
)

__1_10_0__ = _(
    "Release 1.10: calendar ships under contrib with app label calendar. "
    "Google Calendar sync, webhook settings, namespaces, templates, and integrations "
    "updated from the legacy calendar app naming."
)

__1_2_0__ = _(
    "Introduced Google Calendar integration with sync capabilities, "
    "service configuration, and settings management for seamless "
    "external calendar connectivity."
)

__1_1_1__ = _(
    "Compatibility updates and minor internal improvements to align with "
    "platform architecture and generics framework updates."
)

__1_1_0__ = _(
    "Migrated from Django AppConfig to Horilla AppLauncher and replaced Django utilities"
    "with horilla.utils.decorators, horilla.utils.translation, and horilla.shortcuts where applicable."
)
