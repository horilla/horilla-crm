"""Resolve the model a dashboard component or form points at."""

# First party imports (Horilla)
from horilla.apps import apps
from horilla.contrib.core.models import HorillaContentType
from horilla.registry.feature import FEATURE_REGISTRY


def get_model_by_name(model_name):
    """Return the first installed model whose name matches ``model_name``.

    The match ignores case and the app label. Returns None for an empty or
    unknown name.
    """
    name = (model_name or "").strip().lower()
    if not name:
        return None
    for model in apps.get_models(include_auto_created=True, include_swapped=True):
        if model._meta.model_name == name:
            return model
    return None


def get_dashboard_component_models():
    """
    Return a list of (module_key, model_class) for every model that
    is registered for dashboard components.
    """
    return [
        (model_cls.__name__.lower(), model_cls)
        for model_cls in FEATURE_REGISTRY.get("dashboard_component_models", [])
    ]


def resolve_model_from_module(module):
    """
    Resolve a model class from a ``module`` value: a HorillaContentType pk or a
    model name. The dashboard registry is checked first so the result matches
    the module dropdown; installed apps are the fallback. Returns None if the
    value is empty or matches no model.
    """
    module = (module or "").strip()
    if not module:
        return None
    if module.isdigit():
        try:
            module = HorillaContentType.objects.get(pk=module).model or ""
        except HorillaContentType.DoesNotExist:
            return None
    module_key = module.strip().lower()
    if not module_key:
        return None
    for key, model_cls in get_dashboard_component_models():
        if key == module_key:
            return model_cls
    return get_model_by_name(module_key)
