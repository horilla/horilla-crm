# Horilla Reports app — deep dive (`horilla.contrib.reports`)

## What this app does

- **ReportFolder** — hierarchical organization, favourites, owner-based access (`OWNER_FIELDS = ["folder_owner"]`).
- **Report** — saved definition: underlying model, columns, filters, chart configuration (stored as JSON / FKs—see `models.py` for schema evolution).
- Integrates with **dashboard** app. A report chart or its Detail Table can be added as a dashboard component, and that component uses the report's saved filters.
- **REST API** at `reports/`.

---

## App startup (`apps.py`)

`ReportsConfig`:

| Setting | Value |
|---------|--------|
| `url_prefix` | `reports/` |
| `url_namespace` | `reports` |
| `auto_import_modules` | `registration`, `signals`, `menu` |
| API | `reports/` → `horilla.contrib.reports.api.urls` |

---

## Menu (`menu.py`)

Registers main navigation / floating entries for **Reports list**, **builder**, and shortcuts. Default keyboard shortcuts may register on `User` post_save (see keys app) using `reports:reports_list_view`.

---

## Feature registration (`registration.py`)

- **`register_feature("report_choices", "report_models")`** — models that should appear as reportable modules register here.
- **`ReportFolder`** and **`Report`** — `register_model_for_feature` with `import_data`, `export_data`, `global_search`.

---

## Models — usage notes

### `ReportFolder`

- Self-FK **`parent_folder`** for nesting.
- **`favourited_by`** M2M for quick access.
- **`get_detail_view_url`** → `dashboard:dashboard_folder_detail_list` pattern for cross-app navigation (folders appear in dashboard navigator).

### `Report`

- **`report_owner`** FK — **`OWNER_FIELDS = ["report_owner"]`** for own vs all lists.
- **`module`** → `HorillaContentType`, limited by **`report_models`** feature registry.
- **`folder`** optional FK to `ReportFolder`.
- **Serialized query UI** — `selected_columns`, `row_groups`, `column_groups`, `aggregate_columns`, `filters` (see `*_list` properties on the model).
- **Chart** — `chart_type` (ECharts-oriented: column, line, funnel, sankey, …), `chart_field`, `chart_field_stacked`, `chart_value_field`.
- **Sharing** — `shared_with` M2M, `is_favourite` boolean.
- **`model_class`** property resolves the ORM class from `module`.

---

## Forms (`forms.py`)

### `ReportForm` (`HorillaModelForm`)

- **`field_order`**: `name`, `module`, `folder`, `selected_columns`, `report_owner`
- **`Meta.fields = "__all__"`**
- **`Meta.exclude`**: `row_groups`, `column_groups`, `aggregate_columns`, `filters`, `chart_type`, `chart_field`, `chart_field_stacked`, `chart_value_field`, `is_favourite`, `shared_with` (builder/chart UI uses other views)
- **`__init__`**: folder queryset, module HTMX → column picker, `SelectMultiple` for `selected_columns` (unchanged)
- **View**: `report_owner` in **`hidden_fields`**

### `ChangeChartReportForm` (`HorillaModelForm`)

- **`field_order`**: `chart_type` only
- **`Meta.exclude`**: all other `Report` columns
- **`__init__`**: filters `chart_type` choices when grouping count ≤ 1 (unchanged)

Pivot/chart configuration views may still declare their own `fields` on **`HorillaSingleFormView`**; those are separate from these two form classes.

---

## CRUD and configuration views (`views/report_crud.py`)

Eleven views cover report lifecycle and chart configuration.

### Report management

| View | Base | Purpose |
|------|------|---------|
| `CreateReportView` | `HorillaSingleFormView` | Create report with module + column selection |
| `UpdateReportView` | `HorillaSingleFormView` | Edit report metadata (name, folder, description) |
| `MoveReportView` | `HorillaSingleFormView` | Move report to a different folder |
| `MoveFolderView` | `HorillaSingleFormView` | Move a folder to a new parent folder |
| `ReportUpdateView` | `DetailView` | Configuration panel interface (opens chart/column editor) |
| `GetModuleColumnsHTMXView` | `View` | HTMX endpoint; returns dynamic column widget when module changes |
| `DiscardReportChangesView` | `View` | Clears session preview data (`report_preview_{pk}`) |
| `SaveReportChangesView` | `View` | Persists session preview data to the `Report` model |
| `CloseReportPanelView` | `View` | Closes the configuration panel partial. The close control is in the panel as soon as it opens |

### Chart configuration

| View | Base | Purpose |
|------|------|---------|
| `ChangeChartTypeView` | `HorillaSingleFormView` | Unified chart-type + chart-field selector; filters choices based on group count |
| `ChangeChartFieldView` | `HorillaSingleFormView` | Kept for URL compatibility; use `ChangeChartTypeView` for new work |

