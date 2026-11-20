# Bulk update toolkit (`horilla_generics/views/toolkit/bulk_update.py`)

## Purpose

`HorillaBulkUpdateMixin` is the server-side engine for mass-editing list records in one request.

It handles:

- rendering bulk-update modal state,
- parsing selected IDs,
- validating editable fields against user permissions,
- coercing incoming values to model-compatible Python types,
- applying updates in one queryset operation,
- writing audit log entries per changed record,
- returning HTMX-friendly reload scripts/messages.

---

## Why this mixin exists

Bulk update logic is complex and distinct from list rendering/filtering concerns.
Moving it out of `HorillaListView` keeps list view maintainable while preserving shared behavior across all generic lists.

---

## Core surface

## `handle_bulk_update_post(self, request, record_ids, columns)`

Entrypoint called by list-view POST router.

Return contract:

- returns `HttpResponse` if request belongs to bulk update flow,
- returns `None` if request should fall through to other handlers (e.g., export/delete).

It supports 3 request modes:

1. modal rendering (`bulk_update_form=true`)
2. multi-field bulk apply (`record_ids` + `bulk_update_value_<field>` inputs)
3. legacy single-field mode (`bulk_update_field` + `bulk_update_value`)

---

## Request mode 1: render modal (`bulk_update_form=true`)

Payload input:

- `selected_ids` JSON array (string)

Flow:

1. decode JSON,
2. cast IDs to integers safely,
3. intersect with `self.get_queryset()` (authorization scope),
4. build context from `self.get_context_data()`,
5. set:
   - `selected_ids`
   - `selected_ids_json`
6. render `partials/bulk_update_form.html`.

Error path:

- on JSON parse/cast failure, renders same form with empty selected IDs.

Important nuance:

- code computes `valid_ids` from queryset scope but stores original parsed `selected_ids` in context.
  In practice selected IDs typically come from visible rows, but this is worth noting.

---

## Request mode 2: apply multi-field updates

Triggered when `record_ids` exists and at least one editable field value is posted.

### Input collection

1. parse `record_ids` JSON -> `record_ids_list`
2. resolve editable fields:

```python
editable_bulk_field_names = get_editable_fields(
    request.user, self.model, self.bulk_update_fields
)
```

3. for each editable field, read POST key:

- `bulk_update_value_<field_name>`

4. keep only non-empty submitted values -> `bulk_updates`.

If `bulk_updates` is empty:

- returns `None` (fall through), allowing other list POST handlers to process the request.

---

## Request mode 3: legacy single-field update

Triggered by:

- `bulk_update_field`
- `bulk_update_value`
- `record_ids`

Converts into the same internal call:

- `handle_bulk_update(record_ids_list, {field_name: new_value})`

Used for backward compatibility with older UI payloads.

---

## `render_bulk_update_form(self, request, context)`

Thin rendering wrapper:

- returns `render(request, "partials/bulk_update_form.html", context)`

Kept as method to support override/custom templates in subclasses.

---

## `handle_bulk_update(self, record_ids, bulk_updates)` (core engine)

This method performs validation + type coercion + update + audit logging.

Pipeline:

1. fetch target queryset by IDs
2. build field metadata map (`field_infos`)
3. resolve editable-field allowlist
4. validate/coerce each submitted field value
5. perform queryset `.update(**update_dict)`
6. compute per-record change diffs
7. create `LogEntry` update audit rows
8. return success message + HTMX reload script

---

## Stage 1: target queryset

```python
queryset = self.model.objects.filter(id__in=record_ids)
```

Note:

- uses `self.model.objects`, not `self.get_queryset()`.
- therefore caller is expected to pass authorized IDs.

---

## Stage 2: field metadata source

If list view exposes `_get_model_fields()`, mixin builds:

- `field_infos = {name: metadata_dict}`

This metadata drives type conversion and choice validation.

If metadata missing, update may fail with:

- `Field <name> not found` (`400`)

---

## Stage 3: editable allowlist enforcement

Permissions are checked via:

- `get_editable_fields(self.request.user, self.model, self.bulk_update_fields)`

Only fields in this resolved list are accepted; others are silently skipped.

This provides field-level security for bulk operations.

A list view can narrow a field's options with `bulk_update_choices`: a dict of field name to a callable that returns `(value, label)` pairs. `apply_bulk_update_choices` replaces that field's choices before the modal renders.

`bulk_update_country_state_fields` maps a country field to its state field. Choosing a country reloads the state options from `core:get_country_subdivisions`. User and contact bulk update set this pair.

---

## Stage 4: type coercion and validation rules

For each `(field_name, new_value)`:

- skip if field not editable
- skip if empty value (`""` or `None`)
- lookup `field_type` from metadata
- coerce by type:

### `boolean`

- truthy if value in `("true", "yes", "1")` (case-insensitive string)

### `number` / `integer`

- cast via `int(new_value)`

### `float` / `decimal`

- cast via `Decimal(new_value)`

### `date` / `datetime`

- coerced via `parse_bulk_date_value` / `parse_bulk_datetime_value`
- those methods call `get_datetime_formatter().parse_date` / `parse_datetime` ([DateTimeFormatter](../../formatting/datetime.md), [`_inherit_formatter`](../../../../extension/formatting/inherit.md))
- Gregorian by default; Jalali when the formatter extension is installed
- invalid parse raises `ValueError` -> `400`

### `choice`

- validate against metadata `choices` values
- invalid choice => `400`

### `foreignkey`

- empty string -> `None`
- otherwise attempts `int(new_value)` (keeps raw value if cast fails)

On conversion error:

- returns `400` with field-specific message.

---

## Stage 5: empty update guard

