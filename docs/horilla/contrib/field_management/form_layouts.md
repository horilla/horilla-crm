# Form Layouts (`horilla.contrib.field_management`)

Lets an administrator decide, per company, which fields appear on an opted-in
model's create/edit form and in what order — without editing the model, its
forms, or the generic form views. A trimmed form is useful when records are
entered in a hurry, for example logging a lead while the customer is on the
phone.

As of platform **1.15.1**, a saved layout is offered as an opt-in **Custom
Layout** entry in the form mode switcher (`form_mode`). Default single-step and
multi-step forms are **not** intercepted or redirected; the visitor must follow
the Custom Layout link (`?form_layout=1`) before fields are trimmed. Create and
edit both support Custom Layout; duplicate requests always show every field.

This feature is self-contained inside `horilla.contrib.field_management`.
Turning the app on or off is a single line in `INSTALLED_APPS`.
`horilla.contrib.core`, `horilla.contrib.generics`, and CRM model, form and
view files do not import it. Custom Fields and Field Requirements live in the
same app; see [custom fields](custom_fields.md) and
[field requirements](field_requirements.md).

## App startup (`apps.py`)

Custom Fields, Field Requirements and Form Layouts share one app,
`FieldSettingsConfig` (`AppLauncher`):

| Setting | Value |
|---------|--------|
| `name` | `horilla.contrib.field_management` |
| `label` | `field_management` |
| `verbose_name` | Field Management |
| `auto_import_modules` | `menu`, `registration`, `extensions` |
| `url_prefix` | `field-management/` |
| `url_namespace` | `field_management` |

The feature name stays `form_layouts` (registry key `form_layout_models`).
Page URLs are `field-management/form-layouts/`.

## Feature registration (`registration.py`)

```text
register_feature("form_layouts", "form_layout_models", auto_register_all=False)
```

As with Field Requirements, `auto_register_all=False` keeps models that use
`register_model_for_feature(..., all=True)` from becoming configurable without
an explicit opt-in. Lead and Opportunity opt in from their own
`registration.py` by listing `"form_layouts"` in `features`.

`registry/form_layouts.py` exposes `is_layout_configurable(model)`,
`get_configurable_models()` and `limit_content_types()`.

## Stored layout (`models.py`)

`FormLayoutField` is a `HorillaCoreModel`; one row per field:

| Field | Role |
|-------|------|
| `content_type` | Target model (`HorillaContentType`, limited to opted-in models) |
| `field_name` | Target form field (model fields and runtime fields such as `cf_*`) |
| `is_visible` | Whether the field is shown in Custom Layout mode |
| `sequence` | Position in Custom Layout mode |
| `is_full_width` | Span both columns of the form (`Full Width`) |
| `company` | Company scope (from `HorillaCoreModel`) |

`unique_together` is `(content_type, field_name, company)`. A model with no
rows for the active company has **no layout** and keeps its default forms, so
installing the app changes nothing until a layout is saved.

## Resolution and rules (`utils/form_layouts.py`)

| Helper | Purpose |
|--------|---------|
| `get_form_layout(model)` | `FormLayout(order, hidden, full_width)` for the active company, or `None`; cached on the request |
| `apply_form_layout(form, layout, protected)` | Removes hidden fields and reorders the rest |
| `get_create_form_class(model)` | The form Custom Layout / the settings editor should list, composed with form extensions |
| `build_layout_entries(model, request)` | Fields of that form for the editor, with requiredness |
| `save_form_layout(...)` / `reset_form_layout(...)` | Replace or delete a company's layout |

`get_create_form_class` finds a form view of the model whose `form_mode` names a
counterpart (via `_counterpart_url_name`: the non-`active` entry), then follows
that URL name to the view's `form_class` (Lead: `LeadSingleForm`; Company:
`CompanyFormClassSingle`). Without such a counterpart it falls back to a generic
Horilla model form. That keeps the settings editor aligned with the same
single-page form Custom Layout actually renders.

A field is only left off a form when doing so cannot block or corrupt the save:

- **Required fields always stay.** Requiredness is read from the built form, so
  a field made optional in [Field Requirements](field_requirements.md)
  (for example Lead email) can then be hidden; a non-nullable foreign key such
  as Lead Stage cannot.
- Fields already rendered as hidden inputs, the view's `hidden_fields` and
  `condition_fields`, and any field the view pre-fills through `get_initial()`
  (such as the account when an opportunity is created from a contact) stay.
- Fields the layout does not mention (e.g. a custom field added later) keep
  their place after the ordered fields instead of disappearing.

Removing a field from the form never clears its stored value on edit: Django's
`ModelForm.save()` / `construct_instance` only writes fields present in
`form.fields`, so a hidden optional field keeps whatever the record already has.

## Applying layouts (`extensions/form_layouts.py`)

Layouts use real `_inherit_view` extensions on the shared form view bases (same
pattern as Custom Fields), not monkey-patches:

| Extension | Target | Behaviour |
|-----------|--------|-----------|
| `FormLayoutSingleFormViewExtension` | `HorillaSingleFormView` | When `?form_layout=1` and a layout exists, `get_form` applies the layout. `resolve_form_mode` appends a **Custom Layout** mode entry (and marks it active when that query param is set). |
| `FormLayoutMultiStepFormViewExtension` | `HorillaMultiStepFormView` | `resolve_form_mode` offers a Custom Layout link that points at the wizard's non-active counterpart URL with `?form_layout=1`. The wizard itself never renders the trimmed form. |

