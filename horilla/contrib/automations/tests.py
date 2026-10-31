"""
Tests for the automations app: delivery channels.

Mail and notification are registered channels (``horilla.registry.delivery``)
and a fake phone channel stands in for one another app would add. An
automation stores the selected channel keys comma-separated, in registry
order.
"""

import ast
import importlib
import re
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.signals import user_logged_in
from django.test import SimpleTestCase, TestCase, override_settings
from login_history.models import post_login

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
from horilla.core.exceptions import ValidationError
from horilla.registry.delivery import (
    ADDRESS_PHONE,
    DeliveryChannel,
    get_delivery_channel,
    get_delivery_channels,
    register_delivery_channel,
    unregister_delivery_channel,
)
from horilla.urls import reverse

from .forms import DeliveryChannelsField
from .methods import execute_automation
from .models import (
    HorillaAutomation,
    normalize_delivery_channels,
    split_delivery_channels,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


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
        self.sent.append((automation, instance, list(recipients), user))


def register_fake(test, channel=None):
    """Register a fake channel for one test."""
    channel = channel or FakeSmsChannel()
    register_delivery_channel(channel)
    test.addCleanup(unregister_delivery_channel, channel.key)
    return channel


def in_registry_order(*keys):
    """``keys`` as the stored string: comma-separated in registry order."""
    return ",".join(
        channel.key for channel in get_delivery_channels() if channel.key in keys
    )


class RegistryTests(SimpleTestCase):
    """horilla.registry.delivery."""

    def test_mail_and_notification_are_registered(self):
        """The built-in channels register themselves; "both" is not a channel."""
        self.assertIsInstance(get_delivery_channel("mail"), MailChannel)
        self.assertIsInstance(get_delivery_channel("notification"), NotificationChannel)
        self.assertIsNone(get_delivery_channel("both"))
        self.assertTrue(get_delivery_channel("mail").shows_mail_fields())
        self.assertTrue(
            get_delivery_channel("notification").shows_notification_fields()
        )

    def test_registering_the_same_key_twice_raises(self):
        """A second registration of a key fails instead of replacing the first."""
        register_fake(self)
        with self.assertRaisesMessage(ValueError, "already registered"):
            register_delivery_channel(FakeSmsChannel())

    def test_reserved_and_invalid_keys_are_refused(self):
        """Reserved keys, commas, spaces, empty and long keys are refused."""
        for key in ("both", "mail", "notification"):
            channel = FakeSmsChannel()
            channel.key = key
            with self.subTest(key=key):
                with self.assertRaisesMessage(ValueError, "reserved"):
                    register_delivery_channel(channel)
        for key in ("mail,sms", "sms backup", " sms"):
            channel = FakeSmsChannel()
            channel.key = key
            with self.subTest(key=key):
                with self.assertRaisesMessage(ValueError, "comma or a space"):
                    register_delivery_channel(channel)
        for key in ("", "x" * 51):
            channel = FakeSmsChannel()
            channel.key = key
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    register_delivery_channel(channel)
        with self.assertRaises(TypeError):
            register_delivery_channel(object())

    def test_channels_are_listed_by_availability(self):
        """get_delivery_channels() leaves out unavailable channels and returns a copy."""
        register_fake(self, FakeSmsChannel(available=False))
        keys = [channel.key for channel in get_delivery_channels()]
        self.assertIn("mail", keys)
        self.assertNotIn("fake_sms", keys)
        get_delivery_channels().clear()
        self.assertIsNotNone(get_delivery_channel("mail"))

    def test_registry_and_channels_do_not_import_the_engines(self):
        """The registry imports no contrib app; mail and notifications not Automations."""
        files = {
            "horilla/registry/delivery.py": ("horilla.contrib",),
            "horilla/contrib/mail/delivery.py": (
                "horilla.contrib.automations",
                "horilla.contrib.notifications",
            ),
            "horilla/contrib/notifications/delivery.py": (
                "horilla.contrib.automations",
                "horilla.contrib.mail",
            ),
        }
        for path, forbidden in files.items():
            tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                elif isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                else:
                    continue
                for name in names:
                    with self.subTest(path=path, name=name):
                        self.assertFalse(name.startswith(forbidden))


class StoredValueTests(SimpleTestCase):
    """The comma-separated delivery_channel value."""

    def test_split_reads_tokens_not_substrings(self):
        """Tokens are stripped and kept once; "both" is mail and notification."""
        self.assertEqual(split_delivery_channels(" mail , ,sms,mail"), ["mail", "sms"])
        self.assertEqual(split_delivery_channels("both"), ["mail", "notification"])
        self.assertEqual(split_delivery_channels("sms_backup"), ["sms_backup"])
        self.assertNotIn("sms", split_delivery_channels("sms_backup"))
        self.assertEqual(split_delivery_channels(""), [])
        self.assertEqual(split_delivery_channels(None), [])

    def test_normalize_orders_by_the_registry_and_reports_unknown_keys(self):
        """Stored in registry order; unregistered keys come back separately."""
        self.assertEqual(
            normalize_delivery_channels("notification,mail"),
            (in_registry_order("mail", "notification"), []),
        )
        self.assertEqual(
            normalize_delivery_channels(["both"]),
            (in_registry_order("mail", "notification"), []),
        )
        self.assertEqual(
            normalize_delivery_channels("mail,pigeon"), ("mail", ["pigeon"])
        )

    def test_form_field_shows_and_cleans_the_stored_value(self):
        """The multi-select shows a stored string as keys and cleans back to it."""
        register_fake(self)
        field = DeliveryChannelsField(required=True)
        self.assertEqual(
            [key for key, _label in field.choices],
            [channel.key for channel in get_delivery_channels()],
        )
        self.assertNotIn("both", dict(field.choices))
        self.assertEqual(field.prepare_value("mail,fake_sms"), ["mail", "fake_sms"])
        self.assertEqual(
            field.clean(["fake_sms", "notification", "mail"]),
            in_registry_order("mail", "notification", "fake_sms"),
        )
        self.assertFalse(
            field.has_changed("mail,notification", ["mail", "notification"])
        )
        with self.assertRaises(ValidationError):
            field.clean([])
        with self.assertRaises(ValidationError):
            field.clean(["both"])


class AutomationTestCase(TestCase):
    """A company, a user, templates and a mail server, and the fake channel."""

    def setUp(self):
        super().setUp()
        self.fake = register_fake(self)
        self.company = Company.objects.create(name="Delivery Co")
        self.user = User.objects.create_user(
            username="delivery-user",
            email="user@example.com",
            password="x",
            company=self.company,
            contact_number="09121111111",
        )
        self.colleague = User.objects.create_user(
            username="delivery-colleague",
            email="colleague@example.com",
            password="x",
            company=self.company,
            contact_number="09122222222",
        )
        common = {
            "company": self.company,
            "created_by": self.user,
            "updated_by": self.user,
        }
        self.mail_template = HorillaMailTemplate.objects.create(
            title="Mail", subject="Subject", body="<p>Body</p>", **common
        )
        self.notification_template = NotificationTemplate.objects.create(
            title="Notice", message="<p>Notice for {{ instance.pk }}</p>", **common
        )
        self.mail_server = HorillaMailConfiguration.objects.create(
            type="mail", mail_channel="outgoing", host="localhost", **common
        )
        self.model = HorillaContentType.objects.get_for_model(Activity)

    def automation(self, delivery_channel, save=True, **fields):
        """An automation sending through ``delivery_channel`` (comma-separated keys)."""
        values = {
            "title": f"Automation {HorillaAutomation.objects.count() + 1}",
            "model": self.model,
            "mail_to": "self",
            "trigger": "on_create",
            "delivery_channel": delivery_channel,
            "mail_template": self.mail_template,
            "notification_template": self.notification_template,
            "mail_server": self.mail_server,
            "company": self.company,
            "created_by": self.user,
            "updated_by": self.user,
        }
        values.update(fields)
        automation = HorillaAutomation(**values)
        if save:
            automation.save()
        return automation

    def stored_as(self, automation, value):
        """Write ``value`` straight to the row, as an old row or another order would be."""
        HorillaAutomation.all_objects.filter(pk=automation.pk).update(
            delivery_channel=value
        )
        automation.refresh_from_db()
        return automation


class ModelTests(AutomationTestCase):
    """HorillaAutomation.delivery_channel: comma-separated keys, checked in clean()."""

    def errors(self, automation):
        """The fields full_clean() complains about."""
        try:
            automation.full_clean(exclude=["created_by", "updated_by"])
        except ValidationError as e:
            return set(e.message_dict)
        return set()

    def test_mail_notification_and_both_keep_their_rules(self):
        """mail, notification and mail,notification validate like mail, notification, both."""
        for channel in ("mail", "notification", "mail,notification"):
            with self.subTest(channel=channel):
                self.assertEqual(
                    self.errors(self.automation(channel, save=False)), set()
                )
        cases = [
            ("mail", {"mail_template": None}, {"mail_template"}),
            ("mail", {"mail_server": None}, {"mail_server"}),
            (
                "notification",
                {"notification_template": None},
                {"notification_template"},
            ),
            ("mail,notification", {"mail_template": None}, {"mail_template"}),
            (
                "mail,notification",
                {"notification_template": None},
                {"notification_template"},
            ),
            ("mail,notification", {"mail_server": None}, {"mail_server"}),
        ]
        for channel, fields, expected in cases:
            with self.subTest(channel=channel, fields=fields):
                automation = self.automation(channel, save=False, **fields)
                self.assertEqual(self.errors(automation), expected)

    def test_old_both_is_rewritten(self):
        """A stored "both" is cleaned to mail and notification, in registry order."""
        automation = self.automation("both", save=False)
        self.assertEqual(self.errors(automation), set())
        self.assertEqual(
            automation.delivery_channel, in_registry_order("mail", "notification")
        )

    def test_keys_are_stored_in_registry_order(self):
        """The selection order does not matter; the registry order is stored."""
        automation = self.automation("fake_sms, notification ,mail")
        self.assertEqual(
            automation.delivery_channel,
            in_registry_order("mail", "notification", "fake_sms"),
        )

    def test_unknown_or_empty_values_are_refused(self):
        """An unknown token or no channel at all fails on delivery_channel."""
        for value in ("pigeon", "mail,pigeon", "", " , "):
            with self.subTest(value=value):
                automation = self.automation(value, save=False)
                self.assertEqual(self.errors(automation), {"delivery_channel"})

    def test_registered_channel_needs_only_the_fields_it_shows(self):
        """The fake key needs its notification template; mail,fake also the mail ones."""
        automation = self.automation(
            "fake_sms", save=False, mail_template=None, mail_server=None
        )
        self.assertEqual(self.errors(automation), set())
        automation.notification_template = None
        self.assertEqual(self.errors(automation), {"notification_template"})

        for fields, expected in (
            ({"mail_template": None}, {"mail_template"}),
            ({"mail_server": None}, {"mail_server"}),
        ):
            with self.subTest(fields=fields):
                automation = self.automation("mail,fake_sms", save=False, **fields)
                self.assertEqual(self.errors(automation), expected)

    def test_unavailable_channel_is_refused(self):
        """A channel not available to the company cannot be chosen."""
        self.fake.available = False
        automation = self.automation("fake_sms", save=False)
        self.assertEqual(self.errors(automation), {"delivery_channel"})

    def test_display_and_template(self):
        """Labels are joined; a removed channel shows its key; templates per selection."""
        mail = self.automation("mail")
        self.assertEqual(mail.get_delivery_channel_display(), "Send as Mail")
        self.assertEqual(mail.get_template(), self.mail_template)
        notification = self.automation("notification")
        self.assertEqual(notification.get_template(), self.notification_template)

        both = self.stored_as(self.automation("mail"), "mail,notification")
        self.assertEqual(
            both.get_delivery_channel_display(), "Send as Mail, Send as Notification"
        )
        self.assertIn("Mail Template", str(both.get_template()))
        self.assertIn("Notification Template", str(both.get_template()))

        fake = self.automation("fake_sms")
        self.assertEqual(fake.get_template(), self.notification_template)
        mixed = self.stored_as(self.automation("mail"), "mail,fake_sms")
        self.assertEqual(
            mixed.get_delivery_channel_display(), "Send as Mail, Send as Fake SMS"
        )
        self.assertIn("Mail Template", str(mixed.get_template()))

        unregister_delivery_channel("fake_sms")
        fake.refresh_from_db()
        mixed.refresh_from_db()
        self.assertEqual(fake.get_delivery_channel_display(), "fake_sms")
        self.assertIsNone(fake.get_template())
        self.assertEqual(mixed.get_delivery_channel_display(), "Send as Mail, fake_sms")

    def test_migration_rewrites_both(self):
        """0006 turns stored "both" into "mail,notification" and back."""
        migration = importlib.import_module(
            "horilla.contrib.automations.migrations.0006_delivery_channels"
        )
        old = self.stored_as(self.automation("mail"), "both")
        kept = self.automation("notification")
        historical = SimpleNamespace(
            get_model=lambda *args: SimpleNamespace(
                objects=HorillaAutomation.all_objects
            )
        )
        migration.both_to_mail_and_notification(historical, None)
        old.refresh_from_db()
        kept.refresh_from_db()
        self.assertEqual(old.delivery_channel, "mail,notification")
        self.assertEqual(kept.delivery_channel, "notification")
        migration.mail_and_notification_to_both(historical, None)
        old.refresh_from_db()
        self.assertEqual(old.delivery_channel, "both")


class DefaultRecipientTests(AutomationTestCase):
    """DeliveryChannel's address_kind defaults, as a plugin channel gets them."""

    def test_recipient_choices_follow_the_address_kind(self):
        """Self, user foreign keys, and the fields of the channel's address kind."""
        sms = dict(self.fake.get_recipient_choices(User))
        mail = dict(get_delivery_channel("mail").get_recipient_choices(User))
        self.assertIn("self", sms)
        self.assertIn("instance.contact_number", sms)
        self.assertNotIn("instance.email", sms)
        self.assertIn("instance.email", mail)
        self.assertNotIn("instance.contact_number", mail)
        activity = dict(self.fake.get_recipient_choices(Activity))
        self.assertIn("instance.created_by", activity)
        self.assertEqual(self.fake.get_recipient_choices(None)[0][0], "self")

    def test_resolve_recipients_and_also_sent_to(self):
        """self, field paths and literal values become numbers, each once."""
        numbers = self.fake.resolve_recipients(
            "self, instance.contact_number, 09123333333, instance.missing, self",
            self.colleague,
            self.user,
        )
        self.assertEqual(numbers, ["09121111111", "09122222222", "09123333333"])
        self.assertEqual(
            self.fake.add_also_sent_to(["09121111111"], [self.user, self.colleague]),
            ["09121111111", "09122222222"],
        )

    def test_one_mail_to_serves_every_channel(self):
        """Each channel takes from the shared mail_to what it can use."""
        spec = "self, someone@example.com, 09124444444"
        self.assertEqual(
            get_delivery_channel("mail").resolve_recipients(spec, None, self.user),
            ["user@example.com", "someone@example.com"],
        )
        self.assertEqual(
            self.fake.resolve_recipients("self, 09124444444", None, self.user),
            ["09121111111", "09124444444"],
        )


class ExecuteAutomationTests(AutomationTestCase):
    """execute_automation() sends through each selected channel."""

    def setUp(self):
        super().setUp()
        self.instance = Activity(pk=1)
        self.calls = mock.Mock()
        for name, cls in (("mail", MailChannel), ("notification", NotificationChannel)):
            patcher = mock.patch.object(cls, "send", autospec=True)
            self.calls.attach_mock(patcher.start(), name)
            self.addCleanup(patcher.stop)

    def run_automation(self, automation, user=None):
        execute_automation(automation, self.instance, user or self.user, "on_create")

    def sent(self):
        """``[(channel, recipients), ...]`` in the order the sends happened."""
        return [(name, args[3]) for name, args, _kwargs in self.calls.method_calls]

    def test_each_channel_sends_only_its_own(self):
        """mail sends mail only, notification a notification only."""
        self.run_automation(self.automation("mail"))
        self.assertEqual(self.sent(), [("mail", ["user@example.com"])])
        self.calls.method_calls.clear()
        self.run_automation(self.automation("notification"))
        self.assertEqual(self.sent(), [("notification", [self.user])])

    def test_mail_and_notification_send_in_stored_order(self):
        """mail,notification sends mail then notification, as "both" did."""
        automation = self.stored_as(self.automation("mail"), "mail,notification")
        automation.also_sent_to.add(self.colleague)
        self.run_automation(automation)
        self.assertEqual(
            self.sent(),
            [
                ("mail", ["user@example.com", "colleague@example.com"]),
                ("notification", [self.user, self.colleague]),
            ],
        )

    def test_old_both_still_sends_mail_then_notification(self):
        """A row still holding "both" runs as mail, then notification."""
        automation = self.stored_as(self.automation("mail"), "both")
        self.run_automation(automation)
        self.assertEqual([name for name, _r in self.sent()], ["mail", "notification"])

    def test_empty_mail_list_does_not_skip_the_other_channels(self):
        """A user without an email still gets the notification and the SMS."""
        self.user.email = ""
        self.user.save()
        automation = self.stored_as(
            self.automation("mail"), "mail,notification,fake_sms"
        )
        self.run_automation(automation)
        self.assertEqual(self.sent(), [("notification", [self.user])])
        self.assertEqual(self.fake.sent[0][2], ["09121111111"])

    def test_failing_channel_does_not_stop_the_next(self):
        """An error in mail is logged; the notification still goes out."""
        self.calls.mail.side_effect = RuntimeError("SMTP down")
        automation = self.stored_as(self.automation("mail"), "mail,notification")
        with self.assertLogs("horilla.contrib.automations.methods", "ERROR"):
            self.run_automation(automation)
        self.assertEqual([name for name, _r in self.sent()], ["mail", "notification"])

    def test_missing_channel_is_logged_and_the_others_still_send(self):
        """A key whose app is gone is skipped; the other selected keys run."""
        automation = self.stored_as(self.automation("mail"), "fake_sms,mail")
        unregister_delivery_channel("fake_sms")
        with self.assertLogs("horilla.contrib.automations.methods", "ERROR") as logs:
            self.run_automation(automation)
        self.assertIn("is not registered", logs.output[0])
        self.assertEqual(self.sent(), [("mail", ["user@example.com"])])

    def test_plugin_channel_resolves_its_own_recipients(self):
        """The fake channel's resolve_recipients runs, not the mail one."""
        automation = self.automation(
            "fake_sms", mail_to="self, instance.contact_number"
        )
        automation.also_sent_to.add(self.colleague)
        self.instance = self.colleague
        with mock.patch.object(
            MailChannel, "resolve_recipients", autospec=True
        ) as mail_resolve:
            self.run_automation(automation)
        mail_resolve.assert_not_called()
        self.assertEqual(len(self.fake.sent), 1)
        self.assertEqual(self.fake.sent[0][2], ["09121111111", "09122222222"])
        self.assertEqual(self.sent(), [])


# Saving a notification pushes it over channels; keep that in memory here.
@override_settings(
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
)
class ChannelSendTests(AutomationTestCase):
    """The send code that moved out of Automations still does its job."""

    def test_notification_channel_creates_notifications(self):
        """One rendered notification per user, linked to the instance."""
        automation = self.automation("notification")
        instance = Activity(pk=42)
        context = {"instance": instance, "user": self.user, "self": self.user}
        NotificationChannel().send(
            automation, instance, [self.user, self.colleague], context, self.user
        )
        notices = Notification.objects.filter(message__contains="Notice for 42")
        self.assertEqual(
            sorted(notices.values_list("user__username", flat=True)),
            ["delivery-colleague", "delivery-user"],
        )

    def test_mail_channel_creates_the_mail_and_sends_it_in_a_thread(self):
        """A draft HorillaMail to the recipients, handed to a background thread."""
        automation = self.automation("mail")
        instance = Activity(pk=7)
        context = {
            "instance": instance,
            "user": self.user,
            "active_company": self.company,
        }
        with mock.patch("horilla.contrib.mail.delivery.threading.Thread") as thread:
            MailChannel().send(
                automation,
                instance,
                ["a@example.com", "b@example.com"],
                context,
                self.user,
            )
        mail = HorillaMail.objects.get(object_id=7)
        self.assertEqual(mail.to, "a@example.com,b@example.com")
        self.assertEqual(mail.subject, "Subject")
        self.assertEqual(mail.sender, self.mail_server)
        self.assertEqual(mail.additional_info["request_info"]["user_id"], self.user.pk)
        thread.return_value.start.assert_called_once_with()


class FormAndViewTests(AutomationTestCase):
    """The automation form and its HTMX views use the registry."""

    def setUp(self):
        super().setUp()
        user_logged_in.disconnect(post_login)
        self.addCleanup(user_logged_in.connect, post_login)
        self.admin = User.objects.create_superuser(
            username="delivery-admin",
            email="admin@example.com",
            password="x",
            company=self.company,
        )
        self.client.force_login(self.admin)

    def get(self, name, **params):
        return self.client.get(reverse(name), params, HTTP_HX_REQUEST="true")

    def delivery_select(self, response):
        """The delivery channel <select> of a rendered form."""
        return re.search(
            r'<select[^>]*name="delivery_channel".*?</select>',
            response.content.decode(),
            re.S,
        ).group(0)

    def test_form_is_a_multi_select_of_the_registered_channels(self):
        """Mail, notification and the fake channel; no "both"; mail selected."""
        response = self.get("automations:automation_create_view")
        self.assertEqual(response.status_code, 200)
        select = self.delivery_select(response)
        self.assertIn("multiple", select)
        self.assertEqual(
            re.findall(r'<option value="([^"]+)"', select),
            [channel.key for channel in get_delivery_channels(self.company)],
        )
        self.assertNotIn('value="both"', select)
        self.assertIn("Send as Fake SMS", select)
        self.assertEqual(re.findall(r'value="([^"]+)"\s+selected', select), ["mail"])

    def test_edit_form_selects_the_stored_channels(self):
        """A stored "mail,fake_sms" shows as two selected options."""
        automation = self.automation("mail,fake_sms")
        response = self.client.get(
            reverse("automations:automation_update_view", kwargs={"pk": automation.pk}),
            HTTP_HX_REQUEST="true",
        )
        select = self.delivery_select(response)
        self.assertEqual(
            sorted(re.findall(r'value="([^"]+)"\s+selected', select)),
            ["fake_sms", "mail"],
        )

    def test_saving_the_form_stores_the_selected_channels(self):
        """The whole form saves a multi-selection as comma-separated keys."""
        lead_type = HorillaContentType.objects.get(app_label="leads", model="lead")
        response = self.client.post(
            reverse("automations:automation_create_view"),
            {
                "title": "Mail and SMS",
                "model": lead_type.pk,
                "mail_to": ["self"],
                "trigger": "on_create",
                "delivery_channel": ["fake_sms", "mail"],
                "mail_template": self.mail_template.pk,
                "notification_template": self.notification_template.pk,
                "mail_server": self.mail_server.pk,
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        automation = HorillaAutomation.all_objects.filter(title="Mail and SMS").first()
        form = response.context and response.context.get("form")
        self.assertIsNotNone(automation, form.errors if form else response.content)
        self.assertEqual(
            automation.delivery_channel, in_registry_order("mail", "fake_sms")
        )

    def test_template_fields_follow_the_selected_channels(self):
        """A block shows when any selected channel asks for it."""
        cases = [
            (["mail"], (True, False)),
            (["notification"], (False, True)),
            (["mail", "notification"], (True, True)),
            (["both"], (True, True)),
            (["fake_sms"], (False, True)),
            (["mail", "fake_sms"], (True, True)),
            (["pigeon"], (False, False)),
        ]
        for channels, (mail, notification) in cases:
            with self.subTest(channels=channels):
                response = self.get(
                    "automations:get_template_fields",
                    delivery_channel=channels,
                    model=self.model.pk,
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["show_mail_template"], mail)
                self.assertEqual(response.context["show_mail_server"], mail)
                self.assertEqual(
                    response.context["show_notification_template"], notification
                )

    def test_recipient_picker_is_the_union_of_the_selected_channels(self):
        """The mail_to options combine the selected channels' recipient choices."""
        user_type = HorillaContentType.objects.get_for_model(User)
        sms = self.get(
            "automations:get_template_fields",
            delivery_channel=["fake_sms"],
            model=user_type.pk,
            mail_to="instance.contact_number",
        )
        values = [value for value, _label in sms.context["mail_to_choices"]]
        self.assertIn("instance.contact_number", values)
        self.assertNotIn("instance.email", values)
        self.assertEqual(sms.context["mail_to_selected"], ["instance.contact_number"])
        self.assertContains(sms, 'hx-swap-oob="outerHTML"')

        mixed = self.get(
            "automations:get_template_fields",
            delivery_channel=["mail", "fake_sms"],
            model=user_type.pk,
        )
        values = [value for value, _label in mixed.context["mail_to_choices"]]
        self.assertIn("instance.email", values)
        self.assertIn("instance.contact_number", values)
        self.assertEqual(values.count("self"), 1)

    def test_list_shows_the_channel_labels(self):
        """The list column joins the registry labels."""
        self.stored_as(self.automation("mail"), "mail,fake_sms")
        response = self.get("automations:automation_list_view")
        self.assertContains(response, "Send as Mail, Send as Fake SMS")
