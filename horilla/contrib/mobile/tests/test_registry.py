"""
Tests for how models opt into the phone: the ``mobile`` feature, ``mobile.py``
discovery and the validation of its settings.
"""

# Standard library imports
import sys
import types
from types import SimpleNamespace
from unittest import mock, skipUnless

# Third-party imports (Django)
from django.test import SimpleTestCase

from horilla.contrib.core.models import Company

# First party imports (Horilla)
from horilla.core.exceptions import ImproperlyConfigured
from horilla.registry.feature import FEATURE_REGISTRY, register_model_for_feature

from .base import MOBILE_INSTALLED, TEST_MOBILE_SETTINGS

if MOBILE_INSTALLED:
    from horilla.contrib.mobile import registry

    from .models import MobileTestRecord


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
class BuildConfigTests(SimpleTestCase):
    """A ``MOBILE_MODELS`` entry is validated when it is loaded."""

    def build(self, **changes):
        """Build."""
        options = {**TEST_MOBILE_SETTINGS, **changes}
        return registry.build_config(MobileTestRecord, options)

    def test_valid_settings_build_a_config(self):
        """Valid settings build a config."""
        config = self.build()
        self.assertEqual(config.title_field, "name")
        self.assertEqual(config.phone_fields, ("phone", "mobile_phone"))
        self.assertEqual(config.row_fields, ("city", "owner"))
        self.assertEqual(config.key, "mobile.mobiletestrecord")

    def test_unknown_option_is_rejected(self):
        """Unknown option is rejected."""
        with self.assertRaisesMessage(
            ImproperlyConfigured, "unknown option(s): colour"
        ):
            self.build(colour="red")

    def test_unknown_field_is_rejected(self):
        """Unknown field is rejected."""
        with self.assertRaisesMessage(
            ImproperlyConfigured, "'nickname' is not a field of MobileTestRecord"
        ):
            self.build(search_fields=["nickname"])

    def test_a_single_name_where_a_list_is_expected_is_rejected(self):
        """A single name where a list is expected is rejected."""
        with self.assertRaisesMessage(
            ImproperlyConfigured, "phone_fields must be a list of field names"
        ):
            self.build(phone_fields="phone")

    def test_at_most_two_row_fields(self):
        """At most two row fields."""
        with self.assertRaisesMessage(
            ImproperlyConfigured, "row_fields holds at most 2 fields"
        ):
            self.build(row_fields=["city", "owner", "email"])

    def test_filters_need_values_to_pick_from(self):
        """Filters need values to pick from."""
        with self.assertRaisesMessage(
            ImproperlyConfigured, "'city' must be a choice, foreign key or boolean"
        ):
            self.build(filter_fields=["city"])

    def test_order_must_be_a_whole_number(self):
        """Order must be a whole number."""
        with self.assertRaisesMessage(
            ImproperlyConfigured, "order must be a whole number"
        ):
            self.build(order="first")
        self.assertEqual(self.build(order=2).order, 2)

    def test_models_follow_their_order_then_registration(self):
        """Models follow their order then registration."""
        first = registry.MobileModelConfig(model=MobileTestRecord, order=1)
        second = registry.MobileModelConfig(model=MobileTestRecord, order=2)
        unordered = registry.MobileModelConfig(model=MobileTestRecord)
        self.assertEqual(
            registry.sort_configs([unordered, second, first]),
            [first, second, unordered],
        )

    def test_subtitle_fields_are_accepted(self):
        """Subtitle fields are accepted."""
        config = self.build(subtitle_fields=["city", "email"])
        self.assertEqual(config.subtitle_fields, ("city", "email"))

    def test_status_and_foreign_key_filters_are_accepted(self):
        """Status and foreign key filters are accepted."""
        config = self.build(filter_fields=["owner"])
        self.assertEqual(config.filter_fields, ("owner",))


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
class OptInTests(SimpleTestCase):
    """A model shows on the phone only with both the feature and settings."""

    def tearDown(self):
        """Prepare or clear the records these tests share."""
        registry.unregister_config(MobileTestRecord)
        registered = FEATURE_REGISTRY[registry.REGISTRY_KEY]
        if MobileTestRecord in registered:
            registered.remove(MobileTestRecord)

    def shown(self):
        """Shown."""
        return [config.model for config in registry.get_mobile_configs()]

    def test_feature_and_settings_show_the_model(self):
        """Feature and settings show the model."""
        register_model_for_feature(model_class=MobileTestRecord, features=["mobile"])
        registry.register_config(MobileTestRecord, TEST_MOBILE_SETTINGS)
        self.assertIn(MobileTestRecord, self.shown())
        self.assertIsNotNone(registry.get_mobile_config("mobile", "mobiletestrecord"))

    def test_settings_without_the_feature_are_ignored(self):
        """Settings without the feature are ignored."""
        registry.register_config(MobileTestRecord, TEST_MOBILE_SETTINGS)
        self.assertNotIn(MobileTestRecord, self.shown())
        self.assertIsNone(registry.get_mobile_config("mobile", "mobiletestrecord"))

    def test_the_feature_without_settings_is_skipped(self):
        """The feature without settings is skipped."""
        register_model_for_feature(model_class=MobileTestRecord, features=["mobile"])
        with self.assertLogs("horilla.contrib.mobile.registry", "WARNING"):
            self.assertNotIn(MobileTestRecord, self.shown())

    def test_models_registered_for_all_features_are_not_opted_in(self):
        # Company is registered with all=True in core; the phone feature is
        # registered with auto_register_all=False.
        """Models registered for all features are not opted in."""
        self.assertNotIn(Company, FEATURE_REGISTRY[registry.REGISTRY_KEY])


