"""
Remember the total behind a whole-role split, and notice when it stops adding up.

A whole-role split saves ordinary per-user ``ForecastTarget`` rows. To keep the role
total that was entered, each of those rows gets a small note in the model's existing
``additional_info`` JSON field (no schema change), under the ``role_target`` key:

    batch        id shared by every target created in one Save
    role_id / role_name
    include_below   whether the roles below were included
    total        the role total that was entered (a decimal string)
    share        this user's share at the time
    set_by / set_at

The note is a soft link, not a constraint. The check compares the stored ``total``
with what the batch's targets add up to *now*, so it can never go stale: edit or delete
one target and the difference shows.

Targets saved before this existed simply have no note and are never flagged.
"""

# Standard library imports
import uuid
from decimal import Decimal, InvalidOperation

from horilla.contrib.utils.middlewares import _thread_local

# First party imports (Horilla)
from horilla.db import transaction
from horilla.db.models import Count, Max, Q, Sum
from horilla.utils import timezone

KEY = "role_target"
_BATCH = f"additional_info__{KEY}__batch"
_ROLE = f"additional_info__{KEY}__role_id"
_TOTAL = f"additional_info__{KEY}__total"
_NAME = f"additional_info__{KEY}__role_name"
_INCLUDE = f"additional_info__{KEY}__include_below"


