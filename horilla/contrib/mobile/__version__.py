"""
Version and metadata information for the mobile module.
"""

# First party imports (Horilla)
from horilla.utils.translation import gettext_lazy as _

__version__ = "1.0.8"
__module_name__ = "Mobile"
__release_date__ = ""
__description__ = _(
    "Optional installable phone mode under /m/ for quick on-the-go work."
)
__icon__ = "favicons/android-chrome-192x192.png"

__1_0_8__ = _("The phone sign-in page uses the product name from branding.")

__1_0_7__ = _(
    "Mine / Team switch on the Agenda, as on the desktop calendar: the team's "
    "activities by the All Activities list rule, a team members filter, and "
    "the choice kept between visits."
)

__1_0_6__ = _(
    "Edit details on the record page: the fields of the desktop Details tab "
    "that the user may change, saved by the desktop Edit Details save, for "
    "owners with change_own and users with change."
)

__1_0_5__ = _(
    "New order option in mobile.py: the place of a model among the record "
    "types on the Records tab."
)

__1_0_4__ = _(
    "Agenda tab: the user's own activities day by day with a week strip, "
    "unavailability and the desktop calendar's type filter; meetings and "
    "events are added and edited on the phone with the desktop forms, from "
    "the Agenda or a record page."
)

__1_0_3__ = _(
    "Today tab, now the start page: the user's own tasks, meetings and events "
    "in Overdue, Today and Upcoming, with a Next card, Call buttons and mark "
    "as done with undo."
)

__1_0_2__ = _(
    "Log activity from the record page: log a call and add a task with the "
    "desktop activity forms, and add a short text note. Tapping an activity "
    "or note opens everything saved on it, with an edit button when the user "
    "may change it; rows show the status and the text. New subtitle_fields "
    "option for a line under the record's title."
)

__1_0_1__ = _(
    'Records tab and record page: models opt in with features=["mobile"] '
    "and a mobile.py of display settings; browse, filter and search every "
    "opted-in model; Call and Email, key fields from the desktop detail page, "
    "stage changes through the desktop stage update, open activities and "
    "interactions."
)

__1_0_0__ = _(
    "Installable phone shell under /m/: mobile layout, login and logout, "
    "a web app manifest and a service worker that only caches versioned "
    "static files."
)
