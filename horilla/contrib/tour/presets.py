"""
Reusable step lists for the screens every CRM app shares.

All CRM list and detail pages render from the same generic
templates, so one definition covers them. The per-app differences (the list's
``view_id``, the create button's id) are passed in as arguments, which means an
app can be added to the tour with a few lines and no template change.
"""

# Third-party imports (Django)
from django.utils.text import format_lazy

# First party imports (Horilla)
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .registry import Step


def _condition(kind, doc):
    """Build a condition helper: ``kind`` is the key the browser engine reads."""

    def build(selector):
        return {kind: selector}

    build.__name__, build.__doc__ = kind, doc
    return build


def _action(kind, doc):
    """Build an action helper: ``kind`` is the key the browser engine reads."""

    def build(selector, condition=None):
        return {kind: selector, **(condition or {})}

    build.__name__, build.__doc__ = kind, doc
    return build


if_hidden = _condition("if_hidden", "Condition: the element is currently hidden.")
if_visible = _condition("if_visible", "Condition: the element is currently visible.")
click = _action(
    "click", "Action: click ``selector``, only when the optional ``condition`` holds."
)
mousedown = _action(
    "mousedown",
    "Action: press ``selector`` (for a select2 box, which opens on mousedown).",
)
tap = _action(
    "tap",
    "Action: tap ``selector`` at its centre (a calendar day needs the mouse position).",
)


def _popup(button, panel):
    """
    ``before`` / ``after`` of a step that explains a pop-up: open it from ``button``
    when it is closed, and close it again when the step is left.
    """
    return {
        "before": (click(button, if_hidden(panel)),),
        "after": (click(button, if_visible(panel)),),
    }


def list_page_steps(view_id, create_id, record_plural, intro=None, create_body=None):
    """
    Steps for a generic list page.

    Args:
        view_id: The list view's ``view_id``.
        create_id: The id of the page's create button.
        record_plural: Lower-case plural noun used in the copy.
        intro: Optional text for the first step, to say what the records are
            for. The generic text is used when it is left out.
        create_body: Optional text for the Create step, to say how to add one.
    """
    first_row = f"#data-container-{view_id} tr:first-child"
    sort_headers = f"#table-container-{view_id} th[data-field], #tableview-{view_id} th[data-field]"
    select_all = f"#table-container-{view_id} th input[data-role='select-all']"
    return [
        Step(
            title=format_lazy(_("Welcome to Your {records}"), records=record_plural),
            body=intro
            or _(
                "This quick tour shows the main controls on this page. "
                "You can close it at any time and restart it later from "
                "Product Tours in your profile menu."
            ),
        ),
        Step(
            title=_("Where You Are"),
            body=_("The title tells you which list you are looking at."),
            target="#navBar h3",
        ),
        Step(
            title=_("Saved Views"),
            body=_(
                "Switch between saved views of this list, such as 'All' or "
                "your own filtered lists."
            ),
            target="#viewTypeSelect ~ .select2-container, #viewTypeSelect",
        ),
        Step(
            title=_("Pin a View"),
            body=_(
                "Pin the view you have open to make it the one this list "
                "opens with every time. Click the pin again to unpin it."
            ),
            target="#rotateBtn",
            side="bottom",
        ),
        Step(
            title=_("Search"),
            body=format_lazy(
                _("Type here to find {records} by any searchable field."),
                records=record_plural,
            ),
            target="#searchInput",
        ),
        Step(
            title=_("Reload"),
            body=_(
                "Reload the list to pick up the latest changes, without "
                "refreshing the whole page."
            ),
            target='#navBar button[onclick*="reloadButton"]',
            side="bottom",
        ),
        Step(
            title=_("Filter"),
            body=_(
                "Narrow the list down with one or more conditions. Applied "
                "filters show up as chips below the bar."
            ),
            target="#filterToggleWrapper",
        ),
        Step(
            title=_("Build a Filter"),
            body=_(
                "Pick a field, an operator and a value, add more rows to "
                "combine conditions, then apply."
            ),
            target="#filterpanel",
            side="left",
            **_popup("#filterToggleWrapper", "#filterpanel"),
        ),
        Step(
            title=_("Layouts"),
            body=_(
                "The same data can be shown in different layouts. Open this "
                "menu to choose one."
            ),
            target="#layoutDropdownButton",
        ),
        Step(
            title=_("Pick a Layout"),
            body=_(
                "List, Kanban, Card, Timeline, Group by, Split view and "
                "Chart are available. Your choice is remembered."
            ),
            target="#layoutDropdown",
            side="left",
            **_popup("#layoutDropdownButton", "#layoutDropdown"),
        ),
        Step(
            title=_("Actions"),
            body=_(
                "Import records, choose which columns appear, add quick "
                "filters and more. The options depend on the current layout."
            ),
            target="#dropdownDefaultButton",
            side="left",
        ),
        Step(
            title=_("Action Menu"),
            body=_("Here is everything available for this layout."),
            target="#dropdown",
            side="left",
            **_popup("#dropdownDefaultButton", "#dropdown"),
        ),
        Step(
            title=_("Create"),
            body=create_body or _("Add a new record from here."),
            target=f"#{create_id}",
            side="left",
        ),
        Step(
            title=_("Sort"),
            body=_("Click a column heading to sort the list by it."),
            target=sort_headers,
            side="bottom",
        ),
        Step(
            title=_("Select Rows"),
            body=_("Tick rows, or use the box in the header to select them all."),
            target=select_all,
        ),
        Step(
            title=_("Bulk Actions"),
            body=_(
                "With rows selected, these buttons act on all of them at once: "
                "export, update a field, or delete, depending on your "
                "permissions. Unselect clears the selection."
            ),
            target=f"#tableview-{view_id} div:has(> #select-all-btn-{view_id})",
            only_if=f"#select-all-btn-{view_id}",
            side="bottom",
            before=(
                click(
                    f"#table-container-{view_id} th input[data-role='select-all']",
                    if_hidden(f"#unselect-all-btn-{view_id}"),
                ),
            ),
            after=(
                click(
                    f"#unselect-all-btn-{view_id}",
                    if_visible(f"#unselect-all-btn-{view_id}"),
                ),
            ),
        ),
        Step(
            title=_("Open a Record"),
            body=_("Click a name in a row to open its detail page."),
            target=f"{first_row} td[hx-get]",
            side="bottom",
        ),
        Step(
            title=_("Row Actions"),
            body=_("Edit or act on a single record without leaving the list."),
            target=f"{first_row} .tablebtn",
            side="left",
        ),
    ]


