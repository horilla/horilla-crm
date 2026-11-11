"""
Onboarding step registry.

The home page "Get started" guide is a checklist that every app contributes to.
An app declares one subclass of ``OnboardingSteps`` per step, in its own
``onboarding.py`` (imported at startup through the app's ``auto_import_modules``
only when the app is installed)::

    from horilla.registry.onboarding import OnboardingSteps
    from horilla.utils.translation import gettext_lazy as _

    from .models import Role


    class RolesOnboarding(OnboardingSteps):
        key = "roles"
        title = _("Roles")
        description = _("Create roles to control what users can see in {company}.")
        url_name = "core:roles_view"
        icon = "fa-user-shield"
        permission = "core.view_role"
        order = 20
        model = Role

A step is done when its ``model`` has at least ``min_count`` records for the
company the user is working in. A step with a special rule overrides
``get_queryset()`` (for example "active only") or ``is_done()`` itself, as
``CompanyOnboarding`` does by checking that the company's required fields are filled in::

    class CompanyOnboarding(OnboardingSteps):
        key = "company"
        title = _("Company")
        url_name = "core:company_information"
        order = 10

        def is_done(self, company, user):
            return bool(company.name and company.email and company.country)

``title`` is optional when ``model`` is set: it then defaults to the model's
``verbose_name_plural``. ``permission`` is optional too: it then defaults to the
model's ``view`` permission, read from the model itself.

``title``, ``headline`` and ``description`` may contain ``{company}``, which is
replaced by the name of the active company (``request.active_company``), so a
step never has to name a product.

``get_onboarding_steps()`` returns the steps of the installed apps only, and
``build_onboarding(user, company, skipped)`` turns them into the guide the home page
shows (visible steps, which are done, the next one, the progress). This module
imports no app and no model, so the onboarding system keeps working, without import
errors, when an optional app is not installed or enabled.
"""

# Standard library imports
import logging

# First party imports (Horilla)
from horilla.apps import apps
from horilla.core.exceptions import ImproperlyConfigured
from horilla.urls import NoReverseMatch, reverse

logger = logging.getLogger(__name__)

DEFAULT_ORDER = 100
DEFAULT_ICON = "fa-circle"


class OnboardingSteps:
    """
    Base class of every onboarding step: one subclass is one step.

    Subclasses register themselves when their module is imported. Set
    ``abstract = True`` on an intermediate base class that must not register.
    """

    key = ""
    title = None  # Defaults to the model's ``verbose_name_plural``
    url_name = ""
    description = ""
    headline = ""
    icon = DEFAULT_ICON
    permission = None
    order = DEFAULT_ORDER
    model = None
    min_count = 1
    abstract = False

    _registry = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.__dict__.get("abstract", False):
            return
        registry = OnboardingSteps._registry
        # Re-importing a module (reload, tests) must not register its classes twice.
        registry[:] = [
            known
            for known in registry
            if (known.__module__, known.__qualname__)
            != (cls.__module__, cls.__qualname__)
        ]
        registry.append(cls)

    @classmethod
    def get_title(cls):
        """
        The step's ``title``; when it is not set, the plural verbose name of
        ``model`` (``None`` if there is neither).
        """
        if cls.title:
            return cls.title
        if cls.model is not None:
            return cls.model._meta.verbose_name_plural
        return None

    # ---- hooks a subclass may override ---------------------------------

    def get_permission(self):
        """
        The permission needed to see the step: its ``permission`` if set, else the
        ``view`` permission of its ``model`` (``"<app_label>.view_<model_name>"``,
        read from the model, so a swapped model such as the user model needs no
        hand-typed name), else ``None``.
        """
        if self.permission:
            return self.permission
        if self.model is not None:
            meta = self.model._meta
            return f"{meta.app_label}.view_{meta.model_name}"
        return None

    def is_visible(self, user, company):  # pylint: disable=unused-argument
        """Default: the user holds the step's permission (or it needs none)."""
        permission = self.get_permission()
        return not permission or user.has_perm(permission)

    def get_queryset(self, company):
        """
        The step's records for ``company`` only. ``all_objects`` with an explicit
        company filter keeps the answer right even in "show all companies" mode.
        """
        manager = getattr(self.model, "all_objects", self.model._default_manager)
        return manager.filter(company=company)

    def is_done(self, company, user):  # pylint: disable=unused-argument
        """Done when the model has at least ``min_count`` records for the company."""
        if self.model is None:
            return False
        return self.get_queryset(company)[: self.min_count].count() >= self.min_count


