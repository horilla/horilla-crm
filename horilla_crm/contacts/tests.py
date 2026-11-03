"""
Contacts in the optional phone mode (``horilla.contrib.mobile``), with the
settings in ``contacts/mobile.py``. Skipped when the mobile app isn't
installed.
"""

# Standard library imports
from unittest import skipUnless

# Third-party imports (Django)
from django.contrib.auth.models import Permission
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from login_history.models import post_login, post_logout

# First party imports (Horilla)
from horilla.apps import apps
from horilla.auth.models import User
from horilla.contrib.core.models import Company
from horilla_crm.contacts.models import Contact

MOBILE_INSTALLED = apps.is_installed("horilla.contrib.mobile")


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
class ContactOnThePhoneTests(TestCase):
    """A contact owner finds, opens and calls their contact on the phone."""

    @classmethod
    def setUpClass(cls):
        """Disconnect the login/logout signals so that the test client can log in."""
        super().setUpClass()
        # django-login-history reads request.META['HTTP_USER_AGENT'] on
        # login/logout, which the test client's bare request doesn't set.
        user_logged_in.disconnect(post_login)
        user_logged_out.disconnect(post_logout)

    @classmethod
    def tearDownClass(cls):
        """Reconnect the login/logout signals so that the test client can log in."""
        user_logged_in.connect(post_login)
        user_logged_out.connect(post_logout)
        super().tearDownClass()

    def setUp(self):
        """Set up a company, a seller user, and an contact owned by that user."""

        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        self.seller = User.objects.create_user(
            username="seller",
            email="seller@example.com",
            password="pass",
            company=self.company,
        )
        permission, _created = Permission.objects.get_or_create(
            codename="view_own_contact",
            content_type=ContentType.objects.get_for_model(Contact),
            defaults={"name": "Can view own contact"},
        )
        self.seller.user_permissions.add(permission)
        self.contact = Contact.objects.create(
            first_name="Maryam",
            last_name="Tavakoli",
            title="CFO",
            email="maryam@example.com",
            contact_number="0912 000 1111",
            secondary_contact_number="021 2222 3333",
            contact_owner=self.seller,
            company=self.company,
        )
        self.client.force_login(self.seller)

    def test_the_list_shows_the_name_the_job_title_and_a_call_button(self):
        """The contact list page shows the contacts's job title and a call button."""

        response = self.client.get("/m/records/", {"model": "contacts.contact"})
        self.assertContains(response, "Maryam Tavakoli")
        self.assertContains(response, "<bdi>CFO</bdi>")
        self.assertContains(response, 'href="tel:09120001111"')

    def test_two_numbers_ask_which_one_to_call(self):
        """The contact detail page opens and shows a call button."""

        response = self.client.get(f"/m/records/contacts/contact/{self.contact.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["phones"]), 2)
        self.assertContains(response, 'href="mailto:maryam@example.com"')