If no valid values survived filtering/coercion:

- adds info message:
  - `"No fields were updated as no values were provided."`
- returns script to reload list and clear selection.

This avoids no-op DB updates and provides user feedback.

---

## Stage 6: apply update

Before update:

- captures `records_before = {id: obj}` for diff calculation.

Then:

```python
updated_count = queryset.update(**update_dict)
```

This is a bulk SQL update (fast, no per-instance `save()` hooks/signals by default behavior).

---

## Stage 7: audit log creation

If records were updated:

1. resolve content type:

- `HorillaContentType.objects.get_for_model(self.model)`

2. iterate each requested record ID
3. compare old vs new values per updated field
4. if changed, create `auditlog.models.LogEntry` with:
   - action: `UPDATE`
   - actor: authenticated user (or `None`)
   - timestamp: `timezone.now()`
   - changes map: `[old, new]` (stringified with `"--"` for nulls)

This preserves row-level change history even though update was bulk SQL.

---

## Success response behavior

After completion:

- success message: `"Updated <count> records successfully."`
- returns script:
  - click `#reloadButton`
  - click `#unselect-all-btn-<view_id>`

Designed for HTMX/list UI workflows with checkbox selection reset.

---

## Error handling model

### `400` errors

- invalid `record_ids` JSON
- unknown field metadata
- invalid typed value / invalid choice
- missing required legacy params

### `500` errors

- unexpected failures in update/audit pipeline (`"Bulk update failed: ..."`).

### Soft-failure behavior

- non-editable fields are skipped (not treated as hard errors),
- empty values are skipped.

---

## Security and scope considerations

Key security measure:

- editable field allowlist from `get_editable_fields(...)`.

Important caveat:

- update queryset uses `self.model.objects.filter(id__in=record_ids)` directly; it does not re-apply list queryset permission filters here.

Operational assumption:

- IDs were sourced from authorized list rows in UI. For a user who lacks the blanket `change_<model>` permission but holds `change_own_<model>`, that authorized-row scoping happens one level up, in the entrypoint that computes `record_ids`: it restricts to rows matching `OWNER_FIELDS` OR'd with `get_granted_access_filter(self.model, user, "change")` when the model defines it — so a model opting into [granted access](../list.md#granted-access-per-model-opt-in-beyond-owner_fields) (e.g. `Opportunity` team members) can still be bulk-updated without an `OWNER_FIELDS` match.

If you need stricter defense-in-depth, override to intersect with `self.get_queryset()`.

---

## Practical payload examples

## Example 1: open bulk update modal

```text
POST /your-list-url/
bulk_update_form=true
selected_ids=[11,12,17]
```

Response:

- `partials/bulk_update_form.html` with selected IDs context.

---

## Example 2: multi-field update apply

```text
POST /your-list-url/
record_ids=[11,12,17]
bulk_update_value_stage=qualified
bulk_update_value_owner=5
bulk_update_value_priority=1
```

Behavior:

- validates each field against editable allowlist + metadata
- coerces values
- updates rows
- writes audit entries for changed fields.

---

## Example 3: legacy single-field mode

```text
POST /your-list-url/
record_ids=[11,12,17]
bulk_update_field=status
bulk_update_value=closed_won
```

Behavior:

- converted to internal `bulk_updates` dict and processed with same pipeline.

---

## Child class configuration examples

### Example 1: Disable configurable whitelist (`bulk_update_fields = []`)

```python
from horilla_generics.views.list import HorillaListView
from leads.models import Lead


class LeadListView(HorillaListView):
    model = Lead
    bulk_update_fields = []
```

What this means:

- you are not explicitly whitelisting fields at class level,
- effective editable fields are still governed by `get_editable_fields(...)` logic and permission rules.

Use this when you want default editable-field behavior from central policy.

### Example 2: Restrict to specific fields

```python
from horilla_generics.views.list import HorillaListView
from leads.models import Lead


class LeadListView(HorillaListView):
    model = Lead
    bulk_update_fields = ["stage", "owner", "priority", "next_follow_up_date"]
```

What this means:

- only these fields are considered in bulk update payload parsing,
- and each still requires per-user edit permission.

Use this when business policy requires a strict bulk-edit surface.

### Example 3: Turn off bulk update UI entirely

```python
class LeadListView(HorillaListView):
    model = Lead
    bulk_update_option = False
```

This hides bulk update action entry points in list UI.

---

## Extension points

Common customization options:

- override `render_bulk_update_form(...)` to use custom template/context
- override `parse_bulk_date_value` / `parse_bulk_datetime_value` only if you need view-local coercion — prefer `_inherit_formatter` for calendar systems
- override `handle_bulk_update(...)` to:
  - enforce queryset intersection with `self.get_queryset()`
  - add transaction wrapping
  - support additional field types (JSON, array, duration)
  - inject business-rule validators
- customize `self.bulk_update_fields` in list subclasses to narrow editable scope

---

## Caveats and implementation notes

- datetime parsing goes through `DateTimeFormatter.parse_datetime` (accepts ISO / `datetime-local`); timezone-awareness is not added in this mixin.
- `queryset.update(...)` bypasses model `save()` hooks/signals; audit entries compensate partially but do not replicate all side effects.
- selected IDs context in modal branch currently uses parsed IDs rather than queryset-validated IDs.
- foreign key conversion allows non-int fallback (if int cast fails), which may rely on ORM later raising errors for invalid values.

---

## Summary

`bulk_update.py` implements a permission-aware, type-coercing, audit-logging mass update pipeline for generic list views.
It is optimized for HTMX modal UX and high-performance SQL bulk updates while still preserving per-record change history through `LogEntry`.
