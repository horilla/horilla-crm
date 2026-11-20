# Custom Fields (`horilla.contrib.field_management`)

Lets an administrator define extra fields (`cf_1`, `cf_2`, …) on any
**opted-in** model — small text, large text, number, single choice, multiple
choice, date, or date and time — and surface them wherever that model's data
appears. Values are stored in `CustomFieldValue` rows, **not** as model
columns, so a field can be created, renamed or deleted at runtime without a
migration.

Custom Fields, Field Requirements and Form Layouts are one Settings app. See
[field requirements](field_requirements.md) and [form layouts](form_layouts.md).
The package tree and hook-by-hook notes also live in
`horilla/contrib/field_management/README.md`.

`horilla.contrib.core`, `generics`, `reports`, `dashboard` and the CRM apps
never import this app. Each surface that reads `Model._meta` exposes a generic
hook for fields that are not columns, and this app overrides that hook with an
extension.

## App startup (`apps.py`)

Shared with the other two features. `FieldSettingsConfig` (`AppLauncher`):

| Setting | Value |
|---------|--------|
| `name` | `horilla.contrib.field_management` |
| `label` | `field_management` |
| `url_prefix` | `field-management/` |
| `url_namespace` | `field_management` |
| `auto_import_modules` | `menu`, `registration`, `extensions` |

Settings menu: **Settings → Field Management → Custom Fields**
(`field_management.view_customfielddefinition`). Page URLs are
`field-management/custom-fields/`.

## Feature registration (`registration.py`)

```python
register_feature(
    "custom_fields",
    "custom_fields_models",
    auto_register_all=False,
)
```

A consuming app opts a model in from its own `registration.py`:

```python
register_model_for_feature(
    app_label="leads",
    model_name="Lead",
    features=["custom_fields_models"],
)
```

## Models (`models.py`)

Both extend `HorillaCoreModel` (company-scoped).

### `CustomFieldDefinition`

| Field | Role |
|-------|------|
| `content_type` | Target model (`HorillaContentType`) |
| `name` | Admin-facing label |
| `field_type` | `small_text`, `large_text`, `number`, `choice` (multi), `single_choice`, `date`, `datetime` |
| `is_required` | Form required flag |
| `choices` | Comma-separated options (choice types) |
| `order` | Display order |
| `is_full_width` | Span both columns of the form |

Synthetic form and list keys are `cf_<pk>` (`utils/custom_fields.py`).

### `CustomFieldValue`

One row per `(definition, object)`. Each type has its own typed column:
`value_text` (text and choices), `value_number`, `value_date`, and
`value_datetime` (timezone-aware, stored in UTC). Multiple Choice values are a
JSON list. Date inputs submit Gregorian ISO; with Jalali selected the picker
converts Shamsi selections before submit.

## Surfaces

| Surface | Extension |
|---------|-----------|
| Create / edit forms | `extensions/custom_fields_forms.py` |
| List columns and row values | `custom_fields_list.py`, `custom_fields_view.py` |
| Filter Records | `custom_fields_filter.py` |
| Detail, inline edit, Edit Details | `custom_fields_detail.py`, `custom_fields_view.py` |
| Export and scheduled export | `custom_fields_view.py` |
| Import template download | `custom_fields_import.py` |
| Quick filters | `custom_fields_quick_filter.py` |
| Kanban, Group By, Chart (Single Choice only) | `custom_fields_group_by.py` |
| Reports | `custom_fields_report.py` (`ReportFieldProvider.get_virtual_fields`) |
| Dashboard pickers, table, chart, KPI | `custom_fields_dashboard.py` |
| Condition dropdowns and checks | `custom_fields_conditions.py`, `custom_fields_condition_field.py` |
| Mail / notification "Insert Fields" | `custom_fields_view.py` (`{{ instance\|extension_field:"cf_1" }}`) |
| Field permissions modal | `custom_fields_view.py` (`get_extra_permission_fields`) |

Field permissions apply by `cf_<id>`: **hidden** drops the definition for that
user; **readonly** disables the form field and refuses inline edit.

Reports resolve each visible custom field as a request-cached `VirtualField`
named `cf_<id>` (a `Subquery` on `CustomFieldValue`). Dashboards reuse those
virtual fields through `get_extra_choices` and
`annotate_component_virtual_fields`. Condition engines compare values as text,
except Lead assignment rules, which add date-aware evaluation.
Date and datetime filters use the same relative-date bounds as model fields,
including this fiscal period, quarter and year.

`is_full_width` is applied on create and edit forms (including the wizard)
even when Custom Layout is not the active mode. See
[form layouts](form_layouts.md).

An applied-filter chip for a custom field uses the field's name.
`relabel_applied_filter_slot_rows` rewrites the chip that the navbar built as
`Cf <id>`. A navbar with no model skips that relabel.

## Not supported yet

- Import lists custom fields on the downloaded template, but steps 1–4 only
  map and save model columns. A custom-field column in an uploaded file is
  ignored.
- The report detail table cannot sort by a custom-field column. Reports also
  list text and choice fields under numeric Y-axis choices.
- Multiple Choice fields cannot group Kanban, Group By or Chart.
