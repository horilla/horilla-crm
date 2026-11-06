# List view base (`horilla_generics/views/list.py`)

## What this class is

`HorillaListView` is the **foundation layer** for almost every tabular page in Horilla.
Other generic views (`card`, `kanban`, `groupby`, `timeline`, split/list hybrids) either inherit from it directly or reuse its queryset/context behavior.

It combines:

- Django `ListView`
- `HorillaListViewMixin` (field metadata + filter-row helpers)
- quick-filter toolkit
- bulk mixins (delete/update/export)
- field visibility and editable-permission checks
- HTMX-first rendering model

---

## Why it is feature-heavy

`HorillaListView` is intentionally designed as a **single source of truth** so that:

1. filtering/sorting/searching works the same across modules,
2. permission filtering is consistent at queryset level,
3. bulk operations do not re-implement selection logic in each app,
4. saved/pinned views behave uniformly,
5. complex templates (`list_view.html`) can rely on a stable context contract.

---

## Extension resolution (`_inherit_list` / `_inherit_filter`)

`HorillaListView.as_view()` wraps the class so each request resolves:

- **`get_filterset_class()`** — returns composed filterset when `_inherit_filter` extensions exist (views keep `filterset_class = UserFilter` at class definition time; resolution runs here, same pattern as `get_form_class()` on form views).
- **`resolve_list_view_class()`** — composed list subclass when `_inherit_list` extensions exist.

Target apps register URLs in `AppLauncher.ready()` before extension apps import `lists.py`; `bootstrap_extensions()` in `horilla/urls/project.py` composes all layers after `apps.ready`. See [../../../extension/inherit.md](../../../extension/inherit.md).

### Filter date/datetime parsing

When rebuilding filter rows from query params, `_build_filter_context` calls:

- `parse_filter_date_value(val)`
- `parse_filter_datetime_value(val)` (filter rows for `datetime` fields now use a plain date input and filter by date only, so rebuilt rows go through `parse_filter_date_value`)

Both delegate to `get_datetime_formatter().parse_*` ([DateTimeFormatter](../formatting/datetime.md)) so calendar apps extend parse once via `_inherit_formatter` — not via `HorillaBulkUpdateMixin` or Jalali imports in `list.py`.

---

## Inheritance and base contract

```python
class HorillaListView(HorillaListViewMixin, ListView):
```

Default base contract:

- `template_name = "list_view.html"`
- `context_object_name = "queryset"`
- pagination enabled (`paginate_by = 100`)
- HTMX-aware response rendering

Subclasses usually set:

- `model`
- `view_id`
- `filterset_class`
- `columns`
- `actions`
- `search_url` / `main_url`

---

## Configuration surface (grouped)

### Display and table

| Attribute | Meaning |
|-----------|---------|
| `columns` | Main visible columns. Accepts field names or `(label, field)` pairs. |
| `exclude_columns` | Extra field exclusions for generated columns. |
| `header_attrs` | Per-header HTML attrs (width/style/id). |
| `col_attrs` | Per-cell attrs (often first column HTMX detail link). |
| `table_width`, `table_class`, `table_height_as_class` | Table layout/height styling switches. |
| `list_column_visibility` | Enables column visibility controls UI. |
| `raw_attrs` | Pass-through HTML attrs for template consumers. |

### Sorting

| Attribute | Meaning |
|-----------|---------|
| `enable_sorting` | Enable/disable sort controls in template. |
| `default_sort_field` / `default_sort_direction` | Default ordering when no explicit sort param. |
| `sort_by_mapping` | Map UI sort key -> DB field name. |
| `exclude_columns_from_sorting` | Columns shown but unsortable in UI. |
| `sorting_target` | Optional custom HTMX target for sorting refresh. |

### Filtering and view state

