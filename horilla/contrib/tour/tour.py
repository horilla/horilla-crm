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


def _header_button(title, body, icon=None, target=None):
    """A step on a header action: found by its icon (the translated text never matters) or by ``target``."""
    return Step(
        title=title,
        body=body,
        target=target or f"#header button:has(> .{icon})",
        side="bottom",
        align="end",
    )


class AppShellTour(Tour):
    """The tour every user is offered first, on the Home page."""

    key = "app_shell"
    title = _("Find Your Way Around")
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
            title=_("Quick Actions"),
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
        _header_button(
            _("Toggle Theme"),
            _("Switch between the light and dark theme."),
            target="#darkModeToggle",
        ),
        _header_button(
            _("Settings"),
            _(
                "Open the system settings: users, roles, companies, "
                "integrations and more."
            ),
            "fa-cog",
        ),
        _header_button(
            _("Recently Viewed"),
            _("Jump back to the records you opened lately."),
            "fa-history",
        ),
        _header_button(
            _("Language"), _("Change the language of the interface."), "fa-globe"
        ),
        _header_button(
            _("Switch Company"),
            _(
                "Change the company you are working in, or see all your "
                "companies together."
            ),
            "fa-th-large",
        ),
        _header_button(
            _("Notifications"),
            _("Reminders, assignments and mentions show up here."),
            target="#notificationWrapper",
        ),
        _header_button(
            _("Your Profile"),
            _(
                "Open your settings, take a product tour again or sign out "
                "from the profile menu."
            ),
            target="#header .dropdown-wrapper:has(img.header-profile-avatar)",
        ),
    ]
