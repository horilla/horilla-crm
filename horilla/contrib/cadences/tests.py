"""
Tests for the cadences app
"""

# Standard library imports
from datetime import timedelta

# Third-party imports (Django)
from django.test import TestCase

# First party imports (Horilla)
from horilla.contrib.activity.models import Activity
from horilla.contrib.core.models import Company, HorillaContentType
from horilla.utils import timezone

# Local imports
from . import services
from .models import (
    Cadence,
    CadenceEnrollment,
    CadenceFollowUp,
    CadenceScheduledFollowUp,
)


class DelayedFollowUpTests(TestCase):
    """The "Do This" delay of a follow-up postpones its creation."""

    def setUp(self):
        self.record = Company.objects.create(name="Acme")
        content_type = HorillaContentType.objects.get_for_model(Company)
        self.cadence = Cadence.objects.create(name="Test", module=content_type)
        self.enrollment = CadenceEnrollment.all_objects.create(
            cadence=self.cadence,
            content_type=content_type,
            object_id=self.record.pk,
            started_at=timezone.now(),
        )
        self.first = CadenceFollowUp.objects.create(
            cadence=self.cadence,
            followup_number=1,
            followup_type="task",
            subject="first",
            due_after_days=1,
        )
        self.second = CadenceFollowUp.objects.create(
            cadence=self.cadence,
            followup_number=2,
            followup_type="call",
            previous_status="completed",
            branch_from=self.first,
            purpose="call",
            call_start_after_days=0,
            do_this_unit="minute",
            do_this_value=2,
        )

    def _activities(self):
        return Activity.all_objects.filter(
            additional_info__cadence_runtime__enrollment_id=self.enrollment.pk
        )

    def test_delayed_followup_is_scheduled_not_created(self):
        services.create_first_followups(self.enrollment, self.record)
        services.create_next_followups(
            self.enrollment, self.record, self.first, "completed"
        )
        self.assertEqual(self._activities().count(), 1)
        scheduled = CadenceScheduledFollowUp.all_objects.get(followup=self.second)
        self.assertEqual(scheduled.status, "pending")
        wait = scheduled.scheduled_at - timezone.now()
        self.assertGreater(wait, timedelta(seconds=60))
        self.assertLessEqual(wait, timedelta(minutes=2))

    def test_not_created_twice(self):
        for _run in range(2):
            services.create_next_followups(
                self.enrollment, self.record, self.first, "completed"
            )
        self.assertEqual(CadenceScheduledFollowUp.all_objects.count(), 1)

    def test_pending_followup_keeps_enrollment_active(self):
        services.create_first_followups(self.enrollment, self.record)
        services.create_next_followups(
            self.enrollment, self.record, self.first, "completed"
        )
        self._activities().update(status="completed")
        services.refresh_status(self.enrollment)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, "active")

    def test_due_followup_is_created(self):
        services.create_next_followups(
            self.enrollment, self.record, self.first, "completed"
        )
        scheduled = CadenceScheduledFollowUp.all_objects.get(followup=self.second)
        self.assertEqual(services.due_scheduled_followup_ids(), [])
        CadenceScheduledFollowUp.all_objects.filter(pk=scheduled.pk).update(
            scheduled_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(services.due_scheduled_followup_ids(), [scheduled.pk])
        services.run_scheduled_followup(scheduled.pk)
        scheduled.refresh_from_db()
        self.assertEqual(scheduled.status, "completed")
        self.assertEqual(self._activities().filter(activity_type="log_call").count(), 1)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, "active")

    def test_unenrolled_run_cancels_pending_followup(self):
        services.create_next_followups(
            self.enrollment, self.record, self.first, "completed"
        )
        scheduled = CadenceScheduledFollowUp.all_objects.get(followup=self.second)
        CadenceEnrollment.all_objects.filter(pk=self.enrollment.pk).update(
            status="unenrolled"
        )
        CadenceScheduledFollowUp.all_objects.filter(pk=scheduled.pk).update(
            scheduled_at=timezone.now() - timedelta(seconds=1)
        )
        services.run_scheduled_followup(scheduled.pk)
        scheduled.refresh_from_db()
        self.assertEqual(scheduled.status, "cancelled")
        self.assertEqual(self._activities().count(), 0)

    def test_immediate_followup_still_created_at_once(self):
        CadenceFollowUp.objects.filter(pk=self.second.pk).update(
            do_this_unit="immediately", do_this_value=None
        )
        services.create_next_followups(
            self.enrollment, self.record, self.first, "completed"
        )
        self.assertEqual(self._activities().count(), 1)
        self.assertFalse(CadenceScheduledFollowUp.all_objects.exists())


class StatusOnCreationTests(TestCase):
    """A follow-up waiting for the status an item is created with starts at once."""

    def setUp(self):
        self.record = Company.objects.create(name="Beta")
        content_type = HorillaContentType.objects.get_for_model(Company)
        self.cadence = Cadence.objects.create(name="Chain", module=content_type)
        self.enrollment = CadenceEnrollment.all_objects.create(
            cadence=self.cadence,
            content_type=content_type,
            object_id=self.record.pk,
            started_at=timezone.now(),
        )
        self.call = CadenceFollowUp.objects.create(
            cadence=self.cadence,
            followup_number=1,
            followup_type="call",
            purpose="call",
            call_start_after_days=0,
        )
        self.task = CadenceFollowUp.objects.create(
            cadence=self.cadence,
            followup_number=2,
            followup_type="task",
            previous_status="scheduled",
            branch_from=self.call,
            subject="after scheduled call",
            due_after_days=1,
        )
        self.last = CadenceFollowUp.objects.create(
            cadence=self.cadence,
            followup_number=3,
            followup_type="task",
            previous_status="not_started",
            branch_from=self.task,
            subject="after not started task",
            due_after_days=1,
        )

    def test_chain_follows_creation_statuses(self):
        services.create_first_followups(self.enrollment, self.record)
        subjects = set(
            Activity.all_objects.filter(
                additional_info__cadence_runtime__enrollment_id=self.enrollment.pk
            ).values_list("subject", flat=True)
        )
        self.assertEqual(
            subjects, {"call", "after scheduled call", "after not started task"}
        )
