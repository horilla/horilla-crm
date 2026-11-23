"""
Tour of the Calendar app: the Calendar page.

Picked up through ``"tour"`` in this app's ``auto_import_modules``, like ``menu.py``.
The calendar is drawn by FullCalendar, so the steps point at its generated markup. The
popups a user gets by clicking (an empty day, an event) are opened by the tour itself.
A step whose element is missing (no team scope, no permission to add a calendar, a view
without day cells) is skipped.
"""

# First party imports (Horilla)
from horilla.contrib.tour.presets import click, if_hidden, if_visible, tap
from horilla.contrib.tour.registry import Step, Tour
from horilla.utils.translation import gettext_lazy as _

GRID = "#calendarGrid"
# The small menu of the calendar (shown when a day or an event is clicked) and its close button.
POPUP = "#calendarPopup"
CLOSE_POPUP = "#closePopupBtn"
# A cell to click: a day of the month without events (an event bar would catch the click),
# or a time slot of the day and week views. And an event.
EMPTY_DAY = (
    f"{GRID} .fc-daygrid-day:not(.fc-day-other):not(:has(.fc-daygrid-event)), "
    f"{GRID} .fc-timegrid-slot-lane"
)
EVENT = f"{GRID} .fc-event"

# The side panel: Show (Mine / Team) and the team member picker window.
MINE = '.calendar-scope-btn[data-scope="mine"]'
TEAM = '.calendar-scope-btn[data-scope="team"]'
TEAM_FILTER = "#teamMembersFilter"
MEMBERS_BUTTON = "#teamMembersBtn"
PICKER = "#horillaModalBox"
PICKER_LIST = "#userPickerList"
CLOSE_PICKER = '#horillaModalBox [onclick*="closehorillaModal"]'

# Color by (Type / Status) and the calendars of the Type view.
TYPE = '.color-by-btn[data-color-by="type"]'
STATUS = '.color-by-btn[data-color-by="status"]'
STATUS_PANEL = "#colorByStatusPanel"
CALENDARS = "#colorByTypePanel"
CALENDAR_MENU_BUTTON = f"{CALENDARS} .dropdown-wrapper > button"
CALENDAR_MENU = f"{CALENDARS} .dropdown-wrapper > .dropdown-content"


