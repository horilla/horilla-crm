"""
Models for the workflow app
"""

from horilla.contrib.core.models import HorillaContentType, HorillaCoreModel
from horilla.contrib.utils.methods import render_template

# First party imports (Horilla)
from horilla.db import models
from horilla.registry.limiters import limit_content_types
from horilla.registry.permission_registry import permission_exempt_model
from horilla.urls import reverse_lazy
from horilla.utils.choices import OPERATOR_CHOICES
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .action_types import ACTION_TYPE_MAX_LENGTH, get_action_type_label


class WorkflowRule(HorillaCoreModel):
    """
    Defines an automated workflow that fires when a record is created or edited.
    """

    name = models.CharField(
        max_length=255,
        verbose_name=_("Rule Name"),
    )
    model = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        limit_choices_to=limit_content_types("workflow_models"),
        related_name="workflow_rules",
        verbose_name=_("Module"),
        help_text=_("The module (record type) this rule applies to."),
    )
    description = models.TextField(
        blank=True,
        verbose_name=_("Description"),
    )
    trigger_on_create = models.BooleanField(
        default=True,
        verbose_name=_("When Record Is Created"),
        help_text=_("Run this workflow when a new record is created."),
    )
    trigger_on_edit = models.BooleanField(
        default=False,
        verbose_name=_("When Record Is Edited"),
        help_text=_("Run this workflow when an existing record is edited."),
    )
    only_when_criteria_become_true = models.BooleanField(
        default=False,
        verbose_name=_("Only When the Criteria Become True"),
        help_text=_(
            "When a record is edited, run this workflow only if the record did "
            "not meet the criteria before the edit and meets them after it. "
            "Further edits that keep it matching do not run it again."
        ),
    )

    class Meta:
        """Meta options for WorkflowRule model"""

        verbose_name = _("Workflow Rule")
        verbose_name_plural = _("Workflow Rules")
        ordering = ["-created_at"]

    def __str__(self):
        return str(self.name)

    def is_active_col(self):
        """Return HTML toggle for active status column."""
        if self.is_active:
            confirm_message = _(
                "Are you sure you want to deactivate this workflow rule?"
            )
        else:
            confirm_message = _("Are you sure you want to activate this workflow rule?")
        return render_template(
            path="components/toggle_active_col.html",
            context={
                "instance": self,
                "toggle_url": reverse_lazy(
                    "workflow:workflow_rule_activate_toggle_view",
                    kwargs={"pk": self.pk},
                ),
                "confirm_message": confirm_message,
            },
        )

    def get_execute_display(self) -> str:
        """Human-readable 'Execute on'"""
        c, e = self.trigger_on_create, self.trigger_on_edit
        newly = self.only_when_criteria_become_true
        if c and e:
            if newly:
                return str(_("Create, and Edit when criteria become true"))
            return str(_("Create and Edit"))
        if c:
            return str(_("Create only"))
        if e:
            if newly:
                return str(_("Edit when criteria become true"))
            return str(_("Edit only"))
        return str(_("Not set"))

    def get_detail_url(self):
        """Return the URL for the detail view of this workflow rule. This is used in the name column link on the list view."""
        return reverse_lazy(
            "workflow:workflow_rule_detail_view", kwargs={"pk": self.pk}
        )

    def get_edit_url(self):
        """Return the URL for the edit view of this workflow rule. This is used for the edit button/link on the list and detail views."""
        return reverse_lazy(
            "workflow:workflow_rule_update_view", kwargs={"pk": self.pk}
        )

    def get_delete_url(self):
        """Return the URL for the delete view of this workflow rule. This is used for the delete button/link on the list and detail views."""
        return reverse_lazy(
            "workflow:workflow_rule_delete_view", kwargs={"pk": self.pk}
        )


@permission_exempt_model
class WorkflowCondition(HorillaCoreModel):
    """
    One condition row for a WorkflowRule.
    All rows are evaluated (AND/OR) before the rule's actions fire.
    """

    rule = models.ForeignKey(
        WorkflowRule,
        on_delete=models.CASCADE,
        related_name="conditions",
        verbose_name=_("Workflow Rule"),
    )
    field = models.CharField(
        max_length=100,
        verbose_name=_("Field Name"),
    )
    operator = models.CharField(
        max_length=50,
        choices=OPERATOR_CHOICES,
        verbose_name=_("Operator"),
    )
    value = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Value"),
    )
    logical_operator = models.CharField(
        max_length=3,
        choices=[("and", _("AND")), ("or", _("OR"))],
        default="and",
        verbose_name=_("Logical Operator"),
    )
    order = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Order"),
    )

    class Meta:
        """Meta options for WorkflowCondition model"""

        verbose_name = _("Workflow Condition")
        verbose_name_plural = _("Workflow Conditions")
        ordering = ["order", "created_at"]

    def __str__(self):
        return f"{self.rule.name}: {self.field} {self.operator} {self.value}"


