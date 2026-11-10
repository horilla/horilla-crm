"""
Tests for the cadences app
"""

# Standard library imports
from datetime import timedelta
from unittest import mock

# Third-party imports (Django)
from django.contrib.auth.signals import user_logged_in
from django.db import connection, models
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext, isolate_apps
from login_history.models import post_login

# First party imports (Horilla)
import horilla.registry.delivery as delivery_registry
from horilla.auth.models import User
from horilla.contrib.activity.models import Activity
from horilla.contrib.core.models import Company, HorillaContentType
from horilla.contrib.keys.models import ShortcutKey
from horilla.contrib.notifications.models import Notification, NotificationTemplate
from horilla.core.exceptions import ValidationError
from horilla.registry.delivery import (
    ADDRESS_PHONE,
    DeliveryChannel,
    register_delivery_channel,
    unregister_delivery_channel,
)
from horilla.urls import reverse
from horilla.utils import timezone

# Local imports
from . import services, signals
from .followup_types import (
    get_followup_channel,
    get_followup_type_choices,
    get_followup_type_label,
)
from .forms import CadenceFollowUpForm
from .models import (
    Cadence,
    CadenceCondition,
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


class RecordOwnerFollowUpTests(TestCase):
    """A task or call follow-up can go to the owner of the enrolled record."""

    def setUp(self):
        self.company = Company.objects.create(name="Owners Co")
        self.creator = User.objects.create_user(
            username="cadence-creator", email="creator@example.com", password="x"
        )
        self.fixed = User.objects.create_user(
            username="fixed-owner", email="fixed@example.com", password="x"
        )
        self.record_owner = User.objects.create_user(
            username="record-owner", email="record@example.com", password="x"
        )
        # A core model whose OWNER_FIELDS is a user foreign key.
        self.record = ShortcutKey.objects.create(
            user=self.record_owner, page="/", key="k", command="alt"
        )
        self.cadence, self.enrollment = self.enroll(self.record)

    def enroll(self, record):
        content_type = HorillaContentType.objects.get_for_model(record.__class__)
        cadence = Cadence.objects.create(
            name="Owners",
            module=content_type,
            created_by=self.creator,
            updated_by=self.creator,
        )
        enrollment = CadenceEnrollment.all_objects.create(
            cadence=cadence,
            content_type=content_type,
            object_id=record.pk,
            started_at=timezone.now(),
            source="manual",
        )
        return cadence, enrollment

    def task_followup(self, cadence=None, **fields):
        values = {
            "cadence": cadence or self.cadence,
            "followup_number": 1,
            "followup_type": "task",
            "subject": "Follow up",
            "due_after_days": 1,
            "task_status": "not_started",
            "task_priority": "medium",
        }
        values.update(fields)
        return CadenceFollowUp.objects.create(**values)

    def call_followup(self, **fields):
        values = {
            "cadence": self.cadence,
            "followup_number": 1,
            "followup_type": "call",
            "purpose": "Call back",
            "call_start_after_days": 0,
        }
        values.update(fields)
        return CadenceFollowUp.objects.create(**values)

    def created(self, enrollment=None):
        return Activity.all_objects.get(
            additional_info__cadence_runtime__enrollment_id=(
                enrollment or self.enrollment
            ).pk
        )

    def test_fixed_owner_is_unchanged(self):
        self.task_followup(task_owner=self.fixed)
        services.create_first_followups(self.enrollment, self.record)
        task = self.created()
        self.assertEqual(task.owner, self.fixed)
        self.assertEqual(list(task.assigned_to.all()), [self.fixed])
        self.assertNotIn("owner_source", task.additional_info["cadence_runtime"])

    def test_task_goes_to_the_record_owner(self):
        self.task_followup(task_owner=self.fixed, task_owner_from_record=True)
        services.create_first_followups(self.enrollment, self.record)
        task = self.created()
        self.assertEqual(task.owner, self.record_owner)
        self.assertEqual(list(task.assigned_to.all()), [self.record_owner])
        runtime = task.additional_info["cadence_runtime"]
        self.assertEqual(runtime["owner_source"], "record")
        self.assertNotIn("record_owner_missing", runtime)

    def test_call_goes_to_the_record_owner(self):
        self.call_followup(call_owner_from_record=True)
        services.create_first_followups(self.enrollment, self.record)
        self.assertEqual(self.created().owner, self.record_owner)

    def test_record_without_owner_falls_back_to_the_fixed_owner(self):
        record = Company.objects.create(name="No owner fields")
        cadence, enrollment = self.enroll(record)
        self.task_followup(
            cadence=cadence, task_owner=self.fixed, task_owner_from_record=True
        )
        with self.assertLogs("horilla.contrib.cadences.services", "WARNING"):
            services.create_first_followups(enrollment, record)
        task = self.created(enrollment)
        self.assertEqual(task.owner, self.fixed)
        runtime = task.additional_info["cadence_runtime"]
        self.assertEqual(runtime["owner_source"], "fixed")
        self.assertTrue(runtime["record_owner_missing"])

    def test_record_without_owner_falls_back_to_the_cadence_creator(self):
        record = Company.objects.create(name="No owner fields")
        cadence, enrollment = self.enroll(record)
        self.task_followup(cadence=cadence, task_owner_from_record=True)
        with self.assertLogs("horilla.contrib.cadences.services", "WARNING"):
            services.create_first_followups(enrollment, record)
        task = self.created(enrollment)
        self.assertEqual(task.owner, self.creator)
        self.assertEqual(
            task.additional_info["cadence_runtime"]["owner_source"],
            "cadence_creator",
        )

    def test_record_owner_needs_no_extra_query(self):
        followup = self.task_followup(task_owner_from_record=True)
        with self.assertNumQueries(0):
            owner = services.resolve_followup_owner(followup, self.record, self.cadence)
        self.assertEqual(owner, (self.record_owner.pk, "record"))

    def test_owner_is_optional_only_with_record_owner(self):
        followup = CadenceFollowUp(
            cadence=self.cadence,
            followup_number=1,
            followup_type="task",
            subject="Follow up",
            due_after_days=1,
            task_status="not_started",
            task_priority="medium",
        )
        with self.assertRaises(ValidationError) as error:
            followup.clean()
        self.assertIn("task_owner", error.exception.message_dict)
        followup.task_owner_from_record = True
        followup.clean()

        call = CadenceFollowUp(
            cadence=self.cadence,
            followup_number=1,
            followup_type="call",
            purpose="Call back",
            call_start_after_days=0,
            call_owner_from_record=True,
        )
        call.clean()

    def test_form_shows_the_choice_next_to_the_owner(self):
        task_form = CadenceFollowUpForm(
            initial={"cadence": self.cadence.pk, "followup_type": "task"}
        )
        names = list(task_form.fields)
        self.assertEqual(
            names.index("task_owner_from_record"), names.index("task_owner") + 1
        )
        self.assertNotIn("call_owner_from_record", names)
        call_form = CadenceFollowUpForm(
            initial={"cadence": self.cadence.pk, "followup_type": "call"}
        )
        names = list(call_form.fields)
        self.assertEqual(
            names.index("call_owner_from_record"), names.index("call_owner") + 1
        )
        self.assertNotIn("task_owner_from_record", names)

    def test_editing_the_followup_reassigns_pending_tasks(self):
        followup = self.task_followup(task_owner=self.fixed)
        services.create_first_followups(self.enrollment, self.record)
        self.assertEqual(self.created().owner, self.fixed)

        followup.task_owner_from_record = True
        followup.save()
        task = self.created()
        self.assertEqual(task.owner, self.record_owner)
        self.assertEqual(list(task.assigned_to.all()), [self.record_owner])
        self.assertEqual(
            task.additional_info["cadence_runtime"]["owner_source"], "record"
        )

        followup.task_owner_from_record = False
        followup.save()
        task = self.created()
        self.assertEqual(task.owner, self.fixed)
        self.assertNotIn("owner_source", task.additional_info["cadence_runtime"])

    def test_sync_reads_the_records_once(self):
        other_owner = User.objects.create_user(
            username="other-owner", email="other@example.com", password="x"
        )
        other = ShortcutKey.objects.create(
            user=other_owner, page="/", key="j", command="alt"
        )
        other_enrollment = CadenceEnrollment.all_objects.create(
            cadence=self.cadence,
            content_type=self.enrollment.content_type,
            object_id=other.pk,
            started_at=timezone.now(),
            source="manual",
        )
        followup = self.task_followup(task_owner=self.fixed)
        services.create_first_followups(self.enrollment, self.record)
        services.create_first_followups(other_enrollment, other)

        followup = CadenceFollowUp.objects.get(pk=followup.pk)
        followup.task_owner_from_record = True
        activities = list(
            Activity.all_objects.filter(
                additional_info__cadence_runtime__followup_id=followup.pk
            )
        )
        with CaptureQueriesContext(connection) as queries:
            owners = signals._runtime_activity_owners(followup, activities)
        # One read of the ShortcutKey records for both activities.
        self.assertEqual(len(queries), 1, [q["sql"] for q in queries])
        self.assertEqual(
            sorted(owners.values()), sorted([self.record_owner.pk, other_owner.pk])
        )
        self.assertEqual(self.created(other_enrollment).owner, self.fixed)
        followup.save()
        self.assertEqual(self.created().owner, self.record_owner)
        self.assertEqual(self.created(other_enrollment).owner, other_owner)

    def test_many_to_many_owner_field_gives_its_first_user(self):
        # Activity.OWNER_FIELDS starts with "owner", then the "assigned_to" users.
        company = Company.objects.create(name="Activity Co")
        record = Activity.objects.create(
            subject="Shared", activity_type="task", status="scheduled", company=company
        )
        self.assertIsNone(services._record_owner_id(record))
        record.assigned_to.set([self.record_owner, self.fixed])
        self.assertEqual(
            services._record_owner_id(record),
            min(self.record_owner.pk, self.fixed.pk),
        )
        record.owner = self.creator
        self.assertEqual(services._record_owner_id(record), self.creator.pk)

    def test_no_owner_anywhere_creates_the_task_without_one(self):
        record = Company.objects.create(name="No owner fields")
        content_type = HorillaContentType.objects.get_for_model(Company)
        cadence = Cadence.objects.create(name="Nobody", module=content_type)
        enrollment = CadenceEnrollment.all_objects.create(
            cadence=cadence,
            content_type=content_type,
            object_id=record.pk,
            started_at=timezone.now(),
            source="manual",
        )
        self.task_followup(cadence=cadence, task_owner_from_record=True)
        with self.assertLogs("horilla.contrib.cadences.services", "WARNING"):
            services.create_first_followups(enrollment, record)
        task = self.created(enrollment)
        self.assertIsNone(task.owner)
        self.assertFalse(task.assigned_to.exists())
        runtime = task.additional_info["cadence_runtime"]
        self.assertEqual(runtime["owner_source"], "none")
        self.assertTrue(runtime["record_owner_missing"])

    def test_delayed_followup_goes_to_the_record_owner(self):
        followup = self.task_followup(
            task_owner=self.fixed,
            task_owner_from_record=True,
            do_this_unit="minute",
            do_this_value=5,
        )
        services.create_first_followups(self.enrollment, self.record)
        self.assertFalse(
            Activity.all_objects.filter(
                additional_info__cadence_runtime__followup_id=followup.pk
            ).exists()
        )
        scheduled = CadenceScheduledFollowUp.all_objects.get(
            enrollment=self.enrollment, followup=followup
        )
        services.run_scheduled_followup(scheduled.pk)
        self.assertEqual(self.created().owner, self.record_owner)

    def test_editing_a_call_followup_reassigns_pending_calls(self):
        followup = self.call_followup(call_owner=self.fixed)
        services.create_first_followups(self.enrollment, self.record)
        self.assertEqual(self.created().owner, self.fixed)
        followup.call_owner_from_record = True
        followup.save()
        call = self.created()
        self.assertEqual(call.owner, self.record_owner)
        self.assertEqual(
            call.additional_info["cadence_runtime"]["owner_source"], "record"
        )

    def test_editing_the_followup_leaves_completed_tasks_alone(self):
        followup = self.task_followup(task_owner=self.fixed)
        services.create_first_followups(self.enrollment, self.record)
        Activity.all_objects.filter(pk=self.created().pk).update(status="completed")
        followup.task_owner_from_record = True
        followup.save()
        task = self.created()
        self.assertEqual(task.owner, self.fixed)
        self.assertNotIn("owner_source", task.additional_info["cadence_runtime"])

    def test_editing_the_followup_keeps_the_owner_when_the_record_is_gone(self):
        followup = self.task_followup(task_owner=self.fixed)
        services.create_first_followups(self.enrollment, self.record)
        # The task now points at a record that no longer exists.
        Activity.all_objects.filter(pk=self.created().pk).update(object_id=999999)
        followup.task_owner_from_record = True
        followup.save()
        self.assertEqual(self.created().owner, self.fixed)

    def test_form_saves_record_owner_without_a_fixed_owner(self):
        form = CadenceFollowUpForm(
            data={
                "cadence": self.cadence.pk,
                "followup_number": 1,
                "followup_type": "task",
                "do_this_unit": "immediately",
                "subject": "Follow up",
                "due_after_days": 1,
                "task_status": "not_started",
                "task_priority": "medium",
                "task_owner_from_record": "on",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        followup = form.save()
        self.assertTrue(followup.task_owner_from_record)
        self.assertIsNone(followup.task_owner)

        form = CadenceFollowUpForm(
            data={
                "cadence": self.cadence.pk,
                "followup_number": 1,
                "followup_type": "task",
                "do_this_unit": "immediately",
                "subject": "Follow up again",
                "due_after_days": 1,
                "task_status": "not_started",
                "task_priority": "medium",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("task_owner", form.errors)


@isolate_apps("horilla.contrib.cadences")
class RecordOwnerFieldTests(SimpleTestCase):
    """_record_owner_id() reads OWNER_FIELDS in order and skips what is not a user."""

    def test_first_owner_field_that_holds_a_user(self):
        class Team(models.Model):
            class Meta:
                app_label = "cadences"

        class Deal(models.Model):
            OWNER_FIELDS = ["missing", "team", "reviewer", "owner"]
            team = models.ForeignKey(Team, null=True, on_delete=models.CASCADE)
            reviewer = models.ForeignKey(
                User, null=True, related_name="+", on_delete=models.CASCADE
            )
            owner = models.ForeignKey(
                User, null=True, related_name="+", on_delete=models.CASCADE
            )

            class Meta:
                app_label = "cadences"

        class Note(models.Model):
            class Meta:
                app_label = "cadences"

        self.assertIsNone(services._record_owner_id(Deal(team_id=5)))
        self.assertEqual(services._record_owner_id(Deal(owner_id=7)), 7)
        self.assertEqual(services._record_owner_id(Deal(reviewer_id=3, owner_id=7)), 3)
        self.assertIsNone(services._record_owner_id(Note()))


# ---------------------------------------------------------------------------
# Delivery channel follow-ups
# ---------------------------------------------------------------------------


def only_builtin_channels(test):
    """
    Hide the channels other installed apps register, for one test: only
    mail and notification stay, as on a Horilla without them.
    """
    builtin = {
        key: channel
        for key, channel in delivery_registry._channels.items()
        if key in ("mail", "notification")
    }
    patcher = mock.patch.dict(delivery_registry._channels, builtin, clear=True)
    patcher.start()
    test.addCleanup(patcher.stop)


class FakeSmsChannel(DeliveryChannel):
    """A phone channel, like an SMS app would register; records what it sends."""

    key = "fake_sms"
    label = "Send as Fake SMS"
    address_kind = ADDRESS_PHONE

    def __init__(self, available=True):
        self.available = available
        self.sent = []

    def is_available(self, company=None):
        return self.available

    def shows_notification_fields(self):
        return True

    def send(self, automation, instance, recipients, context, user):
        self.sent.append((automation, instance, list(recipients), context, user))


def register(test, channel):
    """Register ``channel`` for one test."""
    register_delivery_channel(channel)
    test.addCleanup(unregister_delivery_channel, channel.key)
    return channel


class FollowUpTypeTests(SimpleTestCase):
    """followup_types.py: task, call, email plus the registered channels."""

    def setUp(self):
        super().setUp()
        only_builtin_channels(self)

    def keys(self, company=None):
        return [key for key, _label in get_followup_type_choices(company)]

    def test_builtins_then_channels_without_mail(self):
        """The mail channel is the email follow-up; notification is a channel."""
        self.assertEqual(self.keys(), ["task", "call", "email", "notification"])
        register(self, FakeSmsChannel())
        self.assertEqual(
            self.keys(), ["task", "call", "email", "notification", "fake_sms"]
        )

    def test_unavailable_channel_is_not_offered(self):
        register(self, FakeSmsChannel(available=False))
        self.assertNotIn("fake_sms", self.keys())

    def test_channel_and_label(self):
        fake = register(self, FakeSmsChannel())
        self.assertIs(get_followup_channel("fake_sms"), fake)
        for key in ("task", "call", "email", "mail", "", None, "gone"):
            self.assertIsNone(get_followup_channel(key), key)
        self.assertEqual(str(get_followup_type_label("call")), "Call")
        self.assertEqual(get_followup_type_label("fake_sms"), "Send as Fake SMS")
        self.assertEqual(get_followup_type_label("gone"), "gone")
        self.assertEqual(
            CadenceFollowUp(followup_type="fake_sms").get_followup_type_display(),
            "Send as Fake SMS",
        )

    def test_followup_type_has_no_fixed_choices(self):
        field = CadenceFollowUp._meta.get_field("followup_type")
        self.assertFalse(field.choices)
        self.assertEqual(field.max_length, delivery_registry.KEY_MAX_LENGTH)


class ChannelFollowUpTestCase(TestCase):
    """A user record with a phone number, a cadence on users and the fake channel."""

    def setUp(self):
        super().setUp()
        only_builtin_channels(self)
        self.fake = register(self, FakeSmsChannel())
        self.company = Company.objects.create(name="Channel Co")
        self.owner = User.objects.create_user(
            username="cadence-owner",
            email="owner@example.com",
            password="x",
            company=self.company,
        )
        self.record = User.objects.create_user(
            username="cadence-record",
            email="record@example.com",
            password="x",
            company=self.company,
            contact_number="09121111111",
        )
        common = {
            "company": self.company,
            "created_by": self.owner,
            "updated_by": self.owner,
        }
        self.common = common
        self.template = NotificationTemplate.objects.create(
            title="Notice", message="<p>Hi {{ instance.username }}</p>", **common
        )
        self.content_type = HorillaContentType.objects.get_for_model(User)
        self.cadence = Cadence.objects.create(
            name="Channels", module=self.content_type, **common
        )
        self.enrollment = CadenceEnrollment.all_objects.create(
            cadence=self.cadence,
            content_type=self.content_type,
            object_id=self.record.pk,
            started_at=timezone.now(),
            source="manual",
            company=self.company,
        )

    def followup(self, followup_type="fake_sms", number=1, **fields):
        values = {
            "cadence": self.cadence,
            "followup_number": number,
            "followup_type": followup_type,
            "company": self.company,
        }
        if followup_type not in ("task", "call", "email"):
            values["channel_config"] = {
                "template_id": str(self.template.pk),
                "to": "instance.contact_number",
            }
        values.update(fields)
        return CadenceFollowUp.objects.create(**values)

    def run_row(self, followup):
        return CadenceScheduledFollowUp.all_objects.get(
            enrollment=self.enrollment, followup=followup
        )


class ChannelFollowUpModelTests(ChannelFollowUpTestCase):
    """CadenceFollowUp.clean() and the channel template."""

    def test_clean_accepts_builtins_and_registered_channels(self):
        CadenceFollowUp(
            cadence=self.cadence, followup_type="fake_sms", followup_number=1
        ).clean()
        for key in ("gone", "mail"):
            with self.assertRaises(ValidationError, msg=key):
                CadenceFollowUp(
                    cadence=self.cadence, followup_type=key, followup_number=1
                ).clean()

    def test_builtin_clears_the_channel_config(self):
        followup = CadenceFollowUp(
            cadence=self.cadence,
            followup_number=1,
            followup_type="call",
            purpose="Call",
            call_start_after_days=0,
            call_owner=self.owner,
            channel_config={"to": "instance.contact_number"},
        )
        followup.clean()
        self.assertEqual(followup.channel_config, {})

    def test_channel_template(self):
        self.assertEqual(self.followup().get_channel_template(), self.template)
        self.assertIsNone(
            self.followup(channel_config={"template_id": "x"}).get_channel_template()
        )


class ChannelFollowUpRunTests(ChannelFollowUpTestCase):
    """services: a channel follow-up is sent through the channel and recorded."""

    def test_sends_through_the_channel_and_records_the_run(self):
        followup = self.followup()
        created = services.create_first_followups(self.enrollment, self.record)
        self.assertEqual(len(created), 1)
        self.assertEqual(len(self.fake.sent), 1)
        message, instance, recipients, context, _user = self.fake.sent[0]
        self.assertEqual(instance, self.record)
        self.assertEqual(recipients, ["09121111111"])
        self.assertEqual(context["active_company"], self.company)
        # What channels read from an automation, plus the cadence objects.
        self.assertIsInstance(message, services.ChannelFollowUpMessage)
        self.assertEqual(message.title, "Channels")
        self.assertEqual(message.pk, followup.pk)
        self.assertEqual(message.notification_template, self.template)
        self.assertIsNone(message.mail_template)
        self.assertEqual(message.company, self.company)
        self.assertEqual(message.mail_to, "instance.contact_number")
        self.assertEqual(
            (message.cadence, message.followup, message.enrollment),
            (self.cadence, followup, self.enrollment),
        )
        run = self.run_row(followup)
        self.assertEqual(run.status, "completed")
        self.assertIn(followup.pk, services.existing_followup_ids(self.enrollment))

    def test_not_sent_twice(self):
        self.followup()
        for _run in range(2):
            services.create_first_followups(self.enrollment, self.record)
        self.assertEqual(len(self.fake.sent), 1)

    def test_sent_message_starts_the_next_followup(self):
        first = self.followup()
        self.followup(
            "call",
            number=2,
            previous_status="completed",
            branch_from=first,
            purpose="Call after SMS",
            call_start_after_days=0,
        )
        services.create_first_followups(self.enrollment, self.record)
        self.assertEqual(
            list(
                services.enrollment_activities(self.enrollment).values_list(
                    "subject", flat=True
                )
            ),
            ["Call after SMS"],
        )

    def test_failed_send_is_recorded_and_not_retried(self):
        followup = self.followup()
        self.record.contact_number = ""
        self.record.save()
        with self.assertLogs("horilla.contrib.cadences.services", "WARNING"):
            self.assertEqual(
                services.create_first_followups(self.enrollment, self.record), []
            )
        run = self.run_row(followup)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_message, "No recipient could be resolved.")
        services.create_first_followups(self.enrollment, self.record)
        self.assertEqual(self.fake.sent, [])
        services.refresh_status(self.enrollment)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, "failed")

    def test_missing_template_is_not_sent(self):
        followup = self.followup(channel_config={"template_id": "", "to": "self"})
        with self.assertLogs("horilla.contrib.cadences.services", "WARNING"):
            services.create_first_followups(self.enrollment, self.record)
        self.assertEqual(self.fake.sent, [])
        self.assertEqual(self.run_row(followup).status, "failed")

    def test_error_in_the_channel_is_recorded(self):
        self.fake.send = mock.Mock(side_effect=RuntimeError("gateway down"))
        followup = self.followup()
        with self.assertLogs("horilla.contrib.cadences.services", "ERROR"):
            services.create_first_followups(self.enrollment, self.record)
        run = self.run_row(followup)
        self.assertEqual((run.status, run.error_message), ("failed", "gateway down"))

    def test_sent_message_completes_the_enrollment(self):
        self.followup()
        services.create_first_followups(self.enrollment, self.record)
        services.refresh_status(self.enrollment)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, "completed")
        kind, status = services.latest_followup_summary(self.enrollment)
        self.assertEqual((kind, str(status)), ("fake_sms", "Sent"))

    def test_delayed_channel_followup(self):
        followup = self.followup(do_this_unit="minute", do_this_value=5)
        services.create_first_followups(self.enrollment, self.record)
        self.assertEqual(self.fake.sent, [])
        scheduled = self.run_row(followup)
        self.assertEqual(scheduled.status, "pending")
        services.run_scheduled_followup(scheduled.pk)
        scheduled.refresh_from_db()
        self.assertEqual(scheduled.status, "completed")
        self.assertEqual(len(self.fake.sent), 1)

    def test_delayed_failure_keeps_its_reason(self):
        """The delayed row gets the channel's reason, not the generic one."""
        followup = self.followup(do_this_unit="minute", do_this_value=5)
        services.create_first_followups(self.enrollment, self.record)
        self.record.contact_number = ""
        self.record.save()
        with self.assertLogs("horilla.contrib.cadences.services", "WARNING"):
            services.run_scheduled_followup(self.run_row(followup).pk)
        run = self.run_row(followup)
        self.assertEqual(
            (run.status, run.error_message),
            ("failed", "No recipient could be resolved."),
        )
        self.assertEqual(self.fake.sent, [])

    def test_channel_app_gone(self):
        followup = self.followup(do_this_unit="minute", do_this_value=5)
        services.create_first_followups(self.enrollment, self.record)
        unregister_delivery_channel("fake_sms")
        with self.assertLogs("horilla.contrib.cadences.services", "ERROR"):
            services.run_scheduled_followup(self.run_row(followup).pk)
        run = self.run_row(followup)
        self.assertEqual(run.status, "failed")
        self.assertIn("not a built-in or a registered delivery", run.error_message)

    def test_immediate_followup_with_channel_app_gone_is_not_retried(self):
        """It is recorded as failed once, and the next follow-up does not start."""
        followup = self.followup()
        self.followup(
            "call",
            number=2,
            previous_status="completed",
            branch_from=followup,
            purpose="Call after SMS",
            call_start_after_days=0,
        )
        unregister_delivery_channel("fake_sms")
        with self.assertLogs("horilla.contrib.cadences.services", "ERROR"):
            self.assertEqual(
                services.create_first_followups(self.enrollment, self.record), []
            )
        run = self.run_row(followup)
        self.assertEqual(run.status, "failed")
        self.assertEqual(
            run.error_message,
            "The follow-up type fake_sms is not a built-in or a registered "
            "delivery channel.",
        )
        self.assertIn(followup.pk, services.existing_followup_ids(self.enrollment))
        with self.assertNoLogs("horilla.contrib.cadences.services", "ERROR"):
            self.assertEqual(
                services.create_first_followups(self.enrollment, self.record), []
            )
        self.assertFalse(services.enrollment_activities(self.enrollment).exists())
        services.refresh_status(self.enrollment, allow_fail=False)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, "failed")

    @override_settings(
        CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    )
    def test_notification_channel_follow_up(self):
        """The real notification channel renders the template for the user."""
        self.followup(
            "notification",
            channel_config={
                "template_id": str(self.template.pk),
                "to": "record@example.com",
            },
        )
        services.create_first_followups(self.enrollment, self.record)
        notice = Notification.objects.get(user=self.record)
        self.assertIn("Hi cadence-record", notice.message)


class ChannelFollowUpFormTests(ChannelFollowUpTestCase):
    """The follow-up form offers the channels and stores channel_config."""

    def form(self, **data):
        values = {
            "cadence": self.cadence.pk,
            "followup_number": 1,
            "followup_type": "fake_sms",
            "do_this_unit": "immediately",
        }
        values.update(data)
        return CadenceFollowUpForm(data=values)

    def test_type_picker_lists_the_channels(self):
        form = CadenceFollowUpForm(initial={"cadence": self.cadence.pk})
        keys = [key for key, _label in form.fields["followup_type"].choices]
        self.assertEqual(keys, ["task", "call", "email", "notification", "fake_sms"])

    def test_channel_followup_is_saved_with_its_config(self):
        form = self.form(
            channel_template=self.template.pk, channel_to="instance.contact_number"
        )
        self.assertIn("channel_template", form.fields)
        to_keys = [key for key, _label in form.fields["channel_to"].choices]
        self.assertIn("instance.contact_number", to_keys)
        self.assertNotIn("self", to_keys)
        self.assertTrue(form.is_valid(), form.errors)
        followup = form.save()
        self.assertEqual(followup.followup_type, "fake_sms")
        self.assertEqual(
            followup.channel_config,
            {"template_id": str(self.template.pk), "to": "instance.contact_number"},
        )

    def test_template_and_recipient_are_required(self):
        form = self.form()
        self.assertFalse(form.is_valid())
        self.assertIn("channel_template", form.errors)
        self.assertIn("channel_to", form.errors)

    def test_unavailable_channel_is_refused(self):
        self.fake.available = False
        form = self.form(
            channel_template=self.template.pk, channel_to="instance.contact_number"
        )
        self.assertFalse(form.is_valid())
        self.assertIn("followup_type", form.errors)

    def test_after_a_message_only_sent_can_be_chosen(self):
        first = self.followup()
        form = CadenceFollowUpForm(
            initial={
                "cadence": self.cadence.pk,
                "followup_number": 2,
                "branch_from": first.pk,
                "followup_type": "task",
            }
        )
        self.assertEqual(
            str(form.fields["previous_status"].label), "When the previous message is"
        )
        self.assertEqual(
            [key for key, _label in form.fields["previous_status"].widget.choices],
            ["", "completed"],
        )


class ChannelFollowUpDetailTests(ChannelFollowUpTestCase):
    """The cadence board shows a channel follow-up's label and template."""

    def test_card_shows_the_channel(self):
        user_logged_in.disconnect(post_login)
        self.addCleanup(user_logged_in.connect, post_login)
        admin = User.objects.create_superuser(
            username="cadence-admin",
            email="admin@example.com",
            password="x",
            company=self.company,
        )
        self.client.force_login(admin)
        self.followup()
        response = self.client.get(
            reverse("cadences:cadence_detail_view", kwargs={"pk": self.cadence.pk}),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Send as Fake SMS")
        self.assertContains(response, "Notice")


class ConditionRecheckTests(TestCase):
    """
    A cadence on companies with the condition "name is Acme": a later follow-up
    of an automatic enrollment is created only while the record still meets it.
    """

    def setUp(self):
        self.record = Company.objects.create(name="Acme")
        self.content_type = HorillaContentType.objects.get_for_model(Company)
        self.cadence = Cadence.objects.create(
            name="Acme only", module=self.content_type
        )
        CadenceCondition.objects.create(
            cadence=self.cadence, field="name", operator="exact", value="Acme", order=1
        )
        self.first = CadenceFollowUp.objects.create(
            cadence=self.cadence,
            followup_number=1,
            followup_type="task",
            subject="first",
            due_after_days=1,
        )
        self.second = self.delayed("call back")
        self.enrollment = self.enroll("auto")

    def delayed(self, purpose, **fields):
        """A call two minutes after the first follow-up is completed."""
        values = {
            "cadence": self.cadence,
            "followup_number": 2,
            "followup_type": "call",
            "previous_status": "completed",
            "branch_from": self.first,
            "purpose": purpose,
            "call_start_after_days": 0,
            "do_this_unit": "minute",
            "do_this_value": 2,
        }
        values.update(fields)
        return CadenceFollowUp.objects.create(**values)

    def enroll(self, source):
        return CadenceEnrollment.all_objects.create(
            cadence=self.cadence,
            content_type=self.content_type,
            object_id=self.record.pk,
            started_at=timezone.now(),
            source=source,
        )

    def schedule(self, enrollment=None):
        """Schedule the delayed follow-ups and make them due."""
        enrollment = enrollment or self.enrollment
        services.create_next_followups(enrollment, self.record, self.first, "completed")
        CadenceScheduledFollowUp.all_objects.filter(enrollment=enrollment).update(
            scheduled_at=timezone.now() - timedelta(seconds=1)
        )
        return CadenceScheduledFollowUp.all_objects.get(
            enrollment=enrollment, followup=self.second
        )

    def run_due(self, scheduled):
        services.run_scheduled_followup(scheduled.pk)
        scheduled.refresh_from_db()
        return scheduled

    def rename(self, name):
        Company.objects.filter(pk=self.record.pk).update(name=name)

    def calls(self, enrollment=None):
        return Activity.all_objects.filter(
            activity_type="log_call",
            additional_info__cadence_runtime__enrollment_id=(
                enrollment or self.enrollment
            ).pk,
        )

    def assert_stopped(self, enrollment=None):
        enrollment = enrollment or self.enrollment
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, "unenrolled")
        self.assertIsNotNone(enrollment.ended_at)
        self.assertIsNone(enrollment.unenrolled_by)
        self.assertEqual(str(enrollment.cadence_status_col()), "Stopped")

    def test_created_while_the_record_meets_the_conditions(self):
        scheduled = self.run_due(self.schedule())
        self.assertEqual(scheduled.status, "completed")
        self.assertEqual(self.calls().count(), 1)

    def test_record_that_left_the_conditions_stops_the_run(self):
        # A first-stage call that waits longer, still pending when the run stops.
        other = CadenceFollowUp.objects.create(
            cadence=self.cadence,
            followup_number=1,
            followup_type="call",
            purpose="later call",
            call_start_after_days=0,
            do_this_unit="minute",
            do_this_value=30,
        )
        services.create_first_followups(self.enrollment, self.record)
        scheduled = self.schedule()
        self.rename("Other")
        scheduled = self.run_due(scheduled)
        self.assertEqual(scheduled.status, "cancelled")
        self.assertEqual(
            scheduled.error_message,
            "The record no longer meets the cadence conditions.",
        )
        self.assertIsNotNone(scheduled.executed_at)
        self.assertFalse(self.calls().exists())
        self.assert_stopped()
        # The other follow-up still waiting is cancelled with the same reason.
        other_row = CadenceScheduledFollowUp.all_objects.get(followup=other)
        self.assertEqual(other_row.status, "cancelled")
        self.assertEqual(other_row.error_message, scheduled.error_message)

    def test_back_in_the_conditions_by_the_time_it_is_due(self):
        scheduled = self.schedule()
        self.rename("Other")
        self.rename("Acme")
        self.assertEqual(self.run_due(scheduled).status, "completed")
        self.assertEqual(self.calls().count(), 1)

    def test_the_conditions_are_read_as_they_are_when_due(self):
        scheduled = self.schedule()
        self.cadence.conditions.update(value="Other")
        self.assertEqual(self.run_due(scheduled).status, "cancelled")
        self.assert_stopped()

    def test_a_cadence_without_conditions_never_stops(self):
        self.cadence.conditions.all().delete()
        scheduled = self.schedule()
        self.rename("Other")
        self.assertEqual(self.run_due(scheduled).status, "completed")

    def test_a_manual_enrollment_ignores_the_conditions(self):
        CadenceEnrollment.all_objects.filter(pk=self.enrollment.pk).update(
            status="completed"
        )
        manual = self.enroll("manual")
        scheduled = self.schedule(manual)
        self.rename("Other")
        self.assertEqual(self.run_due(scheduled).status, "completed")
        self.assertEqual(self.calls(manual).count(), 1)
        manual.refresh_from_db()
        self.assertEqual(manual.status, "active")

    def test_an_inactive_cadence_cancels_without_stopping_the_run(self):
        scheduled = self.schedule()
        Cadence.objects.filter(pk=self.cadence.pk).update(is_active=False)
        scheduled = self.run_due(scheduled)
        self.assertEqual(scheduled.status, "cancelled")
        self.assertEqual(scheduled.error_message, "The cadence is inactive.")
        self.assertFalse(self.calls().exists())
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, "active")

    def test_tasks_already_created_are_kept(self):
        services.create_first_followups(self.enrollment, self.record)
        scheduled = self.schedule()
        self.rename("Other")
        self.run_due(scheduled)
        task = Activity.all_objects.get(
            activity_type="task",
            additional_info__cadence_runtime__enrollment_id=self.enrollment.pk,
        )
        self.assertNotEqual(task.status, "cancelled")

    def test_completing_a_task_after_leaving_stops_instead_of_advancing(self):
        services.create_first_followups(self.enrollment, self.record)
        task = Activity.all_objects.get(
            activity_type="task",
            additional_info__cadence_runtime__enrollment_id=self.enrollment.pk,
        )
        self.rename("Other")
        task.status = "completed"
        task.save()
        self.assertFalse(
            CadenceScheduledFollowUp.all_objects.filter(
                enrollment=self.enrollment
            ).exists()
        )
        self.assert_stopped()

    def test_completing_a_task_while_matching_still_advances(self):
        services.create_first_followups(self.enrollment, self.record)
        task = Activity.all_objects.get(
            activity_type="task",
            additional_info__cadence_runtime__enrollment_id=self.enrollment.pk,
        )
        task.status = "completed"
        task.save()
        self.assertEqual(
            CadenceScheduledFollowUp.all_objects.get(enrollment=self.enrollment).status,
            "pending",
        )
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, "active")

    def test_a_stopped_run_is_not_restarted_by_a_later_match(self):
        scheduled = self.schedule()
        self.rename("Other")
        self.run_due(scheduled)
        self.rename("Acme")
        signals._trigger_initial_followups(Company.objects.get(pk=self.record.pk))
        self.assertEqual(
            CadenceEnrollment.all_objects.filter(cadence=self.cadence).count(), 1
        )
        self.assert_stopped()

    def test_stopping_a_finished_run_changes_nothing(self):
        CadenceEnrollment.all_objects.filter(pk=self.enrollment.pk).update(
            status="completed"
        )
        self.enrollment.refresh_from_db()
        services.stop_enrollment(self.enrollment, "reason")
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, "completed")
