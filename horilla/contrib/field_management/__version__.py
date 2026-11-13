"""
Version information for the field settings app.
"""

# First party imports (Horilla)
from horilla.utils.translation import gettext_lazy as _

__version__ = "1.0.3"
__module_name__ = "Field Management"
__release_date__ = ""
__description__ = _(
    "Configure fields on opted-in models: add custom fields, choose which "
    "fields are required or optional, and set which fields appear on a form "
    "and in what order, per company."
)
__icon__ = "field_management/assets/icons/field-requirement.svg"

__1_0_3__ = _("List search covers field-management fields.")

__1_0_2__ = _(
    "The form layout Cancel button sits in the navbar. Custom-field "
    "conditions can use audit fields."
)

__1_0_1__ = _(
    "Offer this fiscal period, quarter and year on custom date and datetime "
    "filters, using the same bounds as model date fields."
)

__1_0_0__ = _(
    "Merge the Custom Fields, Field Requirements and Form Layouts apps into one "
    "Field Management app with a single Settings menu entry. Feature registry "
    "names are unchanged; existing installs are upgraded by migrate "
    "alone, keeping data and permissions. Full Width on form layouts and "
    "custom fields. Use custom fields in conditions, reports, dashboards, "
    "grouping, filters and import, including date comparisons. Skip custom "
    "layouts on partial forms that declare their own fields. Stop Kanban "
    "group settings from crashing when the app label is missing."
)
