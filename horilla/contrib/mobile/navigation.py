"""
Bottom navigation of the mobile layout.
"""

# First party imports (Horilla)
from horilla.urls import reverse
from horilla.utils.translation import gettext_lazy as _

# One entry per mobile page, in display order. Later pages (Today, Records,
# Agenda) are added here as they ship.
NAV_ITEMS = [
    {
        "url_name": "more",
        "label": _("More"),
        "icon": "fa-solid fa-bars",
    },
]


def get_nav_items(request):
    """Return the bottom navigation entries, marking the current page active."""
    match = getattr(request, "resolver_match", None)
    current = match.url_name if match and match.namespace == "mobile" else None
    return [
        {
            "url": reverse(f"mobile:{item['url_name']}"),
            "label": item["label"],
            "icon": item["icon"],
            "active": item["url_name"] == current,
        }
        for item in NAV_ITEMS
    ]
