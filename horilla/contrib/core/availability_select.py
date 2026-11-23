"""
Reusable "pick a person, but show who is unavailable" select.

For lead assignment today; made to be reused by workflows, cadences, approvals
and any other form that lets someone pick a user.

Use it in three steps:

1. Build the widget from the users you want to offer::

       from horilla.contrib.core.availability_select import availability_select

       self.fields["assignee"].widget = availability_select(users_queryset)

   People who are unavailable now are listed after the others, greyed out and
   not selectable, with a grey "Unavailable" pill and the tooltip
   "Unavailable until 25 Nov 2026, 5:00 PM". Nothing else is needed on the
   page: the pill is a few lines of CSS sent together with the select (no
   script, and it survives an htmx swap of the field).

2. Keep the unavailable people in the field's ``queryset``. The browser never
   submits a disabled option, but a hand-made request can, and it must reach
   step 3 to get a clear message instead of "not a valid choice".

3. Check on the server, in ``clean_<field>`` or ``clean``::

       from horilla.contrib.core.availability_select import ensure_available

       ensure_available(self.cleaned_data["assignee"])

   It raises a ``ValidationError`` such as "Ann is unavailable until 25 Nov
   2026, 5:00 PM." Pass ``at=`` to check another moment than now.

The widget only draws and flags people; who is unavailable comes from
``horilla.contrib.core.availability``, the one place every feature asks.
"""

# Standard library imports
import json

# Third-party imports (Django)
from django import forms
from django.core.exceptions import ValidationError
from django.utils.safestring import mark_safe

# First party imports (Horilla)
from horilla.contrib.core.availability import format_when, unavailable_until
from horilla.utils import timezone
from horilla.utils.translation import gettext as _


def display_name(user):
    """The name shown for a user: the full name, else the username."""
    return str(user).strip() or user.username


def unavailable_title(back_at):
    """ "Unavailable until 25 Nov 2026, 5:00 PM": the tooltip of an away person."""
    if back_at is None:
        return _("Unavailable")
    return _("Unavailable until %(date)s") % {"date": format_when(back_at)}


class AvailabilitySelect(forms.Select):
    """
    A select that lists people who are unavailable but does not let them be
    picked. ``unavailable`` maps an option value to its tooltip. Those options
    are disabled and carry the tooltip as ``title``.

    Select2 draws the dropdown and gives each disabled row ``aria-disabled``, so
    a little CSS, sent with the select, adds the grey "Unavailable" pill to the
    disabled rows of this select's dropdown (marked by ``DROPDOWN_CLASS``).
    The pill must not depend on ``title``: while a row is hovered the tooltip
    script takes the ``title`` away. (Select2 builds the rows itself, so
    Tailwind classes can not be put on them from a template; the colours below
    are Tailwind's gray-100 and gray-500.) The browser never submits a disabled
    option; the server rejects it as well (see ``ensure_available``).
    """

    # Class select2 adds to this select's dropdown (``data-dropdown-css-class``),
    # so the pill only appears here, not in other selects with disabled options.
    DROPDOWN_CLASS = "availability-select"

    # Every disabled row of such a dropdown is a person who is unavailable.
    PILL_CSS = (
        '.availability-select .select2-results__option[aria-disabled="true"]'
        "{display:flex;align-items:center;justify-content:space-between;gap:8px}"
        '.availability-select .select2-results__option[aria-disabled="true"]'
        "::after{content:%s;"
        "flex-shrink:0;padding:2px 8px 2px 21px;border-radius:6px;"
        "background:#F3F4F6 url(\"data:image/svg+xml,%%3Csvg xmlns='http://www.w3.org/"
        "2000/svg' viewBox='0 0 24 24' fill='none' stroke='%%236B7280' "
        "stroke-width='2.5' stroke-linecap='round'%%3E%%3Ccircle cx='12' cy='12' "
        "r='9'/%%3E%%3Cpath d='M5.6 5.6l12.8 12.8'/%%3E%%3C/svg%%3E\") no-repeat "
        "6px center/11px;color:#6B7280;font-size:10px;font-weight:600;"
        "line-height:16px}"
    )

    def __init__(self, *args, unavailable=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.unavailable = {
            str(value): title for value, title in (unavailable or {}).items()
        }

    def create_option(self, name, value, label, selected, index, *args, **kwargs):
        option = super().create_option(
            name, value, label, selected, index, *args, **kwargs
        )
        title = self.unavailable.get(str(value))
        if title is not None:
            option["attrs"].update({"disabled": True, "title": title})
        return option

    def render(self, name, value, attrs=None, renderer=None):
        """The select, followed by the pill's CSS when someone is unavailable."""
        if not self.unavailable:
            return super().render(name, value, attrs, renderer)
        attrs = {**(attrs or {}), "data-dropdown-css-class": self.DROPDOWN_CLASS}
        html = super().render(name, value, attrs, renderer)
        word = json.dumps(str(_("Unavailable")), ensure_ascii=False).replace("<", "")
        return mark_safe(f"{html}<style>{self.PILL_CSS % word}</style>")


def availability_choices(users, *, at=None, empty_label="---------"):
    """
    Return ``(choices, unavailable)`` for ``users`` (a queryset or any iterable
    of users): the available people first, in the order given, then the ones
    who are unavailable at ``at`` (default: now). ``unavailable`` maps each
    away person's pk to the tooltip. ``empty_label=None`` leaves out the blank
    choice.
    """
    users = list(users)
    back = unavailable_until([user.pk for user in users], at or timezone.now())
    choices = [("", empty_label)] if empty_label is not None else []
    away = []
    for user in users:
        entry = (user.pk, display_name(user))
        (away if user.pk in back else choices).append(entry)
    choices.extend(away)
    return choices, {pk: unavailable_title(back[pk]) for pk, _name in away}


def availability_select(users, *, at=None, attrs=None, empty_label="---------"):
    """A ready ``AvailabilitySelect`` offering ``users`` (see the module doc)."""
    choices, unavailable = availability_choices(users, at=at, empty_label=empty_label)
    return AvailabilitySelect(choices=choices, unavailable=unavailable, attrs=attrs)


def ensure_available(user, *, at=None):
    """
    Raise a ``ValidationError`` naming ``user`` and when they are back when they
    are unavailable at ``at`` (default: now). Does nothing for ``None`` or an
    available person.
    """
    if user is None:
        return
    back_at = unavailable_until([user.pk], at or timezone.now()).get(user.pk)
    if back_at is not None:
        raise ValidationError(
            _("%(user)s is unavailable until %(date)s."),
            code="unavailable",
            params={"user": display_name(user), "date": format_when(back_at)},
        )
