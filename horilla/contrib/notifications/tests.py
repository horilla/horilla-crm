"""Tests for the notifications app."""

# Third-party imports (Django)
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.models import Company, Department
from horilla.contrib.utils.middlewares import _thread_local

# Local imports
from .methods import create_notification, get_user_notifications
from .models import Notification


class UserNotificationsTests(TestCase):
    """get_user_notifications(): records of other companies are left out."""

    def setUp(self):
        self.company = Company.objects.create(name="Acme", email="acme@example.com")
        self.other = Company.objects.create(name="Other", email="other@example.com")
        self.user = User.objects.create_user(
            username="user", email="user@example.com", password="pass", company=self.company
        )
        # The default manager is scoped to the company of the current request.
        request = RequestFactory().get("/")
        request.user = self.user
        request.active_company = self.company
        _thread_local.request = request
        self.addCleanup(setattr, _thread_local, "request", None)

    def department(self, company, name):
        return Department.all_objects.create(department_name=name, company=company)

    def notify(self, instance=None, message="Hello"):
        return create_notification(self.user, message, instance=instance)

    def test_records_of_other_companies_and_deleted_records_are_left_out(self):
        own = self.notify(self.department(self.company, "Sales"))
        foreign = self.notify(self.department(self.other, "Ops"))
        gone_department = self.department(self.company, "Old")
        gone = self.notify(gone_department)
        gone_department.delete()
        unlinked = self.notify()
        self.assertEqual(
            set(get_user_notifications(self.user)), {own, unlinked}
        )
        self.assertTrue(Notification.objects.filter(pk__in=[foreign.pk, gone.pk]).exists())

    def test_query_count_does_not_grow_with_the_notifications(self):
        """It runs on every page (context processor), so it must stay flat."""
        department = self.department(self.company, "Sales")

        def queries_for(count):
            Notification.objects.filter(user=self.user).delete()
            for number in range(count):
                self.notify(department, message=f"Note {number}")
            with CaptureQueriesContext(connection) as context:
                visible = list(get_user_notifications(self.user).filter(read=False))
            self.assertEqual(len(visible), count)
            return len(context.captured_queries)

        self.assertEqual(queries_for(3), queries_for(40))
