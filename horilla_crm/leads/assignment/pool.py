"""
Who can a lead be assigned to?

``resolve_for_data`` mirrors the engine's "first matching condition wins" rule
over a form's data and returns the people that condition can assign to. The
people are found with ``condition_users`` and the owner is picked with
``pick_for_condition`` (least lead count or round robin, as the condition says),
the same functions the post-save engine uses.
"""

# Standard library imports
from dataclasses import dataclass, field

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.db import transaction
from horilla.db.models import Count
from horilla.utils import timezone
from horilla.utils.translation import gettext as _

# Local imports
from horilla_crm.leads.models import Lead, LeadAssignmentCondition
from horilla_crm.leads.models.assignment_rules import ASSIGNMENT_METHOD_ROUND_ROBIN

from .evaluation import Match, condition_result, explain_failure

# The field that holds a lead's owner, as the Lead model declares it.
OWNER_FIELD = Lead.OWNER_FIELDS[0]

MATCHED = "matched"
UNDETERMINED = "undetermined"
NO_MATCH = "no_match"
NO_ASSIGNEES = "no_assignees"

# Where the owner of a lead was decided, as stored in ``additional_info``.
VIA_FORM = "form"
VIA_AUTO = "auto"

# Key of ``Lead.additional_info`` that records the assignment.
ADDITIONAL_INFO_KEY = "assignment"

# How many failing conditions are named in an error message.
MAX_REASONS = 3


@dataclass
class Resolution:
    """What the assignment rules say about a lead (or a part of one)."""

    state: str
    condition: LeadAssignmentCondition | None = None
    conditions: list = field(default_factory=list)
    users: object = None
    default_owner: object = None
    reason: str = ""
    groups: list = field(default_factory=list)

    @property
    def rule(self):
        """The rule of the matched condition, if there is one."""
        return self.condition.rule if self.condition else None


def active_conditions():
    """
    Return the conditions of every active rule in the order the engine tries them.

    Rules are tried by creation date and each rule's conditions by creation
    date. Scoping to the active company is done by the model managers, as it
    is for the engine.
    """
    return list(
        LeadAssignmentCondition.objects.filter(rule__is_active=True)
        .select_related("rule")
        .prefetch_related("assign_to_users", "assign_to_roles", "criteria")
        .order_by("rule__created_at", "rule__pk", "created_at", "pk")
    )


def has_active_rules():
    """Return True if at least one active rule has a condition."""
    return LeadAssignmentCondition.objects.filter(rule__is_active=True).exists()


def condition_users(condition, company=None):
    """
    Return the active users a condition can assign to.

    * ``role`` type: everyone whose role is one of the condition's roles.
    * ``user`` type: the users picked on the condition.

    ``company`` narrows the result to one company; the engine does not pass it.
    """
    if condition.assign_to_type == "role":
        users = User.objects.filter(
            role__in=condition.assign_to_roles.all(), is_active=True
        )
    else:
        users = condition.assign_to_users.filter(is_active=True)
    if company is not None:
        users = users.filter(company=company)
    return users


def pick_least_loaded(users_qs):
    """
    From a queryset of users, return the one currently owning the fewest leads.
    Ties are broken by PK (lowest first) for determinism.
    """
    if not users_qs.exists():
        return None
    # How the user model reaches the leads it owns (the owner field's reverse name).
    leads_owned = Lead._meta.get_field(OWNER_FIELD).related_query_name()
    return (
        users_qs.annotate(lead_count=Count(leads_owned))
        .order_by("lead_count", "pk")
        .first()
    )


def pick_round_robin(users_qs, last_user_id=None):
    """
    From a queryset of users, return the next one in turn.

    People are taken in PK order. The turn goes to the first person after
    ``last_user_id``; after the last person it wraps to the first. The pointer
    is a PK, not a position, so people joining, leaving or being deactivated
    never break the rotation.
    """
    ordered = users_qs.order_by("pk")
    if last_user_id is not None:
        following = ordered.filter(pk__gt=last_user_id).first()
        if following is not None:
            return following
    return ordered.first()


def pick_for_condition(condition, users_qs, *, advance=False):
    """
    Pick one person from ``users_qs`` with the method the condition is set to.

    * least lead count (the default): see ``pick_least_loaded``.
    * round robin: the next person after the one who got the condition's last
      lead. With ``advance=True`` the turn is taken: the condition's pointer
      moves to the person returned, under a row lock so two leads created at
      the same time get different people. With ``advance=False`` (a preview)
      nothing is stored.
    """
    if condition.assignment_method != ASSIGNMENT_METHOD_ROUND_ROBIN:
        return pick_least_loaded(users_qs)
    if not advance:
        return pick_round_robin(users_qs, condition.last_assigned_user_id)

    with transaction.atomic():
        current = (
            LeadAssignmentCondition.all_objects.select_for_update()
            .values_list("last_assigned_user_id", flat=True)
            .get(pk=condition.pk)
        )
        user = pick_round_robin(users_qs, current)
        if user is not None:
            LeadAssignmentCondition.all_objects.filter(pk=condition.pk).update(
                last_assigned_user=user
            )
            condition.last_assigned_user_id = user.pk
    return user


def advance_rotation(condition_id, user_id):
    """
    Record that ``user_id`` took the turn of a round robin condition.

    Used when the owner was chosen on a form: the form only previews the next
    person, so the turn is taken once the lead is saved. Does nothing for a
    condition that uses another method.
    """
    LeadAssignmentCondition.all_objects.filter(
        pk=condition_id, assignment_method=ASSIGNMENT_METHOD_ROUND_ROBIN
    ).update(last_assigned_user_id=user_id)


