"""
Tests for the workflow app: actions sent through delivery channels.

``action_type`` is one key: a built-in (update_field, assign_task, email,
notification) or the key of a channel registered in
``horilla.registry.delivery``. A fake phone channel stands in for one another
app would add (an SMS gateway). Channels other apps register are hidden, so
the tests see mail, notification and their own fakes only.
"""

import re
from unittest import mock

from django.contrib.auth.signals import user_logged_in
from django.test import SimpleTestCase, TestCase, override_settings
from login_history.models import post_login

import horilla.registry.delivery as delivery_registry
from horilla.auth.models import User
from horilla.contrib.activity.models import Activity
from horilla.contrib.core.models import Company, HorillaContentType
from horilla.contrib.mail.delivery import MailChannel
from horilla.contrib.mail.models import (
    HorillaMail,
    HorillaMailConfiguration,
    HorillaMailTemplate,
)
from horilla.contrib.notifications.delivery import NotificationChannel
from horilla.contrib.notifications.models import Notification, NotificationTemplate
from horilla.registry.delivery import (
    ADDRESS_PHONE,
    DeliveryChannel,
    register_delivery_channel,
    unregister_delivery_channel,
)
from horilla.urls import reverse

from . import methods
from .action_types import (
    BUILTIN_ACTION_TYPES,
    get_action_channel,
    get_action_type_choices,
    get_action_type_label,
    get_channel_template_kind,
)
from .forms import WorkflowActionForm, WorkflowTimeTriggerActionForm
from .methods import ChannelActionMessage, execute_action, execute_workflow_rule
from .models import (
    ScheduledWorkflowExecution,
    WorkflowAction,
    WorkflowCondition,
    WorkflowRule,
    WorkflowTimeTriggerAction,
)
from .tasks import (
    execute_workflow_time_trigger,
    process_scheduled_workflow_executions,
)

BUILTIN_KEYS = ["update_field", "assign_task", "email", "notification"]


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


class FakeMailerChannel(FakeSmsChannel):
    """An email channel that sends the mail template (a second mail provider)."""

    key = "fake_mailer"
    label = "Send as Fake Mailer"
    address_kind = "email"
    order = 110

    def shows_notification_fields(self):
        return False

    def shows_mail_fields(self):
        return True


class NotificationAgainChannel(NotificationChannel):
    """The real notification send() under another key."""

    key = "notification_again"
    label = "Send as Notification Again"


class MailAgainChannel(MailChannel):
    """The real mail send() under another key."""

    key = "mail_again"
    label = "Send as Mail Again"


def register(test, channel):
    """Register ``channel`` for one test."""
    register_delivery_channel(channel)
    test.addCleanup(unregister_delivery_channel, channel.key)
    return channel


