# Quick filter toolkit (`horilla_generics/views/toolkit/quick_filter.py`)

## Purpose

`quick_filter.py` provides standalone helper functions for "quick filters" in list views.
Unlike mixin-based toolkit modules, these functions are called from the view layer directly and do not require inheritance.

It supports:

- discovering quick-filterable model fields,
- storing active quick filter definitions per user/model (`QuickFilter` rows),
- generating valid choice lists for each quick filter,
- applying quick filter values to queryset,
- handling HTMX add/remove quick filter actions,
- injecting quick-filter UI context into list templates.

---

## Quick filter concept

There are two separate layers:

1. **Filter definition layer** (`QuickFilter` model rows)
   - which fields user wants in quick-filter bar.
2. **Filter value layer** (`qf_<field_name>` query params)
   - selected values currently applied to list query.

So adding/removing a quick filter changes UI structure, while GET params control current filtered results.

---

## Field discovery logic

## `get_available_quick_filter_fields(view)`

Auto-detects fields eligible for quick filters when `view.enable_quick_filters=True`.

Includes only:

- `ForeignKey`
- fields with `choices`
- `BooleanField` / `NullBooleanField`

Skips:

- `id`
- `auto_created` fields
- non-editable fields
- names listed in `view.exclude_quick_filter_fields`

Output shape:

```python
[
  {"name": "stage", "verbose_name": "Stage", "type": "choice"},
  {"name": "owner", "verbose_name": "Owner", "type": "foreignkey"},
]
```

If quick filters are disabled, returns `[]`.

---

## Stored quick filters retrieval

## `get_quick_filters(view)`

Returns active `QuickFilter` rows scoped by:

- current user
- model app label
- model class name

Used across render/apply/add/remove flows.

---

## Choice generation logic

## `get_quick_filter_choices(view, field_name)`

Builds selectable values for one quick-filter field.

### Boolean fields

Returns:

- `true` -> `Yes`
- `false` -> `No`

### Choice fields

Returns model `choices` as `{value,label}` pairs.

### ForeignKey fields

Base queryset:

- `related_model.objects.all()`

Then optional refinement using `view.filterset_class`:

- instantiates temporary filterset
- if target filter exists, tries to use filter field's queryset

Finally:

- limits to first 200 records
- serializes to `{value: pk, label: str(obj)}`.

If any error occurs, logs and returns `[]`.

---

## Value validation

## `is_valid_quick_filter_value(view, field_name, filter_value)`

Checks whether incoming GET value is in generated choices for the field.

Benefits:

- invalid/tampered values are ignored,
- prevents applying arbitrary values that are not in allowed choice set.

---

## Queryset application

## `apply_quick_filters(queryset, view)`

Applies active quick filter values from GET params.

Important gate:

- quick filters apply **only when `view_type == "all"`**.
- if user is in another view type (`saved_list_*`, `recently_viewed`, etc.), function returns queryset unchanged.

Application loop:

1. iterate each active `QuickFilter` row,
2. read GET key `qf_<field_name>`,
3. validate value via `is_valid_quick_filter_value`,
4. apply filter by field type:
   - boolean -> python bool
   - foreign key -> `<field>_id`
   - others -> direct equality

Invalid values are skipped silently (with safe fallback behavior).

---

## POST action handler

## `handle_quick_filter_post(request, action, view)`

Handles quick-filter add/remove operations and returns HTMX responses.

Returns:

- handled response (`HttpResponse`) for quick-filter actions,
- `None` when action does not belong here.

### Action: `add_quick_filter`

Input:

- `field_name` list from POST

Flow:

1. intersect submitted names with available quick-filter fields,
2. if no valid fields:
   - re-render add form with error message
   - set HTMX retarget/rewap/reselect headers to keep modal content stable,
3. compute existing filter count and existing names,
4. `bulk_create` missing `QuickFilter` rows with sequential `display_order`,
5. re-render the main list template (`view.template_name`), which includes the quick filter bar,
6. return it with `HX-Retarget`/`HX-Reselect` set to `#<view_id>` and `HX-Reswap: outerHTML`.

### Action: `remove_quick_filter`

Input:

- `filter_id`

Flow:

1. load and delete selected `QuickFilter` row for current user,
2. remove corresponding GET param `qf_<field_name>` from request copy,
3. temporarily replace `request.GET` with cleaned params,
4. rebuild quick filter bar + list content with cleaned query state,
5. restore original `request.GET`,
6. return combined response and optionally push clean URL.

URL behavior:

- when `view.filter_url_push=True` (default):
  - sets `HX-Push-Url` and `HX-Replace-Url` to cleaned URL,
- otherwise disables push (`HX-Push-Url=false`).

Error path:

- on removal failure, returns small reload snippet retargeted to table container.

---

## GET action handler

## `handle_quick_filter_get(request, view)`

Handles modal form rendering for adding quick filters.

Trigger:

