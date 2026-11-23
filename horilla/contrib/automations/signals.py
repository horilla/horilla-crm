"""
Signals for the automations app
"""

# Standard library imports
import logging
import sys

# Third-party imports (Django)
from django.conf import settings
from django.dispatch import receiver

from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.utils.middlewares import _thread_local, get_active_company

# First party imports (Horilla)
from horilla.db import connection
from horilla.db.models.signals import post_save, pre_delete
from horilla.registry.feature import FEATURE_REGISTRY

# Local imports
from .methods import trigger_automations
from .models import HorillaAutomation
from .tasks import execute_automation_task

# Try to import Celery task, but don't fail if Celery is not available
try:
    CELERY_AVAILABLE = True
except Exception as e:
    logger = logging.getLogger(__name__)
    logger.warning(
        "Celery tasks not available, will use synchronous execution: %s", str(e)
    )
    CELERY_AVAILABLE = False
    execute_automation_task = None

if not "logger" in locals():
    logger = logging.getLogger(__name__)


def is_running_migrations():
    """
    Check if Django migrations are currently running.
    This prevents signal handlers from executing during migrations when tables may not exist.
    """
    # Check if 'migrate' is in the command line arguments
    if "migrate" in sys.argv:
        return True

    # Additionally, check if auditlog_logentry table exists
    # If it doesn't exist, we're likely mid-migration and should skip signal handlers
    try:
        db_table_names = connection.introspection.table_names()
        if "auditlog_logentry" not in db_table_names:
            return True
    except Exception:
        # If we can't check, assume we're not migrating to be safe
        # This ensures signal handlers work normally if the check fails
        pass

    return False


@receiver(post_save)
def trigger_automations_on_save(sender, instance, created, **kwargs):
    """
    Trigger automations when a model instance is saved.
    Handles both create and update triggers.
    """
    # Skip during migrations to avoid errors when tables don't exist yet
    if is_running_migrations():
        return

    # Only process signals for automation-enabled models (from FEATURE_REGISTRY)
    # Replaces hardcoded skips with dynamic, maintainable filtering
    allowed_models = FEATURE_REGISTRY.get("automation_models", [])
    if sender not in allowed_models:
        return

    try:
        # Check if there are any automations for this model
        content_type = HorillaContentType.objects.get_for_model(instance)
        has_automations = HorillaAutomation.objects.filter(model=content_type).exists()

        if not has_automations:
            return

        # Determine trigger type
        trigger_type = "on_create" if created else "on_update"

        # Get user and company from thread local if available
        request = getattr(_thread_local, "request", None)
        user = getattr(request, "user", None) if request else None
        company = get_active_company(request) if request else None

        # Prepare request info for background task
        request_info = {}
        if request:
            request_info = {
                "meta": getattr(request, "META", {}),
                "host": request.get_host() if hasattr(request, "get_host") else "",
                "scheme": request.scheme if hasattr(request, "scheme") else "https",
            }

        # Check if we should use async or sync execution
        use_async = getattr(settings, "USE_ASYNC_AUTOMATIONS", False)

        if use_async and CELERY_AVAILABLE and execute_automation_task:
            try:
                result = execute_automation_task.delay(
                    content_type_id=content_type.pk,
                    object_id=instance.pk,
                    trigger_type=trigger_type,
                    user_id=user.pk if user else None,
                    company_id=company.pk if company else None,
                    request_info=request_info,
                )
                logger.debug(
                    "Queued automation task: %s for %s %s",
                    result.id,
                    sender.__name__,
                    instance.pk,
                )
                return
            except Exception as celery_error:
                logger.warning(
                    "Failed to queue Celery task, falling back to sync: %s",
                    celery_error,
                )

                try:
                    trigger_automations(instance, trigger_type=trigger_type, user=user)
                except Exception as sync_error:
                    logger.error(
                        "Error in synchronous automation execution: %s",
                        sync_error,
                        exc_info=True,
                    )
        else:
            # Execute synchronously (default behavior)
            try:
                trigger_automations(instance, trigger_type=trigger_type, user=user)
            except Exception as sync_error:
                logger.error(
                    "Error in synchronous automation execution: %s",
                    sync_error,
                    exc_info=True,
                )

    except Exception as e:
        logger.error(
            "Error in trigger_automations_on_save for %s : %s",
            sender.__name__,
            str(e),
            exc_info=True,
        )


@receiver(pre_delete)
def trigger_automations_on_delete(sender, instance, **kwargs):
    """
    Trigger automations when a model instance is deleted.
    """
    # Skip during migrations to avoid errors when tables don't exist yet
    if is_running_migrations():
        return

    # Only process signals for automation-enabled models (from FEATURE_REGISTRY)
    # Replaces hardcoded skips with dynamic, maintainable filtering
    allowed_models = FEATURE_REGISTRY.get("automation_models", [])
    if sender not in allowed_models:
        return

    try:
        # Check if there are any automations for this model
        content_type = HorillaContentType.objects.get_for_model(instance)
        has_automations = HorillaAutomation.objects.filter(
            model=content_type, trigger="on_delete"
        ).exists()

        if not has_automations:
            return

        # Get user and company from thread local if available
        request = getattr(_thread_local, "request", None)
        user = getattr(request, "user", None) if request else None
        company = get_active_company(request) if request else None

        # Prepare request info for background task
        request_info = {}
        if request:
            request_info = {
                "meta": getattr(request, "META", {}),
                "host": request.get_host() if hasattr(request, "get_host") else "",
                "scheme": request.scheme if hasattr(request, "scheme") else "https",
            }

        # Check if we should use async or sync execution
        use_async = getattr(settings, "USE_ASYNC_AUTOMATIONS", False)

        if use_async and CELERY_AVAILABLE and execute_automation_task:
            try:
                result = execute_automation_task.delay(
                    content_type_id=content_type.pk,
                    object_id=instance.pk,
                    trigger_type="on_delete",
                    user_id=user.pk if user else None,
                    company_id=company.pk if company else None,
                    request_info=request_info,
                )
                logger.debug(
                    "Queued delete automation task: %s for %s %s",
                    result.id,
                    sender.__name__,
                    instance.pk,
                )
                return
            except Exception as celery_error:
                logger.warning(
                    "Failed to queue Celery task, falling back to sync: %s",
                    celery_error,
                )
                try:
                    trigger_automations(instance, trigger_type="on_delete", user=user)
                except Exception as sync_error:
                    logger.error(
                        "Error in synchronous delete automation execution: %s",
                        sync_error,
                        exc_info=True,
                    )
        else:
            # Execute synchronously (default)
            try:
                trigger_automations(instance, trigger_type="on_delete", user=user)
            except Exception as sync_error:
                logger.error(
                    "Error in synchronous delete automation execution: %s",
                    sync_error,
                    exc_info=True,
                )

    except Exception as e:
        logger.error(
            "Error in trigger_automations_on_delete for %s : %s ",
            sender.__name__,
            str(e),
            exc_info=True,
        )
