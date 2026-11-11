"""
Tests for the onboarding step registry (``horilla.registry.onboarding``) and the
onboarding steps owned by core.
"""

# Standard library imports
import ast
from pathlib import Path
from unittest import mock

# Third-party imports (Django)
from django.test import SimpleTestCase, TestCase

# First party imports (Horilla)
from horilla.apps import apps
from horilla.auth.models import User
from horilla.core.exceptions import ImproperlyConfigured
from horilla.registry import onboarding as registry_module
from horilla.registry.onboarding import OnboardingSteps, get_onboarding_steps

# Local imports
from .models import Company, Role
from .onboarding import CompanyOnboarding, RolesOnboarding, UsersOnboarding


def _isolated_registry():
    """An empty registry for the duration of a test, so test steps never leak."""
    return mock.patch.object(OnboardingSteps, "_registry", [])


class RegistryIsIndependentOfAppsTests(SimpleTestCase):
    """The registry must keep working when an optional app is not installed."""

    def test_registry_module_imports_no_app_or_model(self):
        """Only the standard library, ``horilla.apps`` and ``horilla.core`` are imported."""
        tree = ast.parse(Path(registry_module.__file__).read_text())
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)

        for name in imported:
            self.assertFalse(
                name.startswith(("horilla.contrib", "horilla_crm", "django.db")),
                f"registry imports {name}",
            )


class RegistryCollectionTests(SimpleTestCase):
    """Registering, validating, ordering and filtering steps."""

    def test_subclass_registers_and_abstract_does_not(self):
        """A concrete subclass registers; ``abstract = True`` does not."""
        with _isolated_registry():

            class Base(OnboardingSteps):
                abstract = True

            class Real(Base):
                key, title, url_name = "real", "Real", "core:home"
                order = 5

                def is_done(self, company, user):
                    return True

            self.assertEqual([step.key for step in get_onboarding_steps()], ["real"])

    def test_steps_sort_by_order_then_key(self):
        """Lower ``order`` first; ties are broken by ``key``."""
        with _isolated_registry():
            for key, order in (("b", 10), ("c", 5), ("a", 10)):
                type(
                    key,
                    (OnboardingSteps,),
                    {
                        "key": key,
                        "title": key,
                        "url_name": "x",
                        "order": order,
                        "is_done": lambda self, company, user: False,
                    },
                )
            self.assertEqual([s.key for s in get_onboarding_steps()], ["c", "a", "b"])

    def test_reimporting_a_module_does_not_register_a_class_twice(self):
        """Defining the same class again replaces it instead of duplicating it."""
        with _isolated_registry():
            for _ in range(2):

                class Again(OnboardingSteps):
                    key, title, url_name = "again", "Again", "x"

                    def is_done(self, company, user):
                        return False

            self.assertEqual(len(get_onboarding_steps()), 1)

    def test_duplicate_key_raises(self):
        """Two steps with the same key are a configuration error."""
        with _isolated_registry():
            for name in ("One", "Two"):
                type(
                    name,
                    (OnboardingSteps,),
                    {
                        "key": "same",
                        "title": "t",
                        "url_name": "x",
                        "is_done": lambda self, company, user: False,
                    },
                )
            with self.assertRaises(ImproperlyConfigured):
                get_onboarding_steps()

    def test_incomplete_step_raises_naming_the_class(self):
        """A missing key, title or url_name is reported with the class name."""
        for missing in ("key", "title", "url_name"):
            with _isolated_registry():
                attrs = {
                    "key": "k",
                    "title": "t",
                    "url_name": "x",
                    "is_done": lambda self, company, user: False,
                }
                attrs[missing] = ""
                type("Broken", (OnboardingSteps,), attrs)
                with self.assertRaisesMessage(ImproperlyConfigured, "Broken"):
                    get_onboarding_steps()

    def test_step_needs_a_model_or_its_own_is_done(self):
        """Without a model and without an ``is_done`` override the step cannot work."""
        with _isolated_registry():
            type(
                "NoModel",
                (OnboardingSteps,),
                {"key": "k", "title": "t", "url_name": "x"},
            )
            with self.assertRaisesMessage(ImproperlyConfigured, "NoModel"):
                get_onboarding_steps()

    def test_classes_of_apps_that_are_not_installed_are_skipped(self):
        """A step whose module is not in an installed app is ignored."""
        with _isolated_registry():
            type(
                "Orphan",
                (OnboardingSteps,),
                {
                    "key": "orphan",
                    "title": "t",
                    "url_name": "x",
                    "is_done": lambda self, company, user: False,
                },
            )
            with mock.patch.object(
                apps, "get_containing_app_config", return_value=None
            ):
                self.assertEqual(get_onboarding_steps(), [])