def detail_page_steps(intro=None, stages_body=None, related_lists=()):
    """
    Steps for a generic record detail page.

    Args:
        intro: Optional text for the first step, to say what this record is.
        stages_body: Optional text for the Stages step, to say what the stages
            of this kind of record mean.
        related_lists: Optional ``(name, title, body)`` entries, one per list on
            the Related Lists tab, in the order the tab shows them. ``name`` is
            the list's key in the app's related list config (the button id is
            ``tab-<name>-btn``). Each one gets a step that opens the list and
            says what it holds. A list the user cannot see is skipped.
    """
    # (tab id, title, what it holds)
    tabs = (
        (
            "details",
            _("Details"),
            _("All fields of the record. Edit them in place from here."),
        ),
        (
            "activity",
            _("Activity"),
            _("Plan and log calls, meetings, emails and tasks for this record."),
        ),
        (
            "cadence",
            _("Cadence"),
            _(
                "Follow-ups lined up for this record by a cadence: a set "
                "sequence of tasks, calls and emails."
            ),
        ),
        ("related-lists", _("Related Lists"), _("Records linked to this one.")),
        (
            "notes-attachments",
            _("Notes & Attachments"),
            _("Keep notes and files together with the record."),
        ),
        (
            "history",
            _("History"),
            _("A timeline of every change made to this record, and by whom."),
        ),
        (
            "potential-duplicates",
            _("Potential Duplicates"),
            _("Other records that look like this one, so you can spot duplicates."),
        ),
    )

    steps = [
        Step(
            title=_("Record Page"),
            body=intro
            or _(
                "This is the full view of one record. Let's look at the "
                "parts that matter most."
            ),
        ),
        Step(
            title=_("Breadcrumb"),
            body=_(
                "Shows where you are. Click an earlier name in the trail to " "go back."
            ),
            target="#detailViewport ul:has(> li > a[title])",
            side="bottom",
        ),
        Step(
            title=_("Fields"),
            body=_(
                "Choose which fields this page shows, so you only see what "
                "matters to you."
            ),
            target="#detailViewport button:has(> .fa-sliders)",
            side="bottom",
            align="end",
        ),
        Step(
            title=_("Summary"),
            body=_("The header shows the record's key facts at a glance."),
            target="#detailHeaderCard",
            side="bottom",
        ),
        Step(
            title=_("Actions"),
            body=_(
                "Everything you can do with this record, depending on your permissions."
            ),
            target="#dropdownLeftEndButton",
            side="left",
        ),
        Step(
            title=_("Stages"),
            body=stages_body
            or _("Click a stage to move the record forward in your pipeline."),
            target="#pipeline-choices",
            side="bottom",
        ),
        Step(
            title=_("Expand"),
            body=_(
                "Give the tabs more room by hiding the summary and the stages "
                "above them. Click it again to bring them back."
            ),
            target=".detail-tab-expand-btn",
            side="left",
        ),
    ]
    for tab_id, title, body in tabs:
        steps.append(
            Step(
                title=title,
                body=body,
                target=f"#tab-{tab_id}-content",
                only_if=f"#tab-{tab_id}",
                side="over",
                before=(click(f"#tab-{tab_id}"),),
            )
        )
        if tab_id != "related-lists":
            continue
        for name, list_title, list_body in related_lists:
            button = f"#tab-{name}-btn"
            steps.append(
                Step(
                    title=list_title,
                    body=list_body,
                    target=button,
                    # The buttons are only on screen while the tab is open, so a list
                    # the user cannot see is skipped at once, without waiting.
                    only_if=button,
                    side="right",
                    before=(
                        click("#tab-related-lists", if_hidden("#related-tabs")),
                        click(button),
                    ),
                )
            )
    return steps