class ActionTypeTests(SimpleTestCase):
    """action_types.py: the built-ins plus the registered channels."""

    def setUp(self):
        super().setUp()
        only_builtin_channels(self)

    def keys(self, company=None):
        return [key for key, _label in get_action_type_choices(company)]

    def test_without_other_channels_the_list_is_the_builtins(self):
        """mail and notification are the email and notification built-ins."""
        self.assertEqual(self.keys(), BUILTIN_KEYS)

    def test_registered_channels_follow_the_builtins_in_registry_order(self):
        """One entry per channel key, after the built-ins, by channel order."""
        register(self, FakeMailerChannel())
        register(self, FakeSmsChannel())
        self.assertEqual(self.keys(), BUILTIN_KEYS + ["fake_sms", "fake_mailer"])
        labels = dict(get_action_type_choices())
        self.assertEqual(labels["fake_sms"], "Send as Fake SMS")

    def test_unavailable_channel_is_not_offered(self):
        """A channel whose is_available() is false is left out."""
        register(self, FakeSmsChannel(available=False))
        self.assertEqual(self.keys(), BUILTIN_KEYS)

    def test_action_channel(self):
        """Built-ins and their channel keys are not channels; others are."""
        fake = register(self, FakeSmsChannel())
        self.assertIs(get_action_channel("fake_sms"), fake)
        for key in BUILTIN_KEYS + ["mail", "", None, "gone"]:
            self.assertIsNone(get_action_channel(key), key)

    def test_labels(self):
        """The built-in's label, the channel's, or the key when its app is gone."""
        register(self, FakeSmsChannel())
        self.assertEqual(str(get_action_type_label("email")), "Mail")
        self.assertEqual(get_action_type_label("fake_sms"), "Send as Fake SMS")
        self.assertEqual(get_action_type_label("gone"), "gone")
        self.assertEqual(
            str(WorkflowAction(action_type="assign_task").get_action_type_display()),
            "Assign Task",
        )
        self.assertEqual(
            WorkflowTimeTriggerAction(action_type="fake_sms").get_action_type_display(),
            "Send as Fake SMS",
        )

    def test_template_kind(self):
        """notification template for text channels, mail template for mail ones."""
        self.assertEqual(get_channel_template_kind(FakeSmsChannel()), "notification")
        self.assertEqual(get_channel_template_kind(FakeMailerChannel()), "mail")
        self.assertIsNone(get_channel_template_kind(None))

    def test_action_type_has_no_fixed_choices(self):
        """Both action models store any key up to a channel key's length."""
        for model in (WorkflowAction, WorkflowTimeTriggerAction):
            field = model._meta.get_field("action_type")
            self.assertFalse(field.choices, model.__name__)
            self.assertEqual(field.max_length, delivery_registry.KEY_MAX_LENGTH)
        self.assertEqual([key for key, _l in BUILTIN_ACTION_TYPES], BUILTIN_KEYS)


class WorkflowTestCase(TestCase):
    """A company, two users, templates, a mail server, a rule and the fake channel."""

    def setUp(self):
        super().setUp()
        only_builtin_channels(self)
        self.fake = register(self, FakeSmsChannel())
        self.company = Company.objects.create(name="Workflow Co")
        self.user = User.objects.create_user(
            username="workflow-user",
            email="user@example.com",
            password="x",
            company=self.company,
            contact_number="09121111111",
        )
        self.colleague = User.objects.create_user(
            username="workflow-colleague",
            email="colleague@example.com",
            password="x",
            company=self.company,
            contact_number="09122222222",
        )
        self.common = {
            "company": self.company,
            "created_by": self.user,
            "updated_by": self.user,
        }
        self.mail_template = HorillaMailTemplate.objects.create(
            title="Mail", subject="Subject", body="<p>Body</p>", **self.common
        )
        self.notification_template = NotificationTemplate.objects.create(
            title="Notice", message="<p>Notice for {{ instance.pk }}</p>", **self.common
        )
        self.mail_server = HorillaMailConfiguration.objects.create(
            type="mail", mail_channel="outgoing", host="localhost", **self.common
        )
        self.rule = WorkflowRule.objects.create(
            name="Welcome",
            model=HorillaContentType.objects.get_for_model(Activity),
            trigger_on_create=True,
            **self.common,
        )
        self.instance = Activity(pk=1)

    def action(self, action_type, config=None, model=WorkflowAction, **fields):
        """A saved action of ``action_type`` on the rule."""
        values = {
            "rule": self.rule,
            "action_type": action_type,
            "action_config": config or {},
            "order": model.all_objects.count() + 1,
            **self.common,
        }
        values.update(fields)
        return model.objects.create(**values)

    def sms_action(self, **config):
        """A fake_sms action to the triggering user, with the notification template."""
        values = {
            "template_id": str(self.notification_template.pk),
            "to": "self",
            "also_send_to": "",
        }
        values.update(config)
        return self.action("fake_sms", values)


