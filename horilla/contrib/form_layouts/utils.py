"""
Resolve, apply and store per-company create form layouts.

A layout is the ordered set of ``FormLayoutField`` rows for one model in the
active company. A model without rows has no layout, so installing this app
changes nothing until an administrator saves one.
"""

# Standard library imports
import inspect
import logging
import pkgutil
from dataclasses import dataclass
from importlib import import_module

# Third-party imports (Django)
from django import forms
from django.apps import apps as django_apps
from django.db import transaction

# First party imports (Horilla)
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.utils.middlewares import get_current_request

# Local imports
from .models import FormLayoutField
from .registry import is_layout_configurable

logger = logging.getLogger(__name__)

_REQUEST_CACHE_ATTR = "_form_layout_cache"


@dataclass(frozen=True)
class FormLayout:
    """A saved layout: field names in display order, and the ones to leave out."""

    order: tuple
    hidden: frozenset


@dataclass(frozen=True)
class LayoutEntry:
    """One field of a create form, as shown in the settings editor."""

    name: str
    label: str
    required: bool
    visible: bool
    is_custom: bool


def get_form_layout(model):
    """
    Return the saved create form layout for ``model``, or None.

    Scoped to the active company through the model's default manager. Results
    are cached on the current request so a page that builds several forms for
    the same model does not re-query.
    """
    if model is None or not is_layout_configurable(model):
        return None

    cache_key = model._meta.label_lower
    request = get_current_request()
    cache = None
    if request is not None:
        cache = getattr(request, _REQUEST_CACHE_ATTR, None)
        if cache is None:
            cache = {}
            setattr(request, _REQUEST_CACHE_ATTR, cache)
        if cache_key in cache:
            return cache[cache_key]

    content_type = HorillaContentType.objects.get_for_model(model)
    rows = list(
        FormLayoutField.objects.filter(content_type=content_type, is_active=True)
        .order_by("sequence", "pk")
        .values_list("field_name", "is_visible")
    )
    layout = None
    if rows:
        layout = FormLayout(
            order=tuple(name for name, _visible in rows),
            hidden=frozenset(name for name, visible in rows if not visible),
        )

    if cache is not None:
        cache[cache_key] = layout
    return layout


def clear_form_layout_cache(request=None):
    """Forget layouts cached on ``request`` (defaults to the current request)."""
    request = request or get_current_request()
    if request is not None and hasattr(request, _REQUEST_CACHE_ATTR):
        delattr(request, _REQUEST_CACHE_ATTR)


def is_empty_value(value):
    """Return True for the values a form treats as "nothing entered"."""
    return value is None or value == "" or value == [] or value == ()


def apply_form_layout(form, layout, protected=()):
    """
    Leave hidden fields out of ``form`` and put the rest in layout order.

    A field is only removed when leaving it out cannot block or corrupt the
    save: required fields, fields that already render as hidden inputs and
    names in ``protected`` (e.g. values the view pre-filled) always stay.
    Fields the layout does not mention keep their position after the ordered
    ones, so a field added later shows up instead of silently disappearing.

    Returns the names that were removed.
    """
    if form is None or layout is None:
        return []

    protected = set(protected or ())
    removed = []
    for name in layout.hidden:
        field = form.fields.get(name)
        if field is None or name in protected:
            continue
        if field.required or field.widget.is_hidden:
            continue
        del form.fields[name]
        removed.append(name)

    form.order_fields([name for name in layout.order if name in form.fields])
    return removed


def get_create_form_class(model):
    """
    Return the single-page create form class for ``model``.

    Looks for ``ModelForm`` subclasses of ``model`` in its app's ``forms``
    module that are not multi-step wizards, preferring one named
    ``*SingleForm``, and composes it with registered form extensions. Falls
    back to a generic Horilla model form when the app defines none.
    """
    # First party imports (Horilla)
    from horilla.contrib.generics.forms import HorillaModelForm, HorillaMultiStepForm
    from horilla.extension.forms.resolve import resolve_form_class

    candidates = []
    try:
        app_config = django_apps.get_app_config(model._meta.app_label)
    except LookupError:
        app_config = None

    if app_config is not None:
        for module in _iter_forms_modules(app_config):
            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if obj.__module__ != module.__name__:
                    continue
                if getattr(obj, "__horilla_composed__", False):
                    continue
                if not issubclass(obj, forms.BaseModelForm):
                    continue
                if issubclass(obj, HorillaMultiStepForm):
                    continue
                if getattr(getattr(obj, "Meta", None), "model", None) is not model:
                    continue
                candidates.append(obj)

    if candidates:
        candidates.sort(
            key=lambda cls: (not cls.__name__.endswith("SingleForm"), cls.__name__)
        )
        return resolve_form_class(candidates[0])

    return forms.modelform_factory(model, form=HorillaModelForm, fields="__all__")