class WorkflowAction(HorillaCoreModel):
    """
    One action to execute when a WorkflowRule fires.

    action_type is one key: a built-in (update_field, assign_task, email,
    notification) or the key of a registered delivery channel (see
    ``action_types.py``). It has no fixed choices. All type-specific config is
    stored in action_config (JSONField), keeping the table schema flat — same
    pattern as ApprovalProcessRule.rule_config.
    """

    rule = models.ForeignKey(
        WorkflowRule,
        on_delete=models.CASCADE,
        related_name="actions",
        verbose_name=_("Workflow Rule"),
    )
    action_type = models.CharField(
        max_length=ACTION_TYPE_MAX_LENGTH,
        verbose_name=_("Action"),
    )
    action_config = models.JSONField(
        default=dict,
        blank=True,
        help_text=_(
            "Type-specific configuration. "
            "update_field: {field, value}. "
            "assign_task: {title, due_basis, due_in_days, status, priority, description}. "
            "email: {template_id, to, also_send_to}. "
            "notification: {template_id, to, also_notify_to, custom_message}. "
            "A delivery channel: {template_id, to, also_send_to}."
        ),
    )
    order = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Order"),
    )

    class Meta:
        """Meta options for WorkflowAction model"""

        verbose_name = _("Workflow Action")
        verbose_name_plural = _("Workflow Actions")
        ordering = ["order", "created_at"]

    def get_action_type_display(self):
        """The built-in's or the delivery channel's label (the key if its app is gone)."""
        return get_action_type_label(self.action_type)

    def __str__(self):
        return f"{self.rule.name} — {self.get_action_type_display()}"


@permission_exempt_model
class WorkflowTimeTriggerAction(HorillaCoreModel):
    """
    A time-delayed action attached to a WorkflowRule.

    Fires `delay_value` `delay_unit` (after/before) a `trigger_date_field`
    on the target record (or 'rule_trigger_date' for the moment the rule fired).

    action_type and action_config follow the same schema as WorkflowAction.
    """

    DELAY_UNIT_CHOICES = [
        ("minutes", _("Minutes")),
        ("hours", _("Hours")),
        ("days", _("Days")),
    ]

    DELAY_DIRECTION_CHOICES = [
        ("after", _("After")),
        ("before", _("Before")),
    ]

    rule = models.ForeignKey(
        WorkflowRule,
        on_delete=models.CASCADE,
        related_name="time_trigger_actions",
        verbose_name=_("Workflow Rule"),
    )
    delay_value = models.PositiveIntegerField(
        default=1,
        verbose_name=_("Delay"),
    )
    delay_unit = models.CharField(
        max_length=10,
        choices=DELAY_UNIT_CHOICES,
        default="days",
        verbose_name=_("Unit"),
    )
    delay_direction = models.CharField(
        max_length=10,
        choices=DELAY_DIRECTION_CHOICES,
        default="after",
        verbose_name=_("Direction"),
    )
    trigger_date_field = models.CharField(
        max_length=100,
        verbose_name=_("Trigger Date"),
        help_text=_(
            "Use 'rule_trigger_date' to fire relative to when the rule triggered, "
            "or enter a date field name from the target model."
        ),
    )
    action_type = models.CharField(
        max_length=ACTION_TYPE_MAX_LENGTH,
        verbose_name=_("Action Type"),
    )
    action_config = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Action Config"),
    )
    order = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Order"),
    )

    class Meta:
        """Meta options for WorkflowTimeTriggerAction."""

        verbose_name = _("Workflow Time Trigger Action")
        verbose_name_plural = _("Workflow Time Trigger Actions")
        ordering = ["order", "created_at"]

    def get_action_type_display(self):
        """The built-in's or the delivery channel's label (the key if its app is gone)."""
        return get_action_type_label(self.action_type)

    def __str__(self):
        return (
            f"{self.rule.name} — {self.delay_value} {self.get_delay_unit_display()} "
            f"{self.get_delay_direction_display()} {self.trigger_date_field} "
            f"→ {self.get_action_type_display()}"
        )


@permission_exempt_model
class ScheduledWorkflowExecution(HorillaCoreModel):
    """
    Tracks a pending/completed time-triggered workflow action for a specific record.
    Created by execute_workflow_rule; processed by the Celery periodic task.
    """

    STATUS_PENDING = "pending"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"
    STATUS_CHOICES = [
        (STATUS_PENDING, _("Pending")),
        (STATUS_COMPLETED, _("Completed")),
        (STATUS_FAILED, _("Failed")),
        (STATUS_SKIPPED, _("Skipped")),
    ]

    time_trigger = models.ForeignKey(
        WorkflowTimeTriggerAction,
        on_delete=models.CASCADE,
        related_name="scheduled_executions",
        verbose_name=_("Time Trigger"),
    )
    object_id = models.PositiveIntegerField(verbose_name=_("Record ID"))
    scheduled_at = models.DateTimeField(
        db_index=True,
        verbose_name=_("Scheduled At"),
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
        verbose_name=_("Status"),
    )
    executed_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Executed At")
    )
    error_message = models.TextField(blank=True, verbose_name=_("Error"))

    class Meta:
        """Meta options for ScheduledWorkflowExecution."""

        verbose_name = _("Scheduled Workflow Execution")
        verbose_name_plural = _("Scheduled Workflow Executions")
        ordering = ["scheduled_at"]
        indexes = [
            models.Index(fields=["status", "scheduled_at"]),
        ]

    def get_record_name(self):
        """Return the string representation of the target record."""
        try:
            model_class = self.time_trigger.rule.model.model_class()
            instance = model_class.objects.get(pk=self.object_id)
            return str(instance)
        except Exception:
            return str(self.object_id)

    def __str__(self):
        return f"{self.time_trigger} | obj={self.object_id} | {self.scheduled_at}"
