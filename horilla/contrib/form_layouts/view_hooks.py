"""
Apply saved create form layouts to Horilla's generic form views.

``horilla.views.generic.FormView`` subclasses Django's FormView directly, so
``_inherit_view`` extensions never reach ``HorillaSingleFormView`` or
``HorillaMultiStepFormView``. This module wraps a few of their methods at
import time instead, the same way ``custom_fields.form_hooks`` does, so no
Horilla source file has to change:

* ``HorillaSingleFormView.get_form`` leaves hidden fields out and reorders
  the rest when a record is being created.
* ``HorillaSingleFormView.get_multi_step_url`` hides the wizard toggle, since
  the wizard would ignore the layout.
* ``HorillaMultiStepFormView.get`` answers a create request with the
  single-page form when the model has a layout and the view names one.

Edit and duplicate requests are passed through unchanged.
"""

# Standard library imports
import logging
from urllib.parse import urlsplit

# First party imports (Horilla)
from horilla.urls import resolve

# Local imports
from .registry import is_layout_configurable
from .utils import apply_form_layout, get_form_layout, is_empty_value

logger = logging.getLogger(__name__)


def is_create_request(view):
    """Return True when ``view`` is handling the creation of a new record."""
    pk_key = view.get_pk_key() if hasattr(view, "get_pk_key") else "pk"
    kwargs = getattr(view, "kwargs", None) or {}
    if kwargs.get(pk_key) or kwargs.get("pk"):
        return False
    if getattr(view, "object", None) is not None:
        return False
    return not getattr(view, "duplicate_mode", False)


def get_active_create_layout(view):
    """Return the layout that applies to ``view``'s current request, or None."""
    model = getattr(view, "model", None)
    if model is None or not is_layout_configurable(model):
        return None
    if not is_create_request(view):
        return None
    return get_form_layout(model)


def get_prefilled_field_names(view):
    """Return fields the view pre-fills (e.g. the account on a related create)."""
    try:
        initial = view.get_initial() or {}
    except Exception:
        logger.exception("form_layouts: could not read initial data")
        return set()
    return {name for name, value in initial.items() if not is_empty_value(value)}


def _patch_single_form_view(view_class):
    """Wrap ``get_form`` and ``get_multi_step_url`` on the single form view."""
    if hasattr(view_class, "_form_layouts_original_get_form"):
        return

    original_get_form = view_class.get_form
    original_get_multi_step_url = view_class.get_multi_step_url

    def get_form(self, form_class=None):
        form = original_get_form(self, form_class)
        try:
            layout = get_active_create_layout(self)
            if layout is not None and form is not None:
                protected = set(getattr(self, "hidden_fields", None) or [])
                protected |= set(getattr(self, "condition_fields", None) or [])
                protected |= get_prefilled_field_names(self)
                apply_form_layout(form, layout, protected)
        except Exception:
            logger.exception("form_layouts: could not apply the create form layout")
        return form

    def get_multi_step_url(self):
        try:
            if get_active_create_layout(self) is not None:
                return None
        except Exception:
            logger.exception("form_layouts: could not check the create form layout")
        return original_get_multi_step_url(self)

    view_class._form_layouts_original_get_form = original_get_form
    view_class._form_layouts_original_get_multi_step_url = original_get_multi_step_url
    view_class.get_form = get_form
    view_class.get_multi_step_url = get_multi_step_url


def _render_single_step_view(request, url):
    """Dispatch ``request`` to the view behind ``url``; None if it cannot resolve."""
    try:
        match = resolve(urlsplit(str(url)).path)
    except Exception:
        logger.exception("form_layouts: could not resolve %s", url)
        return None
    # The response is a lazily rendered TemplateResponse, so the single-page
    # view's match has to stay on the request until the template renders.
    request.resolver_match = match
    return match.func(request, *match.args, **match.kwargs)


def _patch_multi_step_view(view_class):
    """Wrap ``get`` so create requests open the single-page form instead."""
    if hasattr(view_class, "_form_layouts_original_get"):
        return

    original_get = view_class.get

    def get(self, request, *args, **kwargs):
        single_step_url = None
        try:
            if get_active_create_layout(self) is not None:
                single_step_url = self.get_single_step_url()
        except Exception:
            logger.exception("form_layouts: could not check the create form layout")
        if single_step_url:
            response = _render_single_step_view(request, single_step_url)
            if response is not None:
                return response
        return original_get(self, request, *args, **kwargs)

    view_class._form_layouts_original_get = original_get
    view_class.get = get


def install_view_hooks():
    """Install the wrappers once; safe to call repeatedly."""
    # First party imports (Horilla)
    from horilla.contrib.generics.views.multi_form import HorillaMultiStepFormView
    from horilla.contrib.generics.views.single_form import HorillaSingleFormView

    _patch_single_form_view(HorillaSingleFormView)
    _patch_multi_step_view(HorillaMultiStepFormView)


install_view_hooks()
