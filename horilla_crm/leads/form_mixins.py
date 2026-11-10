"""
Form mixin that adds "Assign using rules" to the lead create forms.

When at least one active assignment rule exists, a new lead's form shows an
"Assign using rules" checkbox right below the Owner field. With it ticked:

* the Owner field is limited to the people the matching rule can assign to,
  with the person the condition's assignment method picks (least lead count
  or round robin) pre-selected;
* the lead must satisfy a rule condition, otherwise the form is rejected;
* the form records its decision on the lead (``_assignment_condition_id``) so
  the post-save engine does not pick an owner a second time.

With it unticked nothing changes: the owner is the one picked in the form.

The checkbox is drawn by the Owner widget, so it always sits under the owner
(also in a Form Layout). The ``apply_assignment_rule`` form field only reads its
value, which lets the multi-step wizard keep it between steps.

The mixin has to be the outermost base of the form, in front of
``OwnerQuerysetMixin``, because that mixin sets the owner queryset at the end
of its own ``__init__``.
"""

# Standard library imports
import json

# Third-party imports (Django)
from django import forms

# First party imports (Horilla)
from horilla.contrib.generics.forms.condition_fields import (
    get_condition_field_extension,
)
from horilla.urls import reverse_lazy
from horilla.utils.html import format_html
from horilla.utils.translation import gettext_lazy as _

# Local imports
from horilla_crm.leads.assignment.owner_lock import owner_locked
from horilla_crm.leads.assignment.pool import (
    MATCHED,
    NO_ASSIGNEES,
    NO_MATCH,
    OWNER_FIELD,
    UNDETERMINED,
    VIA_FORM,
    active_conditions,
    build_assignment_info,
    has_active_rules,
    resolve_for_data,
    union_resolution,
)
from horilla_crm.leads.models.assignment_rules import ASSIGNMENT_METHOD_ROUND_ROBIN

APPLY_FIELD = "apply_assignment_rule"

# Class of the select shown for the owner while the rule is applied. It is a
# plain select with the people already listed: the ajax select the owner field
# normally uses would load every user again and ignore the restriction.
OWNER_SELECT_CLASS = "js-example-basic-single headselect"

# The checkbox lives in the field container that holds the owner select; the
# browser swaps the content of that box when the checkbox is toggled.
OWNER_BOX_SELECTOR = f"div:has(> #id_{OWNER_FIELD})"


class _ApplyCheckboxReader(forms.CheckboxInput):
    """
    Reads the checkbox the Owner widget draws and renders nothing itself.

    It reports itself as hidden so form templates do not give it a row of its
    own.
    """

    input_type = "hidden"

    def render(self, name, value, attrs=None, renderer=None):
        """The Owner widget draws the checkbox."""
        return ""


