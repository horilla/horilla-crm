"""
Horilla generics views package.

Aggregates generic list, detail, form, kanban, group-by, and helper views.
Import order is significant to avoid circular imports.
"""

from horilla.contrib.generics.views.core import (
    HorillaView,
    HorillaTabView,
    HorillaHistorySectionView,
    HorillaDynamicCreateView,
)
from horilla.contrib.generics.views.field_selection import HorillaFieldSelectionView
from horilla.contrib.generics.views.delete import HorillaSingleDeleteView
from horilla.contrib.generics.views.details import (
    HorillaDetailView,
    HorillaModalDetailView,
    resolves_within_settings_shell,
)
from horilla.contrib.generics.views.list import HorillaListView
from horilla.contrib.generics.views.card import HorillaCardView
from horilla.contrib.generics.views.split_view import HorillaSplitView
from horilla.contrib.generics.views.detail_tabs import (
    HorillaDetailTabView,
    HorillaDetailSectionView,
)
from horilla.contrib.generics.views.groupby import HorillaGroupByView
from horilla.contrib.generics.views.chart import (
    ChartConfigJSONEncoder,
    HorillaChartView,
)
from horilla.contrib.generics.views.kanban import HorillaKanbanView
from horilla.contrib.generics.views.timeline import HorillaTimelineView
from horilla.contrib.generics.views.attachments import (
    AttachmentListView,
    HorillaNotesAttachementSectionView,
    HorillaNotesAttachementDetailView,
    HorillaNotesAttachmentCreateView,
    HorillaNotesAttachmentDeleteView,
)
from horilla.contrib.generics.views.global_search import GlobalSearchView
from horilla.contrib.generics.views.related_list import (
    HorillaRelatedListSectionView,
    HorillaRelatedListContentView,
)
from horilla.contrib.generics.views.single_form import HorillaSingleFormView
from horilla.contrib.generics.views.multi_form import HorillaMultiStepFormView
from horilla.contrib.generics.views.navbar import HorillaNavView
from horilla.contrib.generics.views.inline_edit import (
    HorillaInlineEditMixin,
    HorillaInlineEditNavMixin,
)

__all__ = [
    # Core Views
    "HorillaView",
    "HorillaTabView",
    "HorillaHistorySectionView",
    "HorillaFieldSelectionView",
    "HorillaDynamicCreateView",
    # Delete View
    "HorillaSingleDeleteView",
    # Detail Views
    "HorillaDetailView",
    "HorillaModalDetailView",
    # List View
    "HorillaListView",
    # Card View
    "HorillaCardView",
    # Split View
    "HorillaSplitView",
    # Detail Tabs
    "HorillaDetailTabView",
    "HorillaDetailSectionView",
    # GroupBy Views
    "HorillaGroupByView",
    # Chart Views
    "ChartConfigJSONEncoder",
    "HorillaChartView",
    # Kanban Views
    "HorillaKanbanView",
    # Timeline Views
    "HorillaTimelineView",
    # Attachment Views
    "AttachmentListView",
    "HorillaNotesAttachementSectionView",
    "HorillaNotesAttachementDetailView",
    "HorillaNotesAttachmentCreateView",
    "HorillaNotesAttachmentDeleteView",
    # Global Search
    "GlobalSearchView",
    # Related List
    "HorillaRelatedListSectionView",
    "HorillaRelatedListContentView",
    # Single Form View
    "HorillaSingleFormView",
    # Multi Form Views
    "HorillaMultiStepFormView",
    # Navbar View
    "HorillaNavView",
    "HorillaInlineEditMixin",
    "HorillaInlineEditNavMixin",
]
