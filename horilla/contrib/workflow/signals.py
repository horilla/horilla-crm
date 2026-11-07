"""
Signals for the workflow app.

Listens to post_save on every model registered under the "workflow_models"
feature key and fires matching active WorkflowRules. A pre_save receiver
records whether an edited record met the criteria before the save, for rules
that run on edit only when their criteria become true.
"""

# Standard library imports
import logging

# Third-party imports (Django)
from django.dispatch import receiver

from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.utils.middlewares import _thread_local

# First party imports (Horilla)
from horilla.db.models.signals import post_save, pre_save
from horilla.registry.feature import FEATURE_REGISTRY

# Local imports
from .methods import (
    criteria_met_before_save,
    is_running_migrations,
    trigger_workflow_rules,
)
from .models import WorkflowRule

logger = logging.getLogger(__name__)

# Instance attribute holding {rule pk: criteria met before the save}.
_MET_BEFORE_ATTR = "_workflow_criteria_met_before"


def _is_workflow_save(sender, instance):
    """
    True when a save of this instance may run workflow rules.

    The cheap checks come first: ``is_running_migrations()`` lists the
    database tables, so it runs only for a save that could run a rule.
    """
    if sender not in FEATURE_REGISTRY.get("workflow_models", []):
        return False
    # Re-entrancy guard: skip if this save was issued by a workflow action
    executing_set = getattr(_thread_local, "_workflow_executing", set())
    if (sender, instance.pk) in executing_set:
        return False
    return not is_running_migrations()


@receiver(pre_save)
def remember_workflow_criteria_before_save(sender, instance, raw=False, **kwargs):
    """
    Before an existing registered record is saved, record whether its stored
    copy meets the criteria of the rules with ``only_when_criteria_become_true``.

    Costs one rule query per edit of a registered model; the stored record is
    read and the criteria evaluated only when such a rule exists.
    """
    instance.__dict__.pop(_MET_BEFORE_ATTR, None)
    if raw or instance.pk is None or instance._state.adding:
        return
    if not _is_workflow_save(sender, instance):
        return
    try:
        met_before = criteria_met_before_save(instance)
        if met_before:
            instance.__dict__[_MET_BEFORE_ATTR] = met_before
    except Exception as exc:
        logger.error(
            "Error in remember_workflow_criteria_before_save for %s: %s",
            sender.__name__,
            exc,
            exc_info=True,
        )


@receiver(post_save)
def trigger_workflow_rules_on_save(sender, instance, created, **kwargs):
    """
    Fire all active WorkflowRules when a registered model instance is saved.

    Only models listed in FEATURE_REGISTRY["workflow_models"] are processed so
    that every single model save in the system does not incur the overhead of a
    WorkflowRule query.

    A thread-local re-entrancy guard prevents the update_field action's own
    save() call from re-triggering workflow rules on the same instance.

    On an update, rules with ``only_when_criteria_become_true`` run only when
    the pre_save receiver found their criteria not met before the save.
    """
    met_before = instance.__dict__.pop(_MET_BEFORE_ATTR, None)
    if not _is_workflow_save(sender, instance):
        return

    executing_set = getattr(_thread_local, "_workflow_executing", set())
    instance_key = (sender, instance.pk)

    try:
        content_type = HorillaContentType.objects.get_for_model(instance)
        has_rules = WorkflowRule.objects.filter(
            model=content_type, is_active=True
        ).exists()
        if not has_rules:
            return

        trigger_type = "on_create" if created else "on_update"

        request = getattr(_thread_local, "request", None)
        user = getattr(request, "user", None) if request else None

        executing_set.add(instance_key)
        _thread_local._workflow_executing = executing_set
        try:
            trigger_workflow_rules(
                instance, trigger_type=trigger_type, user=user, met_before=met_before
            )
        finally:
            executing_set.discard(instance_key)

    except Exception as exc:
        logger.error(
            "Error in trigger_workflow_rules_on_save for %s: %s",
            sender.__name__,
            exc,
            exc_info=True,
        )