def _iter_forms_modules(app_config):
    """Import ``{app}.forms`` and, when it is a package, its submodules."""
    module_name = f"{app_config.name}.forms"
    try:
        module = import_module(module_name)
    except ModuleNotFoundError:
        return
    except Exception:
        logger.exception("Could not import %s while discovering forms", module_name)
        return

    yield module
    paths = getattr(module, "__path__", None)
    if not paths:
        return

    for module_info in pkgutil.walk_packages(paths, prefix=module_name + "."):
        if module_info.name.rsplit(".", 1)[-1] in {"tests", "test_forms"}:
            continue
        try:
            yield import_module(module_info.name)
        except Exception:
            logger.exception(
                "Could not import %s while discovering forms", module_info.name
            )


def build_layout_entries(model, request=None):
    """
    Describe the fields of ``model``'s create form for the settings editor.

    The form is built the way a create request builds it, so custom fields
    and requiredness overrides from other apps are reflected. Entries follow
    the saved layout, then the form's own order for fields it does not cover.
    """
    # First party imports (Horilla)
    from horilla.contrib.generics.forms import HorillaModelForm

    form_class = get_create_form_class(model)
    kwargs = {}
    if issubclass(form_class, HorillaModelForm):
        kwargs["request"] = request or get_current_request()
    form = form_class(**kwargs)

    layout = get_form_layout(model)
    hidden = layout.hidden if layout else frozenset()
    position = (
        {name: index for index, name in enumerate(layout.order)} if layout else {}
    )

    indexed = []
    for index, (name, field) in enumerate(form.fields.items()):
        if field.widget.is_hidden:
            continue
        required = bool(field.required)
        entry = LayoutEntry(
            name=name,
            label=str(form[name].label or name),
            required=required,
            visible=required or name not in hidden,
            is_custom=_is_custom_field(name, field),
        )
        indexed.append((position.get(name, len(position)), index, entry))

    indexed.sort(key=lambda item: (item[0], item[1]))
    return [entry for _position, _index, entry in indexed]


def _is_custom_field(name, field):
    """Return True for fields added at runtime by a custom-fields app."""
    if getattr(field, "is_custom_field", False):
        return True
    if not django_apps.is_installed("custom_fields"):
        return False
    try:
        # First-party / Horilla apps
        from custom_fields.utils import is_custom_field_name
    except ImportError:
        return False
    return is_custom_field_name(name)


def save_form_layout(model, ordered_names, visible_names, company, request=None):
    """
    Replace the stored layout for ``model`` in ``company``.

    Unknown names are ignored, required fields are always stored as visible,
    fields missing from ``ordered_names`` are appended in form order and rows
    for fields the form no longer has are removed. Returns the saved entries.
    """
    entries = {entry.name: entry for entry in build_layout_entries(model, request)}
    visible_names = set(visible_names or ())

    order = [name for name in dict.fromkeys(ordered_names or ()) if name in entries]
    order += [name for name in entries if name not in order]

    content_type = HorillaContentType.objects.get_for_model(model)
    with transaction.atomic():
        existing = {
            row.field_name: row
            for row in FormLayoutField.all_objects.filter(
                content_type=content_type, company=company
            )
        }
        for sequence, name in enumerate(order, start=1):
            row = existing.pop(name, None) or FormLayoutField(
                content_type=content_type, company=company, field_name=name
            )
            row.is_visible = entries[name].required or name in visible_names
            row.sequence = sequence
            row.is_active = True
            row.save()
        for row in existing.values():
            row.delete()

    clear_form_layout_cache(request)
    return build_layout_entries(model, request)


def reset_form_layout(model, company, request=None):
    """Delete the stored layout for ``model`` in ``company``; returns rows removed."""
    content_type = HorillaContentType.objects.get_for_model(model)
    deleted, _details = FormLayoutField.all_objects.filter(
        content_type=content_type, company=company
    ).delete()
    clear_form_layout_cache(request)
    return deleted
