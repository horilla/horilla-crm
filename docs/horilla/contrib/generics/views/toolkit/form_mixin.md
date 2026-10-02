# Form common mixin (`horilla_generics/views/toolkit/form_mixin.py`)

## Purpose

`FormViewCommonMixin` centralizes cross-cutting logic shared by:

- `HorillaSingleFormView`
- `HorillaMultiStepFormView`

It provides common behavior for:

- permission resolution (create/edit/duplicate + owner-aware),
- object lookup helpers,
- dynamic-create field filtering by permission,
- field-level permissions,
- **`form_mode`** resolution (single ↔ multi ↔ extension modes such as Custom Layout),
- dynamic related-model metadata for template-side quick-create integrations.

This avoids duplicating sensitive permission and metadata logic in both form view types.

---

## Design intent

The mixin assumes form views can run in multiple modes:

- create
- edit
- duplicate (treated as create for permission semantics)

and that models may enforce ownership via:

- custom `is_owned_by(user)`,
- `OWNER_FIELDS`,
- fallback owner-like fields (`owner`, `created_by`, `user`, etc.).

It is designed to be inherited as a **first base class** so its methods are consistently available and override-friendly.

---

## Method-by-method reference

## `get_pk_key()`

Returns URL kwarg key used as object identifier.

Default:

- `pk`

Override point:

- set `pk_url_kwarg` on view class for custom URL patterns.

---

## `get_filtered_dynamic_create_fields()`

Filters `dynamic_create_fields` to only fields user can create related objects for.

Input sources:

- `self.dynamic_create_fields` (list of FK/M2M field names)
- optional `self.dynamic_create_field_mapping` (per-field config)

Algorithm:

1. skip if no model or no configured dynamic fields,
2. for each field name:
   - resolve model field,
   - keep only FK/M2M fields,
   - determine permissions:
     - custom from mapping (`permission`)
     - else default `"<app>.add_<related_model>"`,
   - include field if user has any required permission.

Returns:

- filtered list of field names safe to expose for quick-create UI.

Why it matters:

- prevents UI from showing "create related record" controls the user cannot use.

---

## `get_field_permissions()`

Delegates to:

- `get_field_permissions_for_model(self.request.user, self.model)`

Returns field-level permission map, or `{}` when no model.

Used by single/multi form implementations to hide/disable fields by policy.

---

## `get_permission_denied_response(request)`

Standardized 403-style response for form workflows.

Behavior:

- renders `permission_denied_template` if configured, else `403.html`,
- includes `{"modal": True}` context for modal-aware template behavior.

This keeps denial UX consistent across both form view types.

---

## `get_object_or_error_response(request)`

Safe object resolver with response contract:

- success: `(object, None)`
- no pk in URL: `(None, None)` (create mode)
- lookup failure: `(None, HttpResponse(...reload/close script...))`

Details:

- reads pk from `self.kwargs[get_pk_key()]`
- resolves with `get_object_or_404(self.model, pk=pk)`
- on exception:
  - pushes Django error message
  - returns script response:
    - click `#reloadButton`
    - `closeModal()`

This avoids hard crashes in modal flows when record is unavailable.

---

## `form_mode` / `resolve_form_mode()` / `resolve_url_name()`

Views declare alternate UIs as a list of mode dicts on `form_mode` (default `[]`):

```python
form_mode = [
    {
        "title": _("Single-Step Form"),
        "url_name": {"create": "app:create_single", "edit": "app:edit_single"},
        "active": True,
    },
    {
        "title": _("Multi-Step Form"),
        "url_name": {"create": "app:create", "edit": "app:edit"},
        "active": False,
    },
]
```

`resolve_form_mode()` builds the template-facing list:

- each entry needs `title` plus either `url_name` or a literal `hx_get`
- `resolve_url_name(url_name)` picks create vs edit from whether a pk is present
  (`str` or `{"create": ..., "edit": ...}`)
- on create (no pk), URLs resolved from `url_name` get `?new=true` so the wizard
  clears stale session state; literal `hx_get` values are left untouched
- defaults: `hx_target="#modalBox"`, `hx_swap="innerHTML"`, `active=False`
- if the view declares **no** `form_mode`, a single **"Default Form"** entry
  (`_default_form_mode_entry()`) pointing at `request.path` is used so extension
  apps (e.g. Form Layouts **Custom Layout**) always have something to switch
  away from — the template only shows the switcher when there is more than one
  entry

There is no `kind` marker on entries. Extension apps that need a counterpart
URL take the non-`active` entry structurally (the view marks its own mode
`active: True`). Platform generics must not hard-code another app's module
path or the string `form_layout` in Python sources — Form Layouts discovers
the counterpart that way on its own. See
[form layouts](../../form_layouts/form_layouts.md).

Both `HorillaSingleFormView` and `HorillaMultiStepFormView` put
`context["form_mode"] = self.resolve_form_mode()`.

---

## Permission system internals

## `get_auto_permissions()`

Generates default permission requirements based on mode:

- edit mode (pk present, not duplicate): `change_<model>`
- create or duplicate mode: `add_<model>` and `add_own_<model>`

Duplicate nuance:

- duplicate is intentionally treated like create, not change.

