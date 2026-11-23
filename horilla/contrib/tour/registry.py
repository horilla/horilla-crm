"""
Tour registry: how tours are declared and found.

A tour is a subclass of ``Tour``. Defining the class registers it, so an app only
needs a ``tour.py`` listed in its ``auto_import_modules``. ``tour.js`` runs the
steps in the browser and skips any step whose element is missing.
"""

# Standard library imports
from dataclasses import asdict, dataclass
from typing import Optional, Tuple

# Third-party imports (Django)
from django.core.exceptions import ImproperlyConfigured

# First party imports (Horilla)
from horilla.urls import NoReverseMatch, Resolver404, resolve, reverse

SIDES = ("top", "bottom", "left", "right", "over")
ALIGNS = ("start", "center", "end")

# key -> Tour subclass
_registry = {}


@dataclass(frozen=True)
class Step:  # pylint: disable=too-many-instance-attributes
    """
    One popover of a tour.

    title, body    text shown (use ``gettext_lazy``)
    target         CSS selector to highlight; ``None`` gives a centred card
    side, align    where the popover sits; use ``align="end"`` at the right edge
    only_if        only for a step with ``before`` clicks, or one that needs a different
                   element than ``target``: the selector that must be visible, otherwise the
                   step is skipped. Without it the step is skipped when ``target`` is missing.
                   A step that has it waits longer for its target (a pop-up can be slow)
    also           a second element to light together with ``target``, for a button
                   and the pop-up it opens when the pop-up sits outside the button
    before, after  actions run when entering / leaving the step, for example to open
                   and close a menu: ``{"click": "#btn", "if_hidden": "#menu"}``. The kinds
                   are ``click``, ``mousedown`` (a select2 box) and ``tap`` (a calendar day);
                   build them with the helpers in ``presets``
    """

    title: str
    body: str
    target: Optional[str] = None
    side: str = "bottom"
    align: Optional[str] = None
    only_if: Optional[str] = None
    also: Optional[str] = None
    before: Tuple[dict, ...] = ()
    after: Tuple[dict, ...] = ()

    def to_dict(self):
        """Return the JSON-serialisable form sent to the browser."""
        data = asdict(self)
        data.update(
            title=str(self.title),
            body=str(self.body),
            before=list(data["before"]),
            after=list(data["after"]),
        )
        return data


class Tour:
    """
    A guided tour. Subclass it and set the attributes below.

    key, title, description   id and the text on the panel card
    group, icon, order        how the card is listed in the panel
    match                     URL names of the pages the tour belongs to
    open_with                 ``{"from": url_name, "click": selector}``: the page to
                              start from and what to click to reach the tour's screen
    ready                     selector to wait for before the first step
    permission                permission(s) needed to see the tour (any one)
    auto_start                start by itself the first time a matching page opens
    steps                     list of ``Step``
    """

    abstract = True

    key = None
    title = ""
    description = ""
    group = ""
    icon = "/assets/icons/about-system.svg"
    order = 100
    match = ()
    open_with = None
    ready = None
    permission = None
    auto_start = False
    steps = ()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.__dict__.get("abstract", False):
            return
        cls._validate()
        _registry[cls.key] = cls

    @classmethod
    def _validate(cls):
        """Fail loudly at import time for a malformed tour definition."""
        name = cls.__qualname__
        if not cls.key:
            raise ImproperlyConfigured(f"{name}: 'key' is required.")
        if not cls.title:
            raise ImproperlyConfigured(f"{name}: 'title' is required.")
        if not cls.match or isinstance(cls.match, str):
            raise ImproperlyConfigured(f"{name}: 'match' must be a list of URL names.")
        if not cls.steps:
            raise ImproperlyConfigured(f"{name}: at least one step is required.")
        if cls.open_with is not None and not (
            isinstance(cls.open_with, dict) and {"from", "click"} <= set(cls.open_with)
        ):
            raise ImproperlyConfigured(
                f"{name}: 'open_with' needs 'from' and 'click' entries."
            )
        for index, step in enumerate(cls.steps):
            if not isinstance(step, Step):
                raise ImproperlyConfigured(f"{name}: step {index} is not a Step.")
            if not step.title or not step.body:
                raise ImproperlyConfigured(
                    f"{name}: step {index} needs title and body."
                )
            if step.side not in SIDES:
                raise ImproperlyConfigured(
                    f"{name}: step {index} has invalid side '{step.side}'."
                )
            if step.align is not None and step.align not in ALIGNS:
                raise ImproperlyConfigured(
                    f"{name}: step {index} has invalid align '{step.align}'."
                )

    @classmethod
    def match_names(cls):
        """
        URL names of the pages the tour belongs to.

        ``match`` unless a tour overrides this for a page whose URL changes while
        it is used, such as Settings, which opens its pages in place.
        """
        return list(cls.match)

    @classmethod
    def matches(cls, view_name):
        """Whether the page called ``view_name`` belongs to this tour."""
        return bool(view_name) and view_name in cls.match_names()

    @classmethod
    def is_visible_to(cls, user):
        """Whether ``user`` may see this tour (permission check)."""
        if not (user and user.is_authenticated):
            return False
        perms = (
            [cls.permission]
            if isinstance(cls.permission, str)
            else list(cls.permission or [])
        )
        return not perms or any(user.has_perm(perm) for perm in perms)

    @classmethod
    def start_link(cls):
        """URL the Start button should open, or ``None`` if it can't be built."""
        name = cls.open_with["from"] if cls.open_with else cls.match[0]
        try:
            return f"{reverse(name)}?tour={cls.key}"
        except NoReverseMatch:
            return None

    @classmethod
    def to_dict(cls):
        """Full definition (including steps) sent to the browser."""
        return {
            "key": cls.key,
            "title": str(cls.title),
            "description": str(cls.description),
            "match": cls.match_names(),
            "open_with": dict(cls.open_with) if cls.open_with else None,
            "start_url": cls.start_link(),
            "ready": cls.ready,
            "steps": [step.to_dict() for step in cls.steps],
        }


def get_visible_tour(key, user):
    """The tour for ``key`` if it exists and ``user`` may see it, otherwise ``None``."""
    tour = _registry.get(key) if isinstance(key, str) else None
    return tour if tour and tour.is_visible_to(user) else None


def get_tours_for(user):
    """All tours ``user`` may see, ordered for display."""
    tours = [tour for tour in _registry.values() if tour.is_visible_to(user)]
    return sorted(tours, key=lambda tour: (tour.order, str(tour.title)))


def resolve_view_name(path):
    """Resolve a URL path to ``"namespace:url_name"``, or ``None``."""
    try:
        match = resolve(path)
    except Resolver404:
        return None
    return match.view_name or None
