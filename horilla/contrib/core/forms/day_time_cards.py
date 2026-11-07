"""
Shared styling for per-weekday start/end time inputs.

Each day's start and end input is drawn as one bordered card with the day name
as its legend. Used by the Business Hour and Shift Hour forms.
"""

# First-party imports (Horilla)
from horilla.utils.choices import DAY_LABELS, SHORT_TO_DAY_PREFIX, WEEK_ORDER
from horilla.utils.html import format_html
from horilla.utils.translation import gettext_lazy as _

_CARD_BASE = (
    "position: relative; border-top: 1px solid #e5e7eb; "
    "border-bottom: 1px solid #e5e7eb; padding: 1.15rem 0.75rem 0.75rem;"
)
_START_STYLE = (
    f"{_CARD_BASE} border-left: 1px solid #e5e7eb; "
    "border-top-left-radius: 0.5rem; border-bottom-left-radius: 0.5rem;"
)
_END_STYLE = (
    f"{_CARD_BASE} border-right: 1px solid #e5e7eb; "
    "border-top-right-radius: 0.5rem; border-bottom-right-radius: 0.5rem; "
    "margin-left: -1rem; width: calc(100% + 1rem);"
)
_LEGEND_STYLE = (
    "position: absolute; top: -0.55rem; left: 0.6rem; "
    "padding: 0 0.35rem; background: #fff; "
    "font-weight: 600; font-size: 0.8rem; color: #111827;"
)
_SUBLABEL_STYLE = (
    "display: block; font-weight: 400; font-size: 0.75rem; color: #6b7280;"
)


def style_day_time_cards(fields, field_prefix="", legend_prefix=""):
    """Give each ``<field_prefix><day>_start`` / ``_end`` field the day-card look.

    ``fields`` is the form's ``fields`` mapping; missing or hidden fields are skipped.
    ``legend_prefix`` is optional text before the day name (e.g. ``"Break 1 – "``).
    Returns the names of the fields that were styled.
    """
    styled = []
    for short_code in WEEK_ORDER:
        day = SHORT_TO_DAY_PREFIX[short_code]
        start_name = f"{field_prefix}{day}_start"
        end_name = f"{field_prefix}{day}_end"
        if start_name in fields and not fields[start_name].widget.is_hidden:
            fields[start_name].label = format_html(
                '<span style="{legend_style}">{legend}</span>'
                '<span style="{sublabel_style}">{start}</span>',
                legend_style=_LEGEND_STYLE,
                legend=f"{legend_prefix}{DAY_LABELS[short_code]}",
                sublabel_style=_SUBLABEL_STYLE,
                start=_("Start"),
            )
            fields[start_name].widget.attrs["container_style"] = _START_STYLE
            fields[start_name].help_text = ""
            styled.append(start_name)
        if end_name in fields and not fields[end_name].widget.is_hidden:
            fields[end_name].label = format_html(
                '<span style="{sublabel_style}">{end}</span>',
                sublabel_style=_SUBLABEL_STYLE,
                end=_("End"),
            )
            fields[end_name].widget.attrs["container_style"] = _END_STYLE
            fields[end_name].help_text = ""
            styled.append(end_name)
    return styled