class ExecuteActionTests(WorkflowTestCase):
    """execute_action() runs a built-in or calls the registered channel."""

    def test_builtins_run_their_executors(self):
        """Existing values keep their executors; no channel is called."""
        for key in BUILTIN_KEYS:
            action = self.action(key)
            executor = mock.Mock()
            with mock.patch.dict(methods.BUILTIN_EXECUTORS, {key: executor}):
                self.assertTrue(execute_action(action, self.instance, self.user))
            executor.assert_called_once_with(action, self.instance, self.user)
        self.assertEqual(self.fake.sent, [])

    def test_channel_action_sends_through_the_channel(self):
        """The channel resolves "to" for its address kind and adds also_send_to."""
        action = self.sms_action(also_send_to=f"{self.colleague.pk},{self.user.pk}")
        self.assertTrue(execute_action(action, self.instance, self.user))
        self.assertEqual(len(self.fake.sent), 1)
        message, instance, recipients, context, user = self.fake.sent[0]
        self.assertEqual(recipients, ["09121111111", "09122222222"])
        self.assertIs(instance, self.instance)
        self.assertEqual(user, self.user)
        self.assertEqual(context["instance"], self.instance)
        self.assertEqual(context["user"], self.user)
        self.assertEqual(context["active_company"], self.company)
        # What channels read from an automation.
        self.assertIsInstance(message, ChannelActionMessage)
        self.assertEqual(message.notification_template, self.notification_template)
        self.assertIsNone(message.mail_template)
        self.assertIsNone(message.mail_server)
        self.assertEqual(message.title, "Welcome")
        self.assertEqual(message.pk, action.pk)
        self.assertEqual(message.company, self.company)
        self.assertEqual(message.mail_to, "self")
        self.assertEqual(message.action, action)
        self.assertEqual(message.rule, self.rule)

    def test_mail_kind_channel_gets_the_mail_template(self):
        """template_id is a mail template for a channel that shows the mail fields."""
        mailer = register(self, FakeMailerChannel())
        action = self.action(
            "fake_mailer",
            {"template_id": str(self.mail_template.pk), "to": "self"},
        )
        execute_action(action, self.instance, self.user)
        message, _i, recipients, _c, _u = mailer.sent[0]
        self.assertEqual(recipients, ["user@example.com"])
        self.assertEqual(message.mail_template, self.mail_template)
        self.assertIsNone(message.notification_template)

    def test_missing_template_or_recipients_sends_nothing(self):
        """
        A channel that needs a template does not send without one (or with
        another company's), or to no one.
        """
        with self.assertLogs("horilla.contrib.workflow.methods", "WARNING") as logs:
            execute_action(self.sms_action(template_id=""), self.instance, self.user)
            execute_action(self.sms_action(template_id="999999"), self.instance, None)
            self.colleague.contact_number = ""
            self.colleague.save()
            execute_action(
                self.sms_action(to="instance.pk", also_send_to=str(self.colleague.pk)),
                self.instance,
                self.user,
            )
            other = Company.objects.create(name="Other Co")
            foreign = NotificationTemplate.objects.create(
                title="Other",
                message="x",
                company=other,
                created_by=self.user,
                updated_by=self.user,
            )
            execute_action(
                self.sms_action(template_id=str(foreign.pk)), self.instance, self.user
            )
        self.assertEqual(self.fake.sent, [])
        self.assertEqual(len(logs.output), 4)
        self.assertIn("no recipients", logs.output[2])
        self.assertIn("not found", logs.output[3])

    def test_unknown_action_type_is_logged_and_skipped(self):
        """A key whose app is gone returns False instead of raising."""
        action = self.sms_action()
        unregister_delivery_channel("fake_sms")
        with self.assertLogs("horilla.contrib.workflow.methods", "ERROR") as logs:
            self.assertFalse(execute_action(action, self.instance, self.user))
        self.assertIn("not a built-in or a registered delivery channel", logs.output[0])

    def test_rule_runs_one_action_per_channel_in_order(self):
        """Mail then SMS is two actions; they run in order, an error does not stop the next."""
        mailer = register(self, FakeMailerChannel())
        calls = []
        mailer.send = lambda *args: calls.append("fake_mailer")
        self.fake.send = lambda *args: calls.append("fake_sms")
        self.action(
            "fake_mailer",
            {"template_id": str(self.mail_template.pk), "to": "self"},
            order=1,
        )
        self.action("gone", order=2)
        self.sms_action(order=3)
        with mock.patch.object(methods, "_schedule_time_triggers"):
            with self.assertLogs("horilla.contrib.workflow.methods", "ERROR"):
                execute_workflow_rule(self.rule, self.instance, self.user, "on_create")
        self.assertEqual(calls, ["fake_mailer", "fake_sms"])

    def test_failing_channel_does_not_stop_the_next_action(self):
        """execute_workflow_rule() logs a channel error and runs the next action."""
        self.fake.send = mock.Mock(side_effect=RuntimeError("gateway down"))
        self.sms_action(order=1)
        update = mock.Mock()
        self.action("update_field", {"field": "subject", "value": "x"}, order=2)
        with mock.patch.dict(methods.BUILTIN_EXECUTORS, {"update_field": update}):
            with mock.patch.object(methods, "_schedule_time_triggers"):
                with self.assertLogs("horilla.contrib.workflow.methods", "ERROR"):
                    execute_workflow_rule(
                        self.rule, self.instance, self.user, "on_create"
                    )
        self.fake.send.assert_called_once()
        update.assert_called_once()


