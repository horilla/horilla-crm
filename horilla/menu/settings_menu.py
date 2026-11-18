"""
Settings menu registry for Horilla, managing settings pages with permissions and ordering.
"""

from typing import Any, Dict, List, Type

from horilla.menu import condition_met

settings_registry: List[Any] = []


def register(cls: Type[Any]):
    """Decorator to register a settings page class."""
    settings_registry.append(cls)
    return cls


def get_settings_menu(request=None) -> List[Dict]:
    """Return all registered settings pages as dicts (optionally filter by request)."""
    pages = []

    for cls in sorted(
        settings_registry,
        key=lambda c: (
            (
                0
                if hasattr(c, "order") and getattr(c, "order") >= 0
                else 1 if not hasattr(c, "order") else 2
            ),
            getattr(c, "order", 0),
        ),
    ):
        obj = cls()
        if not condition_met(getattr(obj, "condition", True), request):
            continue

        data = {
            "title": getattr(obj, "title", None),
            "icon": getattr(obj, "icon", None),
            "items": [],
        }

        perm_list = []
        items = getattr(obj, "items", [])
        items = sorted(
            items,
            key=lambda i: (
                0 if "order" in i and i["order"] >= 0 else 1 if "order" not in i else 2,
                i.get("order", 0),
            ),
        )

        for item in items:
            if callable(item):
                item = item(request) or {}
                if not item:
                    continue

            if not condition_met(item.get("condition", True), request):
                continue

            data["items"].append(item)

            if (
                isinstance(item, dict)
                and item.get("perm")
                and isinstance(item["perm"], str)
            ):
                perm_list.append(item["perm"])

        if (
            request
            and request.user.is_authenticated
            and (not perm_list or request.user.has_any_perms(perm_list))
        ):
            pages.append(data)

    return pages
