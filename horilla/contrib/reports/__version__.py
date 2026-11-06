"""Package metadata for the `horilla.contrib.reports` app."""

# First party imports (Horilla)
from horilla.utils.translation import gettext_lazy as _

__version__ = "1.11.15"
__module_name__ = "Reports"
__release_date__ = ""
__description__ = _(
    "Module for creating and customizing reports across all system modules."
)
__icon__ = "reports/assets/icons/icon5.svg"

__1_11_15__ = _(
    "Redesign the report page, filter panel and related-field filters, and "
    "limit related fields in pickers to user relations. Apply view-own and "
    "export-own to report rows, exports and lists. The Detail Table uses "
    "the generic list scroll, can be added to a dashboard, and Save and "
    "Discard return to the detail URL."
)

__1_11_14__ = _("Show the close button as soon as the report edit panel opens.")

__1_11_13__ = _(
    "Convert lazy field labels to strings when exporting a report to Excel."
)

__1_11_12__ = _(
    "Accept custom fields as report columns, including detail virtual fields."
)

__1_11_11__ = _(
    "Reduce default-report database queries. Refresh the sub-sidebar when "
    "switching main sections."
)

__1_11_10__ = _(
    "Show a single empty-state message when a report has no data. Close cross-tenant "
    "and privilege-escalation gaps in the Reports API."
)

__1_11_9__ = _(
    "Derive list column labels from model verbose_name; mark empty-state no_record_msg "
    "strings for translation; stop forcing labels to title case; wrap remaining "
    "user-facing strings with gettext."
)

__1_11_8__ = _(
    "Fit reports folder and list views to the viewport instead of overflowing."
)

__1_11_7__ = _(
    "Pass the viewing user into currency display helpers so report pivot amounts "
    "respect the user's number_format preference."
)

__1_11_6__ = _(
    "Seed default CRM reports and extend the engine to load them. Add an empty state for "
    "report filters and refresh report-detail navbar button styles. Store relative referer "
    "URLs with a full-nav fallback from report detail."
)

__1_11_5__ = _(
    "Gate report export through export permissions and get_export_queryset / "
    "is_exportable_field helpers."
)

__1_11_4__ = _(
    "Avoid RelatedObjectDoesNotExist in create-report form_invalid when related objects "
    "are missing."
)

__1_11_3__ = _(
    "Re-raise HttpNotFound with exception chaining in report detail, export, and CRUD "
    "views to preserve context."
)

__1_11_2__ = _(
    "Added pivot cell active state and filter badge with clear action. Fixed detail table "
    "filtering for empty and null pivot group values."
)

__1_11_1__ = _(
    "Removed redundant fields attributes superseded by form_class on report CRUD views, "
    "standardized first-party import groups, and added docstrings for pylint compliance."
)

__1_10_1__ = _(
    "Report forms aligned with ModelForm layout: field_order and "
    'Meta.fields = "__all__" with Meta.exclude; folder and column HTMX unchanged.'
)

__1_10_0__ = _(
    "Release 1.10: reports ship under contrib with app label reports. "
    "Cross-app report wiring, ContentType references, namespaces, and registrations "
    "updated for the contrib naming scheme."
)

__1_2_1__ = _(
    "Improved report compatibility with dashboard multi-widget support, "
    "enhanced chart_value_field handling, and minor stability improvements "
    "for report rendering and filter processing."
)

__1_2_0__ = _(
    "Added support for advanced chart types including Treemap, Area charts, "
    "Heatmaps, Sankey diagrams, and Radar charts. Improved compatibility with "
    "the new visualization and analytics framework."
)

__1_1_0__ = _(
    "Migrated from AppConfig to AppLauncher and and replaced"
    "utilities with utils.decorators, utils.translation,"
    "and shortcuts where applicable."
)
