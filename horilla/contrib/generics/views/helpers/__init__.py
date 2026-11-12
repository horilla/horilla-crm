"""
Horilla generics view helpers.

Condition widgets, detail/edit fields, filter list, kanban group-by, list columns, and select2 helpers.
"""

from horilla.contrib.generics.views.details import HorillaDetailView
from horilla.contrib.generics.views.helpers.condition_widget import (
    RemoveConditionRowView,
    GetFieldValueWidgetView,
    GetModelFieldChoicesView,
)
from horilla.contrib.generics.views.helpers.detail_field import (
    _ensure_json_serializable,
    get_detail_field_defaults_no_request,
    _get_detail_field_defaults,
    DetailFieldSelectorView,
    ResetDetailFieldsView,
    SaveDetailFieldsView,
    SplitColumnSelectorView,
)
from horilla.contrib.generics.views.helpers.edit_field import (
    EditAllFieldsView,
    UpdateAllFieldsView,
)
from horilla.contrib.generics.views.helpers.filter_list import (
    SaveFilterListView,
    PinView,
    DeleteSavedListView,
)
from horilla.contrib.generics.views.helpers.kanban_groupby import (
    HorillaKanbanGroupByView,
    KanbanLoadMoreView,
    GroupByLoadMoreView,
    GroupByExpandView,
)
from horilla.contrib.generics.views.helpers.timeline_settings import (
    TimelineSettingsFormView,
    get_timeline_span_by_row,
    get_saved_timeline_fields,
)
from horilla.contrib.generics.views.helpers.list_column import (
    get_default_columns_from_view,
    ListColumnSelectFormView,
    ResetColumnToDefaultView,
)
from horilla.contrib.generics.views.helpers.select2 import (
    _is_allowed_import_module_path,
    HorillaSelect2DataView,
)
from horilla.contrib.generics.views.helpers.queryset_utils import (
    get_queryset_for_module,
    filter_viewable_queryset,
    apply_conditions,
)
from horilla.contrib.generics.views.helpers.user_picker import (
    _get_model_fields,
    _apply_filters,
    UserPickerFilterView,
    UserPickerListView,
    UserPickerModalView,
)

__all__ = [
    # Detail View
    "HorillaDetailView",
    # Condition Widget
    "RemoveConditionRowView",
    "GetFieldValueWidgetView",
    "GetModelFieldChoicesView",
    # Detail Fields
    "_ensure_json_serializable",
    "get_detail_field_defaults_no_request",
    "_get_detail_field_defaults",
    "DetailFieldSelectorView",
    "ResetDetailFieldsView",
    "SaveDetailFieldsView",
    "SplitColumnSelectorView",
    # Edit Fields
    "EditAllFieldsView",
    "UpdateAllFieldsView",
    # Filter List
    "SaveFilterListView",
    "PinView",
    "DeleteSavedListView",
    # Kanban Group-By
    "HorillaKanbanGroupByView",
    "KanbanLoadMoreView",
    "GroupByLoadMoreView",
    "GroupByExpandView",
    # Timeline Settings
    "TimelineSettingsFormView",
    "get_timeline_span_by_row",
    "get_saved_timeline_fields",
    # List Column
    "get_default_columns_from_view",
    "ListColumnSelectFormView",
    "ResetColumnToDefaultView",
    # Select2
    "_is_allowed_import_module_path",
    "HorillaSelect2DataView",
    # Queryset Utils
    "get_queryset_for_module",
    "filter_viewable_queryset",
    "apply_conditions",
    # User Picker
    "_get_model_fields",
    "_apply_filters",
    "UserPickerFilterView",
    "UserPickerListView",
    "UserPickerModalView",
]