class LeadAssignmentRuleFormMixin:
    """Adds the "Assign using rules" option to a lead create form."""

    # Set by the preview endpoint: the form only answers "who can be the owner",
    # so it must not treat missing values as final.
    _assignment_preview = False

    # The active conditions, loaded once per form (see ``_conditions``).
    _conditions_cache = None

    def __init__(self, *args, **kwargs):
        owner_is_locked = self._lock_owner_field(kwargs)
        super().__init__(*args, **kwargs)
        if owner_is_locked:
            self._keep_current_owner()
        self.assignment_resolution = None
        self._assignment_decision = None
        self._pool_mode = False
        self._checkbox_checked = False
        self._owner_note = ""

        if not self._assignment_applicable():
            return

        checked = self._apply_requested()
        self._checkbox_checked = checked
        self.fields[APPLY_FIELD] = forms.BooleanField(
            required=False, initial=checked, widget=_ApplyCheckboxReader()
        )
        if checked:
            self._enter_pool_mode(
                union_resolution(
                    self._assignment_company(), conditions=self._conditions()
                )
            )
        self._draw_checkbox_with_owner()

    # ------------------------------------------------------------------ setup

    @staticmethod
    def _lock_owner_field(kwargs):
        """
        Make the Owner read-only when the lead's rule does not let this user
        change it (see ``assignment.owner_lock``).

        The form classes already show a read-only field disabled and put the
        stored value back in ``clean()``, so the field is only marked here.
        """
        request = kwargs.get("request")
        user = getattr(request, "user", None)
        if not owner_locked(kwargs.get("instance"), user):
            return False
        permissions = dict(kwargs.get("field_permissions") or {})
        permissions[OWNER_FIELD] = "readonly"
        kwargs["field_permissions"] = permissions
        return True

    def _keep_current_owner(self):
        """
        Let the locked Owner field accept the lead's current owner.

        A read-only field is checked against its queryset and against the
        user's own list of people like any other, and that list may not contain
        the owner (a deactivated user, or one outside the user's hierarchy).
        Without this the lead could not be saved at all, though only the owner
        is locked. The owner cannot change, because the form puts the stored
        one back in ``clean()``.
        """
        self._unrestricted_fields = set(getattr(self, "_unrestricted_fields", ())) | {
            OWNER_FIELD
        }
        field = self.fields.get(OWNER_FIELD)
        queryset = getattr(field, "queryset", None)
        if queryset is None:
            return
        owner_id = getattr(
            self.instance, self.instance._meta.get_field(OWNER_FIELD).attname
        )
        field.queryset = queryset.model._base_manager.filter(pk=owner_id)

    def _assignment_applicable(self):
        """The option is offered on create forms while an active rule exists."""
        if self.instance is not None and self.instance.pk:
            return False
        return has_active_rules()

    def _assignment_company(self):
        """Company whose people can be assigned: the request's active company."""
        request = getattr(self, "request", None)
        if request is None:
            return None
        return getattr(request, "active_company", None) or getattr(
            request.user, "company", None
        )

    def _is_multi_step(self):
        return bool(getattr(self, "step_fields", None))

    def _apply_requested(self):
        """Whether the checkbox is ticked in the submitted (or stored) data."""
        data = getattr(self, "data", None)
        if not data:
            return False
        return forms.CheckboxInput().value_from_datadict(
            data, getattr(self, "files", None), self.add_prefix(APPLY_FIELD)
        )

    def _conditions(self):
        """The active conditions, loaded once for this form."""
        if self._conditions_cache is None:
            self._conditions_cache = active_conditions()
        return self._conditions_cache

    def _criteria_fields(self):
        """Names of the fields the active rules look at, in a stable order."""
        names = []
        for condition in self._conditions():
            for criteria in condition.criteria.all():
                if criteria.field not in names:
                    names.append(criteria.field)
        return names

    def _htmx_attrs(self):
        """Attributes that make the checkbox reload the owner field."""
        fields = self._criteria_fields()
        include = ", ".join(f"[name='{name}']" for name in [OWNER_FIELD, *fields])
        # Reload when the checkbox itself is toggled and, while it is ticked,
        # when a field the rules depend on changes. The field is listened to
        # directly: select2 sends its change to the select only, it does not
        # bubble to the form. A change of the owner itself must not reload it,
        # or the dropdown would reset while it is being used.
        mode = "multi" if self._is_multi_step() else "single"
        triggers = ["change"]
        triggers += [f"change[this.checked] from:#id_{name}" for name in fields]
        trigger = ", ".join(triggers)
        return {
            "id": f"id_{APPLY_FIELD}",
            "hx-get": reverse_lazy("leads:assignment_rule_owner"),
            "hx-trigger": trigger,
            "hx-include": include,
            "hx-target": OWNER_BOX_SELECTOR,
            "hx-swap": "innerHTML",
            "hx-sync": "this:replace",
            "hx-vals": json.dumps({"mode": mode}),
            # Same box as the Shift hours form's checkbox options, a little smaller.
            "class": "shrink-0 bg-[#E9EDF7] rounded-sm accent-primary-600",
            "style": "width: 14px; height: 14px",
        }

    def _checkbox_html(self):
        """The "Assign using rules" checkbox shown under the Owner field."""
        box = forms.CheckboxInput(attrs=self._htmx_attrs()).render(
            self.add_prefix(APPLY_FIELD), self._checkbox_checked
        )
        return format_html(
            '<label for="id_{}" class="mt-2 w-fit flex items-center gap-2 '
            'text-color-600 cursor-pointer" style="font-size: 12px">'
            '{}<span class="select-none">{}</span></label>',
            APPLY_FIELD,
            box,
            _("Assign using rules"),
        )

    def _draw_checkbox_with_owner(self):
        """
        Make the Owner widget draw the checkbox right below the owner field.

        Drawn by the widget, the checkbox sits inside the owner's own box, so it
        is redrawn together with the owner when that box is swapped, and it
        follows the owner in Form Layout.
        """
        owner = self.fields.get(OWNER_FIELD)
        if owner is None or owner.widget.is_hidden:
            # A later step of the multi-step form keeps the owner as a hidden input.
            return
        widget = owner.widget
        if getattr(widget, "_draws_assignment_checkbox", False):
            return
        original_render = widget.render

        def render(name, value, attrs=None, renderer=None):
            field_html = original_render(name, value, attrs, renderer)
            note = self._owner_note
            return format_html("{}{}{}", field_html, note, self._checkbox_html())

        widget.render = render
        widget._draws_assignment_checkbox = True

    # -------------------------------------------------------------- owner pool

    def _enter_pool_mode(self, resolution, *, list_people=True):
        """Limit the owner field to ``resolution.users`` as a flat list of people."""
        owner = self.fields.get(OWNER_FIELD)
        if owner is None:
            return
        self._pool_mode = True
        # The generic form re-checks that the user may assign to the chosen
        # owner; people of a rule can be assigned whatever the user's own
        # permissions are, and membership of the pool is checked in clean().
        self._unrestricted_fields = set(getattr(self, "_unrestricted_fields", ())) | {
            OWNER_FIELD
        }
        owner.queryset = resolution.users
        if owner.widget.is_hidden:
            # A later step of the multi-step form keeps the owner as a hidden input.
            return

        choices = [("", "---------")]
        seen = set()
        # Until a condition is settled nobody is offered: the list would only
        # show people of rules the lead may not satisfy.
        for _label, users in resolution.groups if list_people else ():
            for user in users:
                if user.pk not in seen:
                    seen.add(user.pk)
                    choices.append((user.pk, str(user).strip() or user.username))
        owner.widget = forms.Select(
            choices=choices,
            attrs={"class": OWNER_SELECT_CLASS, "id": f"id_{OWNER_FIELD}"},
        )
        current = self.data.get(OWNER_FIELD) if self.data else None
        if current:
            self.initial[OWNER_FIELD] = current
        self._draw_checkbox_with_owner()

    def _hide_unsettled_pool(self, resolution):
        """
        True while the owner list is previewed and no condition is settled yet.

        A condition that still waits for a value the user can fill in on this
        form offers nobody. One that waits for a later step of the multi-step
        form can not be settled yet, so the people of the conditions that may
        still apply stay selectable and are checked on the last step.
        """
        if not self._assignment_preview or resolution.state != UNDETERMINED:
            return False
        later = self._unknown_names()
        return not any(
            criteria.field in later
            for condition in resolution.conditions
            for criteria in condition.criteria.all()
        )

    def _prefer_owner(self, resolution):
        """
        Pre-select the person the condition's method suggests.

        The form often arrives with an owner (Duplicate copies the source
        lead's, an owner left from an earlier preview stays). Keeping it would
        hand the same person every lead, whatever the method (least lead count
        or round robin), so the suggestion is selected again on each preview.
        The user can still pick anyone from the list afterwards.
        """
        owner = resolution.default_owner
        if owner is None:
            return
        data = self.data.copy()
        data[OWNER_FIELD] = owner.pk
        self.data = data

    # --------------------------------------------------------------- validation

    def _assignment_is_final(self):
        """True when the form holds every value a rule can look at."""
        if self._assignment_preview:
            return False
        if self._is_multi_step():
            return getattr(self, "current_step", 1) >= max(self.step_fields)
        return True

    def _unknown_names(self):
        """Fields whose value is not available yet on this step of the wizard."""
        if not self._is_multi_step() or self._assignment_is_final():
            return set()
        current = getattr(self, "current_step", 1)
        later = {
            name
            for step, names in self.step_fields.items()
            if step > current
            for name in names
        }
        # Custom fields are asked on the last step.
        custom = {name for name in self.fields if self._is_extension_field(name)}
        return later | custom

    @staticmethod
    def _is_extension_field(name):
        """True for a field that is not a Lead column, e.g. a custom field."""
        return get_condition_field_extension(name) is not None

    def _rule_data(self, cleaned_data):
        """The values the rules are checked against."""
        unknown = self._unknown_names()
        data = {
            name: value for name, value in cleaned_data.items() if name not in unknown
        }
        if self._assignment_preview:
            # The user may not have got to a blank field yet.
            data = {
                name: value
                for name, value in data.items()
                if value not in (None, "", [], ())
            }
        # Lead fields that are not on the form keep the value a new lead has.
        for name in self._criteria_fields():
            if name in data or name in self.fields or name in unknown:
                continue
            if self._is_extension_field(name):
                continue
            if hasattr(self.instance, name):
                data[name] = getattr(self.instance, name)
        return data

    def _owner_error(self, message):
        """Attach an owner error to the field when it is shown, else to the form."""
        owner = self.fields.get(OWNER_FIELD)
        if owner is not None and not owner.widget.is_hidden:
            self.add_error(OWNER_FIELD, message)
        else:
            self.add_error(None, message)

    def clean(self):
        """Check the lead against the rules when the checkbox is ticked."""
        cleaned_data = super().clean()
        if cleaned_data is None or not cleaned_data.get(APPLY_FIELD):
            return cleaned_data
        self._validate_assignment(cleaned_data)
        return cleaned_data

    def _validate_assignment(self, cleaned_data):
        final = self._assignment_is_final()
        if final and any(name != OWNER_FIELD for name in self._errors):
            # A value that failed its own validation is not known; the form is
            # rejected anyway and a "no match" would only add noise. The owner
            # is left out: it is checked against the rule's people below.
            final = False

        resolution = resolve_for_data(
            self._rule_data(cleaned_data),
            final=final,
            company=self._assignment_company(),
            conditions=self._conditions(),
        )
        self.assignment_resolution = resolution

        if resolution.state == NO_ASSIGNEES:
            self.add_error(None, resolution.reason)
            return
        if resolution.state == NO_MATCH:
            self.add_error(None, self._no_match_message(resolution.reason))
            return

        self._enter_pool_mode(
            resolution, list_people=not self._hide_unsettled_pool(resolution)
        )
        if resolution.state != MATCHED:
            # Which rule applies is not settled yet, so nobody is suggested.
            return
        if self._assignment_preview and self.fields.get(OWNER_FIELD) is not None:
            self._prefer_owner(resolution)

        owner = cleaned_data.get(OWNER_FIELD)
        if owner is None:
            return
        if not resolution.users.filter(pk=owner.pk).exists():
            self._owner_error(
                _("Choose one of the people rule “%(rule)s” assigns to.")
                % {"rule": resolution.rule.name}
            )
            return
        if final:
            self._assignment_decision = (resolution.condition, owner)

    @staticmethod
    def _no_match_message(reason):
        message = _(
            "The lead does not satisfy any active assignment rule%(reason)s. "
            "Change the values or untick “Assign using rules”."
        )
        return message % {"reason": f" ({reason})" if reason else ""}

    # ------------------------------------------------------------------- saving

    def save(self, commit=True):
        """Tell the post-save engine the owner was already decided by a rule."""
        decision = self._assignment_decision
        if decision is not None:
            condition, owner = decision
            self.instance._assignment_condition_id = condition.pk
            self.instance._assignment_owner_id = owner.pk
            self.instance.additional_info = build_assignment_info(
                self.instance.additional_info, condition, owner, VIA_FORM
            )
        return super().save(commit=commit)

    # ------------------------------------------------------------------ preview

    def render_owner_preview(self):
        """
        HTML that replaces the Owner box while the checkbox is toggled.

        Unticked: the owner field as the form normally renders it. Ticked: the
        owner field limited to the rule's people, with a short note. Both come
        with the checkbox under the field.
        """
        resolution = self.assignment_resolution
        if not self._apply_requested() or resolution is None:
            return str(self[OWNER_FIELD])

        if resolution.state == MATCHED:
            if resolution.condition.assignment_method == ASSIGNMENT_METHOD_ROUND_ROBIN:
                note = _(
                    "Rule “%(rule)s” applies. The owner is picked from its people "
                    "by round robin, the next person in turn; you can choose "
                    "another one."
                )
            else:
                note = _(
                    "Rule “%(rule)s” applies. The owner is picked from its people "
                    "by the fewest leads; you can choose another one."
                )
            note = note % {"rule": resolution.rule.name}
            css = "text-gray-500"
        elif resolution.state == UNDETERMINED:
            note = _("The rule is confirmed when the remaining fields are filled in.")
            css = "text-gray-500"
        elif resolution.state == NO_ASSIGNEES:
            note = resolution.reason
            css = "text-red-500"
        else:
            note = self._no_match_message(resolution.reason)
            css = "text-red-500"

        if resolution.state in (NO_MATCH, NO_ASSIGNEES):
            # Nobody can be picked from a rule, so show the owner field as it
            # is, with the checkbox still ticked.
            data = self.data.copy()
            data.pop(APPLY_FIELD, None)
            plain = self.__class__(data=data, request=self.request)
            plain._checkbox_checked = True
            plain._conditions_cache = self._conditions_cache
            plain._owner_note = format_html(
                '<p class="text-xs mt-1 {}">{}</p>', css, note
            )
            return str(plain[OWNER_FIELD])
        self._owner_note = format_html('<p class="text-xs mt-1 {}">{}</p>', css, note)
        return str(self[OWNER_FIELD])