| Attribute | Meaning |
|-----------|---------|
| `filterset_class` | Advanced filter implementation class. |
| `filter_url_push` | Whether filter actions should push URL state. |
| `filter_panel_option` | When `False`, hide the floating filter panel (list, card, kanban-style shells that include the panel). Default `True`. |
| `enable_quick_filters` | Enable quick-filter controls/context. Only effective when `supports_quick_filters` is also true: it is `True` on `HorillaListView` and `False` on the kanban, group-by, card, split, chart and timeline views, so those layouts ignore `enable_quick_filters`. |
| `exclude_quick_filter_fields` | Block specific fields from quick filters. |
| `owner_filtration` | Apply view/view_own ownership queryset filtering. |

### Actions and bulk operations

| Attribute | Meaning |
|-----------|---------|
| `actions` | Row action list (edit/delete/etc). |
| `max_visible_actions` | Actions above this are moved into dropdown. |
| `custom_bulk_actions` | Named custom bulk actions with optional handlers. |
| `additional_action_button` | Extra custom actions (same routing style). |
| `bulk_select_option` | Show row multi-select checkboxes. |
| `bulk_delete_enabled` | Toggle bulk delete UI/behavior. |
| `bulk_update_option` | Toggle bulk update UI/behavior. |
| `bulk_export_option` | Toggle bulk export UI/behavior. |
| `bulk_update_fields` | Fields allowed in bulk update form. |
| `bulk_update_two_column` | Two-column bulk-update layout switch. |

### UX and empty states

| Attribute | Meaning |
|-----------|---------|
| `no_record_section` | Show/hide no-record block. |
| `no_record_add_button` | Add button config callable/data. |
| `no_record_msg` | Custom empty-message text. |
| `no_found_img` | Optional image for no-results area. |
| `save_to_list_option` | Toggle save-filter-list UI. |

### Session and navigation helpers

| Attribute | Meaning |
|-----------|---------|
| `store_ordered_ids` | Store current ordered ids in session (`ordered_ids_<model>`). |
| `number_of_recent_view` | Intended recent-limit config (context-driven behavior). |

---

## Initialization behavior (`__init__`)

### 1) cache/session key setup

- Initializes `_model_fields_cache`.
- If `store_ordered_ids=True`, creates:
  - `self.ordered_ids_key = "ordered_ids_<model_name_lower>"`

### 2) column normalization

When `self.columns` is provided, each entry is normalized into `(label, field_name)`:

- tuple/list `(label, field_name)` -> if `label` is a plain string that itself
  names a real model field, resolved to that field's verbose name (e.g.
  `("is_active", "is_active_col")` displays the `is_active` field's verbose
  name); otherwise `label` is used as-is
- string field name -> attempts model field lookup for verbose name
- string `get_<field>_display` -> resolves the verbose name of `<field>`
- string naming a method/property with a `short_description` attribute
  (Django admin convention) -> uses that as the label
- fallback -> title-cased string label

The lookup is wrapped in `translation.override("en")` so labels are stable for UI metadata.

---

## View type model (`get_default_view_type` + request state)

The list supports a **view mode** system:

- pinned default from `PinnedView` (`user + model`)
- request override with `?view_type=...`
- special handling for bulk operations to avoid accidental context drift

Supported built-ins in `get_queryset`:

- `all`
- `recently_viewed`
- `recently_created`
- `recently_modified`
- `oldest_first`
- `saved_list_<id>`

`oldest_first` orders by `created_at` ascending (navbar label **Oldest First**).

`saved_list_<id>` merges saved filter params with current search-related params before applying the filterset.

---

## Query pipeline in detail (`get_queryset`)

`get_queryset()` is the most important method in this class.

### Step A: base queryset + quick filters

```text
super().get_queryset() -> quick_filter.apply_quick_filters(...)
```

Quick filters are applied early so all subsequent logic (saved lists, sort, pagination) uses the same filtered base.

### Step B: resolve active `view_type`

For bulk delete-related POSTs, it avoids stale pinned-mode assumptions and prefers request mode.

### Step C: built-in view mode transforms

- **recently_viewed**: fetches PK order from `RecentlyViewed` manager.
- **recently_created / recently_modified**: shortlists latest records by timestamp.
- **oldest_first**: `order_by("created_at")` (ascending).
- **saved_list_***: loads `SavedFilterList`, merges params, applies filterset.

