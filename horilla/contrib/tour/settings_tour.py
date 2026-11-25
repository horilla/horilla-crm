"""
Tours of the Settings pages: Settings (system) and My Settings (personal).

The core app owns these pages but must not depend on the tour app, so their tours live
here, in the tour app, and are picked up through ``"settings_tour"`` in this app's
``auto_import_modules``. The tour app may depend on core; core never imports the tour
app.
The two tours only explain the page itself (search, the menu and where a page opens),
not each settings page, because the pages come from many apps and change often. A step
whose element is missing (a menu section the user has no permission for, an empty
menu) is skipped.
"""

# Standard library imports
from functools import lru_cache

# First party imports (Horilla)
from horilla.menu.my_settings_menu import my_settings_menu
from horilla.menu.settings_menu import settings_registry
from horilla.urls import Resolver404, resolve
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .registry import Step, Tour

# Settings: the search box, the menu and the area a page opens in.
SETTINGS_SEARCH = "#settings-search-wrapper"
SETTINGS_MENU = "#settings-menu-list"
# The menu is taller than the screen, so the steps light one section at a time: the first
# (open, with its pages) and the button of the second.
SETTINGS_FIRST_SECTION = f"{SETTINGS_MENU} .settings-menu-group:first-child"
SETTINGS_FIRST_PAGE = f"{SETTINGS_FIRST_SECTION} .settings-menu-item:first-child"
SETTINGS_SECOND_SECTION = f"{SETTINGS_MENU} .settings-menu-group:nth-child(2) > button"
SETTINGS_CONTENT = "#settings-content"

# My Settings: the profile card, the menu and the area a page opens in.
MY_SIDEBAR = "#my-settings-sidebar"
MY_PROFILE = f"{MY_SIDEBAR} > div:first-child"
MY_MENU = f"{MY_SIDEBAR} ul"
MY_CONTENT = "#my-settings-content"


def _view_name(url):
    """The URL name of a menu item's URL, or ``None`` if it does not resolve."""
    try:
        return resolve(str(url).split("?")[0]).view_name or None
    except Resolver404:
        return None


def _page_names(own_name, urls):
    """
    ``own_name`` plus the URL name of every URL in ``urls``.

    Settings and My Settings open their pages in place and push their URL, so the
    address changes from the page's own URL to that of the first page (and then of
    each page picked). The tour belongs to all of them. The menus are registered when
    the apps load, so the callers build the list on first use.
    """
    names = {own_name, *map(_view_name, urls)}
    names.discard(None)
    return tuple(sorted(names))


@lru_cache(maxsize=None)
def settings_page_names():
    """URL names of Settings and of every page its menu opens."""
    items = (
        (item(None) or {}) if callable(item) else item
        for menu in settings_registry
        for item in getattr(menu(), "items", [])
    )
    return _page_names("core:settings_view", (item.get("url") for item in items))


@lru_cache(maxsize=None)
def my_settings_page_names():
    """URL names of My Settings and of every page its menu opens."""
    return _page_names(
        "core:my_settings_view",
        (getattr(item(), "url", None) for item in my_settings_menu),
    )


class SettingsTour(Tour):
    """The Settings page."""

    key = "settings"
    title = _("Finding Your Way in Settings")
    description = _(
        "Search the settings, open a section and see where each page opens."
    )
    group = _("Settings")
    icon = "/assets/icons/general.svg"
    order = 700
    match = ("core:settings_view",)
    permission = "core.can_view_horilla_settings"
    # The menu is drawn with the page.
    ready = f"{SETTINGS_MENU} .settings-menu-group"
    auto_start = True

    @classmethod
    def match_names(cls):
        """Settings and every page it opens, whose URL replaces the Settings one."""
        return list(settings_page_names())

    steps = [
        Step(
            title=_("Settings"),
            body=_(
                "Manage your company, users and system configuration. This "
                "short tour shows how the page is laid out."
            ),
        ),
        Step(
            title=_("Search Settings"),
            body=_(
                "Type what you are looking for, such as a user, a role or a "
                "currency. The matches are grouped by section, and a click "
                "opens the page."
            ),
            target=SETTINGS_SEARCH,
            side="right",
        ),
        Step(
            title=_("Sections"),
            body=_(
                "Settings are grouped into sections, such as General. You only "
                "see the sections and pages your role may open."
            ),
            target=SETTINGS_FIRST_SECTION,
            side="right",
        ),
        Step(
            title=_("Open a Page"),
            body=_(
                "Click a page to open it on the right. The page you are on is marked."
            ),
            target=SETTINGS_FIRST_PAGE,
            side="right",
        ),
        Step(
            title=_("Open or Close a Section"),
            body=_("Click a section name to show its pages or hide them."),
            target=SETTINGS_SECOND_SECTION,
            side="right",
        ),
        Step(
            title=_("The Page"),
            body=_(
                "The page you pick opens here. Edit or add records in place "
                "without leaving Settings."
            ),
            target=SETTINGS_CONTENT,
            side="left",
        ),
    ]


class MySettingsTour(Tour):
    """The My Settings page."""

    key = "my_settings"
    title = _("Finding Your Way in My Settings")
    description = _(
        "Your profile, password, regional formats, login history, holidays "
        "and shift hours."
    )
    group = _("Settings")
    icon = "/assets/icons/general.svg"
    order = 701
    match = ("core:my_settings_view",)
    ready = MY_SIDEBAR
    auto_start = True

    @classmethod
    def match_names(cls):
        """My Settings and every page it opens, whose URL replaces the My Settings one."""
        return list(my_settings_page_names())

    steps = [
        Step(
            title=_("My Settings"),
            body=_(
                "Manage your personal profile, password and preferences. "
                "These settings only change your own account."
            ),
        ),
        Step(
            title=_("Your Profile"),
            body=_("Your name and role. Click it to open and edit your profile."),
            target=MY_PROFILE,
            side="right",
        ),
        Step(
            title=_("Your Pages"),
            body=_(
                "Regional and formatting, password, login history, holidays "
                "and shift hours. Click one to open it on the right."
            ),
            target=MY_MENU,
            side="right",
        ),
        Step(
            title=_("The Page"),
            body=_("The page you pick opens here, and you can change it in place."),
            target=MY_CONTENT,
            side="left",
        ),
    ]
