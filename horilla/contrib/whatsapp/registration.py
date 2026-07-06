"""
Feature registration for the whatsapp app.
"""

# Standard library imports
import logging

from horilla.registry.feature import register_feature

# First party imports (Horilla)
from horilla.urls import path

logger = logging.getLogger(__name__)

# Lets any model registered with all=True elsewhere become a valid content_type
# choice for WhatsAppTemplate.content_type and a valid link target for
# WhatsAppConversation (see models.py's ContentTypeLimiter('whatsapp_template_models')).
register_feature("whatsapp_template", "whatsapp_template_models")

# Lets Automations (and Workflow, Cadences) send an approved WhatsApp template
# to a record's phone number. Automations itself is not edited: the channel is
# one more entry in the delivery channel registry.
from horilla.registry.delivery import (  # noqa: E402
    get_delivery_channel,
    register_delivery_channel,
)

from .delivery import WhatsAppChannel  # noqa: E402

if get_delivery_channel(WhatsAppChannel.key) is None:
    register_delivery_channel(WhatsAppChannel())

# Lets any model registered with all=True elsewhere become selectable as the
# target model for a Bot Rule's create_record/update_record/search_record
# node, without this app importing those models directly.
register_feature("whatsapp_flow_action", "whatsapp_flow_action_models")


def whatsapp_tab_url_name(model, namespaced=True):
    """
    Return the conventional whatsapp tab url name for a model, e.g.
    'lead_whatsapp_tab'. Pass namespaced=False for the bare name used when
    declaring the url pattern itself (path(..., name=...) inside urls.py is
    already inside the "whatsapp" app_name namespace).
    """
    bare_name = f"{model._meta.model_name}_whatsapp_tab"
    return f"whatsapp:{bare_name}" if namespaced else bare_name


def register_whatsapp_tab(model):
    """
    Register a WhatsApp conversation tab for the given model class.

    Creates a WhatsAppRecordTabView subclass for the model and adds its URL
    to the whatsapp urlpatterns, under a conventional name/path derived from
    the model itself — no app-specific registration list to maintain.
    """
    try:
        import horilla.contrib.whatsapp.urls as whatsapp_urls
        from horilla.contrib.whatsapp.views.inbox import WhatsAppRecordTabView

        app_label = model._meta.app_label
        model_name = model.__name__
        url_name = whatsapp_tab_url_name(model, namespaced=False)
        url_prefix = f"{model._meta.model_name}-whatsapp-tab/<int:pk>/"

        view_class = type(
            f"{model_name}WhatsAppTab",
            (WhatsAppRecordTabView,),
            {"app_label": app_label, "model_name": model_name},
        )

        whatsapp_urls.urlpatterns.append(
            path(url_prefix, view_class.as_view(), name=url_name)
        )

    except Exception as e:
        logger.warning("register_whatsapp_tab failed for %s: %s", model, e)


def _phone_field_names():
    """Return the shared phone-field-name set used across Horilla's forms."""
    from horilla.contrib.generics.forms.form_class_mixin import HorillaFormMixin

    return HorillaFormMixin._DEFAULT_PHONE_FIELD_NAMES


def _model_has_phone_field(model):
    """Return True if the model declares a field named like a phone number."""
    phone_names = _phone_field_names()
    return any(field.name in phone_names for field in model._meta.get_fields())


_tabs_registered = False


def register_whatsapp_tabs_for_registered_models(**kwargs):
    """
    Register a WhatsApp tab for every model already opted into the
    'whatsapp_template' feature (via register_model_for_feature(all=True))
    that also declares a phone-like field.

    FEATURE_REGISTRY is only fully populated once every app's own
    registration.py has run, which may happen after this app's (whatsapp
    loads before horilla_crm in INSTALLED_APPS). So this is deferred to
    Django's request_started signal — fired once, after all apps are ready,
    before the first request is served — rather than called at import time.
    """
    global _tabs_registered
    if _tabs_registered:
        return
    _tabs_registered = True

    from horilla.registry.feature import FEATURE_REGISTRY

    registered_any = False
    for model in FEATURE_REGISTRY.get("whatsapp_template_models", []):
        if _model_has_phone_field(model):
            register_whatsapp_tab(model)
            registered_any = True

    if registered_any:
        from horilla.urls import clear_url_caches

        clear_url_caches()


def _register_tabs_once_apps_are_ready():
    """Connect tab registration to run exactly once, after all apps are ready."""
    from django.core.signals import request_started

    request_started.connect(
        register_whatsapp_tabs_for_registered_models,
        dispatch_uid="whatsapp_register_tabs_for_registered_models",
    )


_register_tabs_once_apps_are_ready()
