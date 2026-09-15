# Form Layouts (`horilla.contrib.form_layouts`)

Lets an administrator decide, per company, which fields appear on an opted-in
model's **create** form and in what order — without editing the model, its
forms, or the generic form views. A trimmed form is useful when records are
entered in a hurry, for example logging a lead while the customer is on the
phone.

This app is self-contained. Turning it on or off is a single line in
`INSTALLED_APPS`. `horilla.contrib.core`, `horilla.contrib.generics`, and CRM
model, form and view files do not import it.

## App startup (`apps.py`)

`FormLayoutsConfig` (`AppLauncher`):

| Setting | Value |
|---------|--------|
| `name` | `horilla.contrib.form_layouts` |
| `label` | `form_layouts` |
| `auto_import_modules` | `menu`, `registration`, `view_hooks` |
| `url_prefix` | `form-layouts/` |
| `url_namespace` | `form_layouts` |

## Feature registration (`registration.py`)

```text
register_feature("form_layouts", "form_layout_models", auto_register_all=False)
```

As with Field Requirements, `auto_register_all=False` keeps models that use
`register_model_for_feature(..., all=True)` from becoming configurable without
an explicit opt-in. Lead and Opportunity opt in from their own
`registration.py` by listing `"form_layouts"` in `features`.

`registry.py` exposes `is_layout_configurable(model)`,
`get_configurable_models()` and `limit_content_types()`.

## Stored layout (`models.py`)

`FormLayoutField` is a `HorillaCoreModel`; one row per field:

| Field | Role |
|-------|------|
| `content_type` | Target model (`HorillaContentType`, limited to opted-in models) |
| `field_name` | Target form field (model fields and runtime fields such as `cf_*`) |
| `is_visible` | Whether the field is shown on the create form |
| `sequence` | Position on the create form |
| `company` | Company scope (from `HorillaCoreModel`) |

`unique_together` is `(content_type, field_name, company)`. A model with no
rows for the active company has **no layout** and keeps its default forms, so
installing the app changes nothing until a layout is saved.

## Resolution and rules (`utils.py`)

| Helper | Purpose |
|--------|---------|
| `get_form_layout(model)` | `FormLayout(order, hidden)` for the active company, or `None`; cached on the request |
| `apply_form_layout(form, layout, protected)` | Removes hidden fields and reorders the rest |
| `get_create_form_class(model)` | The model's single-page create form (a non-wizard `ModelForm` in its app's `forms`, preferring `*SingleForm`), composed with form extensions |
| `build_layout_entries(model, request)` | Fields of that form for the editor, with requiredness |
| `save_form_layout(...)` / `reset_form_layout(...)` | Replace or delete a company's layout |

A field is only left off a form when doing so cannot block or corrupt the save:

- **Required fields always stay.** Requiredness is read from the built form, so
  a field made optional in [Field Requirements](../field_requirements/field_requirements.md)
  (for example Lead email) can then be hidden; a non-nullable foreign key such
  as Lead Stage cannot.
- Fields already rendered as hidden inputs, the view's `hidden_fields` and
  `condition_fields`, and any field the view pre-fills through `get_initial()`
  (such as the account when an opportunity is created from a contact) stay.
- Fields the layout does not mention (e.g. a custom field added later) keep
  their place after the ordered fields instead of disappearing.

Hidden fields are removed from the form, so Django never assigns them and the
model default (usually an empty value) is stored.

## Applying layouts (`view_hooks.py`)

`horilla.views.generic.FormView` subclasses Django's `FormView` directly, so
`_inherit_view` extensions do not reach `HorillaSingleFormView` or
`HorillaMultiStepFormView`. The app wraps three methods once at import time
(guarded against double patching), the same technique `custom_fields` uses:

| Wrapped method | Behaviour when the model has a layout and the request creates a record |
|----------------|--------------------------------------------------------------------------|
| `HorillaSingleFormView.get_form` | Applies the layout to the form used for GET and POST |
| `HorillaSingleFormView.get_multi_step_url` | Returns `None`, hiding the wizard toggle |
| `HorillaMultiStepFormView.get` | Renders the view's `single_step_url_name["create"]` view in place of the wizard |

The multi-step wizard is not trimmed: its steps are fixed on the view and it
assigns fields to steps before any form extension runs. Sending create
requests to the single-page form keeps every entry point (list, kanban,
related-record buttons) consistent. Views without a single-page counterpart
keep their wizard.

Edit requests (a `pk` in the URL) and duplicate requests are passed through
unchanged; edit forms always show every field.

## Settings UI

Admins with `form_layouts.view_formlayoutfield` open
**Settings → Form Layouts → Create Form Layout** and pick a model.

The editor opens **read-only**: numbered fields in their current order, each
marked Shown or Hidden, with a count of shown fields. Nothing can change until
a user with `change_formlayoutfield` clicks **Edit Layout**, which swaps in
edit mode:

- drag a field by its grip handle, or use its up/down arrows (keyboard
  friendly), to change its position; positions renumber live;
- switch an optional field off to hide it; required fields show a lock
  instead of a switch;
- **Show all** / **Hide optional fields** change every switch at once;
- an unsaved-changes note appears after the first change, and **Cancel** asks
  before discarding; **Save Layout** stores the layout and returns to the
  read-only view. Saving an untouched list still activates the layout.

The drag handle is an icon, not an `<img>`: a browser starts its own native
image drag on an image handle, which cancels the pointer events SortableJS
needs and leaves the row "selected" without moving it. The ghost is appended
to `body` (`fallbackOnBody`) so scrolling containers cannot clip it. The
edit-mode script is idempotent and re-initialises after an htmx history
restore.

| URL name | Role | Permission |
|----------|------|------------|
| `form_layouts:form_layout_view` | Settings page (read-only editor) | `view_formlayoutfield` |
| `form_layouts:form_layout_editor` | Switch model, `?mode=edit`, or cancel (HTMX) | `view_formlayoutfield`; edit mode also needs `change_formlayoutfield` |
| `form_layouts:form_layout_save` | Store order and visibility (HTMX POST) | `change_formlayoutfield` |
| `form_layouts:form_layout_reset` | Delete the layout (HTMX POST) | `delete_formlayoutfield` |

Saving ignores unknown field names, stores required fields as visible and
removes rows for fields the form no longer has. **Reset to Default** deletes
the company's rows, which brings the wizard back.
