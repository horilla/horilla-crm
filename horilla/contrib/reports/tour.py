"""
Tours of the Reports app: the list of reports (the gear menu and the window that loads
the default reports) and a single report.

Picked up through ``"tour"`` in this app's ``auto_import_modules``, like ``menu.py``.
The list tour is short on purpose: it explains the one thing a new user must do first
(load the ready-made reports) rather than every control of the page. The detail tour
walks through each part of a report. A step whose element is missing (no permission to
add reports, a report with no grouping so no pivot) is skipped.
"""

# First party imports (Horilla)
from horilla.contrib.tour.presets import click, if_hidden, if_visible
from horilla.contrib.tour.registry import Step, Tour
from horilla.utils.translation import gettext_lazy as _

REPORT_VIEW_PERMS = ["reports.view_report", "reports.view_own_report"]
REPORTS_LIST_URL = "reports:reports_list_view"
# The box shown instead of the tables when a report has no data: it follows the summary
# strip where the tables (#rpt-grid) would be.
EMPTY_REPORT = "#rpt-summary + div:not(#rpt-grid)"
FIRST_REPORT = "#data-container-reports-list tr:first-child td[hx-get]"

# The gear of the list page and the menu it opens.
GEAR = "#dropdownDefaultButton"
GEAR_MENU = "#dropdown"
LOAD_DEFAULTS = "#reports-load"
# The "Select Default Reports" window.
WINDOW = "#modalBox"
CLOSE_WINDOW = '#modalBox [onclick*="closeModal"]'
WINDOW_OPEN = "#master-select-all"


class ReportsListTour(Tour):
    """The list of reports: load the ready-made reports."""

    key = "reports_list"
    title = _("Getting Started with Reports")
    description = _(
        "Open the gear to load ready-made reports, so you do not have to "
        "start from scratch."
    )
    group = _("Reports")
    icon = "/assets/icons/reports.svg"
    order = 500
    match = (REPORTS_LIST_URL,)
    ready = "#navBar h3"
    permission = REPORT_VIEW_PERMS
    auto_start = True
    steps = [
        Step(
            title=_("Reports"),
            body=_("Reports turn your CRM data into tables and charts."),
        ),
        Step(
            title=_("Settings"),
            body=_("Click the gear for more options."),
            target=GEAR,
            only_if=GEAR,
            side="bottom",
            align="end",
            # Coming back from the menu or the window: close them first.
            before=(
                click(CLOSE_WINDOW, if_visible(WINDOW_OPEN)),
                click(GEAR, if_visible(GEAR_MENU)),
            ),
        ),
        Step(
            title=_("Load Default Reports"),
            body=_(
                "Adds ready-made reports, such as Leads by Source or Sales "
                "Forecast, so you do not have to start from scratch."
            ),
            # The gear and the menu it opens are lit together.
            target=GEAR_MENU,
            also=GEAR,
            only_if=GEAR,
            side="left",
            before=(
                click(CLOSE_WINDOW, if_visible(WINDOW_OPEN)),
                click(GEAR, if_hidden(GEAR_MENU)),
            ),
        ),
        # Only the first step of the window opens it; the next ones just find their part.
        Step(
            title=_("Select Default Reports"),
            body=_("Choose the ready-made reports you want to add."),
            target=WINDOW,
            # The menu closes by itself when the user clicks Next, so look for the gear.
            only_if=GEAR,
            side="right",
            before=(
                click(GEAR, if_hidden(GEAR_MENU)),
                click(LOAD_DEFAULTS, if_hidden(WINDOW_OPEN)),
            ),
        ),
        Step(
            title=_("Select All"),
            body=_("Tick this to choose every report at once."),
            target=f"{WINDOW} label:has(> {WINDOW_OPEN})",
            side="right",
        ),
        Step(
            title=_("The Reports"),
            body=_("Or tick only the ones you need."),
            target=f"{WINDOW} .grid",
            side="right",
        ),
        Step(
            title=_("Create"),
            body=_("Click Create to add them to your reports."),
            target=f'{WINDOW} button[type="submit"]',
            side="top",
            after=(click(CLOSE_WINDOW, if_visible(WINDOW_OPEN)),),
        ),
    ]


