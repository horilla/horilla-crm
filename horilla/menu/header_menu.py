"""
Header account-menu registry.

A registered class is one dropdown link, the same shape as a My Settings
entry: ``title`` and ``url``, plus optional ``order``, ``perm``, and
``condition``. Extra HTML attributes belong in ``attrs`` and are copied
onto the ``<a>``.
"""

from typing import Any, Dict, List, Type

from horilla.menu import condition_met

header_registry: List[Any] = []


def register(cls: Type[Any]):
    """Decorator to register one header account-menu link."""
    header_registry.append(cls)
    return cls


def _order_key(order):
    """Sort non-negative orders first, missing orders next, negatives last."""
    if order is None:
        return (1, 0)
    if order >= 0:
        return (0, order)
    return (2, order)


def get_header_menu(request=None) -> List[Dict]:
    """Return visible account-dropdown rows for the header template.

    Each row is ``title``, ``url``, ``order``, and ``attrs``. The template
    writes ``attrs`` onto the anchor. An empty ``url`` renders a button.
    """
    rows = []
    for cls in header_registry:
        obj = cls()
        if not condition_met(getattr(obj, "condition", True), request):
            continue

        perm = getattr(obj, "perm", None)
        if perm and request:
            user = getattr(request, "user", None)
            if (
                user is None
                or not getattr(user, "is_authenticated", False)
                or not user.has_any_perms(
                    [perm] if isinstance(perm, str) else list(perm)
                )
            ):
                continue

        rows.append(
            {
                "title": getattr(obj, "title", None),
                "url": getattr(obj, "url", None) or "",
                "order": getattr(obj, "order", 100),
                "attrs": getattr(obj, "attrs", {}) or {},
            }
        )

    rows.sort(key=lambda row: _order_key(row["order"]))
    return rows
