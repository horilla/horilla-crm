"""
Tours that belong to the tour app itself.

Tours for a specific app live in that app's own ``tour.py`` (listed in its
``auto_import_modules``, like ``menu.py``). This one covers the application shell
(the sidebar and the header), so it belongs to no single app.
"""

# First party imports (Horilla)
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .registry import Step, Tour


class AppShellTour(Tour):
    """The tour every user is offered first, on the Home page."""

    key = "app_shell"
    title = _("Find your way around")
    description = _(
        "The sidebar and every action in the header: search, settings, "
        "notifications, your profile and more."
    )
    group = _("General")
    icon = "tour/assets/icons/tour.svg"
    order = 0
    match = ("dashboard:home_view",)
    ready = "#sidebar nav"
    auto_start = True
    steps = [
        Step(
            title=_("Welcome"),
            body=_(
                "Take a minute to see how to get around. You can close this "
                "tour whenever you like and restart it later from "
                "Product Tours in your profile menu."
            ),
        ),
        Step(
            title=_("Sidebar"),
            body=_(
                "Each icon is a section of the CRM, such as Home, Sales or "
                "Analytics. Click one to see the pages inside it."
            ),
            target="#sidebar nav",
            side="right",
        ),
        Step(
            title=_("Quick actions"),
            body=_(
                "Create a record from anywhere. Open this button and pick "
                "what you want to add."
            ),
            target="#sidebar .floating-menu",
            side="right",
        ),
        Step(
            title=_("Global Search"),
            body=_("Search across the CRM from any page."),
            target="#header-search",
            side="bottom",
        ),
        Step(
            title=_("Toggle Theme"),
            body=_("Switch between the light and dark theme."),
            target="#darkModeToggle",
            side="bottom",
            align="end",
        ),
        Step(
            title=_("Settings"),
            body=_(
                "Open the system settings: users, roles, companies, "
                "integrations and more."
            ),
            target="#header button:has(> .fa-cog)",
            side="bottom",
            align="end",
        ),
        Step(
            title=_("Recently viewed"),
            body=_("Jump back to the records you opened lately."),
            target="#header button:has(> .fa-history)",
            side="bottom",
            align="end",
        ),
        Step(
            title=_("Language"),
            body=_("Change the language of the interface."),
            target="#header button:has(> .fa-globe)",
            side="bottom",
            align="end",
        ),
        Step(
            title=_("Switch company"),
            body=_(
                "Change the company you are working in, or see all your "
                "companies together."
            ),
            target="#header button:has(> .fa-th-large)",
            side="bottom",
            align="end",
        ),
        Step(
            title=_("Notifications"),
            body=_("Reminders, assignments and mentions show up here."),
            target="#notificationWrapper",
            side="bottom",
            align="end",
        ),
        Step(
            title=_("Your profile"),
            body=_(
                "Open your settings, take a product tour again or sign out "
                "from the profile menu."
            ),
            target="#header .dropdown-wrapper:has(img.header-profile-avatar)",
            side="bottom",
            align="end",
        ),
    ]
