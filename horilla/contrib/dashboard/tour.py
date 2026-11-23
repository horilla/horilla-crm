"""
Tour of the Dashboard app: the Home page, the landing page after sign-in.

Picked up through ``"tour"`` in this app's ``auto_import_modules``, like ``menu.py``.
A step whose element is missing (no permission, a dashboard shown instead of the
default layout, no onboarding checklist) is skipped.
"""

# First party imports (Horilla)
from horilla.contrib.tour.presets import click, if_hidden, if_visible
from horilla.contrib.tour.registry import Step, Tour
from horilla.utils.translation import gettext_lazy as _

DASHBOARD_VIEW_PERMS = ["dashboard.view_dashboard", "dashboard.view_own_dashboard"]
DASHBOARD_LIST_URL = "dashboard:dashboard_list_view"
FIRST_DASHBOARD = "#data-container-dashboard-list tr:first-child td[hx-get]"

# Reorder mode: the Cancel / Save buttons that replace the Reorder button, and the drag
# handle each card shows while it is on.
EDIT_MODE = "#editModeActions"
CANCEL_EDIT = "#cancelEditBtn"
DRAG_HANDLE = (
    "#reorderable-kpis .edit-drag-handle, #reorderable-components .edit-drag-handle"
)

# The cards of a dashboard, each with the "…" button that opens its menu.
KPI_CARD = "#reorderable-kpis > :first-child"
CHART_CARD = "#reorderable-components .dashboard-component-card:first-child"
TABLE_CARD = "#reorderable-components .dashboard-component-card:has(table)"
MENU_BUTTON = '[id^="dropdownbtn-"]'
MENU = f"{MENU_BUTTON} ~ .dropdown-content"


def menu_step(title, body, card):
    """A step that opens the "…" menu of ``card`` and lights the button with its menu."""
    button = f"{card} {MENU_BUTTON}"
    menu = f"{card} {MENU}"
    return Step(
        title=title,
        body=body,
        target=button,
        also=menu,
        only_if=button,
        side="left",
        before=(click(button, if_hidden(menu)),),
        after=(click(button, if_visible(menu)),),
    )


class DashboardHomeTour(Tour):
    """The Home page."""

    key = "dashboard_home"
    title = _("Your Home Page")
    description = _(
        "The overview you land on after signing in: date range, key "
        "numbers and charts."
    )
    group = _("Dashboard")
    icon = "/assets/icons/home.svg"
    order = 100
    match = ("dashboard:home_view",)
    ready = "#mainContent h1"
    auto_start = True
    steps = [
        Step(
            title=_("Home"),
            body=_("A quick look at how your business is doing today."),
        ),
        Step(
            title=_("Date Range"),
            body=_("Change the period every number and chart is based on."),
            target="#dateRangeFilterContainer",
            side="bottom",
        ),
        Step(
            title=_("Key Numbers"),
            body=_("Your most important figures, as cards."),
            target="#default-home-kpis, #reorderable-kpis",
            side="bottom",
        ),
        Step(
            title=_("Charts"),
            body=_(
                "Charts show your data at a glance. Each card sums up one "
                "part of the numbers above."
            ),
            target=(
                "#default-home-charts-and-tables .chart-container, "
                "#reorderable-components .dashboard-component-card"
            ),
            side="top",
        ),
        Step(
            title=_("Tables"),
            body=_(
                "Lists of records you can scroll through and open without "
                "leaving the page."
            ),
            target="#default-home-charts-and-tables .table-container",
            side="left",
        ),
        Step(
            title=_("Arrange Your Page"),
            body=_("Reorder the cards and charts to suit the way you work."),
            target="#editLayoutBtn",
            side="left",
        ),
        Step(
            title=_("All Dashboards"),
            body=_(
                "This button leads to the list of all your dashboards, where "
                "you can create new ones, organise them in folders and mark "
                "your favourites."
            ),
            target="#viewAllDashboardsBtn",
            side="bottom",
            align="end",
        ),
        Step(
            title=_("Get Started"),
            body=_("A short checklist to finish setting up your CRM."),
            target="#onboarding, #onboarding-link",
            side="bottom",
        ),
    ]


