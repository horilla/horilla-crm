# Horilla Dashboard app — deep dive (`horilla.contrib.dashboard`)

## What this app does

- **Folders** and **dashboards** owned by users, scoped by **company** (`HorillaCoreModel`).
- **DashboardComponent** rows — KPI, chart, or table tiles; optional FK to a saved **`Report`** from `horilla.contrib.reports`.
- **ComponentCriteria** — per-component filter rows (operators align with `OPERATOR_CHOICES` from `horilla.utils.choices`).
- **DefaultHomeLayoutOrder** — lightweight ordering model for the home shell layout.
- **Home** views compose dashboards or fall back to dynamic KPI/chart/table generation (see [default_dashboard_generator.md](default_dashboard_generator.md) for the generator that lives alongside dashboard views in this codebase).
- **REST API** at `/dashboard/`.

---

## App startup (`apps.py`)

`DashboardConfig`:

| Setting | Value |
|---------|--------|
| `url_prefix` | `dashboard/` |
| `url_namespace` | `dashboard` |
| `auto_import_modules` | `registration`, `signals`, `menu` |
| API | `/dashboard/` → `horilla.contrib.dashboard.api.urls` |

Apps that contribute **default home** tiles add `"dashboard"` to their own `auto_import_modules` and ship a `dashboard.py` that appends to `DefaultDashboardGenerator.extra_models` (see generator guide).

---

## Models (`models.py`)

### `DashboardFolder`

- **`folder_owner`** — `OWNER_FIELDS = ["folder_owner"]`.
- **`parent_folder`** self-FK for tree structure.
- **`favourited_by`** M2M.
- **`actions` / `actions_detail`** — render custom HTMX action partials.

### `Dashboard`

- **`dashboard_owner`**, **`OWNER_FIELDS = ["dashboard_owner"]`**.
- **`folder`** optional FK.
- **`is_default`** — `save()` clears other defaults for same **user + company** so only one default dashboard exists.
- **`get_default_dashboard(user)`** classmethod returns the active default for shell routing.
- **Favourites** M2M mirroring folders.

### `DashboardComponent`

- **`dashboard`** FK (cascade).
- **`component_type`** — `chart` | `table_data` | `kpi`.
- **`reports`** optional FK to **`Report`** — when set, chart/table can reuse saved report definition.
- **`module`** — `HorillaContentType` limited by **`dashboard_component_models`** for ad-hoc components not tied to a `Report`.
- Metric and grouping fields (`metric_type`, `grouping_field`, `y_axis_metric_type`, `columns`, …).
- **`component_owner`** + **`OWNER_FIELDS`** for row-level security on components.

### `ComponentCriteria`

- Child rows describing AND/OR filter lines for a component (linked FK from `DashboardComponent`).

### `DefaultHomeLayoutOrder`

- Plain `models.Model` (not `HorillaCoreModel`) for ordering keys on default home (see model fields).

---

## Forms (`forms.py`)

### `DashboardForm` (`HorillaModelForm`)

- **`field_order`**: `name`, `description`, `folder`, `is_default`, `dashboard_owner`
- **`Meta.fields = "__all__"`**, **`Meta.exclude = ["favourited_by"]`**
- **`__init__`**: limits `folder` queryset by owner (unchanged)

### `DashboardCreateForm` (`HorillaModelForm`)

- **`field_order`**: `name`, `component_type`, `chart_type`, `module`, grouping/metric/column fields, then `icon`, `dashboard`, `sequence`, `component_owner`, `reports`
- **`Meta.fields = "__all__"`** — no extra `exclude`; chart/KPI/table fields are hidden at runtime in **`__init__`** by `component_type`
- **View**: `DashboardComponentFormView` sets **`hidden_fields`** for `dashboard`, `sequence`, `component_owner`, `reports`, `company`, etc.
- **Conditions**: `ComponentCriteria` via `condition_fields` on the view

Core audit fields are auto-excluded via **`HORILLA_FORM_EXCLUDE`**; do not duplicate them in `Meta.exclude`.

---

## Views and templates

