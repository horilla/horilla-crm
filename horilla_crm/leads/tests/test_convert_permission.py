"""The convert-lead permissions exist and gate the conversion form."""

# Third-party imports (Django)
from django.contrib.auth.models import Permission
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.contrib.messages import get_messages
from django.test import TestCase
from login_history.models import post_login, post_logout

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.models import Company
from horilla.urls import reverse
from horilla_crm.contacts.models import Contact
from horilla_crm.leads.models import Lead, LeadStatus

DENIED_TEXT = "You do not have permission to view this page."


class LeadConvertPermissionTests(TestCase):
    """A role-based user can be allowed to convert leads, not only a superuser."""

    def setUp(self):
        """Log in a non-superuser who holds every standard Lead permission."""
        user_logged_in.disconnect(post_login)
        user_logged_out.disconnect(post_logout)
        self.addCleanup(user_logged_in.connect, post_login)
        self.addCleanup(user_logged_out.connect, post_logout)

        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        self.user = User.objects.create_user(
            username="sales",
            email="sales@example.com",
            password="pass",
            company=self.company,
        )
        self.other = User.objects.create_user(
            username="other",
            email="other@example.com",
            password="pass",
            company=self.company,
        )
        standard = [
            f"{action}_lead"
            for action in (
                "add",
                "change",
                "view",
                "delete",
                "add_own",
                "change_own",
                "view_own",
                "delete_own",
            )
        ]
        self.user.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="leads", codename__in=standard
            )
        )
        status = LeadStatus.all_objects.create(
            name="New", probability=0, company=self.company
        )
        self.own_lead = self._lead("own@example.com", self.user, status)
        self.others_lead = self._lead("other@example.com", self.other, status)

        self.client.force_login(self.user)
        session = self.client.session
        session["active_company_id"] = self.company.pk
        session.save()

    def _lead(self, email, owner, status):
        """Create an unconverted lead owned by ``owner``."""
        return Lead.all_objects.create(
            first_name="Ada",
            last_name="Lovelace",
            email=email,
            lead_company="Prospect Pioneers",
            lead_owner=owner,
            lead_status=status,
            company=self.company,
        )

    def _grant(self, codename):
        """Give the user one leads permission by codename."""
        self.user.user_permissions.add(
            Permission.objects.get(content_type__app_label="leads", codename=codename)
        )

    def _open_conversion(self, lead):
        """GET the conversion form the way the lead page opens it."""
        return self.client.get(
            reverse("leads:convert_lead", kwargs={"pk": lead.pk}),
            HTTP_HX_REQUEST="true",
        )

    def test_convert_permissions_exist(self):
        """Both permissions are real rows, so roles can grant them."""
        codenames = set(
            Permission.objects.filter(
                content_type__app_label="leads", content_type__model="lead"
            ).values_list("codename", flat=True)
        )
        self.assertIn("convert_lead", codenames)
        self.assertIn("convert_own_lead", codenames)

    def test_standard_lead_permissions_alone_do_not_allow_conversion(self):
        """Create/change/view/delete on leads is not enough to convert."""
        response = self._open_conversion(self.own_lead)
        self.assertContains(response, DENIED_TEXT)

    def test_convert_lead_allows_any_lead(self):
        """convert_lead opens the form for a lead someone else owns."""
        self._grant("convert_lead")
        response = self._open_conversion(self.others_lead)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, DENIED_TEXT)

    def test_convert_own_lead_allows_only_own_leads(self):
        """convert_own_lead opens the form for the user's own lead only."""
        self._grant("convert_own_lead")
        self.assertNotContains(self._open_conversion(self.own_lead), DENIED_TEXT)
        self.assertContains(self._open_conversion(self.others_lead), DENIED_TEXT)

    def test_a_missing_permission_on_save_is_reported(self):
        """
        A user who may create every record but not change contacts links one of
        their own contacts: the save is refused with a message, not a crash.
        """
        self._grant("convert_lead")
        for app_label, codename in (
            ("accounts", "add_account"),
            ("contacts", "add_contact"),
            ("opportunities", "add_opportunity"),
        ):
            self.user.user_permissions.add(
                Permission.objects.get(
                    content_type__app_label=app_label, codename=codename
                )
            )
        contact = Contact.all_objects.create(
            first_name="Grace",
            last_name="Hopper",
            email="grace@example.com",
            contact_owner=self.user,
            company=self.company,
        )
        response = self.client.post(
            reverse("leads:convert_lead", kwargs={"pk": self.own_lead.pk}),
            {
                "account_action": "create_new",
                "account_name": "Prospect Pioneers",
                "contact_action": "select_existing",
                "existing_contact": contact.pk,
                "opportunity_action": "create_new",
                "opportunity_name": "Pioneer deal",
                "owner": self.user.pk,
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.own_lead.refresh_from_db()
        self.assertFalse(self.own_lead.is_convert)
        self.assertIn(
            "link the selected contact",
            " ".join(str(message) for message in get_messages(response.wsgi_request)),
        )