### Step D: `filterset_class`

If filterset not already constructed by saved-list flow, it runs:

- `self.filterset = filterset_class(request.GET, queryset, request=request)`
- `queryset = self.filterset.filter_queryset(queryset)`

### Step E: sorting

Sort selection precedence:

1. explicit `sort` / `direction`
2. view-specific recent mode defaults
3. class default sort
4. `-id`

For recently viewed mode, it preserves the manager-returned order using `Case/When`.

### Step F: session ordered ids

If enabled, stores the **ordered current queryset ids** to `ordered_ids_<model>`.

### Step F.5: row-display and row-action `select_related` (`_apply_list_display_select_related`)

Runs right before ownership filtration, on every subclass (Card/Kanban/GroupBy/Split/
Timeline all reuse this `get_queryset()` — none override it, so this applies
everywhere with no per-view wiring):

- joins the FK for every displayed list column (`self.columns`/`self._get_columns()`)
  that resolves to a `ForeignKey`/`OneToOneField`, plus `company` (used by currency
  formatting) — this is the original purpose of the method, avoiding a lazy query per
  row when a cell renders a related object.
- **also** joins the FK named by any action's or column-attrs' `owner_field` (via
  `_get_owner_field_candidates()`), which reads `self.actions` and `self.col_attrs`
  (both safe to access here — by the time `get_queryset()` runs, `View.setup()` has
  already populated `self.request`/`self.kwargs`, so a `@cached_property` `actions`
  works too). Without this, `has_action_permission`'s `owner_field` branch
  (`action_tags.py`) does a plain `getattr(row, owner_field)` for every row, which is
  a lazy per-row query for any FK not already selected as a display column — e.g.
  `lead_owner` on `LeadListView`, `account_owner` on `AccountListView`. Declaring
  `owner_field` on an action is enough to get the join automatically; no subclass
  needs its own `get_queryset()` override for this.

### Step G: ownership permission filtration

If `owner_filtration=True`:

- user with `view_<model>` gets the queryset unchanged
- anyone else is limited to `get_viewable_queryset(user, model)`
  (`helpers/queryset_utils.py`): `view_own_<model>` sees records owned by the
  user or a subordinate role (`OWNER_FIELDS`, via `get_allowed_user_ids`) plus
  any **granted-access** filter (see below); no matching permission returns
  an empty queryset

Reports and dashboard tables call the same helper, so a list, a report and a
dashboard table show the same records. The list intersects its own queryset
with that result by primary key.

#### Granted access (per-model opt-in, beyond `OWNER_FIELDS`)

Some models grant a user access to specific records through a mechanism other
than plain ownership — e.g. being added as a team member on an `Opportunity`
via `OpportunityTeamMember`. A model opts in by defining a classmethod:

```python
@classmethod
def granted_access_filter(cls, user, action):
    """Return a Q object (usable in queryset.filter(...)) matching records
    that grant `user` access to `action` ("view", "change", or "delete")."""
    ...
```

`horilla.contrib.generics.views.helpers.queryset_utils.get_granted_access_filter(model, user, action)`
calls this hook (returning `None` if the model doesn't define it, or on
error) and the result is OR'd into the ownership queryset filter above. The
same helper module's `user_has_granted_access(obj, user, action)` does the
equivalent per-instance check (via an optional `has_granted_access(user,
action)` instance method) and is used by detail, delete, and kanban views to
allow single-object access/actions that plain `OWNER_FIELDS` ownership
wouldn't grant.

---

## Sorting engine detail (`_apply_sorting`)

### Input normalization

- Converts `get_<field>_display` sort keys back to raw field names.
- Applies alias map from `sort_by_mapping`.

### Safety checks

- skips unknown attributes
- skips callable/property targets (not DB-sortable)

### GenericForeignKey support

If target field is `GenericForeignKey`, it sorts by backing fields:

- `content_type_id`
- `object_id`

### Fallback

If `order_by` raises, returns original queryset and logs warning.