**Chart type filtering** — `ChangeChartTypeView.__init__` removes stacked chart types when `row_groups` count ≤ 1, keeping the choice list relevant. The "Stack by" field (`chart_field_stacked`) is hidden for non-stacked chart types via `form_invalid()` which rebuilds field choices dynamically on each render.

**Preview mode** — editing stores incremental changes in `request.session["report_preview_{pk}"]`. `SaveReportChangesView` moves session data to the database; `DiscardReportChangesView` removes it. This allows multi-step configuration without committing after every interaction. Save and Discard then reload the report's detail URL.

**Rows and exports** — the detail table, preview and export start from `get_viewable_queryset` (see [list owner filtration](../generics/views/list.md#step-g-ownership-permission-filtration)), so a user with only `view_own` on the report's model sees the same records as on that model's list. Export also requires `reports.export_report` or `reports.export_own_report`, and the matching export permission on the model when the model defines one.

**Related fields** — a relation expands only to fields registered in `horilla.contrib.generics.related_fields` (the user's department, role and company). `register_report_related_fields(app_label, model_name, relations)` overrides that list for one report model, or passes an empty list so the relation itself stays selectable and its fields do not. The Detail Table uses the generic list scroll and has its own **Add to Dashboard** action (`component_type=table_data`).

**Owner access control** — create/update views check `reports.add_report` / `reports.change_report` permissions or confirm `report_owner == request.user` before allowing edits.

## Default reports and query behavior

`LoadDefaultReportsModalView` discovers report definitions from installed apps'
`report_files`. `CreateSelectedDefaultReportsView` creates the selected
definitions and resolves their `HorillaContentType` modules in one bulk lookup
for the distinct `(app_label, model)` pairs. Missing content types still cause
that report to be skipped.

Default report folders are cached by name for the duration of the request, so
repeated reports in the same folder reuse one `get_or_create()` result. This
also preserves recursive parent-folder creation.

`ReportsListView` and `FavouriteReportsListView` use
`select_related("module")` because the `module_verbose_name` list column reads
the report's `HorillaContentType`. New report list querysets should retain this
eager loading to avoid one content-type query per visible row.

---

## Signals (`signals.py`)

May update denormalized counts when reports run on a schedule, or touch `RecentlyViewed`—read module for senders.

---

## Typical flows

1. User builds a **lead pipeline** chart → saves **Report** row in folder.
2. User pins report to **Dashboard** component → `DashboardComponent` references report PK (see dashboard models).
3. API consumer lists **`/reports/`** → serializer returns metadata without executing heavy query until `run` endpoint.

---

## Virtual fields and extensions

A **virtual field** is a value computed with `queryset.annotate()` that has no database column (Opportunity registers `days_open`, `close_month`, …). Column pickers, filters, row/column groups, previews, the detail table and exports all resolve them through `horilla.contrib.reports.utils`:

| API | Role |
|-----|------|
| `register_virtual_field(app_label, model_name, field_name, verbose_name, annotation, choices=None, show_in_detail=False)` | Static registration from an app's `registration.py` |
| `ReportFieldProvider.get_virtual_fields(model_class)` | Extension seam for fields that come from the current request or user (company-scoped, runtime-created, permission-filtered). Resolved through `get_report_field_provider()`; override with an `_inherit_view` extension. Returns `{name: VirtualField}` |
| `VirtualField(name, verbose_name, annotation, choices=None, show_in_detail=False)` | `choices` makes it groupable; `show_in_detail` makes it a column of the report detail table (the rows carry the annotated value); `is_relation` is `False` |
| `detail_virtual_fields(model)` | Column-picker entries (`name` / `verbose_name` / `field_type`) for virtual fields with `show_in_detail` |
| `virtual_field_choices(model, purpose)` | `(name, label)` pairs for a picker; `purpose` is `"detail"`, `"grouping"` (has choices) or `"numeric"` (number output) |
| `annotate_virtual_fields(queryset, model, names)` | Annotate the virtual fields named in `names` |

`_virtual_fields_for(model)` merges the registry with the provider's fields, so every helper above sees both. The Columns tab of the report panel (panel context, `SearchAvailableFieldsView`, `AddColumnView`) and the detail table (`ReportDetailView`) include virtual fields that have `show_in_detail`; virtual fields without it keep working for grouping, filtering and aggregation only. Known limits: every virtual field is listed as numeric in the Y-axis choices, and the detail table cannot sort by a virtual column.

The Custom Fields app supplies `cf_<id>` virtual fields through `ReportFieldProvider` — see [field_management/README.md](../../../../horilla/contrib/field_management/README.md#reports-and-dashboards).

---

## Related documentation

- Dashboard models referencing `Report`: [../dashboard/dashboard.md](../dashboard/dashboard.md)
- Chart views in generics: [../generics/views/chart.md](../generics/views/chart.md)