- **Home** — one template, `home/home.html`, serves both the dynamic default home (`is_default_home=True`) and a dashboard used as home; `default_home.html` no longer exists. The date range control is the shared `components/date_range_filter.html`. "Set to Default" only shows for a layout that differs from the template default (KPIs by index, then two charts per table); saving an order equal to the default deletes the stored `DefaultHomeLayoutOrder`, and the save response returns `is_custom`.
- **Dashboard detail** — `dashboard_detail_view.html` uses the generic navbar (`dashboard_detail_nav_actions.html`). Other partials live under `templates/` / `templates/home/`.
- **Folder detail** — navigates mixed lists of child folders + dashboards (`get_detail_view_url` on folder model points at `dashboard:dashboard_folder_detail_list`).

### Dashboard action views (`views/dashboard_actions.py`)

Five focused views handle state mutations for dashboards.

| View | Base | URL pattern | Behavior |
|------|------|-------------|----------|
| `DashboardDefaultToggleView` | `View` | POST | Sets `is_default=True` on target; clears `is_default` on all other dashboards for the same user+company pair |
| `DashboardFavoriteToggleView` | `View` | POST (GET → 403) | Adds or removes the current user from `Dashboard.favourited_by` M2M |
| `DashboardCreateFormView` | `HorillaSingleFormView` | GET+POST | Create/update `Dashboard`; falls back to `_thread_local` for `active_company` when not on request |
| `DashboardDeleteView` | `HorillaSingleDeleteView` | POST | Deletes dashboard and redirects |
| `ResetDashboardLayoutOrderView` | `View` | POST | Clears `DefaultHomeLayoutOrder` rows for the current user, resetting home tile ordering |

**Default toggle logic** — `DashboardDefaultToggleView` uses a queryset `update()` to deactivate all other defaults in one query, then sets the target via `save()`. This guarantees only one default dashboard per user per company at any time.

**Favorite toggle** — responds only to POST (returns HTTP 403 for GET). Checks M2M membership before deciding add vs. remove.

**HTMX reload** — all action views return a response containing `<script>$('#reloadButton').click();</script>` to trigger a list refresh without a full page load.

---

## Typical flows

1. User creates **folder** → adds **dashboards** → sets one as **default** → home loads that layout.
2. User adds a **chart** or the report's **Detail Table** as a component. Table pages, sorting and exports start from `get_viewable_queryset`, then `apply_report_table_queryset` applies that report's saved filters and column virtual fields. Chart components apply the same report filters. A model registered with `dashboard_component` (including Activity) can be chosen as a component.
3. Third-party client hits **`/dashboard/`** API → JSON mirrors web serializer shape.

---

## Field pickers and extension hooks

The component form and the HTMX field-picker views list a model's columns. Fields that aren't model columns are added through one hook:

| Where | Hook |
|-------|------|
| `ExtraFieldChoicesView` (base of `ModuleFieldChoicesView`, `ColumnFieldChoicesView`, `GroupingFieldChoicesView`, `SecondaryGroupingFieldChoicesView`, `MetricFieldChoicesView`, `YAxisMetricFieldChoicesView`) | `get_extra_choices(model, purpose)` |
| `DashboardCreateForm` (pickers built in `__init__`) | `get_extra_choices(model, purpose)` |

`purpose` is `"condition"` (condition field list), `"detail"` (table column), `"grouping"` (chart grouping / secondary grouping) or `"numeric"` (KPI / Y-axis metric). Both default to `[]`; an `_inherit_view` / `_inherit_form` extension overrides them (a `ViewExtension` on the base class applies to every picker view through base-class resolution).

Rendering reads the same fields from the reports engine's virtual fields (see [reports.md](../reports/reports.md#virtual-fields-and-extensions)): `annotate_component_virtual_fields(queryset, model, component)` in `dashboard/utils.py` annotates the grouping, secondary grouping, metric and column fields before the KPI, chart, chart preview and table code group, aggregate or list them; chart code resolves the grouping field with `resolve_report_field`, and table columns accept virtual fields with `show_in_detail`. Component conditions go through `apply_conditions`, which honours condition-field extensions.

---

## Related documentation

- Default dashboard generator (fallback when no default dashboard): [default_dashboard_generator.md](default_dashboard_generator.md)
- Reports model: [../reports/reports.md](../reports/reports.md)
- Generics chart view: [../generics/views/chart.md](../generics/views/chart.md)
