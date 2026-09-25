"""
Version information for the custom_fields app.
"""

# First party imports (Horilla)
from horilla.utils.translation import gettext_lazy as _

__version__ = "1.0.3"
__module_name__ = "Custom Fields"
__release_date__ = ""
__description__ = _(
    "Define extra fields on Leads and Opportunities. Configure them in "
    "Settings and use them on create/edit forms, detail views, list columns, "
    "filters, and exports."
)
__icon__ = "assets/icons/custom-field.svg"

__1_0_3__ = _(
    "Add Date and Date and Time field types with typed storage, Jalali-aware "
    "pickers and display, date filters, and date operators in assignment rules."
)

__1_0_2__ = _(
    "Support bulk Edit Details save for cf_* fields; export via the generics "
    "bulk-export hook; recognize single_choice fields in filters."
)

__1_0_1__ = _(
    "Replace CRM monkey-patches with Form, Filter, List, Detail, Mixin, and "
    "View extensions; register through the generic extension registry and "
    "drop remaining ad-hoc hooks."
)

__1_0_0__ = _(
    "Add a Custom Fields settings app for Leads and Opportunities. Support "
    "small text, large text, number, and multiple choice fields. Inject values "
    "into create/edit forms, detail views, list columns, record filters, and "
    "exports without changing Horilla core."
)