---

## GET request router (`get`)

`get()` does more than default ListView GET:

1. computes `self.object_list` and base context,
2. handles dynamic filter UI actions:
   - add filter row
   - remove filter
   - clear all filters
   - remove filter field
3. handles HTMX widget updates:
   - field-change (operator/value widget refresh)
   - operator-change (value-input shape refresh)
4. for HTMX full refresh: renders `list_view.html`
5. non-HTMX: falls through `render_to_response`

---

## POST router (`post`)

POST paths handled:

### 1) custom actions

- checks `custom_bulk_actions` and `additional_action_button` by `action` name
- parses `record_ids` JSON
- delegates to `handle_custom_bulk_action`

### 2) built-in bulk operations (delegated)

- delete -> `HorillaBulkDeleteMixin`
- update -> `HorillaBulkUpdateMixin`
- export -> `HorillaBulkExportMixin`

### 3) quick filter post actions

- delegated to `quick_filter.handle_quick_filter_post`

### 4) invalid payload

- returns `400` with generic invalid request text

---

## Custom bulk action helper (`handle_custom_bulk_action`)

Supports two patterns:

### A) handler function pattern

Action config includes `"handler": "method_name"`:

- method is looked up on view instance
- called as `handler(record_ids, request)`

### B) generic HTMX action pattern

Action config contains URL + target metadata:

- generates `hx-post`/`hx-get`, `hx-target`, `hx-swap`, `hx-vals`
- injects selected ids into context
- re-renders list with action trigger wiring

Useful for custom modals/workflows without rewriting list selection logic.

---

## Context contract (`get_context_data`) in depth

This method builds a very large context object consumed by `list_view.html` and partials.

### A) columns and attrs

- `columns = self._get_columns()` (permission-filtered)
- `header_attrs` merged as dict
- `col_attrs` mapped primarily to first visible column

### B) filter field metadata

- `filter_fields` from `_get_model_fields(...)`
- operators/types/choices per field
- `field_verbose_names`
- `operator_display` human labels

Relative-date operators in the filter row include `today`, `yesterday`, `this_week`, `this_month`, `this_year` and the fiscal ones `this_fiscal_period` (This FP), `this_fiscal_quarter` (This FQ), `this_fiscal_year` (This FY).

### C) active filter rows reconstruction

From query params (`field`, `operator`, `value`, `start_value`, `end_value`):

- rebuilds each row for UI
- resolves display labels for FK/choice values
- parses date/datetime/time values
- creates fallback initial empty row when none present

### D) saved list metadata

When `view_type` is `saved_list_*`:

- resolves list name
- adds ownership flag (`saved_list_is_owner`)

### E) actions and dropdown splitting

If actions exceed `max_visible_actions`:

- `visible_actions`
- `dropdown_actions`
- `use_dropdown=True`

### F) selection and totals

- `total_records_count`
- `selected_ids` / `selected_ids_json`
- session write: `list_view_queryset_ids_<model>`

This key is used by detail/modal flows for prev-next traversal in current filtered scope.

### G) bulk/update/export controls

- editable bulk fields resolved by `get_editable_fields(user, model, bulk_update_fields)`
- sets bulk feature toggles and UI flags

### H) URL and query state

- `search_url`, `main_url`
- `current_query`, `search_params`, `query_params`
- sorting state (`current_sort`, `current_direction`)
- htmx flag (`is_htmx_request`)

### I) quick filter context injection

Final step delegates to `quick_filter.update_quick_filter_context`.

---

## Render behavior (`render_to_response`)

Always adds `request_params`.

- HTMX request -> render partial `list_view.html` directly
- non-HTMX -> default parent response flow

This keeps list responses composable in split views, tabs, and modal sections.

---

## Feature dependencies inside this file

Primary integrations:

- `HorillaListViewMixin`
- `quick_filter` toolkit
- `HorillaBulkDeleteMixin`
- `HorillaBulkUpdateMixin`
- `HorillaBulkExportMixin`
- `PinnedView`, `RecentlyViewed`, `SavedFilterList`
- `filter_hidden_fields`, `get_editable_fields`