# Saving a notification pushes it over channels; keep that in memory here.
@override_settings(
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
)
class RealChannelTests(WorkflowTestCase):
    """The mail and notification channels' own send() work with a workflow action."""

    def test_notification_channel_send(self):
        """NotificationChannel.send renders the template for each user."""
        register(self, NotificationAgainChannel())
        action = self.action(
            "notification_again",
            {
                "template_id": str(self.notification_template.pk),
                "to": "self",
                "also_send_to": str(self.colleague.pk),
            },
        )
        execute_action(action, Activity(pk=42), self.user)
        notices = Notification.objects.filter(message__contains="Notice for 42")
        self.assertEqual(
            sorted(notices.values_list("user__username", flat=True)),
            ["workflow-colleague", "workflow-user"],
        )

    def test_mail_channel_send(self):
        """MailChannel.send creates the mail with the company's outgoing server."""
        register(self, MailAgainChannel())
        action = self.action(
            "mail_again",
            {"template_id": str(self.mail_template.pk), "to": "self"},
        )
        with mock.patch("horilla.contrib.mail.delivery.threading.Thread") as thread:
            execute_action(action, Activity(pk=7), self.user)
        mail = HorillaMail.objects.get(object_id=7)
        self.assertEqual(mail.to, "user@example.com")
        self.assertEqual(mail.subject, "Subject")
        self.assertEqual(mail.sender, self.mail_server)
        thread.return_value.start.assert_called_once_with()


class TimeTriggerTests(WorkflowTestCase):
    """execute_workflow_time_trigger() calls the same dispatcher."""

    def execution(self, action_type, config):
        trigger = self.action(
            action_type,
            config,
            model=WorkflowTimeTriggerAction,
            delay_value=1,
            delay_unit="days",
            trigger_date_field="rule_trigger_date",
        )
        activity = Activity.objects.create(
            subject="Call", activity_type="task", **self.common
        )
        return ScheduledWorkflowExecution.objects.create(
            time_trigger=trigger,
            object_id=activity.pk,
            scheduled_at=activity.created_at,
            **self.common,
        )

    def test_channel_time_trigger_sends_and_completes(self):
        execution = self.execution(
            "fake_sms",
            {"template_id": str(self.notification_template.pk), "to": "self"},
        )
        execute_workflow_time_trigger(execution.pk)
        execution.refresh_from_db()
        self.assertEqual(execution.status, ScheduledWorkflowExecution.STATUS_COMPLETED)
        self.assertEqual(len(self.fake.sent), 1)
        # The rule's user stands in for the one who triggered it.
        self.assertEqual(self.fake.sent[0][2], ["09121111111"])

    def test_unregistered_channel_fails_without_retry(self):
        execution = self.execution("gone", {})
        with self.assertLogs("horilla.contrib.workflow.methods", "ERROR"):
            execute_workflow_time_trigger(execution.pk)
        execution.refresh_from_db()
        self.assertEqual(execution.status, ScheduledWorkflowExecution.STATUS_FAILED)
        self.assertIn("'gone'", execution.error_message)


