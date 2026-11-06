"""
Version information for the cadences app
"""

# First party imports (Horilla)
from horilla.utils.translation import gettext_lazy as _

__version__ = "1.11.11"
__module_name__ = "Cadences"
__release_date__ = ""
__description__ = _(
    "Module for managing cadence workflows and runtime activity sequences."
)
__icon__ = "cadences/assets/icons/cadence.svg"

__1_11_11__ = _(
    "Honor the Do This delay (minutes, hours, days, months) of a follow-up. "
    "Delayed follow-ups are scheduled and created by a Celery beat task, and "
    "the enrollment stays ongoing while one is pending. A follow-up can also "
    "send through a registered delivery channel, such as a notification, "
    "besides a task, a call or an email. The add button reads Add Follow Up."
)

__1_11_10__ = _(
    "Add cadence enrollments, so a record can be enrolled and un-enrolled "
    "by hand from its Cadence tab, and each run keeps its own activities. "
    "Allow several first follow-ups, rework the add buttons and highlight "
    "the path on hover. The detail page uses the shared navbar, and the "
    "feature registers without auto-registering every model."
)

__1_11_9__ = _(
    "Require cadences.view_cadence on the cadence report and navbar. Show "
    "the 404 page when the cadence in a report is missing."
)

__1_11_8__ = _("Add settings nav description for Cadence.")

__1_11_7__ = _(
    "Replace runtime injection with a ViewExtension. Reuse prefetched cadence "
    "conditions on lead record tabs."
)

__1_11_6__ = _(
    "Validate outgoing mail configuration before enabling cadence email features."
)

__1_11_5__ = _(
    "Use the shared is_active toggle column partial. Derive list column labels from model "
    "verbose_name; wrap remaining form strings with gettext."
)

__1_11_4__ = _(
    "Decouple the Cadence tab from generics/CRM into a cadences extension. "
    "Apply runtime viewport fit on the cadence settings view."
)

__1_11_3__ = _(
    "Stop rendering blank cards for branch parents without a continuation. "
    "Extend the New Lead Outreach demo cadence with a multi-stage follow-up flow."
)

__1_11_2__ = _(
    "Standardized exception chaining in cadence forms to preserve root-cause tracebacks."
)

__1_11_1__ = _(
    "Migrated signal and timezone imports to the horilla shims, standardized first-party "
    "import groups, and added class and method docstrings for pylint compliance."
)

__1_10_1__ = _(
    "Cadence forms aligned with HorillaModelForm layout: field_order, "
    'Meta.fields = "__all__", Meta.exclude, and keep_on_form; save logic and HTMX unchanged.'
)

__1_10_0__ = _(
    "Release 1.10: cadences ship under contrib with app label cadences. "
    "Signals, registrations, URLs, and static paths updated to match the new contrib layout."
)

__1_0_0__ = _(
    "Implemented cadence signals for runtime activities, enabling "
    "automated cadence-driven workflow execution and activity tracking."
)
