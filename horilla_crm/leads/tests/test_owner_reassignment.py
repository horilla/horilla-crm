"""
Tests for "Allow Owner Reassignment" on lead assignment rules.

For a lead a rule assigned, the owner can be changed by a superuser, by a user
with ``leads.change_lead``, and, while the option is on (the default), by a user
with ``leads.change_own_lead`` whose hierarchy covers the owner: the owner
themselves or a manager over them. Turned off, only the first two can. A lead no
rule assigned is never locked.
"""

# Standard library imports
from types import SimpleNamespace
from unittest import mock

# Third-party imports (Django)
from django.contrib.auth.models import Permission
from django.test import TestCase

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.models import Role
from horilla.contrib.utils.middlewares import _thread_local
from horilla.core.exceptions import PermissionDenied
from horilla_crm.leads.assignment.owner_lock import (
    can_bypass_owner_lock,
    is_rule_assigned,
    owner_locked,
    reassignment_allowed,
)
from horilla_crm.leads.assignment.pool import ADDITIONAL_INFO_KEY, OWNER_FIELD
from horilla_crm.leads.models import LeadAssignmentRule
from horilla_crm.leads.views.core import _change_owner_hidden_if

from .test_assignment_on_forms import AssignmentFixtureMixin

ASSIGNED = {ADDITIONAL_INFO_KEY: {"rule_name": "Website leads", "via": "auto"}}