This aligns business semantics: duplication creates a new record.

---

## `has_permission()`

Primary gatekeeper for form access.

Evaluation order:

1. superuser => allow
2. evaluate explicit `self.permission_required` if present, else `get_auto_permissions()`
3. if user has any listed permission => allow
4. if edit mode and user has `change_own_<model>` => defer to object ownership check
5. if create/duplicate mode and user has `add_own_<model>` => allow
6. else deny

Key behavior:

- supports string or list permission specs
- integrates model-level and object-level permission paths
- duplicate mode affects branch selection (`is_create_or_duplicate`).

---

## `has_object_permission()`

Checks ownership for object-level permission scenarios.

Flow:

1. require pk + model
2. load object by pk
3. ownership checks in order:
   - `obj.is_owned_by(user)` if method exists — when defined, its result is final
   - `check_record_change_access(user, obj)` from `views/details.py`, the same rule the list and detail views apply to their Edit actions:
     - model-declared `OWNER_FIELDS`, ForeignKey or ManyToMany, naming the user or anyone in a subordinate role (`get_allowed_user_ids(user)` from `horilla.contrib.core.utils`), so a manager can edit their team's records
     - per-instance **granted access** hook: `user_has_granted_access(obj, user, "change")` (see [list.md — Granted access](../list.md#granted-access-per-model-opt-in-beyond-owner_fields)) — lets a model grant edit access some other way (e.g. `Opportunity` team membership) even when `OWNER_FIELDS` doesn't match
   - fallback fields, matched against the user only:
     - `<model_name>_owner`
     - `owner`
     - `created_by`
     - `user`
4. return `True` on first ownership match, else `False`

Errors:

- `DoesNotExist` returns `False`.

This gives robust ownership detection across heterogeneous models.

---

## Dynamic related-model metadata

## `get_related_models_info()`

Builds template-ready metadata for dynamic-create fields that passed filtering.

For each allowed FK/M2M field:

- identifies related model meta:
  - `model_name`
  - `app_label`
  - `verbose_name`
- serializes permission config (`permission`) as comma string when list
- computes `initial` values from mapping config:
  - supports static values
  - supports callables
  - passes `request.active_company` when callable accepts company context

Output shape per field:

```python
{
  "department": {
    "model_name": "department",
    "app_label": "hr",
    "verbose_name": "Department",
    "permission": "hr.add_department",
    "initial": {"company": 3}
  }
}
```

Error handling:

- per-field exceptions are swallowed to avoid breaking whole form render.

---

## How single and multi form views use this mixin

### `HorillaSingleFormView`

Common uses:

- resolves duplicate mode permissions through `has_permission()`
- passes filtered dynamic create fields to dynamic form builder
- injects related model info into context for quick-create controls
- uses object resolver helper for edit/duplicate mode.

### `HorillaMultiStepFormView`

Common uses:

- same permission logic for create/edit paths
- same dynamic-create field filtering for step forms
- shared related model info generation for step templates.

This guarantees both form paradigms follow identical permission + metadata policy.

---

## Practical configuration examples

## Example 1: custom dynamic create mapping

```python
dynamic_create_fields = ["department", "job_position"]
dynamic_create_field_mapping = {
    "department": {
        "permission": ["hr.add_department", "hr.add_own_department"],
        "initial": {
            "company": lambda company: company.id if company else None
        },
    }
}
```

Effect:

- field appears only if user has one of configured permissions,
- quick-create modal receives initial company prefill.

---

## Example 2: form_mode mapping

```python
form_mode = [
    {
        "title": _("Single-Step Form"),
        "url_name": {"create": "employee-create", "edit": "employee-edit"},
        "active": True,
    },
    {
        "title": _("Multi-Step Form"),
        "url_name": {
            "create": "employee-create-wizard",
            "edit": "employee-edit-wizard",
        },
        "active": False,
    },
]
```

`resolve_form_mode()` / `resolve_url_name()` choose the create/edit URL from pk
presence and mark the active mode for the template switcher.

---

## Example 3: custom ownership strategy on model

```python
class Employee(models.Model):
    OWNER_FIELDS = ["employee_user", "manager"]
```

`has_object_permission()` will evaluate both fields automatically.

---

## Extension points

Common overrides for project-specific rules:

- `get_auto_permissions()` for non-standard permission naming
- `has_object_permission()` for tenant-aware ownership rules
- `get_filtered_dynamic_create_fields()` for stricter per-field logic
- `get_related_models_info()` for richer initial payloads/UI metadata
- `get_permission_denied_response()` for custom denial UX

---

## Caveats and behavior notes

- broad `except Exception: pass` in dynamic-field/metadata loops favors resilience over strict error visibility.
- `has_permission()` uses "any permission" semantics for provided permission list.
- fallback owner-field heuristics may not fit all schemas; override object permission method for strict domain rules.
- duplicate mode permission behavior is intentional and important: duplicate requires add-like rights.

---

## Summary

`form_mixin.py` is the shared policy and utility layer for Horilla generic form views.
It standardizes create/edit/duplicate permissions, ownership checks, object lookup safety, `form_mode` switching, and dynamic related-model metadata, ensuring single-form and multi-step form implementations behave consistently and securely.