def _validate(cls):
    """Raise ``ImproperlyConfigured`` naming the class if a step is incomplete."""
    for field in ("key", "title", "url_name"):
        value = cls.get_title() if field == "title" else getattr(cls, field, None)
        if not value:
            raise ImproperlyConfigured(
                f"Onboarding step {cls.__module__}.{cls.__qualname__} must set '{field}'."
            )
    if cls.model is None and cls.is_done is OnboardingSteps.is_done:
        raise ImproperlyConfigured(
            f"Onboarding step {cls.__module__}.{cls.__qualname__} must set 'model' "
            "or override is_done()."
        )


def get_onboarding_steps():
    """
    Instances of the registered steps of the installed apps, sorted by
    ``(order, key)``.

    A class whose module is not in an installed app is skipped. An incomplete
    class or a duplicate ``key`` raises ``ImproperlyConfigured``.
    """
    steps = {}
    for cls in list(OnboardingSteps._registry):
        if apps.get_containing_app_config(cls.__module__) is None:
            continue
        _validate(cls)
        if cls.key in steps:
            raise ImproperlyConfigured(
                f"Onboarding step key '{cls.key}' is used by both "
                f"{steps[cls.key].__module__}.{steps[cls.key].__qualname__} and "
                f"{cls.__module__}.{cls.__qualname__}."
            )
        steps[cls.key] = cls
    return [
        cls() for cls in sorted(steps.values(), key=lambda cls: (cls.order, cls.key))
    ]


def _render(text, company):
    """Replace ``{company}`` in a step text with the active company's name."""
    return str(text).replace("{company}", str(company.name))


def build_onboarding(user, company, skipped=()):
    """
    Return the guide for ``user`` in ``company`` as a dict, or ``None`` when there
    is nothing to show (not a superuser, no company, no visible steps, or every
    visible step done). The guide is for superusers only.

    ``skipped`` holds the keys of the steps the user pressed "Skip For Now" on: the
    next step is the first unfinished step that is not skipped, or ``None`` when
    every unfinished step was skipped (the steps stay in the stepper).
    """
    if user is None or company is None or not user.is_superuser:
        return None

    steps = []
    for step in get_onboarding_steps():
        if not step.is_visible(user, company):
            continue
        try:
            url = reverse(step.url_name)
        except NoReverseMatch:
            logger.warning("Onboarding step %s has no URL %s", step.key, step.url_name)
            continue
        title = step.get_title()
        steps.append(
            {
                "key": step.key,
                "number": len(steps) + 1,
                "title": _render(title, company),
                "headline": _render(step.headline or title, company),
                "description": _render(step.description, company),
                "icon": step.icon,
                "url": url,
                "done": step.is_done(company, user),
                "is_next": False,
            }
        )

    if not steps:
        return None

    done_count = sum(1 for step in steps if step["done"])
    if done_count == len(steps):
        return None

    next_step = next(
        (step for step in steps if not step["done"] and step["key"] not in skipped),
        None,
    )
    if next_step:
        next_step["is_next"] = True

    return {
        "company_name": company.name,
        "steps": steps,
        "total": len(steps),
        "done_count": done_count,
        "percent": round(done_count * 100 / len(steps)),
        "next_step": next_step,
    }
