# Single-step form base (`horilla_generics/forms/single_step.py`)

## Purpose

`HorillaModelForm` is the base form class for standard (single-page) generic form workflows.

It combines:

- field permission handling (`hidden` / `readonly`)
- dynamic condition-row field integration
- FK/M2M Select2 widget wiring
- date/time widget normalization
- file initial-state metadata handling
- server-side validation for stale/tampered selectable values

This is the form foundation used by `HorillaSingleFormView` and related dynamic form builders.

Fieldset forms (`form_fieldset.html`) show a field's `help_text` as an info icon. The icon's accessible name is that text.

---

## Class overview

```python
class HorillaModelForm(HorillaFormMixin, forms.ModelForm):
```

Base mixin dependency:

- `HorillaFormMixin` from `form_class_mixin.py`

Primary external helper dependency:

- `horilla_generics.forms.condition_fields` module (dynamic condition logic and validation)

---

## Automatic core-field exclusion (`__init_subclass__`)

`HorillaModelForm` overrides `__init_subclass__` so every subclass automatically
excludes `HORILLA_FORM_EXCLUDE` fields from its `Meta` — no import or helper call
needed in the child.

### What gets excluded by default

Defined in `horilla_generics/forms/constants.py`:

```python
HORILLA_FORM_EXCLUDE = [
    "company",
    "is_active",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
    "additional_info",
]
```

These are `HorillaCoreModel` audit/tenant fields that should never appear on
create/edit forms unless explicitly requested.

### Merge logic

At class definition time `__init_subclass__` runs once and:

1. reads `Meta.keep_on_form` (defaults to empty) — fields to **remove** from the base list
2. reads `Meta.exclude` (defaults to empty) — child's own extra fields to hide
3. produces `merged = child_exclude + base_exclude_not_already_present`
4. writes `merged` back onto `meta.exclude`

The child's explicit fields come first; base fields fill in after, no duplicates.

### `Meta.keep_on_form`

Iterable of field names that are normally excluded but should be **visible** on
this specific form.

```python
class AdminForm(HorillaModelForm):
    class Meta:
        model = MyModel
        fields = "__all__"
        keep_on_form = ("company",)   # company shown; rest still hidden
```

### Patterns

| Child `Meta` | Effective `exclude` |
|---|---|
| No `exclude`, no `keep_on_form` | Full `HORILLA_FORM_EXCLUDE` |
| `exclude = ["name"]` | `["name"] + HORILLA_FORM_EXCLUDE` (no duplicates) |
| `keep_on_form = ("company",)` | `HORILLA_FORM_EXCLUDE` minus `company` |
| `exclude = ["name"]` + `keep_on_form = ("company",)` | `["name"]` + core fields minus `company` |

### Why `__init_subclass__` not a helper function

A helper like `horilla_core_form_exclude()` required every child to remember to
import and call it.  `__init_subclass__` makes the exclusion a **guarantee** —
forgetting to do anything is the correct action.

---

## Fieldsets and `get_fieldsets()`

`HorillaModelForm.fieldsets` is an optional Django-admin-style tuple of `(name, options)` groups. `get_fieldsets()` returns bound fields for templates so extension apps can inject columns with `fieldsets_insert` without editing HTML.

```python
fieldsets = (
    (
        _("Date Time Format"),
        {"fields": ("date_time_format", "date_format", "time_format")},
    ),
)
```

```django
{% for fieldset in form.get_fieldsets %}
    <h3>{{ fieldset.name }}</h3>
    {% for field in fieldset.fields %}
        {{ field.label }} {{ field }}
    {% endfor %}
{% endfor %}
```

Each item is `{"name", "fields", "description"}`. Only names present on the live form instance are included (hidden widgets are skipped when `fieldsets` is empty). If `fieldsets` is empty, all visible fields are returned in one untitled group.

