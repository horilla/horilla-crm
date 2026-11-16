"""
Named date-range presets shared by the dashboard and history date filters.

``date_range`` request values are one of: ``all`` (no filter), ``custom``
(explicit ``date_from``/``date_to``) or a preset key from ``DATE_RANGE_KEYS``.
"""

from datetime import timedelta

from horilla.utils.translation import gettext_lazy as _

# Preset key -> (plain label, "created" label), in display order. Keys are what
# travels in ``?date_range=``; labels are only presentation.
_PRESETS = {
    "today": (_("Today"), _("Created Today")),
    "yesterday": (_("Yesterday"), _("Created Yesterday")),
    "this_week": (_("This Week"), _("Created This Week")),
    "this_month": (_("This Month"), _("Created This Month")),
}

DATE_RANGE_KEYS = list(_PRESETS)


def get_date_range_choices(created=False, keys=None):
    """Build the ``(key, label)`` options for the date-range dropdown.

    ``created=True`` gives "Created Today" style labels (for lists of records);
    the default gives plain "Today" labels (e.g. history). ``keys`` limits and
    orders the presets shown. Pass the result to the dropdown as
    ``date_range_choices``.
    """
    index = 1 if created else 0
    return [
        (key, _PRESETS[key][index])
        for key in (keys if keys is not None else DATE_RANGE_KEYS)
        if key in _PRESETS
    ]


def get_preset_date_bounds(date_range, today):
    """Return the inclusive ``(start, end)`` dates for a preset key.

    ``today`` is the current date in the timezone the data is shown in.
    Weeks start on Monday. Returns ``(None, None)`` for an unknown key.
    """
    key = str(date_range)
    if key == "today":
        return today, today
    if key == "yesterday":
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    if key == "this_week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    if key == "this_month":
        start = today.replace(day=1)
        next_month = (start + timedelta(days=31)).replace(day=1)
        return start, next_month - timedelta(days=1)
    return None, None