- `show_add_quick_filter=true` in GET

Behavior:

1. computes available quick-filter fields,
2. removes fields already active in existing `QuickFilter` rows,
3. renders `partials/add_quick_filter_form.html`.

If trigger absent, returns `None`.

---

## Context injection helper

## `update_quick_filter_context(context, view)`

Injects all template data needed for quick-filter UI.

When disabled:

- sets safe defaults:
  - `enable_quick_filters=False`
  - empty quick filter arrays
  - `quick_filters_height_adjustment=0`

When enabled:

1. builds `quick_filters` list with:
   - id, field metadata, choices, selected GET value
2. computes `available_quick_filter_fields` (not currently active)
3. computes `quick_filters_height_adjustment` for layout:
   - base behavior:
     - no filters: 245
     - 1-4 filters: 285
     - >4 filters: additional row-based increments

This height value is used by list/split layouts to keep content panel height aligned with filter bar growth.

---

## Extension hooks

`get_available_quick_filter_fields(view)`, `get_quick_filter_choices(view, field_name)` and `apply_quick_filters(queryset, view)` give the view a chance to supply fields that aren't model columns, through three default-no-op methods on `HorillaListView` (see [list.md](../list.md#extension-hooks-for-fields-that-arent-model-columns)):

| Function | Calls | Effect |
|----------|-------|--------|
| `get_available_quick_filter_fields` | `view.get_extra_quick_filter_fields()` | Entries are appended to the available-fields list |
| `get_quick_filter_choices` | `view.get_extra_quick_filter_choices(field_name)` | A non-`None` result is returned instead of resolving a model field |
| `apply_quick_filters` | `view.apply_extra_quick_filter(queryset, field_name, value)` | A non-`None` queryset replaces the model-column filtering for that quick filter |

Adding, removing and rendering quick filters need no other change: they only look at the field name and the choices.

---

## Templates involved

Quick-filter helper functions render or compose:

- `partials/add_quick_filter_form.html`
- `partials/quick_filters_bar.html`
- main list template (`view.template_name`) for the refreshed list body, which includes the filter bar

This design allows one action to refresh both filter bar and list table in a single HTMX response.

---

## Child class configuration examples

### Example 1: enable quick filters with defaults

```python
from horilla_generics.views.list import HorillaListView
from leads.models import Lead


class LeadListView(HorillaListView):
    model = Lead
    enable_quick_filters = True
```

### Example 2: exclude fields from quick-filter discovery

```python
class LeadListView(HorillaListView):
    model = Lead
    enable_quick_filters = True
    exclude_quick_filter_fields = ["company", "created_by"]
```

### Example 3: disable URL push when removing quick filters

```python
class LeadListView(HorillaListView):
    model = Lead
    enable_quick_filters = True
    filter_url_push = False
```

---

## HTMX interaction examples (conceptual)

### Add quick filter fields

```text
POST /leads/list/
action=add_quick_filter
field_name=stage
field_name=owner
```

Result:

- persists missing `QuickFilter` rows,
- returns combined HTML replacing quick filter bar and list body.

### Remove one quick filter

```text
POST /leads/list/?view_type=all&qf_stage=qualified&qf_owner=4
action=remove_quick_filter
filter_id=27
```

Result:

- deletes filter definition,
- removes corresponding `qf_*` param from URL/context,
- returns refreshed quick bar + list,
- pushes cleaned URL (if enabled).

---

## Integration points in list/navbar flow

- Navbar action can open add-quick-filter modal when `enable_quick_filters=True`.
- List queryset pipeline should call `apply_quick_filters(...)` during queryset construction.
- List context builder should call `update_quick_filter_context(...)` before render.
- POST/GET handlers should delegate quick-filter actions via:
  - `handle_quick_filter_post(...)`
  - `handle_quick_filter_get(...)`.

This keeps quick-filter concerns modular and reusable outside a specific mixin hierarchy.

---

## Error handling and resilience

- choice generation failures are logged and yield empty choice lists,
- invalid submitted fields for add action render modal with validation feedback,
- invalid filter values in GET are ignored (not fatal),
- remove action failures trigger safe list reload response.

The module prioritizes non-breaking UI behavior over hard errors.

---

## Caveats and behavior notes

- ForeignKey choices are capped at 200 values; large related tables may need search-based UX for scalability.
- Quick filters are only applied for `view_type=all`; users may expect same behavior in saved/custom views unless documented.
- Removal flow temporarily mutates `request.GET` and restores it in `finally`; this is safe in current sync request lifecycle.
- Field detection relies on model field classes and metadata. Fields that aren't model columns are added through the view hooks described in [Extension hooks](#extension-hooks) below.

---

## Summary

`quick_filter.py` is a complete helper toolkit for user-configurable quick filters: discovery, persistence, validation, queryset application, HTMX add/remove actions, and context preparation. It enables dynamic, per-user filter bars while keeping list view implementations clean and reusable.