@skipUnless(MOBILE_INSTALLED, "horilla.contrib.mobile is not installed")
class DiscoveryTests(SimpleTestCase):
    """``MobileConfig`` imports each installed app's ``mobile`` module."""

    module_name = "mobile_discovery_test_app.mobile"

    def setUp(self):
        """Create the records these tests share."""
        package = types.ModuleType("mobile_discovery_test_app")
        package.__path__ = []
        module = types.ModuleType(self.module_name)
        module.MOBILE_MODELS = {"MobileTestRecord": TEST_MOBILE_SETTINGS}
        self.modules = {"mobile_discovery_test_app": package, self.module_name: module}
        self.app_config = SimpleNamespace(
            name="mobile_discovery_test_app",
            label="mobile",
            get_model=lambda name: {"MobileTestRecord": MobileTestRecord}[name],
        )

    def tearDown(self):
        """Prepare or clear the records these tests share."""
        registry.unregister_config(MobileTestRecord)

    def discover(self, app_configs):
        """Discover."""
        with mock.patch.dict(sys.modules, self.modules), mock.patch.object(
            registry.apps, "get_app_configs", return_value=app_configs
        ), mock.patch.object(
            registry.importlib.util,
            "find_spec",
            side_effect=lambda name: object() if name in self.modules else None,
        ):
            registry.discover_mobile_modules()

    def test_mobile_module_settings_are_loaded(self):
        """Mobile module settings are loaded."""
        self.discover([self.app_config])
        self.assertIn(MobileTestRecord, registry._CONFIGS)

    def test_apps_without_a_mobile_module_are_skipped(self):
        """Apps without a mobile module are skipped."""
        other = SimpleNamespace(name="no_mobile_here", label="other")
        self.discover([other])
        self.assertNotIn(MobileTestRecord, registry._CONFIGS)

    def test_unknown_model_name_stops_startup(self):
        """Unknown model name stops startup."""
        self.modules[self.module_name].MOBILE_MODELS = {"Nope": {}}
        self.app_config.get_model = mock.Mock(side_effect=LookupError)
        with self.assertRaisesMessage(ImproperlyConfigured, "no model 'Nope'"):
            self.discover([self.app_config])
