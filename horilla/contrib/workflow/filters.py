"""
Filters for the workflow app
"""

# First party imports (Horilla)
from horilla.contrib.generics.filters import HorillaFilterSet

# Local imports
from .models import ScheduledWorkflowExecution, WorkflowRule


class WorkflowRuleFilter(HorillaFilterSet):
    """FilterSet for WorkflowRule model, allowing filtering by name and other fields, excluding additional_info and process_config."""

    class Meta:
        """Meta class for WorkflowRuleFilter, specifying the model, fields to include/exclude, and search fields."""

        model = WorkflowRule
        fields = "__all__"
        exclude = ["additional_info", "process_config"]
        search_fields = ["name", "description"]


class ScheduledWorkflowExecutionFilter(HorillaFilterSet):
    """FilterSet for ScheduledWorkflowExecution history list."""

    class Meta:
        """Meta class for ScheduledWorkflowExecutionFilter."""

        model = ScheduledWorkflowExecution
        fields = "__all__"
        exclude = ["additional_info", "time_trigger", "error_message"]
        search_fields = ["object_id", "error_message"]
