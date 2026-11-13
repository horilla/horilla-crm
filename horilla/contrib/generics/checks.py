"""
System checks for the generics app.

Reports a misconfigured ``boolean_labels`` on any Horilla form class when Django
runs its checks (``runserver``, ``check``, ``migrate``), so the mistake stops the
server at startup instead of surfacing when the form is first opened.
"""

# Standard library imports
import importlib

# Third-party imports (Django)
from django.apps import apps
from django.core import checks

# Local imports
from .forms.form_class_mixin import HorillaFormMixin


def _all_subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _all_subclasses(sub)


def _import_form_modules():
    """Import each installed app's ``forms`` module so its form classes exist."""
    for config in apps.get_app_configs():
        try:
            importlib.import_module(f"{config.name}.forms")
        except ImportError:
            continue


@checks.register()
def check_boolean_labels(app_configs=None, **kwargs):
    """Validate ``boolean_labels`` on every Horilla form class."""
    _import_form_modules()
    found = []
    for form_class in set(_all_subclasses(HorillaFormMixin)):
        for message in form_class._boolean_label_errors():
            found.append(checks.Error(message, obj=form_class, id="generics.E001"))
    return found
