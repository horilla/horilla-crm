"""
Tour of the Forecast app: the Forecast page.

Picked up through ``"tour"`` in this app's ``auto_import_modules``, like ``menu.py``.
The page is built from a tab per forecast type and a table of periods, so the steps are
written here rather than taken from the shared list presets. The table headers carry no
ids, so each column is found by its position (Period, Target, Achievement, Gap, Closed,
Commit Forecast, Best Case, Open Pipeline). A step whose element is missing (no forecast
type yet, no permission to pick another user, a single user selected) is skipped.
"""

# First party imports (Horilla)
from horilla.contrib.tour.presets import click, if_hidden, if_visible, mousedown
from horilla.contrib.tour.registry import Step, Tour
from horilla.utils.translation import gettext_lazy as _

TABLE = "#forecast-table table"
# The pop-ups (charts, deals) share one modal; this closes whichever is open.
CLOSE_MODAL = '#contentModal [onclick*="closeContentModal"]'
CHART_MODAL = "#forecast-modal-chart-column"
# The whole pop-up (title and the three charts), not one chart.
CHART_WINDOW = "#contentModalBox"
DEALS_MODAL = "#default-styled-tab"
CHART_BUTTON = 'button[hx-get*="forecast-charts-modal"]'
# The "Best Case" amount of the Total row (the table's first row): it adds up every
# period, so the list of deals behind it is rarely empty.
DEALS_BUTTON = f'{TABLE} tbody tr:first-child td:nth-child(7) button[hx-get*="/forecast/opportunities/"]'
USER_BOX = "#user-data-container .select2-selection"
PERIOD_FORM = "#forecast-period-range-form"
PERIOD_TRIGGER = "#forecast-period-range-trigger"
PERIOD_MENU = "#forecast-period-range .dropdown-content"
PERIOD_TOGGLE = f'{TABLE} tr.period-main-row button[onclick*="togglePeriod"]'
USER_ROWS = f"{TABLE} tbody.user-details-tbody"
# The trend arrows are images, found by icon so the translated alt text does not matter.
TREND_ARROW = (
    f'{TABLE} tr.period-main-row img[src*="up-arrow"], '
    f'{TABLE} tr.period-main-row img[src*="down-arrow"]'
)


def open_chart():
    """Open the Chart Analysis pop-up, if it is not already open."""
    return (click(CHART_BUTTON, if_hidden(CHART_MODAL)),)


def open_deals():
    """Open the list of deals behind an amount, if it is not already open."""
    return (click(DEALS_BUTTON, if_hidden(DEALS_MODAL)),)


def column(position):
    """Selector of one column header of the forecast table (1 is Period)."""
    return f"{TABLE} thead th:nth-child({position})"


class ForecastTour(Tour):
    """The Forecast page."""

    key = "forecast"
    title = _("Understanding the Forecast")
    description = _(
        "Compare your target with what you have won and what you expect to "
        "win, period by period."
    )
    group = _("Forecast")
    icon = "/assets/icons/forecast.svg"
    order = 230
    match = ("forecast:forecast_view",)
    # The table loads after the page, and only exists once a forecast type is set up.
    ready = TABLE
    permission = [
        "opportunities.view_opportunity",
        "opportunities.view_own_opportunity",
    ]
    auto_start = True
    steps = [
        Step(
            title=_("Forecast"),
            body=_("See how much you expect to sell, compared with your target."),
        ),
        Step(
            title=_("Forecast Types"),
            body=_(
                "Each tab counts your deals in a different way: by amount, by "
                "expected revenue or by number of deals."
            ),
            target="#forecast-tab-view",
            side="bottom",
        ),
        Step(
            title=_("Whose Forecast"),
            body=_("Pick All Users, your own forecast or a team member's."),
            # The box and the list it opens are lit together.
            target="#user-data-container",
            also=".select2-dropdown",
            only_if="#user-data-container",
            side="right",
            before=(mousedown(USER_BOX, if_hidden(".select2-dropdown")),),
            after=(mousedown(USER_BOX, if_visible(".select2-dropdown")),),
        ),
        Step(
            title=_("Periods"),
            body=_("Choose the first and last period, then click Apply."),
            target=PERIOD_TRIGGER,
            also=PERIOD_MENU,
            only_if=PERIOD_TRIGGER,
            side="left",
            before=(click(PERIOD_TRIGGER, if_hidden(PERIOD_FORM)),),
            after=(click(PERIOD_TRIGGER, if_visible(PERIOD_FORM)),),
        ),
        Step(
            title=_("Chart Analysis"),
            body=_(
                "The Chart Analysis button opens these charts: your target "
                "against what you achieved, how both move over time, and how "
                "your deals split into Closed, Commit, Best Case and Pipeline."
            ),
            target=CHART_WINDOW,
            only_if=CHART_BUTTON,
            side="bottom",
            before=open_chart(),
            after=(click(CLOSE_MODAL, if_visible(CHART_MODAL)),),
        ),
        Step(
            title=_("Target"),
            body=_("The goal for each period."),
            target=column(2),
            side="bottom",
        ),
        Step(
            title=_("Achievement"),
            body=_("How much of the target you have reached."),
            target=column(3),
            side="bottom",
        ),
        Step(
            title=_("Gap"),
            body=_("How much is still missing to reach the target."),
            target=column(4),
            side="bottom",
        ),
        Step(
            title=_("Closed"),
            body=_("Deals you have already won."),
            target=column(5),
            side="bottom",
        ),
        Step(
            title=_("Commit Forecast"),
            body=_("Deals that are very likely to close."),
            target=column(6),
            side="bottom",
        ),
        Step(
            title=_("Best Case"),
            body=_("Deals with a fair chance of closing."),
            target=column(7),
            side="bottom",
        ),
        Step(
            title=_("Open Pipeline"),
            body=_("Early deals that are still far from closing."),
            target=column(8),
            side="bottom",
            align="end",
        ),
        Step(
            title=_("Open a Period"),
            body=_("Click a period to see each team member's numbers."),
            target=f"{USER_ROWS} tr.user-details-row",
            only_if=PERIOD_TOGGLE,
            side="bottom",
            before=(click(PERIOD_TOGGLE, if_hidden(USER_ROWS)),),
            after=(click(PERIOD_TOGGLE, if_visible(USER_ROWS)),),
        ),
        Step(
            title=_("Trend Arrow"),
            body=_(
                "An arrow shows if the number went up or down since the "
                "last period. Hover over it to see by how much."
            ),
            target=TREND_ARROW,
            side="top",
        ),
        Step(
            title=_("See the Deals"),
            body=_("Click an amount to list the deals behind it."),
            target=DEALS_BUTTON,
            side="top",
            # Coming back from the list: close it first.
            before=(click(CLOSE_MODAL, if_visible(DEALS_MODAL)),),
        ),
        Step(
            title=_("Deals by Category"),
            body=_("Switch between Closed, Committed, Best Case and Open Pipeline."),
            target=DEALS_MODAL,
            only_if=DEALS_BUTTON,
            side="bottom",
            before=open_deals(),
        ),
        Step(
            title=_("The Deals"),
            body=_("Each deal with its amount, close date and stage."),
            target="#default-styled-tab-content",
            side="over",
            after=(click(CLOSE_MODAL, if_visible(DEALS_MODAL)),),
        ),
    ]
