"""Version and metadata for the horilla.contrib.workflow app."""

from horilla.utils.translation import gettext_lazy as _

__version__ = "1.11.10"
__module_name__ = _("Workflow")
__release_date__ = ""
__description__ = _(
    "Record-triggered workflow rules with field conditions, immediate actions "
    "(update field, assign task, email, notification), and time-based triggers "
    "scheduled relative to record or rule dates."
)
__icon__ = "assets/icons/automation.svg"

__1_11_10__ = _(
    "Workflow actions send through registered delivery channels, including "
    "channels added by other apps. Mail and notification stay the built-in "
    "email and notification actions. The email action explains when "
    "outgoing mail is not configured."
)

__1_11_9__ = _("Show readable condition values on workflow rule details.")

__1_11_8__ = _(
    "Evaluate custom fields in workflow conditions and show their labels on "
    "rule details."
)

__1_11_7__ = _("Add settings nav description for Workflow Rules.")

__1_11_6__ = _(
    "Prevent NoReverseMatch when saving an action or time-trigger with an invalid rule. "
    "Remove orphaned WorkflowCondition CRUD view, form, and template. Gate email actions "
    "on outgoing mail configuration."
)

__1_11_5__ = _(
    "Use the shared is_active toggle column partial. Derive list column labels from model "
    "verbose_name; stop forcing labels to title case."
)

__1_11_4__ = _("Apply runtime viewport fit on the workflow rules settings list.")

__1_11_3__ = _(
    "Re-raise HttpNotFound with exception chaining in workflow detail views to "
    "preserve context."
)

__1_11_2__ = _(
    "Migrated workflow execution engine transaction imports from django.db to horilla.db."
)

__1_11_1__ = _(
    "Migrated signal imports to the horilla.db.models.signals shim and standardized "
    "first-party import groups; behavior unchanged."
)

__1_11_0__ = _(
    "Workflow automation engine: WorkflowRule / WorkflowCondition / WorkflowAction models, "
    "dynamic condition evaluation, immediate dispatch on record saves, Celery "
    "WorkflowTimeTriggerAction and ScheduledWorkflowExecution, execution history modal, "
    "FilterSet support, auto-registration for workflow-enabled models via feature "
    "registration (e.g. users, departments, holidays), modular views, hidden-field action "
    "configuration fixes, restored workflow detail pages, and improved routing namespaces."
)

__1_10_1__ = _(
    "WorkflowRuleForm aligned with HorillaModelForm layout: field_order, "
    'Meta.fields = "__all__", and keep_on_form for is_active; action forms unchanged.'
)

__1_10_0__ = _(
    "Initial release: workflow rules per ContentType with create/edit triggers, "
    "AND/OR conditions, ordered immediate actions, time-trigger actions with "
    "Celery scheduling and execution history, Settings → Automations → Workflow Rules, "
    "and integration with registered models via feature registration."
)
