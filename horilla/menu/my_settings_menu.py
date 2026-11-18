"""
My settings menu system for Horilla, with registration and permission-based filtering.
"""

from typing import Any, List, Type

from horilla.menu import condition_met

my_settings_menu: List[Any] = []


def register(cls: Type[Any]):
    """Decorator to register a settings menu class."""
    my_settings_menu.append(cls)
    return cls


def get_my_settings_menu(request=None) -> list[dict]:
    """Return registered settings menu items, filtered by conditions and permissions."""
    items = []
    for cls in my_settings_menu:
        obj = cls()
        if not condition_met(getattr(obj, "condition", True), request):
            continue

        perm = getattr(obj, "perm", None)
        if perm and request:
            if not request.user.is_authenticated or not request.user.has_any_perms(
                [perm] if isinstance(perm, str) else perm
            ):
                continue

        data = {
            "title": getattr(obj, "title", None),
            "url": getattr(obj, "url", None),
            "active_urls": getattr(obj, "active_urls", []),
            "icon": getattr(obj, "icon", None),
            "order": getattr(obj, "order", 100),
            "attrs": getattr(obj, "attrs", {}),
        }
        items.append(data)

    return sorted(
        items,
        key=lambda x: (
            (
                0
                if x["order"] is not None and x["order"] >= 0
                else 1 if x["order"] is None else 2
            ),
            x["order"] if x["order"] is not None else 0,
        ),
    )
