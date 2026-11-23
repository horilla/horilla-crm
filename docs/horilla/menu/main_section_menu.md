# Main Section Menu

## 🎯 Purpose

The `horilla.menu.main_section_menu` module provides:

- **Registration system** — a decorator-based registry for top-level sidebar navigation sections
- **Position-based ordering** — items are sorted by an explicit `position` value before rendering
- **Context processor integration** — auto-injected into every template as `main_section_menu`
- **Permission-aware rendering** — the template uses `has_section_perm_url` to show only accessible sections

It is the standard way for any Horilla app to add itself as a named section in the left sidebar without modifying core templates.

**Note:** Code examples below use **explicit arguments** (including optional ones) so the full call shape is visible at a glance.

---

## 🧠 Core concept

### ❌ Avoid ad-hoc sidebar modifications

```python
# Do not hardcode section links in sidebar.html or base templates
```

```python
# ✅ Preferred — register via the decorator in the app's menu.py
from horilla.menu import main_section_menu

@main_section_menu.register
class MySection:
    ...
```

**Simple rule:** Every top-level sidebar section that belongs to a specific app must be defined in that app's `menu.py` and registered with `@main_section_menu.register`. The sidebar renders whatever is in the registry — apps never need to touch `sidebar.html` directly.

---

## 📦 Module location

```text
horilla/menu/
│
├── main_section_menu.py     # Registry, register(), get_main_section_menu()
└── ...

<app>/
├── menu.py                  # Where apps define and register their section
└── apps.py                  # Where "menu" is listed in auto_import_modules
```

---

## 🔁 What `horilla.menu.main_section_menu` provides

### ➕ Registry & utilities

- `main_section_menu` — module-level list holding all registered classes
- `register` — decorator that appends a class to `main_section_menu`
- `get_main_section_menu` — returns a position-sorted list of dicts for the current request

---

## 🗂️ Registry

### 📍 Variable

```python
main_section_menu: List[Any] = []
```

### 🎯 Purpose

A module-level list that accumulates every class decorated with `@main_section_menu.register`. It is populated at startup when each app's `menu.py` is imported via `auto_import_modules`.

---

## 🏷️ `register`

### 📍 Decorator

```python
def register(cls: Type[Any]) -> Type[Any]:
    ...
```

### 🎯 Purpose

Appends the decorated class to `main_section_menu` and returns it unchanged. Works as a **class decorator** — the class itself is not modified.

### 🧪 Example

```python
from horilla.menu import main_section_menu

@main_section_menu.register
class AnalyticsSection:
    """Registers the Analytics section in the main sidebar."""
    ...
```

After this runs (at import time), `AnalyticsSection` is in `main_section_menu`.

---

## 🔍 `get_main_section_menu`

### 📍 Function

```python
get_main_section_menu(request=None) -> List[Dict]
```

### 🎯 Purpose

Iterates the registry, instantiates each class, builds a dict for each item, and returns the list **sorted by `position`**. No permission filtering is performed here — that is handled at the template level by the `has_section_perm_url` tag.

### ✅ Behavior

- Every registered class is included regardless of `request` or user.
- Items are sorted using a three-tier key:
  1. **Positive `position`** (`>= 0`) — rendered first, in ascending order.
  2. **`position` is `None`** — rendered after all explicitly positioned items.
  3. **Negative `position`** — rendered last.

### 📐 Sort key logic

| `position` value | Sort bucket | Order within bucket |
|-----------------|-------------|---------------------|
| `>= 0` (e.g. `1`, `4`) | `0` — first | Ascending by value |
| `None` | `1` — middle | Stable insertion order |
| `< 0` (e.g. `-1`) | `2` — last | Ascending by value |

### 📐 Returned dict shape

| Key | Source on the class | Description |
|-----|---------------------|-------------|
| `section` | `cls.section` | Unique section identifier (used in URL and `id` attribute) |
| `name` | `cls.name` | Human-readable label shown as tooltip and `aria-label` |
| `url` | `cls.url` | Optional default URL for the section |
| `icon` | `cls.icon` | Static path to the section's SVG icon |
| `position` | `cls.position` | Integer controlling sidebar order |
| `attrs` | `cls.attrs` | Extra HTML attributes for the link (defaults to `{}`) |

