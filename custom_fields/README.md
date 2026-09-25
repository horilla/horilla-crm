# Custom Fields (`custom_fields`)

**Package:** `custom_fields` (top-level Django app; installed as `"custom_fields"`)
**Current version:** see [`__version__.py`](__version__.py)
**Settings URL prefix:** `/custom-fields/` · namespace `custom_fields`

Lets an administrator define extra fields (`cf_1`, `cf_2`, …) on any **opted-in**
model — small text, large text, number, single choice, multiple choice, date, or
date and time — and
surface them wherever that model’s data appears:

| Surface | How it plugs in |
|---------|-----------------|
| Create / edit forms (single-step & multi-step wizards) | `FormExtension` |
| List columns + column picker | `ListExtension` / `ViewExtension` / `MixinExtension` |
| Filters (“Filter Records”) | `FilterExtension` + mixin |
| Detail header & Details tab + field selector | `DetailExtension` / `DetailSectionExtension` / mixin |
| Exports (column picker + cell values) | `ViewExtension` + mixin |

No CRM model is imported by name inside this app. Touch points are model-agnostic
and driven by the feature registry. Integration uses real
`horilla.extension.*` registrations — **not** monkey-patches.

> This app lives at the **repository root** (`custom_fields/`), alongside
> `booking/` and `calls/`. It is **not** under `horilla/contrib/`, but it follows
> the same isolation rules as contrib features (`field_requirements`,
> `form_layouts`, `duplicates`).

---

## Isolation rules

| Layer | Expectation |
|-------|-------------|
| `horilla.contrib.core` / `generics` | Do **not** import `custom_fields` |
| CRM model files (`horilla_crm/*/models*.py`) | Do **not** mention custom fields |
| Consuming app `registration.py` | Explicit `register_model_for_feature(..., features=["custom_fields"])` |
| This app’s tests | Prefer generic / registry fixtures; CRM HTTP scenarios belong in `horilla_crm` when needed |

Turning the feature on or off is a single line in `INSTALLED_APPS`
(`horilla/settings/horilla_apps.py` already includes `"custom_fields"`).

---

## Install / enable

```python
# horilla/settings/horilla_apps.py (or local INSTALLED_APPS)
INSTALLED_APPS = [
    # ...
    "custom_fields",
]
```

Settings menu entry: **Settings → Custom Fields** (`CustomFieldsSettings` in
`menu.py`), permission `custom_fields.view_customfielddefinition`.

| Route name | Path | Purpose |
|------------|------|---------|
| `custom_fields:view` | `/custom-fields/` | Settings shell |
| `custom_fields:list` | `/custom-fields/list/` | Definition list |
| `custom_fields:create` / `edit` / `delete` | … | CRUD for definitions |

---

## App startup (`apps.py`)

`CustomFieldsConfig` (`AppLauncher`):

| Setting | Value |
|---------|--------|
| `name` | `custom_fields` |
| `verbose_name` | Custom Fields |
| `url_prefix` | `custom-fields/` |
| `url_namespace` | `custom_fields` |
| `auto_import_modules` | `menu`, `view_extensions`, `registration`, `extensions`, `detail_extensions`, `filter_extensions`, `mixin_extensions`, `list_extensions` |

No `ready()` override. Every extension self-registers at import time via
`__init_subclass__`, the same pattern as other `_inherit_*` extensions.

---

## Feature registration (`registration.py`)

```python
register_feature(
    "custom_fields",
    "custom_fields_models",
    auto_register_all=False,
)
```

`auto_register_all=False` is required. Many CRM models call
`register_model_for_feature(..., all=True)`. Without this gate, every
`all=True` model would become custom-field-configurable.

### Opt a model in (consuming app)

From the **consuming** app’s `registration.py` (e.g. `horilla_crm/leads/`):

```python
from horilla.registry.feature import register_model_for_feature

register_model_for_feature(
    app_label="leads",
    model_name="Lead",
    features=["custom_fields"],  # feature name; "custom_fields_models" also works
)
```

Do **not** rely on `all=True` alone — selective features are skipped unless
listed in `features=` (or added to `include_models` when the feature is
registered).

