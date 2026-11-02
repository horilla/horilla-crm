# Timeline view (`horilla_generics/views/timeline.py`)

## Purpose

`HorillaTimelineView` renders records as a **Gantt-like timeline** using start/end date fields, while reusing the same filtering/search/sorting pipeline from `HorillaListView`.

It supports:

- timeline layout routing (`layout=timeline`),
- configurable start/end/title/group fields,
- per-user date/group field visibility filtering,
- saved timeline date preferences,
- grouping rows by choice/FK field,
- timeline scales (`days`, `weeks`, `months`, `quarters`),
- right range padding for better chart readability,
- detail URL linking per bar.

---

## Class: `HorillaTimelineView`

```python
class HorillaTimelineView(HorillaListView):
```

Defaults:

| Attribute | Default | Role |
|-----------|---------|------|
| `template_name` | `timeline_view.html` | Timeline page template. |
| `bulk_select_option` | `False` | No bulk select in timeline mode. |
| `table_class` | `False` | Simplified list/timeline visual style. |
| `table_width` | `False` | Flexible layout for timeline canvas. |
| `paginate_by` | `200` | Larger page for timeline plotting. |
| `timeline_start_field` | `None` | Required start date/datetime field. |
| `timeline_end_field` | `None` | End date; if missing/invalid, falls back to start field. |
| `timeline_title_field` | `None` | Bar title field; defaults to first column then `pk`. |
| `timeline_group_by_field` | `None` | Optional grouping/coloring field (choice/FK). |
| `timeline_fallback_end_field` | `None` | Declared but currently not applied in span computation logic. |

---

## Routing behavior (`dispatch`)

For non-HTMX GET requests:

- if `main_url` exists, it redirects to `main_url` with `layout=timeline`,
- sanitizes GET values using `_normalize_redirect_param_value`:
  - unwraps list-like string values (`"['x']" -> "x"`),
  - drops empty/invalid entries.

This keeps timeline access consistent through the main layout route.

---

## Field resolution logic

## Date field choices (`get_allowed_timeline_date_fields`)

- collects model concrete `DateField` and `DateTimeField`,
- filters by field-level visibility (`filter_hidden_fields`),
- returns `(field_name, verbose_name)` choices for dropdowns.

## Start/end field selection

### `get_timeline_start_field()`

Priority:

1. `GET[timeline_start]` if allowed
2. saved per-user preference (`get_saved_timeline_fields`)
3. class default `timeline_start_field`

### `get_timeline_end_field()`

Priority:

1. `GET[timeline_end]` if allowed
2. saved per-user preference
3. class default `timeline_end_field` (or resolved start field)

If resolved end field does not exist on model, context build falls back to start field.

## Title field (`get_timeline_title_field`)

Priority:

1. `timeline_title_field`
2. first configured `columns` field
3. `"pk"`

---

## Group-by behavior

## Allowed group fields (`get_allowed_timeline_group_by_fields`)

Includes:

- `CharField` with choices,
- all `ForeignKey` fields,

after applying:

- include/exclude filtering via `include_kanban_fields` / `exclude_kanban_fields`,
- extra exclusion of `"country"`,
- field-visibility filter.

## Active group-by field (`get_timeline_group_by_field`)

Priority:

1. `GET[timeline_group_by]`
2. `GET[group_by]`
3. class default `timeline_group_by_field`

Only accepted when present in allowed field list.

## Group label/key extraction (`_get_group_key_label`)

- FK -> key=`pk`, label=`str(related_obj)`; null -> `("none", "None")`
- choice field -> key=`raw value`, label=`get_<field>_display()`

---

## Timeline item construction (`get_context_data`)

Core flow:

1. call parent context and ensure `self.object_list`.
2. resolve start/end/title/group fields.
3. validate start field exists; return `timeline_error` if invalid/missing.
4. prefetch/select related for FK group field.
5. iterate queryset and build timeline items:
   - `start`, `end`, `title`,
   - `start_iso`, `end_iso`,
   - `detail_url` (if object has `get_detail_url()`),
   - `group_key`, `group_label`.

### Date normalization rules

- `_to_date` converts `date`, naive/aware `datetime`, and date-like objects.
- if `end` is missing -> uses `start`.
- if `end < start` -> clamps to `start` (single-day bar).

### Range window

If items exist:

- computes min/max range,
- applies symmetric margin:
  - minimum 7 days,
  - maximum 90 days.

If no items:

- defaults to `today - 90` through `today + 30`.

### Scale

`timeline_scale` GET param accepts:

- `days`, `weeks`, `months`, `quarters`

fallback: `months`.

### Group row assembly

