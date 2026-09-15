"""
Helpers for models whose create form layout may be configured by admins.

Opt-in is explicit: an app must call
``register_model_for_feature(..., features=["form_layouts"])``. That keeps the
settings page limited to models whose create views are known to work with a
trimmed single-page form, rather than every model in the project.
"""

# First party imports (Horilla)
from horilla.db.models import Q
from horilla.registry.feature import FEATURE_REGISTRY

REGISTRY_KEY = "form_layout_models"


def is_layout_configurable(model):
    """Return True when `model` opted in to a configurable create form layout."""
    if getattr(model, "_meta", None) is None:
        return False
    return model in FEATURE_REGISTRY.get(REGISTRY_KEY, [])


def get_configurable_models():
    """Return the registered model classes, sorted by verbose name."""
    models = list(FEATURE_REGISTRY.get(REGISTRY_KEY, []))
    return sorted(models, key=lambda model: str(model._meta.verbose_name).lower())


def limit_content_types():
    """Limit ContentType choices to models opted in for form layouts."""
    configured = FEATURE_REGISTRY.get(REGISTRY_KEY, [])
    if not configured:
        return Q(pk__in=[])

    filters = Q()
    for model in configured:
        filters |= Q(app_label=model._meta.app_label, model=model._meta.model_name)
    return filters