class TimeTriggerRecheckTests(WorkflowTestCase):
    """A due time trigger runs only while its rule still applies to the record."""

    def setUp(self):
        super().setUp()
        WorkflowCondition.objects.create(
            rule=self.rule,
            field="status",
            operator="exact",
            value="scheduled",
            **self.common,
        )
        self.trigger = self.action(
            "fake_sms",
            {"template_id": str(self.notification_template.pk), "to": "self"},
            model=WorkflowTimeTriggerAction,
            delay_value=1,
            delay_unit="days",
            trigger_date_field="rule_trigger_date",
        )
        self.activity = Activity.objects.create(
            subject="Call", activity_type="task", status="scheduled", **self.common
        )
        self.execution = ScheduledWorkflowExecution.objects.create(
            time_trigger=self.trigger,
            object_id=self.activity.pk,
            scheduled_at=self.activity.created_at,
            **self.common,
        )

    def run_execution(self):
        execute_workflow_time_trigger(self.execution.pk)
        self.execution.refresh_from_db()
        return self.execution

    def assert_skipped(self, reason):
        execution = self.run_execution()
        self.assertEqual(self.fake.sent, [])
        self.assertEqual(execution.status, ScheduledWorkflowExecution.STATUS_SKIPPED)
        self.assertEqual(execution.error_message, reason)
        self.assertIsNotNone(execution.executed_at)

    def test_runs_while_the_record_meets_the_criteria(self):
        execution = self.run_execution()
        self.assertEqual(execution.status, ScheduledWorkflowExecution.STATUS_COMPLETED)
        self.assertEqual(len(self.fake.sent), 1)

    def test_skipped_when_the_record_no_longer_meets_the_criteria(self):
        Activity.objects.filter(pk=self.activity.pk).update(status="completed")
        self.assert_skipped("The record no longer meets the workflow rule's criteria.")

    def test_skipped_when_the_rule_is_inactive(self):
        WorkflowRule.objects.filter(pk=self.rule.pk).update(is_active=False)
        self.assert_skipped("The workflow rule is inactive.")

    def test_skipped_when_the_time_trigger_is_inactive(self):
        WorkflowTimeTriggerAction.objects.filter(pk=self.trigger.pk).update(
            is_active=False
        )
        self.assert_skipped("The time trigger is inactive.")

    def test_a_skipped_execution_is_not_run_again(self):
        Activity.objects.filter(pk=self.activity.pk).update(status="completed")
        self.run_execution()
        Activity.objects.filter(pk=self.activity.pk).update(status="scheduled")
        execution = self.run_execution()
        self.assertEqual(self.fake.sent, [])
        self.assertEqual(execution.status, ScheduledWorkflowExecution.STATUS_SKIPPED)

    def test_deleted_record_still_fails(self):
        Activity.all_objects.filter(pk=self.activity.pk).delete()
        execution = self.run_execution()
        self.assertEqual(execution.status, ScheduledWorkflowExecution.STATUS_FAILED)
        self.assertEqual(self.fake.sent, [])

    def test_skip_check_reads_only_the_conditions(self):
        rule_activity = Activity.objects.get(pk=self.activity.pk)
        trigger = WorkflowTimeTriggerAction.objects.select_related("rule").get(
            pk=self.trigger.pk
        )
        # Only the rule's conditions are read.
        with self.assertNumQueries(2):
            self.assertEqual(
                methods.time_trigger_skip_reason(trigger, rule_activity), ""
            )

    def test_runs_when_the_record_is_back_in_the_criteria_when_due(self):
        Activity.objects.filter(pk=self.activity.pk).update(status="completed")
        Activity.objects.filter(pk=self.activity.pk).update(status="scheduled")
        execution = self.run_execution()
        self.assertEqual(execution.status, ScheduledWorkflowExecution.STATUS_COMPLETED)
        self.assertEqual(len(self.fake.sent), 1)

    def test_a_rule_without_criteria_still_runs(self):
        self.rule.conditions.all().delete()
        Activity.objects.filter(pk=self.activity.pk).update(status="completed")
        execution = self.run_execution()
        self.assertEqual(execution.status, ScheduledWorkflowExecution.STATUS_COMPLETED)
        self.assertEqual(len(self.fake.sent), 1)

    def test_the_criteria_are_read_as_they_are_when_due(self):
        self.rule.conditions.update(value="completed")
        self.assert_skipped("The record no longer meets the workflow rule's criteria.")

    def test_the_scheduler_queues_only_pending_executions(self):
        Activity.objects.filter(pk=self.activity.pk).update(status="completed")
        self.run_execution()
        pending = ScheduledWorkflowExecution.objects.create(
            time_trigger=self.trigger,
            object_id=self.activity.pk,
            scheduled_at=self.activity.created_at,
            **self.common,
        )
        with mock.patch.object(execute_workflow_time_trigger, "delay") as delay:
            process_scheduled_workflow_executions()
        delay.assert_called_once_with(pending.pk)


