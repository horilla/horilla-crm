# Shared tag registry (`horilla_generics/templatetags/horilla_tags/_registry.py`)
## Purpose
`_registry.py` defines the single Django template library object used across the `horilla_tags` package:
- `register = template.Library()`
This is the central registration point for all template tags and filters in the package.
---
## What this file contains
Minimal implementation:
```python
from django import template
register = template.Library()
```
Even though it is small, it is foundational: every `@register.filter` and `@register.simple_tag` in sibling modules binds to this object.
---
## Why a shared registry module is used
Without a shared registry module, each tag file could create its own `template.Library()` instance, which can make package organization harder.
By centralizing `register` in `_registry.py`:
- all tag modules use the same registration object,
- package init can load modules consistently,
- `{% load horilla_tags %}` exposes one coherent namespace.
This pattern is cleaner for multi-file template-tag packages.
---
## How other modules use it
Tag modules import:
- `from ._registry import register`
Then decorate functions with:
- `@register.filter`
- `@register.simple_tag(...)`
Examples in this package include:
- `action_tags.py`
- `asset_tags.py`
- `components.py`
- `datetime_filters.py`
- `display_tags.py`
- `field_filters.py`
- `history_display.py`
- `history_i18n.py`
- `icon_tags.py`
- `misc_tags.py`
- `navigation_tags.py`
- `permission_tags.py`
- `url_filters.py`
---
## Relationship with `__init__.py`
`horilla_tags/__init__.py` imports this `register` and imports all tag modules for side-effect registration.
Combined effect:
1. `_registry.py` provides shared library object,
2. submodules attach filters/tags to it,
3. package load makes all registrations available to templates.
---
## Template-level outcome
In templates:
```django
{% load horilla_tags %}
```
This single load statement gives access to all tags/filters registered on the shared `register`.
---
## Maintenance guidance
When adding new template-tag modules:
1. import `register` from `._registry` (do not instantiate a new `template.Library()`),
2. add module import in `horilla_tags/__init__.py`,
3. keep registration decorators attached to the shared `register`.
This preserves consistent package behavior.
---
## Summary
`_registry.py` is the shared registration backbone for Horilla template tags. It provides one canonical `template.Library()` instance so all tag/filter modules contribute to the same `horilla_tags` namespace.