class CalendarTour(Tour):
    """The Calendar page."""

    key = "calendar"
    title = _("Using the Calendar")
    description = _(
        "See your tasks, meetings and time off, add to them and choose what " "shows."
    )
    group = _("Calendar")
    icon = "/assets/icons/calendar.svg"
    order = 600
    match = ("calendar:calendar_view",)
    # The grid is drawn after the page loads.
    ready = f"{GRID} .fc-view-harness"
    auto_start = True
    steps = [
        Step(
            title=_("Calendar"),
            body=_("Your tasks, meetings, events and time off in one place."),
        ),
        Step(
            title=_("This Period"),
            body=_("The month, week or day you are looking at."),
            target="#calendarTitlePill",
            side="bottom",
        ),
        Step(
            title=_("Move Around"),
            body=_("Go to the previous or next period. Today brings you back to now."),
            # The three buttons are lit together.
            target="#prevBtn",
            also="#nextBtn",
            side="bottom",
            align="end",
        ),
        Step(
            title=_("Day, Week, Month, Year"),
            body=_("Choose how much time you see at once."),
            target="#dayView",
            also="#yearView",
            side="bottom",
            align="end",
        ),
        # The next three steps are one small menu. The calendar closes it on any click outside
        # (the tour's own Next button included), so each step opens it again if needed, and
        # the last one closes it.
        Step(
            title=_("Click Any Day"),
            body=_(
                "Click any day, or any time slot in the day and week views, to "
                "open this small menu."
            ),
            # The day and the menu it opens are lit together.
            target=POPUP,
            also=EMPTY_DAY,
            only_if=EMPTY_DAY,
            side="right",
            before=(tap(EMPTY_DAY, if_hidden(POPUP)),),
        ),
        Step(
            title=_("New Activity"),
            body=_("Add a task, call, meeting or event on that day."),
            target='#popupContent button[onclick*="createNewActivity"]',
            only_if=EMPTY_DAY,
            side="right",
            before=(tap(EMPTY_DAY, if_hidden(POPUP)),),
        ),
        Step(
            title=_("Mark as Unavailable"),
            body=_("Block out the time when you are not available."),
            target='#popupContent button[onclick*="markDateUnavailable"]',
            only_if=EMPTY_DAY,
            side="right",
            before=(tap(EMPTY_DAY, if_hidden(POPUP)),),
            after=(click(CLOSE_POPUP, if_visible(POPUP)),),
        ),
        Step(
            title=_("An Event"),
            body=_("Click an event to see its details."),
            target=EVENT,
            side="top",
            # Coming back from the menu or the details: close them first.
            before=(click(CLOSE_POPUP, if_visible(POPUP)),),
        ),
        Step(
            title=_("Event Details"),
            body=_(
                "See the details and act on them: mark a task as complete, "
                "edit it, delete it or open its record."
            ),
            target=POPUP,
            also=EVENT,
            only_if=EVENT,
            side="right",
            before=(click(EVENT, if_hidden(POPUP)),),
            after=(click(CLOSE_POPUP, if_visible(POPUP)),),
        ),
        Step(
            title=_("Show"),
            body=_("Mine shows your own events. Team adds the events of your team."),
            target=MINE,
            also=TEAM,
            only_if=MINE,
            side="left",
            # Coming back from the member window: close it first.
            before=(click(CLOSE_PICKER, if_visible(PICKER_LIST)),),
        ),
        Step(
            title=_("Team Members"),
            body=_(
                "In Team view, choose whose events to show. All members shows "
                "everyone in your team."
            ),
            target=TEAM_FILTER,
            only_if=TEAM,
            side="left",
            before=(click(TEAM, if_hidden(TEAM_FILTER)),),
        ),
        Step(
            title=_("Choose Members"),
            body=_(
                "Search for a name, tick the members you want and click "
                "Select. The calendar then shows only their events."
            ),
            target=PICKER,
            only_if=TEAM,
            side="right",
            before=(
                click(TEAM, if_hidden(TEAM_FILTER)),
                click(MEMBERS_BUTTON, if_hidden(PICKER_LIST)),
            ),
            after=(
                click(CLOSE_PICKER, if_visible(PICKER_LIST)),
                # Back to your own events: the tour must not leave your view on Team.
                click(MINE, if_visible(TEAM_FILTER)),
            ),
        ),
        Step(
            title=_("Color by"),
            body=_("Colour the events by their type or by their status."),
            target=TYPE,
            also=STATUS,
            side="left",
        ),
        Step(
            title=_("Status Colours"),
            body=_(
                "Completed and Not completed each get a colour. Tick one to "
                "show those events, untick it to hide them."
            ),
            target=STATUS_PANEL,
            only_if=STATUS,
            side="left",
            before=(click(STATUS, if_hidden(STATUS_PANEL)),),
            # Back to the Type view, as it was.
            after=(click(TYPE, if_visible(STATUS_PANEL)),),
        ),
        Step(
            title=_("My Calendars"),
            body=_("Tick a calendar to show its events. Untick it to hide them."),
            target=CALENDARS,
            only_if=TYPE,
            side="left",
            before=(click(TYPE, if_hidden(CALENDARS)),),
        ),
        Step(
            title=_("Add a Calendar"),
            body=_("Add a calendar of your own."),
            target=f"{CALENDARS} button:has(> .fa-plus)",
            side="left",
        ),
        Step(
            title=_("Calendar Options"),
            body=_("Show only this calendar, or change its colours."),
            # The arrow and the menu it opens are lit together.
            target=CALENDAR_MENU_BUTTON,
            also=CALENDAR_MENU,
            only_if=CALENDAR_MENU_BUTTON,
            side="left",
            before=(click(CALENDAR_MENU_BUTTON, if_hidden(CALENDAR_MENU)),),
            after=(click(CALENDAR_MENU_BUTTON, if_visible(CALENDAR_MENU)),),
        ),
    ]