Templates heavily tied to this context:

- `list_view.html`
- `partials/list_view_rows.html`
- `partials/filter_row.html`

---

## Real subclass (`LeadListView`) and why it works

```python
@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["leads.view_lead", "leads.view_own_lead"]),
    name="dispatch",
)
class LeadListView(LoginRequiredMixin, HorillaListView):
    model = Lead
    view_id = "leads-list"
    filterset_class = LeadFilter
    search_url = reverse_lazy("leads:leads_list")
    main_url = reverse_lazy("leads:leads_view")
    enable_quick_filters = True
    max_visible_actions = 5
    columns = [
        "title",
        "first_name",
        "last_name",
        "email",
        "lead_status",
        "lead_source",
        "industry",
        "annual_revenue",
    ]
```

Route:

```python
path("leads-list/", views.LeadListView.as_view(), name="leads_list")
```

What this subclass gets automatically:

- filter row builder + quick filters
- saved/pinned/recent view modes
- bulk delete/update/export
- dropdown action splitting
- owner-based visibility filtering
- HTMX-friendly list partial rendering

---

## Extension guidelines (recommended)

### When creating a new list view

Set at minimum:

- `model`
- `view_id`
- `filterset_class` (if advanced filtering needed)
- `columns`
- `search_url` and `main_url`

### When overriding `get_queryset`

Always start with:

```python
queryset = super().get_queryset()
```

Then add app-specific constraints.
Do not bypass base pipeline unless you intentionally want to skip built-in filtering/permissions.

### When adding row actions

Prefer declarative `actions` with permission keys (`permission`, `own_permission`, `owner_field`) so template-level checks remain consistent.

### When adding custom bulk actions

Use `custom_bulk_actions` and optional handler methods; avoid ad-hoc endpoints that duplicate selected-id parsing logic.

---

## Extension hooks for fields that aren't model columns

Some fields have no `Model._meta` entry (e.g. user-defined custom fields stored in a separate table). `HorillaListView` exposes small, default-no-op hooks so an extension app (`_inherit_list`, `_inherit_kanban`, `_inherit_view`) can supply them without any change to the views:

| Hook | Default | Used by |
|------|---------|---------|
| `get_group_field(field_name)` | `self.model._meta.get_field(field_name)` | Kanban, Group By and Chart: every place they resolve the grouping / stacking field. An override may return any object with `choices` (or be a `ForeignKey`), `verbose_name` and `null` |
| `persist_group_value(item, group_by)` | no-op | Kanban card move: called right after `item.save()`; the new value is already set on `item.<group_by>`, so an override can store it somewhere other than a column |
| `get_extra_quick_filter_fields()` | `[]` | Quick filters: extra `{"name", "verbose_name", "type"}` entries for the Add Quick Filter dropdown |
| `get_extra_quick_filter_choices(field_name)` | `None` | Quick filters: options for an extra field (`None` = not one of yours) |
| `apply_extra_quick_filter(queryset, field_name, value)` | `None` | Quick filters: filtered queryset for an extra field (`None` = not one of yours) |

An override that groups by such a field also has to make the grouping column available on the queryset (e.g. `annotate(cf_1=...)`), because the views call `queryset.filter(<field>=value)` and `queryset.values(<field>)`; `_get_allowed_group_by_fields()` / `get_group_by_field_choices()` / `get_chart_dimension_choices()` are the existing places to add the field to the choices. The Custom Fields app is the reference implementation: [field_management/README.md](../../../../../horilla/contrib/field_management/README.md).

---

## Notes and caveats

- `get_context_data()` calls `self.get_queryset()` multiple times for totals/ids; if subclass adds expensive annotations, cache carefully.
- `owner_filtration=False` should be used only when visibility is enforced elsewhere.
- Sorting by non-DB/computed properties is intentionally blocked in `_apply_sorting`.
- The class is HTMX-first; many UI interactions expect partial responses and query-state persistence.