### 🧪 Example

```python
from horilla.menu.main_section_menu import get_main_section_menu

items = get_main_section_menu(request=request)
# → [
#     {"section": "dashboard", "name": "Dashboard", "icon": "...", "position": 1, "url": None},
#     {"section": "schedule",  "name": "Schedule",  "icon": "...", "position": 4, "url": None},
#     ...
#   ]
```

---

## 🌐 Context Processor

`get_main_section_menu` is called inside `menu_context_processor` and exposed as `main_section_menu` to every template automatically:

```python
# horilla/menu/context_processors.py

def menu_context_processor(request):
    """Return context for various menus."""

    current_app_label = (
        request.resolver_match.app_name if request.resolver_match else None
    )
    section_param = request.GET.get("section")

    return {
        "main_section_menu": get_main_section_menu(request),   # ← injected here
        "sub_section_menu": get_sub_section_menu(request),
        "settings_menu": get_settings_menu(request),
        "floating_menu": get_floating_menu(request),
        "my_settings_menu": get_my_settings_menu(request),
        "header_menu": get_header_menu(request),
        "current_section": section_param,
        "current_app_label": current_app_label,
    }
```

No manual context passing is needed in individual views — `main_section_menu` is always available in templates.

---

## 🎨 Template rendering

The `main_section_menu` context variable is consumed in `sidebar.html`. Each item is checked against `has_section_perm_url` — a template tag that resolves the first URL in the section that the user has permission to access. Items where the user has no accessible URL are silently skipped.

```django
{# templates/sidebar.html #}

{% load static i18n horilla_tags %}

<nav class="relative space-y-2">
    {% for item in main_section_menu %}
        {% has_section_perm_url request.user item.section as perm_url %}
        {% if perm_url %}
            <a href="{{ perm_url }}?section={{ item.section }}"
               class="nav-link"
               id="{{ item.section }}"
               title="{{ item.name }}"
               aria-label="{{ item.name }}"
               data-tooltip-placement="right">
                <img src="{% static item.icon %}" alt="" class="w-5 h-5" />
            </a>
        {% endif %}
    {% endfor %}
</nav>
```

Each `<a>` receives:
- `href` — the first permitted URL in the section, with `?section=<section>` appended
- `id` — the `section` identifier, used for active-state highlighting
- `title` / `aria-label` — the item's `name` for tooltip and accessibility
- The icon as a small SVG image

> **Note:** `get_main_section_menu` returns **all** sections; the `{% has_section_perm_url %}` tag is solely responsible for hiding sections the user cannot access. This keeps permission logic in one place and out of Python.

---

## ➕ Registering a main section menu item

### Step 1 — Define the class in the app's `menu.py`

```python
# horilla_calendar/menu.py

from horilla.menu import main_section_menu
from horilla.utils.translation import gettext_lazy as _

@main_section_menu.register
class ScheduleSection:
    """Registers the Schedule section in the main sidebar."""

    section = "schedule"
    name = _("Schedule")
    icon = "/assets/icons/schedule.svg"
    position = 4
```

### Step 2 — Add `"menu"` to `auto_import_modules` in `apps.py`

```python
# horilla_calendar/apps.py

from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _

class HorillaCalendarConfig(AppLauncher):
    """App configuration class for the Horilla Calendar app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_calendar"
    verbose_name = _("Calendar")

    url_prefix = "calendar/"
    url_module = "horilla_calendar.urls"
    url_namespace = "horilla_calendar"

    auto_import_modules = [
        "menu",       # ← triggers @main_section_menu.register at startup
        "signals",
    ]
```

`AppLauncher.ready()` calls `_auto_import_modules()`, which runs:

```python
importlib.import_module("horilla_calendar.menu")
```

This executes the `@main_section_menu.register` decorator, appending `ScheduleSection` to the registry before the first request is served.

---

## 🧩 Class reference

