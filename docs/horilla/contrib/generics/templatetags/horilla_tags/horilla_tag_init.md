# Horilla tags package init (`horilla_generics/templatetags/horilla_tags/__init__.py`)
## Purpose
`__init__.py` in `horilla_tags` is the package bootstrap for Django template tags/filters.
Its job is to ensure:
- all tag/filter submodules are imported,
- they register on one shared `register` object,
- templates can keep using a single load statement:
  - `{% load horilla_tags %}`
---
## What this file does
Core actions in this module:
1. imports shared library object:
   - `from ._registry import register`
2. imports all tag/filter submodules for side effects (registration):
   - `action_tags`
   - `asset_tags`
   - `components`
   - `datetime_filters`
   - `display_tags`
   - `field_filters`
   - `history_display`
   - `history_i18n`
   - `icon_tags`
   - `misc_tags`
   - `navigation_tags`
   - `permission_tags`
   - `url_filters`
3. exports only `register` through:
   - `__all__ = ["register"]`
---
## Why import submodules here
Django template tags are registered at import time.
If a module defining tags is never imported, its decorators never run and those tags are unavailable.
By importing all submodules in `__init__.py`, this package guarantees all registrations happen when `horilla_tags` is loaded.
---
## Shared register pattern
This package uses one common library instance from `._registry`:
- `_registry.py` defines `register = template.Library()`
- each submodule imports that same `register`
- tags/filters are attached to one library namespace
Benefit:
- no fragmentation across multiple `register` objects,
- stable `{% load horilla_tags %}` behavior.
---
## Template usage
In templates:
```django
{% load horilla_tags %}
```
After this load, tags/filters from all imported submodules become available through the same library.
---
## Maintenance guidance
When adding a new tag module under `horilla_tags/`:
1. ensure module imports `register` from `._registry`,
2. add module import to `__init__.py` import tuple,
3. keep backward compatibility for existing template `{% load horilla_tags %}` usage.
If step 2 is missed, tags may appear to "not work" because module registration never executes.
---
## Summary
`horilla_generics/templatetags/horilla_tags/__init__.py` is a registration orchestrator. It wires all tag/filter modules to a shared Django template library so the entire package is accessible through one consistent template load entry point.
