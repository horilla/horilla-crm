"""Version information for the duplicates module."""

# First party imports (Horilla)
from horilla.utils.translation import gettext_lazy as _

__version__ = "1.11.13"
__module_name__ = "Duplicate Control"
__release_date__ = ""
__description__ = _(
    "Module for detecting potential duplicate records and supporting merge workflows."
)
__icon__ = "duplicates/assets/icons/clone.svg"

__1_11_13__ = _(
    "Match custom fields in duplicate rules instead of reading them as model "
    "columns."
)

__1_11_12__ = _(
    "Matching Rules condition Operator narrowing passes condition_model on "
    "module change; move CRM-dependent duplicate demo fixtures into CRM apps."
)

__1_11_11__ = _("Only border Matching Rules list containers when rows exist.")

__1_11_10__ = _("Re-point duplicate checks onto the bulk Edit Details save flow.")

__1_11_9__ = _(
    "Replace runtime injection with ViewExtensions for detail-tab composition."
)

__1_11_8__ = _(
    "Add per-action alert messages and enforce a single active matching rule. Fix "
    "invalid-request errors and remove redundant Cancel buttons on the duplicate "
    "warning modal."
)

__1_11_7__ = _(
    "Adopt shared empty_state partials on matching rules and potential duplicates. Add "
    "cursor-pointer on clickable controls; stop forcing form labels to title case; wrap "
    "remaining model strings with gettext."
)

__1_11_6__ = _("Move matching rules onto the shared settings_list_shell layout.")

__1_11_5__ = _(
    "Apply runtime viewport fit on duplicate-rule and potential-duplicates list views."
)

__1_11_4__ = _(
    "Resolve inline-edit re-renders through get_edit_field_view so _inherit_view "
    "extensions apply. Support numeric and date comparison operators and FilterSet "
    "operator aliases in duplicate-rule conditions."
)

__1_11_3__ = _(
    "Avoid RelatedObjectDoesNotExist in DuplicateRule.clean when related objects are missing."
)

__1_11_2__ = _("Removed deprecated merge_views compatibility shim.")

__1_11_1__ = _(
    "Standardized first-party import groups and aligned with the platform 1.11.1 release; "
    "rules, criteria, and merge behavior unchanged."
)

__1_10_1__ = _(
    "Duplicate rule forms aligned with HorillaModelForm layout: field_order and "
    'Meta.fields = "__all__"; criteria rows and validation unchanged.'
)

__1_10_0__ = _(
    "Release 1.10: duplicate control ships under contrib with app label duplicates. "
    "Feature registration, merge flows, and cross-model references use contrib paths "
    "and matching app labels for clone and duplicate tooling."
)

__1_1_0__ = _(
    "Renamed Clone Management to Duplicate Control. Added duplicate validation "
    "for inline field edits with warning modal for duplicate conflicts. "
    "Fixed duplicate detail tab injection issue and improved merge flow "
    "handling for edge cases."
)

__1_0_0__ = _(
    "Introduced duplicate management capabilities with matching rules, potential duplicate "
    "detection, and merge comparison and summary workflows."
)
