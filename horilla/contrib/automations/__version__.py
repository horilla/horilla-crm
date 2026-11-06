"""Version information for the automations module."""

# First party imports (Horilla)
from horilla.utils.translation import gettext_lazy as _

__version__ = "1.11.10"
__module_name__ = "Automations"
__release_date__ = ""
__description__ = _(
    "Module for automating mail and notifications based on model events and conditions."
)
__icon__ = "assets/icons/automation.svg"

__1_11_10__ = _(
    "Send through one or more registered delivery channels, including "
    "channels added by other apps. Mail and notification stay the built-in "
    "channels. Condition fields include audit fields."
)

__1_11_9__ = _(
    "Add a create action on the automation form for mail and notification "
    "templates, so a template can be added and selected without leaving "
    "the form."
)

__1_11_8__ = _(
    "Limit owner fields on the automation form and resolve extended form paths."
)

__1_11_7__ = _(
    "Render automation email and notification date/time fields in each "
    "recipient's own timezone. Evaluate custom fields in conditions instead "
    "of reading them as model columns."
)

__1_11_6__ = _(
    "Optional edge-trigger-only firing for on_update automations; fix blank "
    "created_by when saving rules."
)

__1_11_5__ = _(
    "Reorder schedule fields and clarify Run Time help text on automation forms."
)

__1_11_4__ = _("Correct scheduled trigger date matching and Run Time comparison.")

__1_11_3__ = _(
    "Exclude Big Deal Alert automations from the general automations list. Wrap remaining "
    "user-facing form and model strings with gettext."
)

__1_11_2__ = _("Apply runtime viewport fit on the automations settings list.")

__1_11_1__ = _(
    "Migrated signal and timezone imports to the horilla shims, standardized first-party "
    "import groups, and added docstrings for pylint compliance; behavior unchanged."
)

__1_10_1__ = _(
    "Celery Beat schedule entries now use the fully qualified task path so "
    "scheduled automations resolve correctly at runtime."
)

__1_10_0__ = _(
    "Release 1.10: automations ship under contrib with app label automations. "
    "Triggers referencing ContentType and Celery task dotted paths updated "
    "alongside imports and registrations for the contrib namespace."
)

__1_2_0__ = _(
    "Improved automation reliability with background processing enhancements, "
    "better schedule-aware form validation, and idempotent run tracking "
    "via AutomationRunLog for scheduled automations."
)

__1_1_2__ = _(
    "Introduced scheduled automations with Celery Beat support, including dynamic schedule fields in the automation form, "
    "server-side validation for scheduled triggers, and execution run logging to prevent duplicate runs."
)

__1_1_1__ = _(
    "Minor compatibility improvements and internal stability updates"
    "to ensure seamless integration with the updated generics framework and platform enhancements."
)

__1_1_0__ = _(
    "Migrated from Django AppConfig to Horilla AppLauncher and replaced Django utilities"
    "with horilla.utils.decorators, horilla.utils.translation, and horilla.shortcuts where applicable."
)