`extensions.py`, `filter_extensions.py`, and `detail_extensions.py` read
`FEATURE_REGISTRY["custom_fields_models"]` at compose time and register
per-model / per-form extensions dynamically. No form or view class is hard-coded
by import path inside this app.

---

## Models (`models.py`)

Both extend `HorillaCoreModel` (company-scoped).

### `CustomFieldDefinition`

One row per custom field on a content type:

| Field | Role |
|-------|------|
| `content_type` | Target model (`HorillaContentType`) |
| `name` | Admin-facing label |
| `field_type` | `small_text`, `large_text`, `number`, `choice` (multi), `single_choice`, `date`, `datetime` |
| `is_required` | Form required flag |
| `choices` | Comma-separated options (choice types) |
| `order` | Display order |

Synthetic form/list keys are `cf_<pk>` (see `utils.is_custom_field_name`).

### `CustomFieldValue`

One row per `(definition, object)` holding the stored value (text / JSON list for
multi-choice via `parse_choice_values` / `serialize_choice_values`).

Each type has its own typed column so filters and rule engines compare real
values: `value_text` (text and choices), `value_number`, `value_date`, and
`value_datetime` (timezone-aware, stored in UTC). `set_value` writes the
column for the definition's type and clears the rest.

**Date and Date and Time** render as `<input type="date">` /
`<input type="datetime-local">`, like Horilla's own date fields. With the
`horilla_jalali` app installed and Shamsi selected, the same inputs open the
Jalali picker, which submits Gregorian ISO values — the database always holds
Gregorian dates. Display (detail, list, export, Edit Details) goes through the
composed `DateTimeFormatter`, so each viewer sees their own date format,
timezone, and calendar. Filters and condition builders (e.g. Lead assignment
rules) get the standard date operators: equals, before/after, between,
today/yesterday/this week/this month, and empty/not empty. Condition values
come back from `get_value` as ISO 8601 strings.

---

## Extension map

Every touch point is a real `horilla.extension.*` registration. See the
[extension index](../docs/horilla/extension/inherit.md).

### Dynamic, per-model discovery

| File | Extension type | Discovers via |
|------|----------------|---------------|
| `extensions.py` | `FormExtension` | `HorillaMultiStepForm` / `HorillaModelForm` whose `Meta.model` opted in |
| `filter_extensions.py` | `FilterExtension` | `HorillaFilterSet` whose `Meta.model` opted in |
| `detail_extensions.py` | `DetailExtension` + `DetailSectionExtension` | Detail view registries for opted-in models |

Each registers a **pre-compose hook**
(`horilla.extension._pre_compose_hooks.register_pre_compose_hook`) so discovery
re-runs whenever Horilla is about to compose that extension type. That covers a
model that opts in *after* `custom_fields` has already loaded (`INSTALLED_APPS`
order). This is an ordinary registration — Horilla bootstrap functions are not
reassigned.

### Bare mixins / functions (`mixin_extensions.py`)

Targets that never go through `as_view()` / `resolve_*_class()` use
`MixinExtension` (`_inherit_mixin` — see
[mixin/inherit.md](../docs/horilla/extension/mixin/inherit.md)):

| Extension | Target |
|-----------|--------|
| `CustomFieldFilterFieldsExtension` | `HorillaListFilterFieldsMixin._get_model_fields` |
| `CustomFieldBulkExportExtension` | `HorillaBulkExportMixin.handle_export` |
| `CustomFieldExportCellExtension` | `get_export_cell_value` (module function) |
| `CustomFieldDetailRenderExtension` | `detail_field.render` |
| `CustomFieldDetailDefaultsExtension` | `detail_field._get_detail_field_defaults` |
| `CustomFieldDetailEnsureSerializableExtension` | `detail_field._ensure_json_serializable` |
| `CustomFieldColumnSelectionFormExtension` | `ColumnSelectionForm.__init__` (plain Django form) |

**Scoped exception:** `CustomFieldBulkExportExtension.handle_export` temporarily
swaps `QuerySet.__iter__` for the duration of one export call (restored in
`finally`) because the stock `handle_export` iterates with a bare
`for obj in queryset:` and offers no override hook.