class FormTests(WorkflowTestCase):
    """The action forms check action_type against the registry."""

    def form(self, action_type, form_class=WorkflowActionForm, **data):
        values = {"rule": self.rule.pk, "action_type": action_type, "order": 1}
        if form_class is WorkflowTimeTriggerActionForm:
            values.update(
                {
                    "delay_value": 1,
                    "delay_unit": "days",
                    "delay_direction": "after",
                    "trigger_date_field": "rule_trigger_date",
                }
            )
        values.update(data)
        return form_class(data=values)

    def test_channel_action_stores_template_to_and_also_send_to(self):
        for form_class in (WorkflowActionForm, WorkflowTimeTriggerActionForm):
            form = self.form(
                "fake_sms",
                form_class,
                channel_template_id=str(self.notification_template.pk),
                channel_to="self,instance.contact_number",
                channel_also_send_to=str(self.colleague.pk),
                # Another action type's leftover fields are not stored.
                email_to="self",
            )
            self.assertTrue(form.is_valid(), form.errors)
            action = form.save()
            self.assertEqual(action.action_type, "fake_sms")
            self.assertEqual(
                action.action_config,
                {
                    "template_id": str(self.notification_template.pk),
                    "to": "self,instance.contact_number",
                    "also_send_to": str(self.colleague.pk),
                },
            )

    def test_channel_action_needs_its_template(self):
        form = self.form("fake_sms", channel_to="self")
        self.assertFalse(form.is_valid())
        self.assertIn("Select a template.", form.non_field_errors())

    def test_unknown_or_unavailable_action_type_is_refused(self):
        for key in ("gone", "mail"):
            form = self.form(key, channel_template_id="1")
            self.assertFalse(form.is_valid(), key)
            self.assertIn("is not an available action", str(form.non_field_errors()))
        self.fake.available = False
        form = self.form("fake_sms", channel_template_id="1")
        self.assertFalse(form.is_valid())

    def test_builtins_keep_their_config(self):
        form = self.form(
            "notification",
            notification_template_id=str(self.notification_template.pk),
            notification_to="self",
            notification_custom_message="Hi",
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.save().action_config,
            {
                "template_id": str(self.notification_template.pk),
                "to": "self",
                "also_notify_to": "",
                "custom_message": "Hi",
            },
        )

    def test_edit_form_seeds_the_channel_fields(self):
        action = self.sms_action(also_send_to=str(self.colleague.pk))
        form = WorkflowActionForm(instance=action)
        self.assertEqual(
            form.fields["channel_template_id"].initial,
            str(self.notification_template.pk),
        )
        self.assertEqual(form.fields["channel_to"].initial, "self")
        self.assertEqual(
            form.fields["channel_also_send_to"].initial, str(self.colleague.pk)
        )


