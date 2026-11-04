"""
This module registers Floating, Settings, My Settings, and Main Section menus
for the duplicates app
"""

from horilla.menu import settings_menu

# First party imports (Horilla)
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import DuplicateRule, MatchingRule


@settings_menu.register
class DuplicateManagementSettings:
    """Settings menu entries for the duplicate management module."""

    title = _("Duplicate Control")
    icon = "/duplicates/assets/icons/clone.svg"
    order = 5
    items = [
        {
            "label": MatchingRule()._meta.verbose_name_plural,
            "url": reverse_lazy("duplicates:matching_rule_view"),
            "hx-target": "#settings-content",
            "hx-push-url": "true",
            "hx-select": "#matching-rule-view",
            "hx-select-oob": "#settings-sidebar",
            "perm": "duplicates.view_matchingrule",
            "order": 1,
        },
        {
            "label": DuplicateRule()._meta.verbose_name_plural,
            "url": reverse_lazy("duplicates:duplicate_rule_view"),
            "hx-target": "#settings-content",
            "hx-push-url": "true",
            "hx-select": "#duplicate-rule-view",
            "hx-select-oob": "#settings-sidebar",
            "perm": "duplicates.view_duplicaterule",
            "order": 2,
        },
    ]