### Required attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `section` | `str` | Unique identifier — used in the URL query string and element `id` |
| `name` | `str` or lazy string | Human-readable label shown as tooltip and `aria-label` |
| `icon` | `str` | Static path to the SVG icon displayed in the sidebar |
| `position` | `int` or `None` | Controls sidebar order (see sorting rules below) |

### Optional attributes

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | `str` or `None` | `None` | Default URL for the section — overridden by `has_section_perm_url` in the template |
| `attrs` | `dict` | `{}` | Extra HTML attributes. Use `MAIN_SECTION_HX_ATTRS` (from `horilla.menu`) for HTMX section switching: it is `MAIN_CONTENT_HX_ATTRS` plus `hx-select-oob="#sideMenuContainer"`, so the sub-sidebar is replaced even when the target page does not render it |

### Positioning guide

| `position` | Effect |
|-----------|--------|
| `0`, `1`, `2`, … | Placed first, in ascending order |
| `None` | Placed after all explicitly positioned items |
| `-1`, `-2`, … | Placed last, in ascending order |

Use `position` to control where in the sidebar a section appears relative to other apps. Leave it as `None` if order does not matter for your section.

---

## 🔐 Permission handling

Unlike `floating_menu`, `get_main_section_menu` performs **no permission filtering** — it always returns every registered section. Permission enforcement happens entirely in the template via the `{% has_section_perm_url %}` tag:

```django
{% has_section_perm_url request.user item.section as perm_url %}
{% if perm_url %}
    {# render the nav link #}
{% endif %}
```

`has_section_perm_url` resolves the first URL within the named section that `request.user` has access to. If no such URL exists, `perm_url` is falsy and the `<a>` is not rendered.

### Comparison with `floating_menu`

| Aspect | `main_section_menu` | `floating_menu` |
|--------|---------------------|-----------------|
| Where permissions are checked | Template tag (`has_section_perm_url`) | Python (`get_floating_menu`) |
| Items returned for unauthenticated user | All items | None |
| `perm` key on the class | Not used | Required inside `items` |

---

## ⚠️ Important guidelines

| Avoid | Prefer |
|-------|--------|
| Hardcoding section links in `sidebar.html` | Register via `@main_section_menu.register` in the app's `menu.py` |
| Omitting `"menu"` from `auto_import_modules` | Always include `"menu"` so the decorator runs at startup |
| Duplicate `section` values across apps | Use a unique, namespaced string (e.g. `"schedule"`, `"crm"`) |
| Skipping `position` when order matters | Set an explicit integer to guarantee correct placement |
| Using a bare string for `name` | Use `_("Name")` / `gettext_lazy` so labels are translatable |

---

## 🧩 Benefits

- **Decoupled** — apps register their own sidebar sections; core templates require no changes
- **Ordered** — explicit `position` values give full control over sidebar layout across all installed apps
- **Accessible** — `name` flows directly into `title` and `aria-label` on the nav link
- **Permission-safe** — `has_section_perm_url` ensures users only see sections they can access
- **Zero boilerplate** — one decorator, one `apps.py` entry, and the section appears automatically

---

## 📌 Summary

| Feature | Without `main_section_menu` | With `main_section_menu` |
|---------|-----------------------------|--------------------------|
| Section definition | Edit core `sidebar.html` | Define class in app's `menu.py` |
| Sidebar ordering | Manual HTML position | Declarative `position` integer |
| Permission filtering | Manual `{% if %}` in templates | Automatic via `has_section_perm_url` tag |
| Startup registration | Manual wiring | `auto_import_modules = ["menu"]` |
| Context availability | Manual view injection | Auto via `menu_context_processor` |
| Translations | Ad-hoc | Built-in via `gettext_lazy` on `name` |

---

## 🏁 Conclusion

The `horilla.menu.main_section_menu` module:

- Provides a **decorator-based registry** so any app can add itself to the sidebar without touching shared templates
- Sorts entries by an explicit **`position`** integer, giving full cross-app layout control
- Leaves **permission enforcement** to the `has_section_perm_url` template tag, keeping Python and template responsibilities cleanly separated

Register in `menu.py`, add `"menu"` to `auto_import_modules`, set a `position`, and the section appears in the correct place in the sidebar for every user who has access to it.