class TitleDefaultTests(SimpleTestCase):
    """A step without a title uses the model's plural verbose name."""

    def test_title_defaults_to_model_verbose_name_plural(self):
        """``title`` unset + ``model`` set -> ``model._meta.verbose_name_plural``."""
        with _isolated_registry():

            class Untitled(OnboardingSteps):
                key, url_name, model = "untitled", "core:roles_view", Role

            self.assertEqual(
                str(Untitled().get_title()), str(Role._meta.verbose_name_plural)
            )

    def test_explicit_title_wins(self):
        """A title set on the class is kept."""
        with _isolated_registry():

            class Titled(OnboardingSteps):
                key, title, url_name, model = "titled", "Mine", "x", Role

            self.assertEqual(Titled().get_title(), "Mine")


class PermissionDefaultTests(SimpleTestCase):
    """A step without ``permission`` needs the view permission of its model."""

    def test_permission_is_read_from_the_model(self):
        """Roles and Users never type their permission; the user model may be swapped."""
        for step_cls, expected in (
            (RolesOnboarding, "core.view_role"),
            (UsersOnboarding, f"{User._meta.app_label}.view_{User._meta.model_name}"),
        ):
            step = step_cls()
            self.assertIsNone(step_cls.permission)
            self.assertEqual(step.get_permission(), expected)

    def test_explicit_permission_wins_and_no_model_means_none(self):
        """The Company step keeps its own permission; no permission and no model needs none."""
        company = CompanyOnboarding()
        self.assertEqual(company.get_permission(), "core.view_company")

        with _isolated_registry():

            class Open(OnboardingSteps):
                key, title, url_name = "open", "Open", "x"

        self.assertIsNone(Open().get_permission())


class DefaultIsDoneTests(TestCase):
    """The default ``is_done()``: the step's model has records for the company."""

    def setUp(self):
        """Two companies and a user."""
        self.acme = Company.objects.create(
            name="Acme", email="a@example.com", country="US"
        )
        self.beta = Company.objects.create(
            name="Beta", email="b@example.com", country="US"
        )
        self.user = User.objects.create_user(
            username="u", email="u@example.com", password="pass", company=self.acme
        )

    def _done(self, step_cls, company):
        instance = step_cls()
        return instance.is_done(company, self.user)

    def test_not_done_without_a_record(self):
        """No role yet."""
        self.assertFalse(self._done(RolesOnboarding, self.acme))

    def test_done_only_in_the_company_with_a_record(self):
        """A role in Acme completes the step for Acme, not for Beta."""
        Role.objects.create(role_name="Sales", company=self.acme)

        self.assertTrue(self._done(RolesOnboarding, self.acme))
        self.assertFalse(self._done(RolesOnboarding, self.beta))

    def test_users_done_with_one_user_in_the_company(self):
        """One user in the company is enough; another company's users do not count."""
        self.assertTrue(self._done(UsersOnboarding, self.acme))
        self.assertFalse(self._done(UsersOnboarding, self.beta))

    def test_min_count_is_respected(self):
        """A step with min_count=2 needs two records."""

        with _isolated_registry():

            class NeedsTwoRoles(RolesOnboarding):
                min_count = 2

        Role.objects.create(role_name="Sales", company=self.acme)
        self.assertFalse(self._done(NeedsTwoRoles, self.acme))

        Role.objects.create(role_name="Support", company=self.acme)
        self.assertTrue(self._done(NeedsTwoRoles, self.acme))

    def test_get_queryset_override_is_used(self):
        """A step can narrow the records that count."""

        class OnlyNamedX(RolesOnboarding):
            abstract = True

            def get_queryset(self, company):
                return super().get_queryset(company).filter(role_name="X")

        Role.objects.create(role_name="Y", company=self.acme)
        self.assertFalse(self._done(OnlyNamedX, self.acme))
        Role.objects.create(role_name="X", company=self.acme)
        self.assertTrue(self._done(OnlyNamedX, self.acme))


class CoreStepsTests(TestCase):
    """The Company step has its own rule."""

    def test_company_step_is_done_once_the_profile_is_filled_in(self):
        """Name, email and country complete it, per company."""
        acme = Company.objects.create(name="Acme", email="a@example.com", country="US")
        beta = Company.objects.create(name="Beta", email="b@example.com", country="")
        user = User.objects.create_user(
            username="u", email="u@example.com", password="pass", company=acme
        )
        step = CompanyOnboarding()

        self.assertTrue(step.is_done(acme, user))
        self.assertFalse(step.is_done(beta, user))

    def test_core_steps_are_registered_in_order(self):
        """Company, Roles and Users come first, in that order."""
        keys = [s.key for s in get_onboarding_steps()]
        self.assertEqual(keys[:3], ["company", "roles", "users"])