**Related:** [`fieldsets_insert`](../../../extension/forms/inherit.md#layout-hooks) · [Regional formatting](../../core/core_app.md#regional-formatting)

---

## Initialization flow (`__init__`)

`__init__` pipeline is ordered and stateful.

## 1) Pop runtime options

`_pop_form_options(kwargs)` extracts and stores:

- layout/form options: `full_width_fields`, `dynamic_create_fields`, `hidden_fields`
- condition config:
  - `condition_fields`
  - `condition_model`
  - `condition_related_name`
  - `condition_related_name_candidates`
  - `condition_hx_include`
  - `row_id`
  - `model_name`
  - `condition_field_choices` (or auto-build)
- request/permission options:
  - `request`
  - `field_permissions`
  - `save_and_new`
  - `duplicate_mode`
- `instance_obj` reference

If `model_name` missing, resolves via:

- `condition_fields_module.get_model_name_from_request_or_instance(...)`

If `condition_field_choices` missing and condition model exists, builds via:

- `condition_fields_module.build_condition_field_choices(...)`

## 2) Standard ModelForm init

- `super().__init__(*args, **kwargs)`

## 3) File/initial setup

Calls `_setup_file_and_initial()`:

- handles existing file markers
- tracks clear/upload states in widget attrs:
  - `data_existing_filename`
  - `data_uploaded_filename`
  - `data_cleared`

## 4) Dynamic condition field injection

If `condition_fields` configured:

- calls `condition_fields_module.add_condition_fields(self)`
- in edit mode with condition model:
  - `set_initial_condition_values(...)`

Always calls:

- `condition_fields_module.add_generic_htmx_to_field(self)`

to wire content-type-driven condition updates.

## 4a) Phone field widget injection

Calls `_apply_phone_fields()` (inherited from `HorillaFormMixin`).

Replaces any `CharField` whose name is in the active phone field set (`phone`, `mobile`, `contact_number`, `fax`, etc.) with `PhoneField` — a Select2 country-code dropdown paired with a number text input. Stored value format: `+XX NNNNNN`.

No migration required. Subclasses can extend or disable via `phone_fields` class attribute — see `form_class_mixin.md`.

## 5) Per-field widget/permission pass

For each form field:

- skip `is_custom_field` generated by condition helpers
- skip fields in `condition_fields` (already fully built by `add_condition_fields`, so their scoped choices are not overwritten)
- force hidden widgets for `hidden_fields`
- compute readonly state from:
  - `field_permissions`
  - existing widget readonly attrs
- in create/duplicate mode:
  - mandatory readonly fields stay editable
- apply generic classes/placeholders
- type-specific processing (date/time, FK, M2M, select, checkbox, textarea)

## 6) Final permission-based removal

Calls:

- `_remove_fields_by_permission(...)`

while protecting condition/hidden fields from accidental removal via `skip_field_names`.

---

## Field processing details

## Hidden fields

Fields in `hidden_fields` (or already hidden widgets) are forced to:

- `forms.HiddenInput`
- class `hidden-input`

---

## Readonly logic

Readonly is inferred from:

- `field_permissions[field_name] == "readonly"` or existing widget attr

Special rule:

- create/duplicate + mandatory field => readonly disabled (user must fill required value).

For select-like widgets:

- disabled with readonly styling via `_apply_readonly_to_select_attrs(...)`

For text-like widgets:

- readonly attribute applied (not disabled).

---

## Date/DateTime/Time handling

`_apply_datetime_like_widget(...)` sets:

- `DateTimeField` -> `DateTimeInput` with `%Y-%m-%dT%H:%M`
- `DateField` -> `DateInput` with `%Y-%m-%d`
- `TimeField` -> `TimeInput` with clock icon background style

Readonly decision delegated to:

- `_readonly_for_datetime_like_field(...)`

---

## M2M field setup

For ManyToMany fields:

- collects initial + submitted values
- resolves selected objects for display choices
- builds attrs via `_build_select2_m2m_attrs(...)`
- sets `SelectMultiple` with selected options
- optionally disables for readonly permission

---

## FK field setup

For ForeignKey fields:

- resolves initial/submitted current value
- builds initial choices (selected + first slice of queryset)
- plain auto-built FK querysets of company-scoped models are narrowed to the active company by `_scope_fk_queryset_to_company()` (instance company when editing, else `request.active_company`/user company); querysets already set on the field are left alone
- when editing, excludes pks returned by the instance's optional `get_select2_excluded_pks(field_name)` hook
- builds attrs via `_build_select2_fk_attrs(...)`
- sets `Select`
- applies readonly-disabled behavior when required

---

## Select/textarea/checkbox normalization

- plain `Select` widgets get `js-example-basic-single headselect` classes
- `CheckboxInput` gets `sr-only peer`
- `Textarea` gets rows + friendly placeholder

---

## Validation flow (`clean`)

`clean()` extends default form validation.

### 1) Base clean

- `cleaned_data = super().clean()`

### 2) Strip condition values when no condition model

If `condition_fields` present but `condition_model` absent:

- removes condition keys from cleaned_data.

### 3) Validate non-condition selectable fields

For each non-condition field with value:

- FK (`ModelChoiceField`):
  - validates selected object still in fresh permitted queryset
- M2M (`ModelMultipleChoiceField`):
  - validates submitted PKs subset of fresh permitted queryset
- plain `ChoiceField`:
  - validates against current choices

Invalid selections add explicit errors.

### 4) Enforce readonly server-side

- `_enforce_readonly_in_cleaned_data(cleaned_data)`

### 5) Validate condition-specific fields

- `condition_fields_module.clean_condition_fields(self, cleaned_data)`

Returns cleaned_data.

---

## Fresh queryset safety helpers

## `_get_fresh_queryset(field_name, related_model)`

Rebuilds current allowed queryset for FK/M2M validation, using ownership/role rules.

Logic:

- fields listed in the form's `_unrestricted_fields` get the full queryset
- for `User` model: if the user has full `add_`/`change_` on the **parent** form
  model (or is superuser), any user is selectable (e.g. Lead Owner); with only
  `*_own_*`, limit to self + subordinates; otherwise self only
- for models with `OWNER_FIELDS`: filter by allowed user IDs across owner fields
  (or unfiltered when the user has global `view_`)
- else returns full queryset

Fallback:

- on errors returns `related_model.objects.all()` (logged).

## `_get_allowed_user_ids(user)`

Returns user + subordinate users by recursive role tree:

- superuser => all user IDs
- no role => current user only
- otherwise includes all users in recursive `role.subroles`.

Used by `_get_fresh_queryset`.

---

## Condition row integration points

`HorillaModelForm` delegates condition behavior to module functions:

- `add_condition_fields`
- `set_initial_condition_values`
- `add_generic_htmx_to_field`
- `extract_condition_rows` (via `_extract_condition_rows`)
- `clean_condition_fields`

This keeps condition feature logic centralized in `condition_fields.py`.

---

## File-state handling (`_setup_file_and_initial`)

In edit mode for file/image fields:

- if clear requested (`id_<field>_clear=true`):
  - initial cleared + `data_cleared=true`
- if new upload in current request:
  - set `data_uploaded_filename`, `data_cleared=false`
- else if existing file:
  - preserve initial existing file + `data_existing_filename`

Also handles POST uploads to ensure uploaded filename metadata is set even when initial absent.

Useful for modal/file widgets that need to display current file state across submissions.

---

## Practical subclass example

```python
from horilla.contrib.generics.forms import HorillaModelForm
from leads.models import Lead


# Core fields excluded automatically — no extra code needed
class LeadForm(HorillaModelForm):
    class Meta:
        model = Lead
        fields = "__all__"


# Hide extra field on top of core defaults
class LeadRestrictedForm(HorillaModelForm):
    class Meta:
        model = Lead
        fields = "__all__"
        exclude = ["internal_notes"]


# Show company on an admin-only screen
class LeadAdminForm(HorillaModelForm):
    class Meta:
        model = Lead
        fields = "__all__"
        keep_on_form = ("company",)
```

In view, pass runtime kwargs such as:

- `field_permissions`
- `condition_fields`
- `condition_model`
- `dynamic_create_fields`
- `duplicate_mode`

to activate advanced behavior.

---

## Caveats

- `clean()` validates permissions by querying fresh related querysets; ensure role/owner relations are configured correctly.
- FK initial choice loading includes selected objects + sliced queryset; very large relations still rely on Select2 backend for full search.
- Extensive per-field processing in `__init__` means unexpected widget overrides in subclasses should be applied carefully (usually after `super().__init__`).
- Condition behavior depends on consistent row/key naming conventions managed by condition helper module.

---

## Summary

`HorillaModelForm` is the comprehensive single-step form base for Horilla generics. It blends permission-aware field shaping, dynamic condition support, robust FK/M2M select validation, date/time widget normalization, and file-state persistence into one reusable form class used across create/update/duplicate flows.
