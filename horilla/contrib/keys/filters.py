"""
Filters for the keys app.
"""

# Third-party imports (Django)
from django.db.models import Q

# First party imports (Horilla)
from horilla.contrib.generics.filters import HorillaFilterSet

# Local imports
from .models import ShortcutKey
from .utils import get_all_page_titles


class ShortKeyFilter(HorillaFilterSet):
    """
    Filter set for ShortcutKey model.

    Used to filter, search, and manage shortcut key records
    across the application.
    """

    class Meta:
        """
        Meta configuration for ShortKeyFilter.
        """

        model = ShortcutKey
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = ["page", "key", "command"]

    def filter_search(self, queryset, name, value):
        """Search by page path, displayed page title, key and command."""
        value = (value or "").strip()
        if not value:
            return queryset

        needle = value.lower()
        matching_pages = [
            page
            for page, title in get_all_page_titles().items()
            if needle in str(title).lower()
        ]
        return queryset.filter(
            Q(page__icontains=value)
            | Q(key__icontains=value)
            | Q(command__icontains=value)
            | Q(page__in=matching_pages)
        )