def _to_decimal(value):
    """A stored decimal string back to ``Decimal`` (0 when missing or malformed)."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def money(value):
    """An amount for messages: thousands separators, no needless decimals (1,030.5)."""
    text = f"{_to_decimal(value):,.2f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def new_batch_id():
    """A fresh id for the targets created by one Save."""
    return uuid.uuid4().hex


def stamp(info, *, batch, role, total, include_below, share, user):
    """
    ``info`` (a target's ``additional_info``) with the role-target note added.

    The dict is merged, never replaced, because other features may keep their own keys
    in the same field.
    """
    info = dict(info or {})
    info[KEY] = {
        "batch": batch,
        "role_id": role.pk,
        "role_name": role.role_name,
        "include_below": bool(include_below),
        "total": str(total),
        "share": str(share),
        "set_by": user.pk,
        "set_at": timezone.now().isoformat(),
    }
    return info


def note_of(target):
    """The role-target note on ``target``, or ``None`` for an ordinary target."""
    info = getattr(target, "additional_info", None)
    note = info.get(KEY) if isinstance(info, dict) else None
    return note if isinstance(note, dict) and note.get("batch") else None


def batch_sums(model):
    """
    ``{batch id: (current sum, number of targets)}`` for every role-target batch.

    One grouped query, cached on the current request so a list page asks only once.
    """
    request = getattr(_thread_local, "request", None)
    cached = getattr(request, "_role_target_sums", None) if request else None
    if cached is not None:
        return cached
    sums = {
        row[_BATCH]: (row["current"] or Decimal("0"), row["members"])
        for row in model.objects.filter(is_active=True, **{f"{_BATCH}__isnull": False})
        .values(_BATCH)
        .annotate(current=Sum("target_amount"), members=Count("id"))
    }
    if request is not None:
        request._role_target_sums = sums
    return sums


def status_of(target):
    """
    How a target's role total compares with what its batch adds up to now.

    ``None`` for a target with no note. Otherwise a dict with ``role_name``, ``total``
    (entered), ``current`` (now), ``difference`` (total minus current), ``matches`` and
    ``members``.
    """
    note = note_of(target)
    if not note:
        return None
    current, members = batch_sums(type(target)).get(note["batch"], (Decimal("0"), 0))
    total = _to_decimal(note.get("total"))
    return {
        "role_name": note.get("role_name") or "",
        "total": total,
        "current": current,
        "difference": total - current,
        "matches": total == current,
        "members": members,
    }


def drift_by_role(model, period_ids, forecast_type):
    """
    The latest role total per ``(period id, role id)`` against what it adds up to now.

    Used by the forecast table's role rows. When a role was split more than once for
    the same period (for example after new users joined), the newest batch wins.
    """
    rows = (
        model.objects.filter(
            is_active=True,
            period_id__in=list(period_ids),
            forcasts_type=forecast_type,
            **{f"{_BATCH}__isnull": False},
        )
        .values("period_id", _BATCH, _ROLE, _TOTAL)
        .annotate(current=Sum("target_amount"), newest=Max("created_at"))
    )
    latest = {}
    for row in rows:
        key = (row["period_id"], row[_ROLE])
        if key not in latest or row["newest"] > latest[key]["newest"]:
            latest[key] = row
    result = {}
    for key, row in latest.items():
        total = _to_decimal(row[_TOTAL])
        current = row["current"] or Decimal("0")
        result[key] = {
            "total": total,
            "current": current,
            "difference": total - current,
            "matches": total == current,
        }
    return result


def current_sum(model, batch):
    """What a batch's active targets add up to right now (always fresh, never cached)."""
    return model.objects.filter(is_active=True, **{f"{_BATCH}": batch}).aggregate(
        total=Sum("target_amount")
    )["total"] or Decimal("0")


def can_change_total(user, model, batch):
    """
    Whether ``user`` may change a role total.

    A role total spans every target of its batch, so changing it is only allowed to
    someone who could set a target for each of those users: an admin (no restriction),
    or a manager whose subtree contains all of them. A manager editing one report's
    target inside a total their own boss set cannot move that total.
    """
    from horilla_crm.forecast.utils import get_assignable_target_user_ids

    allowed = get_assignable_target_user_ids(user)
    if allowed is None:
        return True
    members = set(
        getattr(model, "all_objects", model.objects)
        .filter(**{_BATCH: batch})
        .values_list("assigned_to_id", flat=True)
    )
    return members <= allowed


def change_total(model, batch, new_total, user):
    """
    Make ``new_total`` the role total of every target in ``batch``.

    Each note keeps the total it had (``previous_total``) and who changed it and when,
    so the history of a role total is not lost. Returns how many targets were updated.
    """
    members = getattr(model, "all_objects", model.objects).filter(**{_BATCH: batch})
    changed = 0
    with transaction.atomic():
        for target in members:
            note = note_of(target)
            if not note:
                continue
            note["previous_total"] = note.get("total")
            note["total"] = str(new_total)
            note["total_changed_by"] = user.pk
            note["total_changed_at"] = timezone.now().isoformat()
            info = dict(target.additional_info or {})
            info[KEY] = note
            target.additional_info = info
            target.save(update_fields=["additional_info"])
            changed += 1
    return changed


def rescale_total(model, batch, new_total, user, role_id=None):
    """
    Make ``new_total`` the role total and scale every user's target to match.

    Each target is multiplied by new total / what they add up to now, so unequal splits
    stay proportionally unequal. Cents are rounded per user and the last user takes the
    remainder, so the targets add up to exactly ``new_total``. A role total whose
    targets add up to nothing is divided equally instead. Notes keep the previous total
    and who changed it. Returns how many targets were updated.

    With ``role_id`` only that role's users are scaled, to ``new_total`` for the role.
    The role total then follows (it becomes what all the targets add up to) when it
    matched before the change, and is left alone when it did not.
    """
    from decimal import ROUND_HALF_UP

    cent = Decimal("0.01")
    members = list(
        getattr(model, "all_objects", model.objects)
        .filter(is_active=True, **{_BATCH: batch})
        .select_related("assigned_to")
        .order_by("id")
    )
    members = [m for m in members if note_of(m)]
    everyone = members
    if role_id is not None:
        members = [m for m in everyone if m.assigned_to.role_id == int(role_id)]
    if not members:
        return 0
    batch_matched = None
    if role_id is not None:
        batch_sum = sum((m.target_amount for m in everyone), Decimal("0"))
        batch_matched = batch_sum == Decimal(
            str(note_of(everyone[0]).get("total") or 0)
        )
    old_sum = sum((m.target_amount for m in members), Decimal("0"))
    if old_sum > 0:
        amounts = [
            (m.target_amount * new_total / old_sum).quantize(cent, ROUND_HALF_UP)
            for m in members
        ]
    else:
        amounts = [(new_total / len(members)).quantize(cent, ROUND_HALF_UP)] * len(
            members
        )
    amounts[-1] = new_total - sum(amounts[:-1], Decimal("0"))
    new_by_id = {t.pk: a for t, a in zip(members, amounts)}
    if role_id is None:
        batch_total = new_total
    elif batch_matched:
        others = sum(
            (m.target_amount for m in everyone if m.pk not in new_by_id), Decimal("0")
        )
        batch_total = others + new_total
    else:
        batch_total = None  # the role total stays as it was
    with transaction.atomic():
        for target in everyone:
            if target.pk not in new_by_id and batch_total is None:
                continue
            note = note_of(target)
            if batch_total is not None:
                note["previous_total"] = note.get("total")
                note["total"] = str(batch_total)
                note["total_changed_by"] = user.pk
                note["total_changed_at"] = timezone.now().isoformat()
            fields = ["additional_info"]
            if target.pk in new_by_id:
                note["share"] = str(new_by_id[target.pk])
                target.target_amount = new_by_id[target.pk]
                fields.append("target_amount")
            info = dict(target.additional_info or {})
            info[KEY] = note
            target.additional_info = info
            target.save(update_fields=fields)
    return len(members)


def list_batches(model, period_id=None, forecast_type_id=None, visible_ids=None):
    """
    The role totals to show in the target list, newest first within each role.

    One dict per batch: ``batch``, ``role_id``, ``role_name``, ``include_below``,
    ``total`` (entered), ``current`` (what all its active targets add up to), ``members``,
    ``visible_members`` and ``visible_current`` (only users in ``visible_ids``; all of
    them when it is ``None``), ``set_at`` and ``matches``.

    A viewer who can only see some of a batch's users sees those users' figures and no
    verdict (``matches`` is ``None``), because the full sum would reveal targets they are
    not allowed to see. Batches with none of their users are left out.
    """
    queryset = model.objects.filter(is_active=True, **{f"{_BATCH}__isnull": False})
    if period_id:
        queryset = queryset.filter(period_id=period_id)
    if forecast_type_id:
        queryset = queryset.filter(forcasts_type_id=forecast_type_id)
    seen = Q() if visible_ids is None else Q(assigned_to_id__in=list(visible_ids))
    rows = queryset.values(_BATCH, _ROLE, _NAME, _TOTAL, _INCLUDE).annotate(
        current=Sum("target_amount"),
        members=Count("id"),
        visible_current=Sum("target_amount", filter=seen),
        visible_members=Count("id", filter=seen),
        set_at=Max("created_at"),
    )
    batches = []
    for row in rows:
        if not row["visible_members"]:
            continue
        total = _to_decimal(row[_TOTAL])
        current = row["current"] or Decimal("0")
        complete = row["visible_members"] == row["members"]
        batches.append(
            {
                "batch": row[_BATCH],
                "role_id": row[_ROLE],
                "role_name": row[_NAME] or "",
                "include_below": bool(row[_INCLUDE]),
                "total": total,
                "current": current,
                "members": row["members"],
                "visible_members": row["visible_members"],
                "visible_current": row["visible_current"] or Decimal("0"),
                "set_at": row["set_at"],
                "complete": complete,
                "matches": (total == current) if complete else None,
            }
        )
    batches.sort(key=lambda b: (b["role_name"].lower(), -b["set_at"].timestamp()))
    return batches