`LAYOUT_MODE_PARAM` is `form_layout`; `LAYOUT_MODE_TITLE` is **"Custom Layout"**.
Duplicate mode (`duplicate_mode`) never applies or offers the layout so copied
values stay fully visible for review. Partial forms that declare their own
`fields` list and have no `form_class` (for example Change Owner) are skipped
too: a layout of the full record form does not apply to them
(`is_layoutable_request`).

When Custom Layout is active, fields with `is_full_width` are appended to
`context["full_width_fields"]` so the form template spans both columns.
Custom fields marked full width are added on the single-page form and on the
wizard even when Custom Layout is not the active mode
(`_with_full_width_custom_fields`). A checkbox spans both columns only when
its name is in `full_width_fields`.

The mode switcher only appears when `form_mode` has more than one entry. Views
with no declared `form_mode` get a generic "Default Form" entry from
`FormViewCommonMixin.resolve_form_mode()`, so Custom Layout always has something
to switch away from. See [form_mixin.md](../generics/views/toolkit/form_mixin.md).

## Settings UI

Admins with `field_management.view_formlayoutfield` open
**Settings → Field Management → Form Layout**. The page is a list of saved
layouts (one row per model: model name, fields shown, last updated), the same
shape as Custom Fields. **New** (`add_formlayoutfield`) asks only for the
model, stores a layout with every field shown, and opens that layout's detail
page.

The detail page opens **read-only**: numbered fields in their current order,
each marked Shown or Hidden, with a Full Width badge where set. Nothing can
change until a user with `change_formlayoutfield` clicks **Edit Layout**,
which swaps in edit mode:

- drag a field by its grip handle, or use its up/down arrows (keyboard
  friendly), to change its position; positions renumber live;
- switch an optional field off to hide it; required fields show a lock
  instead of a switch;
- mark a field **Full Width** so it spans both columns when Custom Layout
  is the active form mode;
- **Show all** / **Hide optional fields** change every switch at once;
- an unsaved-changes note appears after the first change. **Cancel** is in the
  navbar: it asks before discarding and reloads the read-only layout itself.
  **Save Layout** stores the layout and returns to the read-only view. Saving
  an untouched list still activates the layout.

The drag handle is an icon, not an `<img>`: a browser starts its own native
image drag on an image handle, which cancels the pointer events SortableJS
needs and leaves the row "selected" without moving it. The ghost is appended
to `body` (`fallbackOnBody`) so scrolling containers cannot clip it. The
edit-mode script is idempotent and re-initialises after an htmx history
restore.

| URL name | Role | Permission |
|----------|------|------------|
| `field_management:form_layout_view` | Settings list shell | `field_management.view_formlayoutfield` |
| `field_management:form_layout_list` | One row per saved layout | `field_management.view_formlayoutfield` |
| `field_management:form_layout_create` | Pick a model and store the default layout | `field_management.add_formlayoutfield` |
| `field_management:form_layout_detail` | Read-only layout for one model | `field_management.view_formlayoutfield` |
| `field_management:form_layout_edit` | Edit mode for one model | `field_management.change_formlayoutfield` |
| `field_management:form_layout_editor` | Switch model, `?mode=edit`, or cancel (HTMX) | view; edit mode also needs change |
| `field_management:form_layout_save` | Store order, visibility and full width (HTMX POST) | `field_management.change_formlayoutfield` |
| `field_management:form_layout_reset` | Delete the layout (HTMX POST) | `field_management.delete_formlayoutfield` |

Saving ignores unknown field names, stores required fields as visible and
removes rows for fields the form no longer has. **Reset to Default** deletes
the company's rows, which removes the Custom Layout mode until a layout is
saved again.

## Tests

The app's own suite (`horilla/contrib/field_management/tests/test_form_layouts.py`) is
module-agnostic. Its fixture is the platform `Company` model, whose core
wizard names a single-page create view. `Company` is opted in only while each
test runs, by patching `FEATURE_REGISTRY`. The suite covers registry opt-in,
layout resolution, `apply_form_layout`, the editor helpers, the view
extensions over HTTP, and the settings views. It also asserts that neither
core/generics nor the app's code reference another module.

**Isolation:** `IsolationFromPlatformTests` fails if any `*.py` under
`horilla/contrib/generics` or `horilla/contrib/core` contains the substring
`form_layout` (including paths like `form_layouts/...` in comments or
docstrings). Keep platform docs of the structural `form_mode` counterpart
lookup free of that string; describe Form Layouts only in this app's docs.

**Editor markup:** optional fields use a visibility switch whose `<label>`
carries `class="relative …"` (possibly on a following line) and wraps an
`sr-only` checkbox. Tests assert that shape so the switch stays positioned
with its row while scrolling.

Module-specific scenarios live with the module that opts in, and skip when the
app is not installed:

- `horilla_crm/leads/tests/test_form_layouts.py` covers Lead's opt-in, the Lead
  create/edit Custom Layout path, default/wizard behaviour when the mode is not
  selected, and the interaction with Field Requirements;
- `horilla_crm/opportunities/test_form_layouts.py` covers Opportunity's opt-in
  and Custom Layout create/edit.

```python
@skipUnless(apps.is_installed("horilla.contrib.field_management"), "...")
```

`apps.is_installed` expects the full app name, not the `field_management` label. The feature name `form_layouts` is only the registry key.
