"""
Tour of the Dashboard app: the Home page, the landing page after sign-in.

Picked up through ``"tour"`` in this app's ``auto_import_modules``, like ``menu.py``.
A step whose element is missing (no permission, a dashboard shown instead of the
default layout, no onboarding checklist) is skipped.
"""

# First party imports (Horilla)
from horilla.contrib.tour.registry import Step, Tour
from horilla.utils.translation import gettext_lazy as _


class DashboardHomeTour(Tour):
    """The Home page."""

    key = "dashboard_home"
    title = _("Your home page")
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
            title=_("Date range"),
            body=_("Change the period every number and chart is based on."),
            target="#dateRangeFilterContainer",
            side="bottom",
        ),
        Step(
            title=_("Key numbers"),
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
            title=_("Arrange your page"),
            body=_("Reorder the cards and charts to suit the way you work."),
            target="#editLayoutBtn",
            side="left",
        ),
        Step(
            title=_("All dashboards"),
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
            title=_("Get started"),
            body=_("A short checklist to finish setting up your CRM."),
            target="#onboarding, #onboarding-link",
            side="bottom",
        ),
    ]
