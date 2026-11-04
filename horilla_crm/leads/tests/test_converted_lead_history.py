"""
Converted lead history tests.

The Activity, Generics and Mail apps are part of the core platform and must not
depend on ``horilla_crm``, so the tests that need Lead, Contact and Opportunity
live in the Lead app.
"""

# Third-party imports (Django)
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.test import TestCase
from login_history.models import post_login, post_logout

from calls.models import CallIntegrationSetting

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.activity.models import Activity
from horilla.contrib.core.models import Company, HorillaAttachment, HorillaContentType
from horilla.contrib.generics.history import history_q, is_record_locked
from horilla.contrib.generics.views.details import (
    check_record_change_access,
    check_record_delete_access,
)
from horilla.urls import reverse
from horilla_crm.accounts.models import Account
from horilla_crm.contacts.models import Contact, ContactAccountRelationship
from horilla_crm.leads.models import Lead, LeadStatus


class ConvertedLeadHistoryTests(TestCase):
    """History of a converted lead shows on its Contact and the lead is locked."""

    @classmethod
    def setUpClass(cls):
        """Disconnect the login/logout signals so the test client can log in without a user agent."""
        super().setUpClass()
        user_logged_in.disconnect(post_login)
        user_logged_out.disconnect(post_logout)

    @classmethod
    def tearDownClass(cls):
        """Reconnect the login/logout signals so other tests are not affected."""
        user_logged_in.connect(post_login)
        user_logged_out.connect(post_logout)
        super().tearDownClass()

    def setUp(self):
        """Create a company, a superuser, a lead and an activity related to that lead."""
        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        self.admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
            company=self.company,
        )
        status = LeadStatus.objects.create(
            name="New", probability=10, company=self.company
        )
        self.lead = Lead.objects.create(
            first_name="Ada",
            last_name="Lovelace",
            email="ada@example.com",
            lead_company="Prospect Pioneers",
            lead_source="website",
            industry="technology",
            lead_owner=self.admin,
            lead_status=status,
            company=self.company,
        )
        self.contact = Contact.objects.create(
            first_name="Ada",
            last_name="Lovelace",
            email="ada@example.com",
            contact_owner=self.admin,
            company=self.company,
        )
        self.lead_ct = HorillaContentType.objects.get_for_model(Lead)
        self.contact_ct = HorillaContentType.objects.get_for_model(Contact)
        self.lead_task = self._task("Lead task", self.lead_ct, self.lead.pk)
        self.contact_task = self._task("Contact task", self.contact_ct, self.contact.pk)

    def _task(self, subject, content_type, object_id):
        """Create an Activity of type "task" with the given subject, content type and object ID."""
        return Activity.objects.create(
            subject=subject,
            title=subject,
            activity_type="task",
            status="not_started",
            owner=self.admin,
            content_type=content_type,
            object_id=object_id,
            company=self.company,
        )

    def _convert(self):
        """Mark the lead as converted to the contact, so its history shows on the contact."""
        self.lead.is_convert = True
        self.lead.converted_contact = self.contact
        self.lead.save()

    def _task_list(self, **extra):
        """Return the HTML of the contact's task list, with optional query parameters."""
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("activity:task_list", kwargs={"object_id": self.contact.pk}),
            {"view_type": "pending", "content_type_id": self.contact_ct.pk, **extra},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_contact_lists_own_and_lead_tasks_after_conversion(self):
        """A contact that is the converted lead shows both its own tasks and the lead's."""
        self._convert()
        html = self._task_list()
        self.assertIn("Contact task", html)
        self.assertIn("Lead task", html)
        self.assertIn("From Lead", html)

    def test_contact_without_conversion_shows_only_own_tasks(self):
        """A contact that is not the converted lead shows only its own tasks, not the lead's."""
        html = self._task_list()
        self.assertIn("Contact task", html)
        self.assertNotIn("Lead task", html)

    def test_history_q_covers_lead_and_contact_rows(self):
        """The history_q() filter returns both the contact's and the lead's rows after conversion."""
        self._convert()
        rows = Activity.objects.filter(history_q(self.contact, self.admin))
        self.assertEqual(
            {a.pk for a in rows}, {self.lead_task.pk, self.contact_task.pk}
        )

    def test_lead_rows_have_no_edit_or_delete_on_contact(self):
        """A converted lead's history rows show on the contact, but cannot be edited or deleted."""
        self._convert()
        html = self._task_list()
        self.assertIn(str(self.contact_task.get_delete_url()), html)
        self.assertNotIn(str(self.lead_task.get_edit_url()), html)
        self.assertNotIn(str(self.lead_task.get_delete_url()), html)
        # Disabled, not hidden: the lead row still renders its action buttons.
        lead_row = html.split("Lead task", 1)[1].split("</tr>", 1)[0]
        self.assertIn("cursor-not-allowed", lead_row)

    def test_converted_lead_is_locked_even_for_superuser(self):
        """A converted lead is locked and cannot be edited or deleted, even by a superuser."""
        self.assertFalse(is_record_locked(self.lead))
        self.assertTrue(check_record_change_access(self.admin, self.lead))
        self._convert()
        self.assertTrue(is_record_locked(self.lead))
        self.assertFalse(check_record_change_access(self.admin, self.lead))
        self.assertFalse(check_record_delete_access(self.admin, self.lead))

    def test_converted_lead_edit_and_delete_views_refuse(self):
        """A converted lead cannot be edited or deleted, even by a superuser."""
        self._convert()
        self.client.force_login(self.admin)
        for url in (
            reverse("leads:leads_edit_single", kwargs={"pk": self.lead.pk}),
            reverse("leads:leads_delete", kwargs={"pk": self.lead.pk}),
        ):
            self.client.get(url, HTTP_HX_REQUEST="true")
            self.client.post(url, {"first_name": "Changed"}, HTTP_HX_REQUEST="true")
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.first_name, "Ada")
        self.assertTrue(Lead.objects.filter(pk=self.lead.pk).exists())

    def test_converted_lead_cannot_be_converted_again(self):
        """A converted lead cannot be converted again, even by a superuser."""
        self._convert()
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("leads:convert_lead", kwargs={"pk": self.lead.pk}),
            HTTP_HX_REQUEST="true",
        )
        self.assertNotIn("lead_convert", getattr(response, "template_name", []) or [])
        self.assertEqual(Contact.objects.count(), 1)

    def test_status_update_refused_for_converted_lead_rows(self):
        """A task attached to a converted lead cannot be marked completed, even by a superuser."""
        self._convert()
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse(
                "activity:activity_status_update", kwargs={"pk": self.lead_task.pk}
            ),
            {"status": "completed"},
        )
        self.assertNotEqual(response.status_code, 500)
        self.lead_task.refresh_from_db()
        self.assertEqual(self.lead_task.status, "not_started")

    def test_contact_notes_tab_shows_lead_notes(self):
        """A note attached to the lead shows on the contact's notes tab after conversion."""
        HorillaAttachment.objects.create(
            title="Lead note",
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            company=self.company,
        )
        self._convert()
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse(
                "contacts:contacts_notes_attachements", kwargs={"pk": self.contact.pk}
            ),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Lead note", response.content.decode())

    def test_deleting_contact_keeps_lead_and_its_history(self):
        """Deleting the contact does not delete the lead or its history rows, even if the lead is converted to that contact."""
        self._convert()
        self.contact.delete()
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.converted_contact)
        self.assertTrue(Activity.objects.filter(pk=self.lead_task.pk).exists())

    def test_converted_lead_details_tab_has_no_edit_button(self):
        """The "Edit Details" button is not rendered for a converted lead, even for a superuser."""
        self.client.force_login(self.admin)
        url = reverse("leads:leads_details_tab", kwargs={"pk": self.lead.pk})
        self.assertIn(
            "Edit Details",
            self.client.get(url, HTTP_HX_REQUEST="true").content.decode(),
        )
        self._convert()
        self.assertNotIn(
            "Edit Details",
            self.client.get(url, HTTP_HX_REQUEST="true").content.decode(),
        )

    def test_converted_lead_inline_edit_is_refused(self):
        """The inline edit form is not rendered for a converted lead, even for a superuser."""
        self._convert()
        self.client.force_login(self.admin)
        url = reverse(
            "generics:edit_all_fields",
            kwargs={"pk": self.lead.pk, "app_label": "leads", "model_name": "lead"},
        )
        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertNotIn("edit_all_fields", response.content.decode().split("<form")[0])
        self.assertNotIn("<form", response.content.decode())

    def test_contact_history_does_not_include_lead_history(self):
        """The lead's history is not copied to the contact; the contact's history is only its own rows and the lead's rows."""
        self._convert()
        models = {entry._meta.model_name for entry in self.contact.full_histories}
        self.assertNotIn("historicallead", models)
        self.assertTrue(
            all(
                "lead" not in type(e).__name__.lower()
                for e in self.contact.full_histories
            )
        )

    def test_tab_list_table_keeps_a_minimum_width_so_it_scrolls(self):
        """table_auto lists get a per-column minimum width, so extra columns scroll."""
        self._convert()
        self.assertIn("min-width: calc(", self._task_list())

    def test_source_column_only_when_a_row_comes_from_a_source(self):
        """No Related To column when the tab has no lead rows; present when it has."""
        self._convert()
        html = self._task_list()
        self.assertIn("Related To", html)
        self.assertIn("Self", html)
        self.assertIn(str(self.lead.get_detail_url()), html)
        self.lead_task.delete()
        self.assertNotIn("Related To", self._task_list())

    def test_pill_link_carries_the_contact_as_breadcrumb_referrer(self):
        """The pill link to the lead's detail view carries the contact as a referrer, so the user can return to the contact."""
        self._convert()
        html = self._task_list()
        self.assertIn("referrer_model=contact", html)
        self.assertIn(f"referrer_id={self.contact.pk}", html)
        self.assertIn("referrer_url=", html)

    def test_converted_lead_activity_tab_has_no_add_buttons(self):
        """Even a superuser (global add permission) gets no Add Task/Meeting/Call/Event."""
        self.client.force_login(self.admin)
        url = reverse("leads:lead_activity_detail_view", kwargs={"pk": self.lead.pk})
        before = self.client.get(url, HTTP_HX_REQUEST="true").content.decode()
        self.assertIn('id="task-create"', before)
        self._convert()
        after = self.client.get(url, HTTP_HX_REQUEST="true").content.decode()
        for button in ("task-create", "meeting-create", "call-create", "event-create"):
            self.assertNotIn(f'id="{button}"', after)

    def test_converted_lead_has_no_call_now_and_click_to_call_refuses(self):
        """The click-to-call modal opens for an unconverted lead, but not for a converted one."""
        self.client.force_login(self.admin)
        # Click-to-call needs the calls integration switched on for the user.
        CallIntegrationSetting.objects.update_or_create(
            company=self.company,
            defaults={
                "is_enabled": True,
                "access_type": CallIntegrationSetting.ACCESS_ALL,
            },
        )
        click_to_call = reverse("calls:click_to_call")
        params = {"model_name": "lead", "object_id": self.lead.pk, "phone_number": "1"}
        # Before conversion the modal opens; after, it is refused.
        before = self.client.get(click_to_call, params, HTTP_HX_REQUEST="true")
        self.assertIn("provider", before.content.decode().lower())
        self._convert()
        after = self.client.get(click_to_call, params, HTTP_HX_REQUEST="true")
        self.assertNotIn("provider", after.content.decode().lower())
        tab = reverse("leads:lead_activity_detail_view", kwargs={"pk": self.lead.pk})
        html = self.client.get(tab, HTTP_HX_REQUEST="true").content.decode()
        self.assertNotIn(click_to_call, html)

    def test_link_records_connects_a_converted_lead_and_shows_its_history(self):
        """A converted lead can be linked to a contact, and its history shows on the contact."""
        self.client.force_login(self.admin)
        url = reverse("leads:lead_link_records", kwargs={"pk": self.lead.pk})
        # An unconverted lead cannot be linked.
        self.client.post(url, {"contact": self.contact.pk}, HTTP_HX_REQUEST="true")
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.converted_contact)
        # A lead converted before links existed (is_convert only) can.
        Lead.objects.filter(pk=self.lead.pk).update(is_convert=True)
        self.assertEqual(self.client.get(url, HTTP_HX_REQUEST="true").status_code, 200)
        self.client.post(url, {"contact": self.contact.pk}, HTTP_HX_REQUEST="true")
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.converted_contact, self.contact)
        self.assertIn("Lead task", self._task_list())
        # The lead's own fields are untouched.
        self.assertEqual(self.lead.first_name, "Ada")

    def test_account_history_comes_from_its_contacts_without_a_stored_account_link(
        self,
    ):
        """A converted lead linked to a contact that is linked to an account shows on the account's history."""
        account = Account.objects.create(
            name="Acme Ltd", account_owner=self.admin, company=self.company
        )
        ContactAccountRelationship.objects.create(
            contact=self.contact, account=account, company=self.company
        )
        self.assertFalse(hasattr(Lead, "converted_account"))
        self.assertEqual(list(account.get_history_sources()), [])
        self._convert()
        self.assertEqual(list(account.get_history_sources()), [self.lead])
        rows = Activity.objects.filter(history_q(account, self.admin))
        self.assertEqual({a.pk for a in rows}, {self.lead_task.pk})

    def test_link_leads_from_the_contact_page(self):
        """A converted lead can be linked to a contact from the contact's page, and unlinked again."""
        self.client.force_login(self.admin)
        Lead.objects.filter(pk=self.lead.pk).update(is_convert=True)
        url = reverse("leads:link_leads_to_contact", kwargs={"pk": self.contact.pk})
        self.assertEqual(self.client.get(url, HTTP_HX_REQUEST="true").status_code, 200)
        self.client.post(url, {"leads": [self.lead.pk]}, HTTP_HX_REQUEST="true")
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.converted_contact, self.contact)
        self.assertIn("Lead task", self._task_list())
        # Clearing the selection unlinks it again.
        self.client.post(url, {}, HTTP_HX_REQUEST="true")
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.converted_contact)

    def test_only_converted_leads_can_be_linked_to_a_contact(self):
        """Unconverted leads cannot be linked to a contact, even by a superuser."""
        self.client.force_login(self.admin)
        url = reverse("leads:link_leads_to_contact", kwargs={"pk": self.contact.pk})
        self.client.post(url, {"leads": [self.lead.pk]}, HTTP_HX_REQUEST="true")
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.converted_contact)

    def test_converted_lead_select2_lists_only_converted_leads(self):
        """The select2 endpoint for linking leads to a record only returns converted leads."""
        self.client.force_login(self.admin)
        url = reverse("leads:converted_lead_select2")
        xhr = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        self.assertEqual(self.client.get(url, **xhr).json()["results"], [])
        Lead.objects.filter(pk=self.lead.pk).update(is_convert=True)
        results = self.client.get(url, {"q": "Ada"}, **xhr).json()["results"]
        self.assertEqual([r["id"] for r in results], [self.lead.pk])
        self.assertEqual(
            self.client.get(url, {"q": "nobody"}, **xhr).json()["results"], []
        )
