"""Version and metadata for the Jalali calendar extension."""

from horilla.utils.translation import gettext_lazy as _

__version__ = "1.0.7"
__module_name__ = _("Jalali Calendar")
__release_date__ = ""
__description__ = _(
    "Optional Shamsi (Jalali) calendar extension. Persian users get Jalali "
    "display, date/time pickers, and FullCalendar month/year views. "
    "Stored values stay Gregorian. Enable via local_settings.py."
)
__icon__ = "assets/icons/calendar-red.svg"

__1_0_7__ = _(
    "The timeline uses Shamsi months and seasons, with Persian day labels. "
    "Bars stay on the Gregorian dates sent by the server."
)

__1_0_6__ = _(
    "Load the Jalali date and time pickers on the optional phone layout " "(/m/) too."
)

__1_0_5__ = _(
    "History datetime parsing: date-only values stay dates; shift stored "
    "DateTime diffs like entry timestamps."
)

__1_0_4__ = _(
    "Wire Jalali history formatting and JS for the generics History Show full "
    "text work."
)

__1_0_3__ = _(
    "Parse Jalali dates through FieldInfoResolver for the bulk Edit Details save."
)

__1_0_2__ = _(
    "Improve Persian digit and AM/PM handling for Shamsi history and picker "
    "datetimes; align Jalali JS with the updated calendar helpers."
)

__1_0_1__ = _(
    "Fix pylint issues in the extension package; align Jalali asset inject partials "
    "with djangofmt formatting."
)

__1_0_0__ = _(
    "Phase 1: DateTimeFormatter, calendar_system on HorillaUser, inline-edit "
    "parse hooks, Jalali date/time pickers, and FullCalendar Shamsi month/year "
    "views. No core template or settings patches."
)
