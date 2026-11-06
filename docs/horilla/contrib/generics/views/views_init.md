# Views package index (`horilla_generics/views/__init__.py`)

## Purpose

`horilla_generics/views/__init__.py` is a **package aggregator**.
It re-exports view classes/functions from many modules so callers can import from one place:

```python
from horilla_generics import views
```

instead of importing each submodule separately.

---

## What it exports

This file uses wildcard re-exports:

- `core`
- `field_selection` (`HorillaFieldSelectionView`)
- `delete`
- `helpers.condition_widget`
- `details`
- `list`
- `card`
- `split_view`
- `detail_tabs`
- `groupby`
- `chart`
- `kanban`
- `timeline`
- `attachments`
- `global_search`
- `related_list`
- `single_form`
- `multi_form`
- `navbar`
- `inline_edit` (`HorillaInlineEditMixin`, `HorillaInlineEditNavMixin`)

and also exposes:

- `helpers` package object (`from horilla_generics.views import helpers`)

---

## Why import order matters

The source docstring explicitly notes:

> Import order is significant to avoid circular imports.

Because many view modules reference shared classes/mixins from each other (and from helper modules), changing this order can trigger import-time cycles.

So this file should be treated as an ordered dependency chain, not a random list.

---

## Usage pattern in the project

Most URL modules use:

```python
from horilla_generics import views
```

Then reference symbols like:

```python
views.HorillaKanbanView
views.HorillaRelatedListContentView
views.GlobalSearchView
```

This works because `__init__.py` re-exports those names into the package namespace.

---

## Trade-offs of wildcard exports

### Pros

- very convenient import surface for app `urls.py` and view composition,
- keeps consumer files short and consistent.



## Maintenance guidelines

- Keep imports grouped and ordered intentionally.
- When adding a new generic view module:
  1. add its import here only if it should be part of public package API;
  2. place it where it will not break existing import dependencies.
- If circular import appears after adding a module, test moving that module’s import lower in this file (or reduce cross-module imports in the module itself).

---

## Example: exposing a new generic view

If you add `horilla_generics/views/matrix.py` with `class HorillaMatrixView(...)`, expose it here:

```python
from horilla_generics.views.matrix import *
```

Then consumers can use:

```python
from horilla_generics import views

path("matrix/", views.HorillaMatrixView.as_view(), name="matrix")
```

---

## Insert Fields modal (`field_selection.py`)

`HorillaFieldSelectionView` is the one shared "Insert Fields" modal (`field_selection_modal.html`) used by the mail form, mail templates and notification templates. It lists a model's fields (plus FK and allowed reverse-relation fields), the current user, the company and request attributes as template variables, selected by the `tab_type` GET param (`instance`, `user`, `company`, `request`).

---

## User picker (`helpers/user_picker.py`)

The modal lists users (or another model) with search and a filter panel.
**Select All** asks the list endpoint for every id matching the current
search and filters (`all_ids=true`), not only the page on screen. Already
selected rows are listed first. Boolean and choice filter values use Select2.
Many-to-many user fields stay on one row; the full set opens in this dialog.
Short dialogs drop the search box. User and role dialogs (calendar assignees,
calls, meeting) render people as pills.

The navbar filter-panel toggle is `toggleFilterPanel()` in `static/assets/js/global.js`.

---

## Summary

`horilla_generics/views/__init__.py` is the **public entry point** for generic views.
Its main job is export aggregation.
