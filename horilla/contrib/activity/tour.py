"""
Tours of the Activity app: the Activities list and a single activity.

Picked up through ``"tour"`` in this app's ``auto_import_modules``, like ``menu.py``.
The page is a list with one tab per kind of activity (Tasks, Meetings, Calls, Events),
so the list tour is written here: it explains the tabs and the columns that are special
to activities. The detail tour starts from the shared one and adds the Related To tab.
A step whose element is missing (no permission to add, a tab or column the kind of
activity does not have) is skipped.
"""

# First party imports (Horilla)
from horilla.contrib.tour.presets import click, detail_page_steps, if_hidden, if_visible
from horilla.contrib.tour.registry import Step, Tour
from horilla.utils.translation import gettext_lazy as _

ACTIVITY_VIEW_PERMS = ["activity.view_activity", "activity.view_own_activity"]
ACTIVITY_LIST_URL = "activity:activity_view"
# The list of the tab on screen: Tasks, Meetings, Calls and Events each have their own.
FIRST_ROW = '[id^="data-container-global-"] tr:first-child'
FIRST_ACTIVITY = f"{FIRST_ROW} td[hx-get]"
LAYOUT_BUTTON = "#layoutDropdownButton"
LAYOUT_MENU = "#layoutDropdown"


class ActivitiesListTour(Tour):
    """The Activities list."""

    key = "activities_list"
    title = _("Working with Activities")
    description = _(
        "Find your tasks, meetings, calls and events, and open the record "
        "each one is for."
    )
    group = _("Activities")
    icon = "/assets/icons/activity.svg"
    order = 610
    match = (ACTIVITY_LIST_URL,)
    ready = "#navBar h3"
    permission = ACTIVITY_VIEW_PERMS
    auto_start = True
    steps = [
        Step(
            title=_("Activities"),
            body=_(
                "The tasks, meetings, calls and events you have to do, in one list."
            ),
        ),
        Step(
            title=_("Tabs"),
            body=_(
                "Each tab shows one kind of activity: Tasks, Meetings, Calls or Events."
            ),
            # The four tabs are lit together.
            target="#tab-tasks",
            also="#tab-events",
            side="bottom",
        ),
        Step(
            title=_("New"),
            body=_("Add a task, meeting, call or event."),
            target='#navBar [hx-get*="activity-create-form"]',
            side="bottom",
            align="end",
        ),
        Step(
            title=_("Layouts"),
            body=_("Open this menu to choose how the activities are shown."),
            target=LAYOUT_BUTTON,
            side="bottom",
            align="end",
            # Coming back from the menu: close it first.
            before=(click(LAYOUT_BUTTON, if_visible(LAYOUT_MENU)),),
        ),
        Step(
            title=_("Pick a Layout"),
            body=_("List shows rows. Kanban shows cards in columns."),
            target=LAYOUT_MENU,
            only_if=LAYOUT_BUTTON,
            side="left",
            before=(click(LAYOUT_BUTTON, if_hidden(LAYOUT_MENU)),),
            after=(click(LAYOUT_BUTTON, if_visible(LAYOUT_MENU)),),
        ),
        Step(
            title=_("Open an Activity"),
            body=_("Click a subject to open the activity."),
            target=FIRST_ACTIVITY,
            side="bottom",
        ),
        Step(
            title=_("Related To"),
            body=_("The record the activity is for. Click it to open that record."),
            target=f"{FIRST_ROW} td:has(a[onclick*='stopPropagation'])",
            side="bottom",
        ),
        Step(
            title=_("Actions"),
            body=_("Edit, duplicate or delete the activity."),
            target=f"{FIRST_ROW} .tablebtn",
            side="left",
        ),
    ]


def _detail_steps():
    """The shared detail steps, with a step for the Related To tab of an activity."""
    steps = detail_page_steps(
        intro=_("One activity in full: what it is, when it is due and who it is for."),
        stages_body=_(
            "The status of the activity. Click one to update where it stands."
        ),
    )
    related_to = Step(
        title=_("Related To"),
        body=_("The record this activity is for."),
        target="#tab-related-to-content",
        only_if="#tab-related-to",
        side="over",
        before=(click("#tab-related-to"),),
    )
    # Right after the Details tab.
    position = [str(step.title) for step in steps].index("Details") + 1
    return steps[:position] + [related_to] + steps[position:]


class ActivitiesDetailTour(Tour):
    """A single activity."""

    key = "activities_detail"
    title = _("Inside an Activity")
    description = _(
        "The status, details and tabs of an activity: the record it is for, "
        "notes and history."
    )
    group = _("Activities")
    icon = "/assets/icons/activity.svg"
    order = 611
    match = ("activity:activity_detail",)
    open_with = {"from": ACTIVITY_LIST_URL, "click": FIRST_ACTIVITY}
    # Not the header card: that is hidden while the tabs are expanded.
    ready = "#detailViewport"
    permission = ACTIVITY_VIEW_PERMS
    auto_start = True
    steps = _detail_steps()
