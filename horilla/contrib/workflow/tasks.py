"""
Celery tasks for the workflow app.

process_scheduled_workflow_executions — periodic task, queues due time triggers.
execute_workflow_time_trigger          — worker task, runs the actual action.
"""

# Standard library imports
import logging

# Third-party imports (Django)
from celery import shared_task

# First party imports (Horilla)
from horilla.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def process_scheduled_workflow_executions():
    """
    Periodic task: find all pending ScheduledWorkflowExecution rows whose
    scheduled_at has passed and queue a worker task for each.
    """
    from .models import ScheduledWorkflowExecution

    due = ScheduledWorkflowExecution.objects.filter(
        status=ScheduledWorkflowExecution.STATUS_PENDING,
        scheduled_at__lte=timezone.now(),
    )

    count = due.count()
    logger.info("Workflow scheduler: %s executions due", count)

    for execution in due:
        execute_workflow_time_trigger.delay(execution.pk)

    return f"Queued {count} workflow time-trigger executions"


@shared_task(bind=True, max_retries=3)
def execute_workflow_time_trigger(self, execution_id):
    """
    Worker task: execute a single ScheduledWorkflowExecution.
    """
    from .methods import execute_action, time_trigger_skip_reason
    from .models import ScheduledWorkflowExecution

    try:
        execution = ScheduledWorkflowExecution.objects.select_related(
            "time_trigger__rule"
        ).get(pk=execution_id)
    except ScheduledWorkflowExecution.DoesNotExist:
        logger.error("ScheduledWorkflowExecution %s not found", execution_id)
        return

    if execution.status != ScheduledWorkflowExecution.STATUS_PENDING:
        return

    time_trigger = execution.time_trigger
    rule = time_trigger.rule

    try:
        model_class = rule.model.model_class()
        instance = model_class.objects.get(pk=execution.object_id)
    except Exception as exc:
        logger.error("Could not load record for execution %s: %s", execution_id, exc)
        execution.status = ScheduledWorkflowExecution.STATUS_FAILED
        execution.error_message = str(exc)
        execution.executed_at = timezone.now()
        execution.save(update_fields=["status", "error_message", "executed_at"])
        return

    skip_reason = time_trigger_skip_reason(time_trigger, instance)
    if skip_reason:
        logger.info("Workflow execution %s skipped: %s", execution_id, skip_reason)
        execution.status = ScheduledWorkflowExecution.STATUS_SKIPPED
        execution.error_message = skip_reason
        execution.executed_at = timezone.now()
        execution.save(update_fields=["status", "error_message", "executed_at"])
        return

    user = rule.updated_by or rule.created_by

    try:
        if not execute_action(time_trigger, instance, user):
            # The action type's app is gone: retrying will not bring it back.
            execution.status = ScheduledWorkflowExecution.STATUS_FAILED
            execution.error_message = (
                f"Action type {time_trigger.action_type!r} is not a built-in "
                "or a registered delivery channel."
            )
            execution.executed_at = timezone.now()
            execution.save(update_fields=["status", "error_message", "executed_at"])
            return

        execution.status = ScheduledWorkflowExecution.STATUS_COMPLETED
        execution.executed_at = timezone.now()
        execution.save(update_fields=["status", "executed_at"])

        logger.info(
            "Workflow execution %s completed (%s on %s pk=%s)",
            execution_id,
            time_trigger.action_type,
            instance.__class__.__name__,
            instance.pk,
        )

    except Exception as exc:
        logger.error(
            "Workflow execution %s failed: %s", execution_id, exc, exc_info=True
        )
        execution.status = ScheduledWorkflowExecution.STATUS_FAILED
        execution.error_message = str(exc)
        execution.executed_at = timezone.now()
        execution.save(update_fields=["status", "error_message", "executed_at"])
        raise self.retry(exc=exc, countdown=300)