class ReportsDetailTour(Tour):
    """A single report."""

    key = "reports_detail"
    title = _("Inside a Report")
    description = _(
        "The summary, the pivot table, the list of records and the chart "
        "of a report."
    )
    group = _("Reports")
    icon = "/assets/icons/reports.svg"
    order = 501
    match = ("reports:report_detail",)
    open_with = {"from": REPORTS_LIST_URL, "click": FIRST_REPORT}
    ready = "#rpt-summary"
    permission = REPORT_VIEW_PERMS
    auto_start = True
    steps = [
        Step(
            title=_("Your Report"),
            body=_("The report's name, and the kind of record it covers."),
            target="#mainContent h3",
            side="bottom",
        ),
        Step(
            title=_("Back"),
            body=_("Go back to the list of reports."),
            target="#mainContent button:has(> .fa-arrow-left)",
            side="bottom",
        ),
        Step(
            title=_("Reload"),
            body=_("Reload the report with the latest data."),
            target='#nav-actions button[onclick*="reloadButton"]',
            side="bottom",
            align="end",
        ),
        Step(
            title=_("Edit"),
            body=_("Change the report: its columns, grouping and filters."),
            target="#toggleBtn",
            side="bottom",
            align="end",
        ),
        Step(
            title=_("Download"),
            body=_("Save the report as an Excel or CSV file."),
            # The gear and the menu it opens are lit together.
            target="#exportDropdownButton",
            also="#exportDropdown",
            only_if="#exportDropdownButton",
            side="left",
            before=(click("#exportDropdownButton", if_hidden("#exportDropdown")),),
            after=(click("#exportDropdownButton", if_visible("#exportDropdown")),),
        ),
        Step(
            title=_("Total Count"),
            body=_("How many records are in this report."),
            target="#rpt-summary .rpt-summary-group > :first-child",
            side="bottom",
        ),
        Step(
            title=_("Grouping"),
            body=_(
                "How the records are grouped, for example by industry. Click "
                "it to change it."
            ),
            target='#rpt-summary [data-edit-tab="grouping"]',
            side="bottom",
        ),
        Step(
            title=_("Filters"),
            body=_(
                "The conditions that narrow the records. None means every "
                "record is included."
            ),
            target='#rpt-summary [data-edit-tab="filter"]',
            side="bottom",
        ),
        Step(
            title=_("No Data Yet"),
            body=_(
                "This report has no records yet. It fills in when there is "
                "data to show; use Reload to refresh it."
            ),
            # Only a report with no data has this box instead of the tables.
            target=EMPTY_REPORT,
            side="bottom",
        ),
        Step(
            title=_("Pivot, Details, Chart"),
            body=_("Show the same data as a table of totals, a list or a chart."),
            target='#rpt-summary [role="tablist"]',
            side="bottom",
            align="end",
        ),
        Step(
            title=_("Pivot"),
            body=_("The records counted and added up for each group."),
            target='[data-rpt-section="pivot"]',
            only_if='#rpt-summary [data-view="pivot"]',
            side="over",
            before=(click('#rpt-summary [data-view="pivot"]'),),
        ),
        Step(
            title=_("Details"),
            body=_("Every record behind the numbers. Click a heading to sort."),
            target='[data-rpt-section="detail"]',
            only_if='#rpt-summary [data-view="detail"]',
            side="over",
            before=(click('#rpt-summary [data-view="detail"]'),),
        ),
        Step(
            title=_("Add to Dashboard"),
            body=_("Show this table on a dashboard."),
            target="#dropdownDetailButton",
            also="#dropdownDetailButton ~ .dropdown-content",
            only_if='#rpt-summary [data-view="detail"]',
            side="left",
            before=(
                click('#rpt-summary [data-view="detail"]'),
                click(
                    "#dropdownDetailButton",
                    if_hidden("#dropdownDetailButton ~ .dropdown-content"),
                ),
            ),
            after=(
                click(
                    "#dropdownDetailButton",
                    if_visible("#dropdownDetailButton ~ .dropdown-content"),
                ),
            ),
        ),
        Step(
            title=_("Chart"),
            body=_("The same numbers as a chart."),
            target='[data-rpt-section="chart"]',
            only_if='#rpt-summary [data-view="chart"]',
            side="over",
            before=(click('#rpt-summary [data-view="chart"]'),),
        ),
        Step(
            title=_("Chart Options"),
            body=_(
                "Change the chart type, save it as a PDF or PNG, or add it to "
                "a dashboard."
            ),
            target="#dropdownLeftEndButton",
            also="#dropdownLeftEndButton ~ .dropdown-content",
            only_if='#rpt-summary [data-view="chart"]',
            side="left",
            before=(
                click('#rpt-summary [data-view="chart"]'),
                click(
                    "#dropdownLeftEndButton",
                    if_hidden("#dropdownLeftEndButton ~ .dropdown-content"),
                ),
            ),
            after=(
                click(
                    "#dropdownLeftEndButton",
                    if_visible("#dropdownLeftEndButton ~ .dropdown-content"),
                ),
                # Leave the report on its first view.
                click('#rpt-summary [data-view="pivot"]'),
            ),
        ),
    ]