def _pool_groups(conditions, company):
    """
    Group the people of ``conditions`` by where they come from, for display.

    A person who comes from more than one source is listed once, under the
    first. Groups are ``(label, [User, ...])``.
    """
    seen = set()
    groups = []
    for condition in conditions:
        rule_name = condition.rule.name
        if condition.assign_to_type == "role":
            sources = [
                (
                    f"{rule_name} · {role.role_name}",
                    condition_users_for_role(role, company),
                )
                for role in condition.assign_to_roles.all()
            ]
        else:
            sources = [
                (f"{rule_name} · {_('Users')}", condition_users(condition, company))
            ]
        for label, users in sources:
            members = [user for user in users if user.pk not in seen]
            seen.update(user.pk for user in members)
            if members:
                members.sort(key=lambda user: (str(user).lower(), user.pk))
                groups.append((label, members))
    return groups


def condition_users_for_role(role, company=None):
    """Return the active users of one role (used to label a pool by role)."""
    users = User.objects.filter(role=role, is_active=True)
    if company is not None:
        users = users.filter(company=company)
    return users


def _build(state, conditions, company, *, condition=None, reason=""):
    """Assemble a Resolution whose pool is everyone the conditions can assign to."""
    pks = set()
    for candidate in conditions:
        pks.update(condition_users(candidate, company).values_list("pk", flat=True))
    users = User.objects.filter(pk__in=pks, is_active=True)
    if state == MATCHED and condition is not None:
        # Only a preview: showing a form must not take anyone's turn.
        default_owner = pick_for_condition(condition, users)
    else:
        default_owner = pick_least_loaded(users)
    return Resolution(
        state=state,
        condition=condition,
        conditions=list(conditions),
        users=users,
        default_owner=default_owner,
        reason=reason,
        groups=_pool_groups(conditions, company),
    )


def union_resolution(company=None, conditions=None):
    """
    Return a Resolution whose pool is everyone any active condition can assign to.

    Used while a form is being validated, before the values that decide which
    condition applies are known, so every possible assignee is accepted for the
    owner field; the exact check is made afterwards with ``resolve_for_data``.
    ``conditions`` is the list from ``active_conditions()`` when the caller has
    it already, so it is not loaded again.
    """
    if conditions is None:
        conditions = active_conditions()
    conditions = [
        condition
        for condition in conditions
        if condition_users(condition, company).exists()
    ]
    return _build(UNDETERMINED, conditions, company)


def _failure_reason(failed, data, final):
    """Join the reasons the first few non-matching conditions give."""
    reasons = []
    for condition in failed:
        text = explain_failure(condition, data, final=final)
        if text and text not in reasons:
            reasons.append(text)
        if len(reasons) >= MAX_REASONS:
            break
    return "; ".join(reasons)


def resolve_for_data(data, *, final, company=None, conditions=None):
    """
    Decide which condition would assign a lead with the given values.

    Mirrors the engine: conditions are tried in order and the first one that
    matches *and has someone to assign to* wins. ``data`` maps field names to
    Python values (a form's ``cleaned_data``).

    * ``MATCHED``: that condition is settled; ``users`` are its people.
    * ``UNDETERMINED``: a condition ahead of any settled match still depends
      on values that are not known yet (``final=False`` only). ``users`` is the
      union of every condition that could still win.
    * ``NO_MATCH``: no condition matches; ``reason`` says why.
    * ``NO_ASSIGNEES``: a condition matches but nobody is available.

    ``conditions`` is the list from ``active_conditions()`` when the caller has
    it already, so it is not loaded again.
    """
    if conditions is None:
        conditions = active_conditions()
    candidates = []
    failed = []
    without_people = []
    winner = None

    for condition in conditions:
        result = condition_result(condition, data, final=final)
        if result is Match.NO:
            failed.append(condition)
            continue
        if not condition_users(condition, company).exists():
            without_people.append(condition)
            continue
        candidates.append(condition)
        if result is Match.YES:
            winner = condition
            break

    if winner is not None and candidates[0] is winner:
        return _build(MATCHED, [winner], company, condition=winner)
    if candidates:
        return _build(UNDETERMINED, candidates, company)
    if without_people:
        names = ", ".join(sorted({c.rule.name for c in without_people}))
        return Resolution(
            state=NO_ASSIGNEES,
            users=User.objects.none(),
            reason=_("%(rules)s has no active people to assign to.") % {"rules": names},
        )
    return Resolution(
        state=NO_MATCH,
        users=User.objects.none(),
        reason=_failure_reason(failed, data, final),
    )


def build_assignment_info(existing, condition, user, via):
    """
    Return ``additional_info`` with a record of how the owner was chosen.

    ``existing`` is the lead's current ``additional_info``; it is copied, not
    changed, and keys other features keep there are left alone. The ids are
    stored with the rule's name so the history stays readable if the rule is
    renamed or deleted later.
    """
    info = dict(existing or {})
    info[ADDITIONAL_INFO_KEY] = {
        "rule_id": condition.rule_id,
        "rule_name": condition.rule.name,
        "condition_id": condition.pk,
        "assigned_user_id": user.pk,
        "via": via,
        "assigned_at": timezone.now().isoformat(),
    }
    return info