class OwnerReassignmentTests(AssignmentFixtureMixin, TestCase):
    """The option, the form, the Change Owner action and the save guard."""

    def setUp(self):
        """A company, an active rule, and a lead the rule assigned."""
        self.create_fixture()
        self.condition = self.make_rule(users=[self.direct])
        self.rule = self.condition.rule
        self.full = self.make_user("full")
        self.grant(self.full, "change_lead")
        self.own = self.make_user("own")
        self.grant(self.own, "change_own_lead")
        # A manager over ``own``: only change_own_lead, but ``own`` is below them.
        rep_role = Role.objects.create(role_name="Rep", company=self.company)
        boss_role = Role.objects.create(role_name="Boss", company=self.company)
        rep_role.parent_role = boss_role
        rep_role.save()
        User.objects.filter(pk=self.own.pk).update(role=rep_role)
        self.own.refresh_from_db()
        self.manager = self.make_user("manager", role=boss_role)
        self.grant(self.manager, "change_own_lead")
        # Has change_own_lead too, but is not above anybody.
        self.stranger = self.make_user("stranger")
        self.grant(self.stranger, "change_own_lead")
        self.lead = self.create_lead(self.own, additional_info=ASSIGNED)
        self.plain_lead = self.create_lead(self.own)
        self.addCleanup(self.clear_request)

    def grant(self, user, codename):
        """Give ``user`` one Lead permission."""
        user.user_permissions.add(
            Permission.objects.get(codename=codename, content_type__app_label="leads")
        )

    def set_option(self, allowed):
        """Turn "Allow Owner Reassignment" on or off for the active rule."""
        LeadAssignmentRule.all_objects.filter(pk=self.rule.pk).update(
            allow_owner_reassignment=allowed
        )

    def refetch(self, lead):
        """The lead as it is stored, so the user's cached permissions do not leak."""
        return type(lead).all_objects.get(pk=lead.pk)

    def login(self, user):
        """Make ``user`` the signed-in user of the current thread."""
        _thread_local.request = self.request_for(user)

    @staticmethod
    def clear_request():
        """Forget the signed-in user."""
        if hasattr(_thread_local, "request"):
            del _thread_local.request

    def edit_form(self, user, lead=None, data=None):
        """The single-step form editing ``lead`` as ``user``."""
        lead = lead or self.lead
        return self.single_form(data, user=user, instance=lead)

    def owner_payload(self, lead, owner):
        """Edit data that keeps the lead as it is but sets the owner."""
        return self.lead_payload(lead_owner=owner.pk, email=lead.email)

    # -------------------------------------------------------------- the option

    def test_option_is_on_by_default(self):
        """A rule, new or existing, keeps the owner editable as it was."""
        self.assertTrue(
            LeadAssignmentRule.objects.create(
                name="New", company=self.company
            ).allow_owner_reassignment
        )
        self.assertTrue(self.refetch_rule().allow_owner_reassignment)

    def refetch_rule(self):
        """The rule as it is stored."""
        return LeadAssignmentRule.all_objects.get(pk=self.rule.pk)

    def test_rule_form_offers_the_option(self):
        """The rule's create / edit form has the checkbox."""
        from horilla_crm.leads.views.assignment_rule import LeadAssignmentForm

        self.assertIn("allow_owner_reassignment", LeadAssignmentForm.fields)

    # -------------------------------------------------------- who is locked

    def test_rule_assigned_lead_is_recognised(self):
        """Leads are recognised by the assignment record, nothing else."""
        self.assertTrue(is_rule_assigned(self.lead))
        self.assertFalse(is_rule_assigned(self.plain_lead))
        self.assertFalse(is_rule_assigned(SimpleNamespace(additional_info=None)))
        self.assertFalse(is_rule_assigned(SimpleNamespace(additional_info={"a": 1})))

    def test_the_owner_may_reassign_while_the_option_is_on(self):
        """The assigned user with change_own_lead can change the owner."""
        self.assertFalse(owner_locked(self.refetch(self.lead), self.own))
        for user in (self.full, self.admin):
            self.assertFalse(owner_locked(self.refetch(self.lead), user))

    def test_a_manager_over_the_owner_may_reassign_while_the_option_is_on(self):
        """Nothing changes for a manager: change_own_lead covers their team."""
        self.assertFalse(owner_locked(self.refetch(self.lead), self.manager))

    def test_a_user_who_does_not_cover_the_owner_is_locked(self):
        """change_own_lead only reaches the owner's own team."""
        self.assertTrue(owner_locked(self.refetch(self.lead), self.stranger))

    def test_user_without_change_permission_is_locked(self):
        """Owning the lead is not enough without change_own_lead."""
        stranger = self.create_lead(self.direct, additional_info=ASSIGNED)
        self.assertTrue(owner_locked(self.refetch(stranger), self.direct))

    def test_the_owner_is_locked_when_the_option_is_off(self):
        """Turned off, change_own_lead no longer allows a reassignment."""
        self.set_option(False)
        self.assertTrue(owner_locked(self.refetch(self.lead), self.own))
        self.assertTrue(owner_locked(self.refetch(self.lead), self.manager))
        self.assertTrue(owner_locked(self.refetch(self.lead), self.stranger))

    def test_change_all_user_and_superuser_are_never_locked(self):
        """The existing permission, or a superuser, can still change the owner."""
        self.set_option(False)
        self.assertTrue(can_bypass_owner_lock(self.full))
        self.assertFalse(owner_locked(self.refetch(self.lead), self.full))
        self.assertFalse(owner_locked(self.refetch(self.lead), self.admin))

    def test_a_lead_no_rule_assigned_is_never_locked(self):
        """Manually created leads keep the owner behaviour they had."""
        self.set_option(False)
        self.assertFalse(owner_locked(self.plain_lead, self.own))

    def test_new_lead_and_anonymous_user_are_not_locked(self):
        """Only a stored lead and a signed-in user can be locked."""
        self.set_option(False)
        unsaved = SimpleNamespace(pk=None, additional_info=ASSIGNED, company_id=1)
        self.assertFalse(owner_locked(unsaved, self.own))
        self.assertFalse(owner_locked(self.lead, None))

    def test_without_an_active_rule_nothing_is_locked(self):
        """No rule to read the option from: reassignment stays allowed."""
        self.set_option(False)
        LeadAssignmentRule.all_objects.filter(pk=self.rule.pk).update(is_active=False)
        self.assertTrue(reassignment_allowed(self.company.pk))
        self.assertFalse(owner_locked(self.refetch(self.lead), self.own))

    def test_option_is_read_once_per_request(self):
        """A list asks once per row; the answer is kept for the request."""
        self.set_option(False)
        self.login(self.own)
        lead = self.refetch(self.lead)
        with mock.patch.object(
            LeadAssignmentRule.all_objects, "filter", wraps=None
        ) as filtered:
            filtered.return_value.values_list.return_value.first.return_value = False
            for _ in range(5):
                owner_locked(lead, self.own)
        self.assertEqual(filtered.call_count, 1)

    # ------------------------------------------------------------------ forms

    def test_owner_field_is_read_only_for_a_locked_user(self):
        """A posted owner is ignored: the stored one is kept."""
        self.set_option(False)
        form = self.edit_form(
            self.own, data=self.owner_payload(self.lead, self.sales[0])
        )
        self.assertEqual(form.field_permissions[OWNER_FIELD], "readonly")
        self.assertTrue(form.fields[OWNER_FIELD].disabled)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data[OWNER_FIELD], self.own)
        form.save()
        self.assertEqual(self.refetch(self.lead).lead_owner, self.own)

    def test_manager_form_is_editable_while_the_option_is_on(self):
        """A manager editing a team member's lead keeps the owner field."""
        form = self.edit_form(self.manager)
        self.assertNotEqual(form.field_permissions.get(OWNER_FIELD), "readonly")

    def test_manager_form_is_read_only_when_the_option_is_off(self):
        """Turned off, the manager's owner field is locked like anybody's."""
        self.set_option(False)
        form = self.edit_form(
            self.manager, data=self.owner_payload(self.lead, self.sales[0])
        )
        self.assertEqual(form.field_permissions[OWNER_FIELD], "readonly")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data[OWNER_FIELD], self.own)

    def test_owner_field_accepts_the_current_owner_outside_the_users_list(self):
        """The owner is not in the user's list, yet the lead can still be saved."""
        lead = self.create_lead(self.direct, additional_info=ASSIGNED)
        form = self.edit_form(self.stranger, lead=lead)
        self.assertNotIn(self.direct.pk, self.hierarchy_pks(self.stranger))
        self.assertEqual(
            list(form.fields[OWNER_FIELD].queryset.values_list("pk", flat=True)),
            [self.direct.pk],
        )

    def hierarchy_pks(self, user):
        """The people the user could pick as an owner without the lock."""
        form = self.single_form(user=user, instance=self.plain_lead)
        return set(form.fields[OWNER_FIELD].queryset.values_list("pk", flat=True))

    def test_multi_step_form_locks_the_owner_too(self):
        """The wizard marks the owner read-only the same way."""
        from horilla.extension.forms.resolve import resolve_form_class
        from horilla_crm.leads.forms import LeadFormClass

        self.set_option(False)
        form = resolve_form_class(LeadFormClass)(
            request=self.request_for(self.own), instance=self.lead, step=1
        )
        self.assertEqual(form.field_permissions[OWNER_FIELD], "readonly")
        self.assertTrue(form.fields[OWNER_FIELD].disabled)

        form = resolve_form_class(LeadFormClass)(
            request=self.request_for(self.full), instance=self.lead, step=1
        )
        self.assertNotEqual(form.field_permissions.get(OWNER_FIELD), "readonly")

    def test_other_fields_stay_editable_when_the_owner_is_locked(self):
        """Only the owner is locked; the rest of the lead can be changed."""
        self.set_option(False)
        form = self.edit_form(
            self.own,
            data=self.owner_payload(self.lead, self.own) | {"first_name": "Zed"},
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["first_name"], "Zed")
        self.assertEqual(form.cleaned_data[OWNER_FIELD], self.own)

    def test_owner_field_is_editable_for_the_owner_while_the_option_is_on(self):
        """The default: the assigned user's form is not touched."""
        form = self.edit_form(self.own)
        self.assertNotEqual(form.field_permissions.get(OWNER_FIELD), "readonly")

    def test_privileged_user_keeps_an_editable_owner(self):
        """With the option off a change-all user can still reassign."""
        self.set_option(False)
        for user in (self.full, self.admin):
            form = self.edit_form(user)
            self.assertNotEqual(
                (form.field_permissions or {}).get(OWNER_FIELD), "readonly"
            )

    def test_plain_lead_form_is_not_touched(self):
        """A lead no rule assigned is edited as before."""
        self.set_option(False)
        form = self.edit_form(self.own, lead=self.plain_lead)
        self.assertNotEqual((form.field_permissions or {}).get(OWNER_FIELD), "readonly")

    def test_create_form_is_not_touched(self):
        """A new lead has no owner to protect."""
        self.set_option(False)
        form = self.single_form(user=self.own)
        self.assertNotEqual((form.field_permissions or {}).get(OWNER_FIELD), "readonly")

    # ------------------------------------------------ Change Owner action

    def test_change_owner_action_is_hidden_only_for_a_locked_user(self):
        """The action disappears for a locked user and nobody else."""
        lead = self.refetch(self.lead)
        self.login(self.stranger)
        self.assertTrue(_change_owner_hidden_if(lead))
        self.clear_request()
        self.login(self.manager)
        self.assertFalse(_change_owner_hidden_if(lead))
        self.clear_request()
        self.login(self.own)
        self.assertFalse(_change_owner_hidden_if(lead))
        self.set_option(False)
        self.clear_request()
        self.login(self.own)
        self.assertTrue(_change_owner_hidden_if(lead))
        self.clear_request()
        self.login(self.full)
        self.assertFalse(_change_owner_hidden_if(lead))

    # ------------------------------------------------ Edit Details (detail tab)

    def section_view(self, user, lead=None):
        """The Details tab the way Edit Details builds it for ``user``."""
        from horilla.contrib.generics.views.helpers.edit_field import (
            _get_section_view_instance,
        )

        lead = lead or self.lead
        view = _get_section_view_instance(type(lead), self.request_for(user), lead.pk)
        view.object = self.refetch(lead)
        return view

    def test_edit_details_does_not_offer_the_owner_to_a_locked_user(self):
        """Edit Details shows the owner as plain text for a locked user."""
        self.set_option(False)
        self.assertIn(OWNER_FIELD, self.section_view(self.own).non_editable_fields)
        self.assertIn(OWNER_FIELD, self.section_view(self.manager).non_editable_fields)

    def test_edit_details_is_not_touched_for_everybody_else(self):
        """Option on, a privileged user, or a plain lead: the owner is editable."""
        self.assertEqual(self.section_view(self.own).non_editable_fields, [])
        self.assertEqual(self.section_view(self.manager).non_editable_fields, [])
        self.assertEqual(
            self.section_view(self.stranger, self.plain_lead).non_editable_fields, []
        )
        self.set_option(False)
        self.assertEqual(self.section_view(self.full).non_editable_fields, [])
        self.assertEqual(self.section_view(self.admin).non_editable_fields, [])
        self.assertEqual(
            self.section_view(self.own, self.plain_lead).non_editable_fields, []
        )

    # ------------------------------------------------------- the save guard

    def change_owner(self, lead, owner):
        """Save ``lead`` with another owner, the way an inline edit would."""
        lead = self.refetch(lead)
        setattr(lead, OWNER_FIELD, owner)
        lead.save()

    def test_save_guard_blocks_a_locked_user(self):
        """A request that skips the form still cannot change the owner."""
        self.set_option(False)
        self.login(self.own)
        with self.assertRaises(PermissionDenied):
            self.change_owner(self.lead, self.sales[0])
        self.assertEqual(self.refetch(self.lead).lead_owner, self.own)

    def test_save_guard_blocks_a_user_who_does_not_cover_the_owner(self):
        """change_own_lead does not reach a lead outside the user's team."""
        self.login(self.stranger)
        with self.assertRaises(PermissionDenied):
            self.change_owner(self.lead, self.sales[0])
        self.assertEqual(self.refetch(self.lead).lead_owner, self.own)

    def test_save_guard_lets_a_manager_reassign_while_the_option_is_on(self):
        """Nothing changes for a manager over the owner; off, they are locked."""
        self.login(self.manager)
        self.change_owner(self.lead, self.sales[0])
        self.assertEqual(self.refetch(self.lead).lead_owner, self.sales[0])

        self.set_option(False)
        self.clear_request()
        self.login(self.manager)
        with self.assertRaises(PermissionDenied):
            self.change_owner(self.lead, self.sales[1])

    def test_save_guard_judges_by_the_stored_owner(self):
        """The owner may hand the lead on: the new owner is not who is checked."""
        self.login(self.own)
        self.change_owner(self.lead, self.manager)
        self.assertEqual(self.refetch(self.lead).lead_owner, self.manager)

    def test_save_guard_allows_other_fields(self):
        """Saving the lead without a new owner is fine."""
        self.set_option(False)
        self.login(self.own)
        lead = self.refetch(self.lead)
        lead.first_name = "Zed"
        lead.save()
        self.assertEqual(self.refetch(self.lead).first_name, "Zed")

    def test_save_guard_lets_everyone_else_through(self):
        """Option on, a privileged user, or a plain lead: the owner changes."""
        self.login(self.own)
        self.change_owner(self.lead, self.sales[0])
        self.assertEqual(self.refetch(self.lead).lead_owner, self.sales[0])

        self.set_option(False)
        self.login(self.full)
        self.change_owner(self.lead, self.sales[1])
        self.assertEqual(self.refetch(self.lead).lead_owner, self.sales[1])

        self.login(self.own)
        self.change_owner(self.plain_lead, self.sales[2])
        self.assertEqual(self.refetch(self.plain_lead).lead_owner, self.sales[2])

    def test_save_guard_ignores_saves_without_a_signed_in_user(self):
        """Background jobs and scripts have no request and are not restricted."""
        self.set_option(False)
        self.clear_request()
        self.change_owner(self.lead, self.sales[0])
        self.assertEqual(self.refetch(self.lead).lead_owner, self.sales[0])

    def test_save_guard_ignores_workflow_actions(self):
        """A workflow's own save is the administrator's automation."""
        self.set_option(False)
        self.login(self.own)
        _thread_local._workflow_executing = {(type(self.lead), self.lead.pk)}
        self.addCleanup(setattr, _thread_local, "_workflow_executing", set())
        self.change_owner(self.lead, self.sales[0])
        self.assertEqual(self.refetch(self.lead).lead_owner, self.sales[0])

    def test_save_guard_does_not_query_for_a_plain_lead(self):
        """No assignment record, no extra query."""
        self.set_option(False)
        self.login(self.own)
        lead = self.refetch(self.plain_lead)
        setattr(lead, OWNER_FIELD, self.sales[0])
        with mock.patch(
            "horilla_crm.leads.assignment.owner_lock.reassignment_allowed"
        ) as allowed:
            lead.save()
        allowed.assert_not_called()