class ViewTests(WorkflowTestCase):
    """The action modals list the registered channels and their fields."""

    def setUp(self):
        super().setUp()
        user_logged_in.disconnect(post_login)
        self.addCleanup(user_logged_in.connect, post_login)
        self.admin = User.objects.create_superuser(
            username="workflow-admin",
            email="admin@example.com",
            password="x",
            company=self.company,
        )
        self.client.force_login(self.admin)

    def get(self, url, **params):
        return self.client.get(url, params, HTTP_HX_REQUEST="true")

    def type_options(self, response, select_id):
        select = re.search(
            rf'<select[^>]*id="{select_id}".*?</select>',
            response.content.decode(),
            re.S,
        ).group(0)
        return re.findall(r'<option value="([^"]*)"', select)

    def test_add_modals_list_the_builtins_and_the_channels(self):
        for url, select_id in (
            (
                reverse("workflow:workflow_action_add_view", args=[self.rule.pk]),
                "wf-action-type-select",
            ),
            (
                reverse("workflow:workflow_time_trigger_add_view", args=[self.rule.pk]),
                "wf-tt-action-type-select",
            ),
        ):
            response = self.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                self.type_options(response, select_id),
                [""] + BUILTIN_KEYS + ["fake_sms"],
            )
            self.assertContains(response, "Send as Fake SMS")

    def test_fields_fragment_for_a_channel(self):
        response = self.get(
            reverse("workflow:workflow_action_fields_view"),
            action_type="fake_sms",
            rule_pk=self.rule.pk,
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('name="channel_template_id"', content)
        self.assertIn(f'value="{self.notification_template.pk}"', content)
        self.assertIn('name="channel_to"', content)
        self.assertIn('name="channel_also_send_to"', content)
        # The fake channel's own recipient choices (phone address kind).
        self.assertIn('value="self"', content)
        self.assertIn('value="instance.owner"', content)

    def test_fields_fragment_refuses_what_is_not_offered(self):
        for key in ("gone", "mail"):
            response = self.get(
                reverse("workflow:workflow_action_fields_view"),
                action_type=key,
                rule_pk=self.rule.pk,
            )
            self.assertEqual(response.content, b"", key)

    def test_edit_modal_selects_the_channel_and_fills_its_fields(self):
        action = self.sms_action(to="self")
        response = self.get(
            reverse("workflow:workflow_action_edit_view", args=[action.pk])
        )
        self.assertRegex(response.content.decode(), r'value="fake_sms"\s+selected')
        self.assertRegex(
            response.content.decode(), r'id="wf-channel-to-val"\s+value="self"'
        )

    def test_edit_modal_keeps_a_type_that_is_no_longer_offered(self):
        action = self.sms_action()
        self.fake.available = False
        response = self.get(
            reverse("workflow:workflow_action_edit_view", args=[action.pk])
        )
        self.assertIn("fake_sms", self.type_options(response, "wf-action-type-select"))

    def test_saving_a_channel_action(self):
        response = self.client.post(
            reverse("workflow:workflow_action_add_view", args=[self.rule.pk]),
            {
                "rule": self.rule.pk,
                "order": 1,
                "action_type": "fake_sms",
                "channel_template_id": self.notification_template.pk,
                "channel_to": "self",
                "channel_also_send_to": "",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        action = WorkflowAction.all_objects.get(rule=self.rule)
        self.assertEqual(action.action_type, "fake_sms")
        self.assertEqual(action.action_config["to"], "self")

    def test_invalid_post_shows_the_error_and_keeps_the_fields(self):
        response = self.client.post(
            reverse("workflow:workflow_action_add_view", args=[self.rule.pk]),
            {
                "rule": self.rule.pk,
                "order": 1,
                "action_type": "fake_sms",
                "channel_to": "self",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, "Select a template.")
        self.assertRegex(
            response.content.decode(), r'id="wf-channel-to-val"\s+value="self"'
        )
        self.assertFalse(WorkflowAction.all_objects.filter(rule=self.rule).exists())

    def test_time_trigger_history_shows_a_skipped_execution_and_why(self):
        trigger = self.action(
            "fake_sms",
            model=WorkflowTimeTriggerAction,
            delay_value=1,
            delay_unit="days",
            trigger_date_field="rule_trigger_date",
        )
        ScheduledWorkflowExecution.objects.create(
            time_trigger=trigger,
            object_id=1,
            scheduled_at=trigger.created_at,
            status=ScheduledWorkflowExecution.STATUS_SKIPPED,
            error_message="The time trigger is inactive.",
            **self.common,
        )
        response = self.get(
            reverse(
                "workflow:workflow_time_trigger_history_view",
                kwargs={"rule_pk": self.rule.pk},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Skipped")
        self.assertContains(response, "The time trigger is inactive.")
