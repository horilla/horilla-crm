"""
This module contains the views for the workflow app, including CRUD operations for WorkflowRule, WorkflowCondition, and WorkflowAction, as well as HTMX-powered detail, form, and fragment views. It also includes support for hidden-field action config serialization and new workflow templates. The views are organized in a way to provide a seamless user experience when managing workflows within the application.
"""

from horilla.contrib.workflow.views.core import (
    WorkflowRuleView,
    WorkflowRuleNavbar,
    WorkflowRuleListView,
    WorkflowRuleDetailNavbar,
    WorkflowRuleDetailView,
    WorkflowTimeTriggerHistoryView,
)

from horilla.contrib.workflow.views.actions import (
    WorkflowActiveToggleView,
    WorkflowCreateUpdateView,
    WorkflowDeleteView,
    WorkflowActionDeleteView,
    WorkflowTimeTriggerDeleteView,
)

from horilla.contrib.workflow.views.fragments import (
    _get_model_fields,
    _build_field_meta,
    _action_form_context,
    _get_date_field_choices,
    WorkflowActionFieldsView,
    WorkflowActionValueWidgetView,
    WorkflowActionSaveView,
    WorkflowTimeTriggerSaveView,
)

__all__ = [
    # Core views
    "WorkflowRuleView",
    "WorkflowRuleNavbar",
    "WorkflowRuleListView",
    "WorkflowRuleDetailNavbar",
    "WorkflowRuleDetailView",
    "WorkflowTimeTriggerHistoryView",
    # Action views
    "WorkflowActiveToggleView",
    "WorkflowCreateUpdateView",
    "WorkflowDeleteView",
    "WorkflowActionDeleteView",
    "WorkflowTimeTriggerDeleteView",
    # Fragment views
    "_get_model_fields",
    "_build_field_meta",
    "_get_date_field_choices",
    "_action_form_context",
    "WorkflowActionFieldsView",
    "WorkflowActionValueWidgetView",
    "WorkflowActionSaveView",
    "WorkflowTimeTriggerSaveView",
]
