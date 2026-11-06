"""Version and metadata for the horilla.contrib.meeting app."""

from horilla.utils.translation import gettext_lazy as _

__version__ = "1.11.12"
__module_name__ = _("Meeting Integration")
__release_date__ = ""
__description__ = _(
    "Zoom and Microsoft Teams meeting integration with company access control, "
    "OAuth connections, personal meeting URLs, and activity meeting links."
)
__icon__ = "meeting/assets/icons/meetings.svg"

__1_11_12__ = _(
    "Offer Google Meet only when the user is allowed by the Google Calendar "
    "access setting."
)

__1_11_11__ = _(
    "Use the shared feature-disabled empty state when meeting integration "
    "is off in user settings."
)

__1_11_10__ = _(
    "Check that meeting integration is enabled before every admin and user " "action."
)

__1_11_9__ = _(
    "Show the allowed users and roles modals as pills with the standard " "search bar."
)

__1_11_8__ = _("Prevent crash on invalid Zoom/Teams OAuth callback state.")

__1_11_7__ = _("Fix Teams guest email display and surface real Microsoft Graph errors.")

__1_11_6__ = _("Cache meeting integration settings per company.")

__1_11_5__ = _(
    "Derive list column labels from model verbose_name instead of hardcoded translations."
)

__1_11_4__ = _(
    "Add connect/read timeouts on outbound Zoom and Microsoft Graph (Teams) OAuth and "
    "API calls so a blocked network path cannot hang a worker indefinitely."
)

__1_11_3__ = _(
    "Restricted allowed-users and allowed-roles list views to HTMX requests."
)

__1_11_2__ = _(
    "Google Meet option now hides when Google Calendar integration is disabled. Resolve "
    "meeting integration settings from the user's company via all_objects and use unfiltered "
    "GoogleCalendarConfig lookups in provider settings and link generation. Handle missing "
    "active company gracefully in integration settings views."
)

__1_11_1__ = _(
    "Fixed MultipleObjectsReturned on the Zoom and Teams OAuth callbacks. Improved the "
    "access-control UI: constrained the section to the viewport, added a count + eye pill "
    "for allowed users and roles that opens a HorillaListView modal, and fixed the "
    "card-wide click handler. Added integration-settings view docstrings for pylint."
)

__1_10_0__ = _(
    "Initial release: company-level meeting integration settings, Zoom and Teams OAuth, "
    "per-user provider settings, MeetingLink CRUD, admin integration screens under "
    "Settings → Integrations, My Settings entries, and generate-link support for activities."
)