### Shared base classes (`list_extensions.py`, `view_extensions.py`)

| Extension | Target | Effect |
|-----------|--------|--------|
| `CustomFieldListContextExtension` | `HorillaListView` | Attach `cf_*` values to rows; exclude from sort |
| `CustomFieldMultiStepFormKwargsExtension` | `HorillaMultiStepFormView` | Keep multi-choice `cf_*` across wizard steps |

Base-class MRO fallback in `resolve_list_view_class()` / `resolve_view_class()`
applies these to every concrete subclass automatically (see
[Targeting a shared base class](../docs/horilla/extension/inherit.md#targeting-a-shared-base-class)).

`view_extensions.py` also registers concrete `ViewExtension`s on
`EditFieldView` / `UpdateFieldView` / `CancelEditView` (inline `cf_*` edit),
`ExportView` (export column modal + writer), and `ListColumnSelectFormView`
(Add Column to List).

---

## Multi-step wizard placement (`integration.py`)

`apply_multi_step_custom_fields()`:

1. Adds `cf_*` widgets to `form.fields`
2. Appends those names to `form.step_fields[last_step]` **explicitly**

Why: `HorillaMultiStepForm.__init__` auto-assigns unlisted fields to the last
step only for real model fields. Synthetic `cf_*` names raise
`FieldDoesNotExist` and are skipped. Because custom fields are injected *after*
that auto-assignment (via `setup_form_extension_fields()` on the composed form),
they must be added to `step_fields` or the wizard never renders them.

`step_fields` is copied per instance (`{**form.step_fields, ...}`) — never mutated
in place — because it is a class-level attribute shared across companies/forms.

---

## Typical end-to-end flow

1. Admin defines **Description** (`small_text`) for `Lead` under Settings → Custom Fields.
2. User opens Lead create → `FormExtension` adds `cf_<id>` (last wizard step or single form).
3. Lead list → `CustomFieldListContextExtension` attaches values; column picker can show the field.
4. Filter by `cf_*` → `FilterExtension` builds a `Q()` on `CustomFieldValue`.
5. Detail page → `DetailExtension` / `DetailSectionExtension` merge into header / Details tab.
6. Export → export `ViewExtension` + bulk-export mixin include the column and cell value.

---

## Package layout

```text
custom_fields/
├── apps.py                 # AppLauncher config
├── registration.py         # register_feature(...)
├── models.py               # Definition + Value
├── menu.py / urls.py / views.py / forms.py / filters.py
├── extensions.py           # FormExtension discovery
├── filter_extensions.py
├── detail_extensions.py
├── list_extensions.py
├── view_extensions.py
├── mixin_extensions.py
├── integration.py          # apply_* / clean / save helpers
├── utils.py                # cf_* naming helpers
├── form_hooks.py / detail_hooks.py / filter_hooks.py / …
├── tests.py
└── __version__.py
```

Legacy hook modules (`*_hooks.py`) remain for helpers used by the extension
layer; new behaviour should go through the extension registrations above.

---

## Related documentation

| Topic | Doc |
|-------|-----|
| Extension system index | [`docs/horilla/extension/inherit.md`](../docs/horilla/extension/inherit.md) |
| `_inherit_mixin` | [`docs/horilla/extension/mixin/inherit.md`](../docs/horilla/extension/mixin/inherit.md) |
| `_inherit_form` / filter / list / view | [`forms`](../docs/horilla/extension/forms/inherit.md) · [`filter`](../docs/horilla/extension/filter/inherit.md) · [`list`](../docs/horilla/extension/list/inherit.md) · [`view`](../docs/horilla/extension/view/inherit.md) |
| Feature registry | [`docs/horilla/registry/feature.md`](../docs/horilla/registry/feature.md) |
| Similar opt-in apps | `horilla.contrib.field_requirements`, `horilla.contrib.form_layouts`, `horilla.contrib.duplicates`, `horilla.contrib.cadences` |
| Versioning | [`docs/versioning.md`](../docs/versioning.md) |