- preserves FK order by related model `order` when available, else `pk`,
- appends `"none"` group at end if nulls exist,
- builds `timeline_group_rows = [{group, items}, ...]`,
- if no grouping -> single `"All"` row.

---

## Context keys exposed

Key outputs include:

- `timeline_items`
- `timeline_groups`
- `timeline_group_rows`
- `timeline_range_start`, `timeline_range_end`
- `timeline_scale`, `timeline_scale_choices`
- `timeline_start_field`, `timeline_end_field`
- `timeline_date_field_choices`
- `timeline_group_by_field`, `timeline_group_by_choices`
- `current_timeline_group_by`, `current_timeline_group_by_label`
- `timeline_span_caption`
- `timeline_title_field`
- `timeline_error` (when applicable)

Plus standard list context from `HorillaListView` (filters, actions, query params, etc.).

---

## Helper methods

### `_normalize_redirect_param_value(value)`

Safely converts request values to scalar string for redirect query building.

### `_to_date(value)`

Normalizes values to date in local timezone (aware datetimes use `localtime()`).

### `get_timeline_span_caption(model, start_field, end_field)`

Returns user-facing caption:

- `"Bars use: <field>"` when same field
- `"From <start> -> <end>"` when different

### `_get_display_value(obj, field_name)`

Uses `get_<field>_display()` when available (choice-friendly), else raw string.

---

## Examples

## Example 1: Lead timeline (standard start/end + choice group)

```python
@method_decorator(
    permission_required_or_denied(["leads.view_lead", "leads.view_own_lead"]),
    name="dispatch",
)
class LeadTimelineView(LoginRequiredMixin, HorillaTimelineView):
    model = Lead
    view_id = "leads-timeline"
    filterset_class = LeadFilter
    search_url = reverse_lazy("leads:leads_list")
    main_url = reverse_lazy("leads:leads_view")
    enable_quick_filters = True
    timeline_start_field = "created_at"
    timeline_end_field = "updated_at"
    timeline_group_by_field = "lead_status"
    timeline_title_field = "title"
    columns = ["title", "first_name", "email", "lead_status"]
    actions = LeadListView.actions
```

Use this pattern when:

- start and end are both reliable,
- grouping by a choice/FK status field.

---

## Example 2: Opportunity timeline (end can be before start)

```python
class OpportunityTimelineView(LoginRequiredMixin, HorillaTimelineView):
    model = Opportunity
    view_id = "opportunity-timeline"
    filterset_class = OpportunityFilter
    search_url = reverse_lazy("opportunities:opportunities_list")
    main_url = reverse_lazy("opportunities:opportunities_view")
    enable_quick_filters = True
    timeline_start_field = "created_at"
    timeline_end_field = "close_date"
    timeline_fallback_end_field = "updated_at"
    timeline_group_by_field = "stage"
    timeline_title_field = "name"
    columns = ["name", "amount", "close_date", "stage", "opportunity_type"]
```

In current implementation, if `close_date < created_at`, end is clamped to start (single-day bar).

---

## Example 3: GET overrides at runtime

Users can change timeline without code change:

```text
?layout=timeline
&timeline_start=created_at
&timeline_end=updated_at
&timeline_group_by=lead_status
&timeline_scale=weeks
```

Overrides are accepted only if fields are in allowed visible choices.

---

## Example 4: Minimal custom timeline

```python
class TicketTimelineView(HorillaTimelineView):
    model = Ticket
    view_id = "ticket-timeline"
    timeline_start_field = "opened_on"
    timeline_end_field = "due_on"
    timeline_title_field = "subject"
    timeline_group_by_field = "priority"
    columns = ["subject", "priority", "assignee"]
    filterset_class = TicketFilter
    search_url = reverse_lazy("tickets:tickets_list")
    main_url = reverse_lazy("tickets:tickets_view")
```

---

## Recommended subclass checklist

- set `model`, `view_id`, `filterset_class`, `search_url`, `main_url`
- define `timeline_start_field` (mandatory for useful timeline)
- define `timeline_end_field` (or allow same-day bars)
- choose `timeline_title_field` for readable bars
- optionally set `timeline_group_by_field`
- keep `columns` small but informative
- if overriding `get_queryset`, start with `super().get_queryset()` to retain list filters/permissions

---

## Notes

- `HorillaTimelineView` intentionally reuses list-level filtering and permissions, so timeline reflects exactly the same data scope as list/kanban/split views.
- Group ordering for FK group fields respects related model `order` when present.
- On RTL pages (`dir="rtl"`) time runs right to left: the axis row is mirrored, bars and grid lines are offset from the right edge, and the initial scroll counts from the right.
- `timeline_fallback_end_field` exists as config but current span logic no longer swaps to fallback when end < start.
