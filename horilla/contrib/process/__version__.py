"""
Version information for the Process Builder
"""

# First party imports (Horilla)
from horilla.utils.translation import gettext_lazy as _

__version__ = "1.11.16"
__module_name__ = "Process Builder"
__release_date__ = ""
__description__ = _(
    "Module for managing the process, including approval processes and review processes."
)
__icon__ = "assets/icons/process-management.svg"

__1_11_16__ = _(
    "Approval and review lists use the field-aware search, and list search "
    "covers their fields."
)

__1_11_15__ = _(
    "Approval and review condition pickers offer a user's department, role "
    "and company, and share the audit-field list."
)

__1_11_14__ = _(
    "Let a pending approver use Edit Details without the change permission. "
    "Show readable condition values on approval and review details."
)

__1_11_13__ = _(
    "Respect the approval edit policy in Edit Details and keep the approval "
    "detail page and sidebar after a reload."
)

__1_11_12__ = _(
    "Evaluate custom fields in approval and review conditions and show their "
    "labels on rule details."
)

__1_11_11__ = _(
    "Block the detail view while a record is pending approval; wire Record owner "
    "approver matching; add Create/Edit triggers on review processes."
)

__1_11_10__ = _(
    "Hide review jobs not assigned to the current user; add settings nav "
    "descriptions for Review and Approval Processes."
)

__1_11_9__ = _(
    "Replace list-view monkey patches with MixinExtension for approvals and "
    "reviews. Wire pending-approval guards into the bulk Edit Details save flow."
)

__1_11_8__ = _("Correct the stage value in Opportunity Field Review seed data.")

__1_11_7__ = _(
    "Use the shared is_active toggle column partial for approvals and reviews. Derive "
    "list/detail column labels from model verbose_name; add missing verbose_name on "
    "approval fields; stop forcing labels to title case; indexes on frequently filtered "
    "fields."
)

__1_11_6__ = _(
    "Apply runtime viewport fit on approval/review process lists and approval job/"
    "history detail screens."
)

__1_11_5__ = _(
    "Reviews: cap review process form modal body height with max-h so short forms no "
    "longer reserve a fixed 500px empty area."
)

__1_11_4__ = _(
    "Approvals: scope delegation to ApprovalInstance.delegated_approver instead of mutating "
    "shared process rules; replace alert()-based responses with messages.error and HTMX "
    "reload; register ApprovalInstance for export_data. Wrap approval form placeholders "
    "with gettext_lazy."
)

__1_11_3__ = _(
    "Re-raise HttpNotFound with exception chaining in process detail views to "
    "preserve context."
)

__1_11_2__ = _(
    "Approvals: fixed type mismatch when excluding pending approval objects from list "
    "view; added job detail body template and adjusted tab container height."
)

__1_11_1__ = _(
    'ApprovalRuleForm refactored to fields="__all__" with field_order, dropping the '
    "unused process_config field and the redundant view fields list. Fixed a KeyError on "
    "review-process create by adding keep_on_form for is_active. Migrated signal imports "
    "to the db.models.signals shim and added docstrings for pylint compliance."
)

__1_10_0__ = _(
    "Release 1.10: Process Builder consolidated under contrib.process with approvals "
    "and reviews sub-apps. Django app labels for approvals and reviews are unchanged; "
    "import paths and includes now use the contrib package layout."
)

__1_1_0__ = _(
    "Enhanced approval workflow with delete support in approval history, "
    "standard HTMX modal delete flow, and inline edit enforcement for "
    "pending/rejected records. Improved approval signals cleanup, "
    "review process table viewport handling, and redirect behavior."
)

__1_0_0__ = _(
    "Introduced unified Process Builder combining reviews and approvals "
    "into a flexible, condition-driven workflow engine with configurable "
    "approvers, field-level controls, and per-app process configuration."
)
