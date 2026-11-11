# Horilla Dashboard app — deep dive (`horilla.contrib.dashboard`)

## What this app does

- **Folders** and **dashboards** owned by users, scoped by **company** (`HorillaCoreModel`).
- **DashboardComponent** rows — KPI, chart, or table tiles; optional FK to a saved **`Report`** from `horilla.contrib.reports`.
- **ComponentCriteria** — per-component filter rows (operators align with `OPERATOR_CHOICES` from `horilla.utils.choices`).
- **DefaultHomeLayoutOrder** — lightweight ordering model for the home shell layout.
- **OnboardingState** — whether the home page **Get started** guide is dismissed, kept per company (see [Get started guide](#get-started-guide-home-page)).
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

Apps that contribute **Get started** steps add `"onboarding"` to their own `auto_import_modules` and ship an `onboarding.py` (see [onboarding registry](../../registry/onboarding.md)).

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

### `OnboardingState`

- Plain `models.Model`: `company` (`OneToOneField` to `core.Company`, `related_name="onboarding_state"`), `is_hidden` (default `False`), `updated_at`. **One row per company**, created the first time a superuser dismisses the guide; no row means the guide is shown.
- There is no `user` field: the choice belongs to the company, so one superuser dismissing the guide dismisses it for that company's other superusers, and never for another company.
- `OnboardingState.is_hidden_for(company)` and `OnboardingState.set_hidden(company, hidden)`.
- Registered in `registration.py` for the `delete_dependency` feature.

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
- **Get started guide** — included in the default home only (`home/onboarding.html`); see below.
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

## Get started guide (home page)

A stepper banner at the top of the default home that walks a new company through its setup. The steps come from [the onboarding registry](../../registry/onboarding.md); this app decides what to show.

### Who sees it

- **Superusers only** (`user.is_superuser`). This includes users added on **Settings → Roles and Permissions → Super Users**, not only the account created at install. Everyone else gets no guide, and the toggle endpoint answers **403** for them.
- It follows the **active company** (company switcher aware). A user with no company gets no guide.
- A step the user lacks the `permission` for is hidden and not counted.
- When every visible step is done the guide is not rendered at all (nothing is stored); it comes back if a step becomes undone, because completion is computed on every render and never saved.

### What it shows

| Part | Content |
|------|---------|
| Header | "Get started with `<company name>`", "`N` of `M` steps done", a progress bar with the percentage, and an **X** (dismiss) button |
| Stepper | One circle per step with a connector line: a red check for done, a ring with a dot for the next step, a number for the rest. Each one links to the step's page. It scrolls sideways on narrow screens |
| Next-step card | "NEXT STEP · `n` OF `M`", the step's `headline` and `description`, **Skip For Now** and **Set Up Now →** |

### Dismiss, show again and skip

| Action | Effect |
|--------|--------|
| **X** | Posts to `dashboard:onboarding_hide`; the banner is removed for the active company |
| **⚡ Show Setup Guide (6/7)** | A small link at the right end of the "Get started by creating your first dashboard…" intro line, shown only while the guide is dismissed. It posts to `dashboard:onboarding_show` and the banner returns |
| **Skip For Now** | Posts to `dashboard:onboarding_skip`; that step leaves the next-step card and the next unfinished step is shown. The stepper keeps every step. Kept in the session, per company |

All of them swap in place with HTMX (no page reload). Dismissing in one company never changes another company.

### Code map

| Piece | Where |
|-------|-------|
| Builder | `horilla/registry/onboarding.py`: `build_onboarding(user, company, skipped)` returns the view-model (`steps`, `total`, `done_count`, `percent`, `next_step`) or `None`. Each step dict has `number`, `title`, `headline`, `description`, `icon`, `url`, `done`, `is_next` |
| Context | `dashboard/get_started.py`: `get_active_company(request)`, the session helpers for skipped steps, and `get_onboarding_context(request)`, which adds whether the guide is hidden |
| Home view | `HomePageView.get_dynamic_default_context` merges `get_onboarding_context` |
| Hide / show view | `views/onboarding.py` `OnboardingVisibilityView` (`POST onboarding/hide/` and `onboarding/show/`, names `onboarding_hide` and `onboarding_show`): `LoginRequiredMixin`, HTMX only, superuser only; 400 when there is no company |
| Banner and show link | `templates/home/onboarding.html`, one template with two parts chosen by `part`: `banner` (`#onboarding`) and `link` (`#onboarding-link`, next to the intro line). `home.html` includes it once for each; the views render `part="both"`, so one HTMX response swaps the banner and the link (`hx-swap-oob`) |
| Skip view | `views/onboarding.py` `OnboardingSkipView` (`POST onboarding/skip/<key>/`, name `onboarding_skip`): remembers the skipped step in the session for the active company; the next unfinished step is shown |

### Tests

`dashboard/tests.py` (per-company hide and show, skip, superuser-only views, builder rules), `core/test_onboarding.py`, `leads/tests/test_onboarding.py`, `opportunities/test_onboarding.py`.

---

## Typical flows

1. User creates **folder** → adds **dashboards** → sets one as **default** → home loads that layout.
2. User adds a **chart** or the report's **Detail Table** as a component. Table pages, sorting and exports start from `get_viewable_queryset`, then `apply_report_table_queryset` applies that report's saved filters and column virtual fields. Chart components apply the same report filters. A model registered with `dashboard_component` (including Activity) can be chosen as a component.
3. Third-party client hits **`/dashboard/`** API → JSON mirrors web serializer shape.
4. A superuser opens the home page of a new company → the Get started banner shows the next pending step → **Set Up Now** opens that page → once its data exists the step turns done and the next one becomes current.

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
- Onboarding steps registry (how apps add steps): [../../registry/onboarding.md](../../registry/onboarding.md)
- Reports model: [../reports/reports.md](../reports/reports.md)
- Generics chart view: [../generics/views/chart.md](../generics/views/chart.md)
