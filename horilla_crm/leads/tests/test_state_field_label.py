"""
The lead forms swap ``state`` for a subdivision select; the select keeps the
model field's translated label instead of Django's "State" fallback.
"""

# Third-party imports (Django)
from django.test import RequestFactory, TestCase
from django.utils import translation

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.models import Company
from horilla.contrib.utils.middlewares import _thread_local
from horilla_crm.leads.forms import LeadFormClass, LeadSingleForm
from horilla_crm.leads.models import Lead


class LeadStateLabelTests(TestCase):
    """Both lead create forms label the state select from the model."""

    def setUp(self):
        company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
            company=company,
        )
        self.request = RequestFactory().get("/")
        self.request.user = user
        _thread_local.request = self.request
        self.addCleanup(delattr, _thread_local, "request")

    def test_state_label_comes_from_the_model(self):
        """The label is the model's verbose_name and follows the active language."""
        verbose_name = Lead._meta.get_field("state").verbose_name
        for form_class in (LeadFormClass, LeadSingleForm):
            with self.subTest(form=form_class.__name__):
                label = form_class(request=self.request).fields["state"].label
                self.assertEqual(label, verbose_name)
                with translation.override("fa"):
                    self.assertEqual(str(label), "استان")
