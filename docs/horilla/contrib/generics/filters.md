# Filtering utilities (`horilla_generics/filters.py`)
## Purpose
`horilla_generics/filters.py` defines the generic filtering foundation used by Horilla list/report UIs:
- operator catalog by field type (`OPERATOR_CHOICES`)
- `HorillaFilterSet` with:
- array-based multi-condition filtering (`field[]`, `operator[]`, `value[]`)
- range filtering (`between` with `start_value`/`end_value`)
- robust empty/not-empty semantics
- smart text search (`search`) with optional split-name logic
It is designed for dynamic filter builders where users can compose multiple rules in one request.
---
## Core constants
## `STRING_LIKE_FIELDS`
Tuple of model field classes treated as text-like for "empty" semantics:
- `CharField`
- `TextField`
- `EmailField`
- `URLField`
- `GenericIPAddressField`
- `SlugField`
Why it matters:
- for these fields, `is empty` means:
- `NULL` **or** `""`
- and `is not empty` means:
- not `NULL` **and** not `""`
This matches user expectations for text fields where blank string is common.
---
## `OPERATOR_CHOICES`
Defines allowed operators per abstract field type:
- `text`: `icontains`, `exact`, `ne`, starts/ends with, empty checks
- `number`/`float`/`decimal`: equality/comparisons + `between` + empty checks
- `date`/`datetime`: equality/order + `between` + relative-date operators (`today`, `yesterday`, `this_week`, `this_month`, `this_year`, `this_fiscal_period`, `this_fiscal_quarter`, `this_fiscal_year`) + empty checks
- `boolean`: `exact`
- `choice` / `foreignkey`: `exact` (multiple comma-separated values become `__in`) + empty checks
- `other`: fallback (`exact`, `icontains`, empty checks)
Labels are lazily translated (`gettext_lazy`). `RELATIVE_DATE_OPERATORS` lists the value-less relative-date operators. The map is consumed by UI metadata builders and filter execution logic.
---
## `HorillaFilterSet`
Subclass of `django_filters.FilterSet` with custom query parsing and search behavior.
`get_fields()` is overridden to drop non-editable model fields, so `fields = "__all__"` does not expose system-managed fields as filters/columns.
Defined filter:
- `search = CharFilter(method="filter_search")`
---
## `get_operators_for_field(field_type)`
Class method returning operator list from `OPERATOR_CHOICES`.
Fallback:
- returns `"other"` operators when field type key is unknown.
Used by filter UI to populate operator dropdowns dynamically.
---
## `_convert_boolean_value(value, model, field_name)`
Converts string boolean inputs to real booleans for boolean model fields.
Behavior:
- if target field is `BooleanField`:
- `"true"` -> `True`
- `"false"` -> `False`
- otherwise returns original value unchanged.
This prevents mismatches where query params are strings but DB filter expects boolean.
---
## `filter_queryset(queryset)` (main engine)
Overrides default django-filter behavior to support parallel filter arrays.
### High-level pipeline
1. if form cleaned data exists, call `super().filter_queryset(queryset)` first
2. resolve request object
3. read parallel arrays:
- `field[]`
- `operator[]`
- `value[]`
- `start_value[]`
- `end_value[]`
- `logic[]` (`AND` / `OR`, index-aligned with the rows)
4. iterate each `(field, operator)` pair, skipping unknown operators and fields in `Meta.exclude`
5. build one `Q` per row with `_build_row_q(...)` and combine it with the previous rows using that row's `logic` (default `AND`; the first row is the anchor so its logic is ignored; invalid values fall back to `AND`)
6. apply the combined `Q` once, then free-text search (`search`) at end
The loop uses `zip(fields, operators)`, so only aligned index pairs are processed.
---
### Operator semantics in execution
## `ne` (not equals)
- reads `value[i]`
- applies boolean conversion if needed
- builds `~Q(field=value)` (for a datetime field with a bare `YYYY-MM-DD` value, `~Q(field__date=value)`)
## `between`
Uses index-aligned:
- `start_value[i]`
- `end_value[i]`
Behavior:
- both provided: `field__gte=start` and `field__lte=end`
- only start: `field__gte=start`
- only end: `field__lte=end`
- datetime fields compare on `field__date__*` (calendar days)
## `isnull`
- for text-like fields: `(field IS NULL) OR (field == "")`
- other fields: `field__isnull=True`
## `isnotnull`
- for text-like fields: `NOT NULL AND != ""`
- other fields: `field__isnull=False`
## relative date operators
- `today`, `yesterday`, `this_week`, `this_month`, `this_year` and the fiscal ones need no `value`
- bounds come from `horilla.contrib.core.services.relative_dates.get_relative_date_bounds(operator)` (fiscal operators follow the company's fiscal year config)
- datetime fields filter on `__date` / `__date__gte`+`__date__lte`; date fields on the field directly
## generic operators (e.g. `exact`, `icontains`, `gt`)
- reads `value[i]`
- `exact` on a choice/foreign-key field splits the value on commas: one value -> `exact`, several -> `__in`
- a bare date against a datetime field uses `field__date__<operator>`
- boolean-converts when relevant
- applies dynamic lookup `Q(**{f"{field}__{operator}": value})`
---
### Error behavior
Per-condition exceptions are caught and logged:
- filtering continues for remaining conditions
- engine favors resilience over hard-fail for one bad clause
This keeps UI usable even with partially invalid query payloads.
---
### Search integration
After condition loop:
- reads `search` from data/GET
- applies `filter_search(...)` if non-empty.
This means search is combined with condition filters in final queryset.
---
## `filter_search(queryset, name, value)`
Search helper with optional smart split-name handling.
Requires:
- `Meta.search_fields` defined on child filterset.
If absent or empty search value:
- returns queryset unchanged.
---
### Name split logic
Reads optional:
- `Meta.name_split_fields`
If missing and both `first_name` + `last_name` exist in `search_fields`, infers:
- `["first_name", "last_name"]`
When search text contains space and split fields are valid:
1. split into first and second parts (`"john doe"` -> `"john"`, `"doe"`)
2. apply full-string `icontains` OR queries to non-name fields
3. apply AND-style name clause:
- `first_name__icontains=first_part`
- `last_name__icontains=second_part`
When no split scenario:
- apply OR `icontains` across all search fields using full value.
Finally:
- `queryset.filter(queries)` (the `Q` itself comes from `build_search_q(value)`, which `apply_search_facets` reuses for `all`)
---
## Field searches (list search box)
After the legacy `search` is applied, `filter_queryset` also applies the repeatable `sf=<field>:<text>` parameter set by the list's search box (see [list search](views/list_search.md)). `field` is `all` (every `Meta.search_fields` entry, with the split-name logic above) or one entry of `Meta.search_fields`; unknown fields and empty text are ignored. `sf` entries on the same field are OR'd and entries on different fields are AND'd.

When `first_name` and `last_name` (or `Meta.name_split_fields`) are both searched, `get_search_field_labels()` offers them as one **Name** choice, `first_name+last_name` (`get_name_search_key()`), applied with `name_search_q()`; `build_field_q(lookup, text)` gives the `Q` for any choice. `get_name_split_fields()` resolves the two name fields for `build_search_q` and these methods alike. The key format is defined once, in `search_support.py` (`make_name_key` builds it, `split_name_key` reads it back, `combined_name_label` names it), so the filterset, the dropdown and the applied-filter tag always agree on it.

The search box's quick filters (My Records, Created Today, ...) need no code here: they are added as ordinary `field` / `operator` / `value` filter rows.

`get_search_field_labels()` (classmethod) returns `{lookup: label}` for `Meta.search_fields`, using the fields' verbose names; entries that are not model fields are left out. The search box uses it for its field choices.
---
## Child class usage examples
## Example 1: minimal filterset
```python
from horilla_generics.filters import HorillaFilterSet
from leads.models import Lead
class LeadFilterSet(HorillaFilterSet):
class Meta:
  model = Lead
  fields = []
  search_fields = ["name", "email", "company__name"]
```
This enables generic condition filtering + search across listed fields.
### Example 2: split full-name search
```python
class EmployeeFilterSet(HorillaFilterSet):
class Meta:
  model = Employee
  fields = []
  search_fields = ["first_name", "last_name", "email"]
  name_split_fields = ["first_name", "last_name"]
```
Search `"jane doe"` matches first/last in split manner while still searching non-name fields.
### Example 3: dynamic UI operators
```python
operators = EmployeeFilterSet.get_operators_for_field("date")
# [("exact","Equals"), ("gt","After"), ("lt","Before"), ...]
```
Used by frontend filter row builders.
---
## Request payload examples (conceptual)
### Multi-condition filter
```text
GET /employees/?apply_filter=true
field=department&operator=exact&value=5
field=is_active&operator=exact&value=true
search=jane
```
Effect:
- department equals 5
- boolean conversion on `is_active`
- plus text search "jane".
### Range filter
```text
GET /leads/?apply_filter=true
field=created_at&operator=between&start_value=2026-01-01&end_value=2026-01-31
```
Effect:
- created_at within inclusive range.
### Empty-string-aware filter
```text
GET /contacts/?apply_filter=true
field=email&operator=isnull
```
Effect for text-like field:
- email is NULL or empty string.
---
## Integration notes
`HorillaFilterSet` is typically paired with:
- `HorillaListFilterFieldsMixin` metadata/UI helpers (`_get_model_fields`, operator/value partial updates),
- list views that pass request/query params into filterset instance,
- quick-filter and saved-filter URL states.
Together they provide a dynamic, operator-driven filtering UX.
---
## Caveats and behavior notes
- parallel arrays rely on index alignment; malformed client payloads can skip intended conditions.
- operator execution trusts field lookup strings from request; invalid lookups are logged and skipped.
- boolean conversion only applies when target model field is actually `BooleanField`.
- search uses `icontains` OR composition (plus special split-name clause) and may be broad on large datasets without indexes.
---
## Summary
`horilla_generics/filters.py` is the core generic filtering engine for Horilla. It standardizes operator choices by field type, executes robust multi-condition filtering with range/empty semantics, and provides smart search behavior that supports both general text queries and full-name split matching.