class DashboardsListTour(Tour):
    """The list of dashboards."""

    key = "dashboards_list"
    title = _("Working with Dashboards")
    description = _(
        "Create a dashboard, keep dashboards in folders and choose the one "
        "you see on Home."
    )
    group = _("Dashboard")
    icon = "/assets/icons/dashboards.svg"
    order = 510
    match = (DASHBOARD_LIST_URL,)
    ready = "#navBar h3"
    permission = DASHBOARD_VIEW_PERMS
    auto_start = True
    steps = [
        Step(
            title=_("Dashboards"),
            body=_("A dashboard puts your key numbers and charts on one page."),
        ),
        Step(
            title=_("New Dashboard"),
            body=_("Create a dashboard, then add numbers and charts to it."),
            target="#dashboard-create",
            side="bottom",
            align="end",
        ),
        Step(
            title=_("New Folder"),
            body=_("Keep related dashboards together in a folder."),
            target="#dashboard-folder-create",
            side="bottom",
            align="end",
        ),
        Step(
            title=_("Open a Dashboard"),
            body=_("Click a name to open the dashboard."),
            target=FIRST_DASHBOARD,
            side="bottom",
        ),
        Step(
            title=_("Is Default"),
            body=_(
                "Turn this on to show the dashboard on your Home page. Only "
                "one dashboard can be the default."
            ),
            # The toggle of the first row (name, description, folder, default, actions).
            target="#data-container-dashboard-list tr:first-child td:nth-child(4)",
            side="bottom",
        ),
        Step(
            title=_("Actions"),
            body=_(
                "Mark it as a favourite, edit it, move it to a folder or " "delete it."
            ),
            target="#data-container-dashboard-list tr:first-child td:last-child > div",
            side="left",
        ),
        Step(
            title=_("Browse"),
            body=_("See all dashboards, your folders or your favourites."),
            target="div:has(> #mainSession) + div",
            side="left",
        ),
    ]


class DashboardsDetailTour(Tour):
    """A single dashboard."""

    key = "dashboards_detail"
    title = _("Inside a Dashboard")
    description = _(
        "The numbers and charts of a dashboard, and how to add, arrange and "
        "change them."
    )
    group = _("Dashboard")
    icon = "/assets/icons/dashboards.svg"
    order = 511
    match = ("dashboard:dashboard_detail_view",)
    open_with = {"from": DASHBOARD_LIST_URL, "click": FIRST_DASHBOARD}
    ready = "#dashboard-detail-view"
    permission = DASHBOARD_VIEW_PERMS
    auto_start = True
    steps = [
        Step(
            title=_("Your Dashboard"),
            body=_("The name of the dashboard. The arrow goes back to the list."),
            # The arrow and the name are lit together.
            target="#navBar button:has(> .fa-arrow-left)",
            also="#navBar h3",
            side="bottom",
        ),
        Step(
            title=_("Add Components"),
            body=_("Add a number, a chart or a table to this dashboard."),
            target="#addComponentBtn",
            side="bottom",
            align="end",
        ),
        Step(
            title=_("Reorder"),
            body=_("Click it to move the cards around."),
            target="#editLayoutBtn",
            only_if="#editLayoutBtn",
            side="bottom",
            align="end",
            # Coming back from reorder mode: leave it first.
            before=(click(CANCEL_EDIT, if_visible(EDIT_MODE)),),
        ),
        # The next two steps are in reorder mode: the first turns it on, the last turns it off.
        Step(
            title=_("Save or Cancel"),
            body=_(
                "Click Save to keep the new order, or Cancel to leave it as it was."
            ),
            target=EDIT_MODE,
            only_if="#editLayoutBtn",
            side="bottom",
            align="end",
            before=(click("#editLayoutBtn", if_hidden(EDIT_MODE)),),
        ),
        Step(
            title=_("Drag"),
            body=_("Hold these dots and drag the card where you want it."),
            target=DRAG_HANDLE,
            side="right",
            after=(click(CANCEL_EDIT, if_visible(EDIT_MODE)),),
        ),
        Step(
            title=_("A Number"),
            body=_("A key figure. Click it to see the records behind it."),
            target=KPI_CARD,
            side="bottom",
        ),
        menu_step(
            _("Number Options"),
            _("Edit it, add it to another dashboard or delete it."),
            KPI_CARD,
        ),
        Step(
            title=_("A Chart"),
            body=_("Your data at a glance."),
            target=CHART_CARD,
            side="top",
        ),
        menu_step(
            _("Chart Options"),
            _(
                "Edit it, save it as a PNG or PDF, add it to another "
                "dashboard or delete it."
            ),
            CHART_CARD,
        ),
        Step(
            title=_("A Table"),
            body=_("A list of records from your CRM."),
            target=TABLE_CARD,
            side="top",
        ),
        menu_step(
            _("Table Options"),
            _("Edit it, add it to another dashboard or delete it."),
            TABLE_CARD,
        ),
    ]
