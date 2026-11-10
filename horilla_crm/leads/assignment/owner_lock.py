"""
Who may change the owner of a lead that an assignment rule assigned?

A user can change it when any of these holds:

* the user is a superuser;
* the user can change every lead (``leads.change_lead``);
* the active rule's "Allow Owner Reassignment" option is on, the user has
  ``leads.change_own_lead`` and the lead's current owner is one of the people
  that permission covers: the user, or somebody below them in the role
  hierarchy (``get_allowed_user_ids``).

So while the option is on (the default) nothing changes for anybody: whoever
could change the owner of such a lead before still can, a manager over their
team included. Turned off, a user who only has ``leads.change_own_lead`` can no
longer change it. Other fields of the lead stay editable, and a lead no rule
assigned is never locked.

A lead counts as assigned by a rule when ``additional_info["assignment"]`` is
set, which the engine and the lead forms both record, so leads assigned before
the option existed are covered too.

The lead forms, the Change Owner action and a ``pre_save`` guard all use these
functions, so the rule is enforced on the server and not only in the page.
"""

# First party imports (Horilla)
from horilla.contrib.core.utils import get_allowed_user_ids, get_current_request

# Local imports
from horilla_crm.leads.assignment.pool import ADDITIONAL_INFO_KEY, OWNER_FIELD
from horilla_crm.leads.models import LeadAssignmentRule

#: Users with this permission can always change the owner.
BYPASS_PERMISSION = "leads.change_lead"

#: With the option on, this permission lets a user reassign the leads it covers.
OWN_PERMISSION = "leads.change_own_lead"


def is_rule_assigned(lead):
    """Return True if an assignment rule chose the owner of ``lead``."""
    info = getattr(lead, "additional_info", None)
    return isinstance(info, dict) and bool(info.get(ADDITIONAL_INFO_KEY))


def reassignment_allowed(company_id):
    """
    Return the "Allow Owner Reassignment" option of the company's active rule.

    Without an active rule there is nothing to read, so reassignment is allowed.
    The answer is kept on the current request, because a list asks once per row.
    """
    if company_id is None:
        return True
    request = get_current_request()
    cache = None
    if request is not None:
        cache = getattr(request, "_owner_reassignment_cache", None)
        if cache is None:
            cache = request._owner_reassignment_cache = {}
        if company_id in cache:
            return cache[company_id]

    allowed = (
        LeadAssignmentRule.all_objects.filter(company_id=company_id, is_active=True)
        .values_list("allow_owner_reassignment", flat=True)
        .first()
    )
    allowed = True if allowed is None else allowed

    if cache is not None:
        cache[company_id] = allowed
    return allowed


def can_bypass_owner_lock(user):
    """Return True for a superuser or a user who can change every lead."""
    return bool(user.is_superuser or user.has_perm(BYPASS_PERMISSION))


def may_be_locked(lead, user):
    """
    Return True if the lock can apply to ``user`` and ``lead`` at all.

    Only the cheapest checks, none of them a query: a lead no rule assigned, a
    new lead, an anonymous user and a user who may always change the owner are
    never locked.
    """
    if lead is None or not lead.pk or not is_rule_assigned(lead):
        return False
    return not (
        user is None or not user.is_authenticated or can_bypass_owner_lock(user)
    )


def owner_locked(lead, user, current_owner_id=None):
    """
    Return True if ``user`` may not change the owner of ``lead``.

    ``current_owner_id`` is the owner as it is stored. It defaults to the
    lead's own owner, which is right unless the lead was changed in memory.
    The database is only read for a user whose permission covers the owner, to
    read the option.
    """
    if not may_be_locked(lead, user):
        return False
    if current_owner_id is None:
        current_owner_id = getattr(lead, lead._meta.get_field(OWNER_FIELD).attname)
    covered = current_owner_id in get_allowed_user_ids(user)
    if not covered or not user.has_perm(OWN_PERMISSION):
        return True
    return not reassignment_allowed(lead.company_id)
