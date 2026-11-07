"""
Horilla generics forms package.

Re-exports form classes and widgets from submodules so callers can use:
from horilla.contrib.generics.forms import HorillaModelForm, KanbanGroupByForm
"""

from horilla.contrib.generics.forms.constants import HORILLA_FORM_EXCLUDE

from horilla.contrib.generics.forms.generics import (
    KanbanGroupByForm,
    TimelineSpanByForm,
    ColumnSelectionForm,
    SaveFilterListForm,
    PasswordInputWithEye,
    HorillaHistoryForm,
    RowFieldWidget,
    RowField,
    CustomFileInput,
    HorillaAttachmentForm,
    PhoneWidget,
    PhoneField,
    CheckboxGridSelectMultiple,
    DayQuickFillWidget,
)
from horilla.contrib.generics.forms.multi_step import HorillaMultiStepForm
from horilla.contrib.generics.forms.single_step import HorillaModelForm

__all__ = [
    # Base Forms
    "KanbanGroupByForm",
    "TimelineSpanByForm",
    "ColumnSelectionForm",
    "SaveFilterListForm",
    "PasswordInputWithEye",
    "HorillaHistoryForm",
    "RowFieldWidget",
    "RowField",
    "CustomFileInput",
    "HorillaAttachmentForm",
    "CheckboxGridSelectMultiple",
    "DayQuickFillWidget",
    # Phone widgets
    "PhoneWidget",
    "PhoneField",
    # Multi-step Forms
    "HorillaMultiStepForm",
    # Single-step Forms
    "HorillaModelForm",
    # Shared exclude list
    "HORILLA_FORM_EXCLUDE",
]
