# My Settings Menu

## 🎯 Purpose

The `horilla.menu.my_settings_menu` module provides:

- **Registration system** — a decorator-based registry for per-user settings sidebar items
- **Permission-based filtering** — items are hidden from users who lack the required permissions
- **Condition-based filtering** — items can be shown or hidden based on arbitrary request-time logic
- **Order-based sorting** — items are sorted by an explicit `order` value before rendering
- **HTMX-compatible navigation** — each item carries arbitrary HTML attributes (e.g. `hx-target`, `hx-select`)
- **Context processor integration** — auto-injected into every template as `my_settings_menu`

It is the standard way for any Horilla app to add entries to the **My Settings** sidebar without modifying core templates.

**Note:** Code examples below use **explicit arguments** (including optional ones) so the full call shape is visible at a glance.

---

## 🧠 Core concept

### ❌ Avoid hardcoding entries in the settings sidebar

```python
# Do not add settings links directly in my_settings.html or base templates
```

```python
# ✅ Preferred — register via the decorator in the app's menu.py
from horilla.menu import my_settings_menu

@my_settings_menu.register
class MySettingsEntry:
    ...
```

**Simple rule:** Every entry in the My Settings sidebar that belongs to a specific app must be defined in that app's `menu.py` and registered with `@my_settings_menu.register`. The sidebar renders whatever passes filtering — apps never need to touch the settings template directly.

The header account dropdown is a separate registry with the same class shape (`title`, `url`, `attrs`). Register those links with `@header_menu.register`. See [header menu](header_menu.md).

---

## 📦 Module location

```text
horilla/menu/
│
├── my_settings_menu.py     # Registry, register(), get_my_settings_menu()
└── ...

<app>/
├── menu.py                 # Where apps define and register their settings entries
└── apps.py                 # Where "menu" is listed in auto_import_modules
```

---

## 🔁 What `horilla.menu.my_settings_menu` provides

### ➕ Registry & utilities

- `my_settings_menu` — module-level list holding all registered classes
- `register` — decorator that appends a class to `my_settings_menu`
- `get_my_settings_menu` — returns a filtered, order-sorted list of dicts for the current request

---

## 🗂️ Registry

### 📍 Variable

```python
my_settings_menu: List[Any] = []
```

### 🎯 Purpose

A module-level list that accumulates every class decorated with `@my_settings_menu.register`. It is populated at startup when each app's `menu.py` is imported via `auto_import_modules`.

---

## 🏷️ `register`

### 📍 Decorator

```python
def register(cls: Type[Any]) -> Type[Any]:
    ...
```

### 🎯 Purpose

Appends the decorated class to `my_settings_menu` and returns it unchanged. Works as a **class decorator** — the class itself is not modified.

### 🧪 Example

```python
from horilla.menu import my_settings_menu

@my_settings_menu.register
class ShortKeySettings:
    """My Settings entry for Short Keys."""
    ...
```

After this runs (at import time), `ShortKeySettings` is in `my_settings_menu`.

---

## 🔍 `get_my_settings_menu`

### 📍 Function

```python
get_my_settings_menu(request=None) -> list[dict]
```

### 🎯 Purpose

Iterates the registry, instantiates each class, applies condition and permission checks, then returns a **sorted list of dicts** ready for the template.

### ✅ Behavior

Filtering is applied in two stages before an item is included:

**Stage 1 — Condition check:**
- If `condition` is a **callable**, it is called with `request`. The item is skipped if it returns falsy or if `request` is `None`.
- If `condition` is a **static value**, the item is skipped when the value is falsy.
- If `condition` is absent (defaults to `True`), the item always passes this stage.

**Stage 2 — Permission check:**
- If `perm` is non-empty and a `request` is provided, `request.user.has_any_perms(perm)` must return `True` — the user needs **at least one** of the listed permissions (any-of semantics).
- A plain string is accepted and treated as a single-item list.
- Unauthenticated users always fail the permission check.
- Items with no `perm` attribute (or `perm = None`) skip this stage entirely.

Items that pass both stages are collected and sorted by `order` using the same three-tier key as `main_section_menu`.

### 📐 Sort key logic

| `order` value | Sort bucket | Order within bucket |
|--------------|-------------|---------------------|
| `>= 0` (e.g. `1`, `6`) | `0` — first | Ascending by value |
| `None` | `1` — middle | Stable insertion order |
| `< 0` (e.g. `-1`) | `2` — last | Ascending by value |

### 📐 Returned dict shape

| Key | Source on the class | Description |
|-----|---------------------|-------------|
| `title` | `cls.title` | Menu link label (passed through `{% trans %}` in the template) |
| `url` | `cls.url` | Navigation URL for the settings entry |
| `active_urls` | `cls.active_urls` | List of URL names used to highlight the active link |
| `icon` | `cls.icon` | Optional static path to an icon |
| `order` | `cls.order` | Integer controlling sidebar order (default `100`) |
| `attrs` | `cls.attrs` | Extra HTML attributes rendered on the `<a>` element |

### 🧪 Example

```python
from horilla.menu.my_settings_menu import get_my_settings_menu

items = get_my_settings_menu(request=request)
# → [
#     {"title": "Short Keys", "url": "/shortkeys/", "active_urls": [...], "order": 6, "attrs": {...}},
#     ...
#   ]
```

---

## 🌐 Context Processor

`get_my_settings_menu` is called inside `menu_context_processor` and exposed as `my_settings_menu` to every template automatically:

```python
# horilla/menu/context_processors.py

def menu_context_processor(request):
    """Return context for various menus."""

    current_app_label = (
        request.resolver_match.app_name if request.resolver_match else None
    )
    section_param = request.GET.get("section")

    return {
        "main_section_menu": get_main_section_menu(request),
        "sub_section_menu": get_sub_section_menu(request),
        "settings_menu": get_settings_menu(request),
        "floating_menu": get_floating_menu(request),
        "my_settings_menu": get_my_settings_menu(request),   # ← injected here
        "header_menu": get_header_menu(request),
        "current_section": section_param,
        "current_app_label": current_app_label,
    }
```

No manual context passing is needed in individual views — `my_settings_menu` is always available in templates.

---

## 🎨 Template rendering

The `my_settings_menu` context variable is consumed in `my_settings.html`. Each item is rendered as a list link; `attrs` key-value pairs are spread onto the `<a>` element as HTML attributes, enabling HTMX navigation without any JavaScript.

```django
{# templates/my_settings.html #}

<ul>
    {% for item in my_settings_menu %}
        <li class="py-1.5">
            <a role="button"
               href="{{ item.url }}?{{ request.GET.urlencode }}"
               {% for attr, value in item.attrs.items %}
                   {{ attr }}="{{ value }}"
               {% endfor %}
               class="font-medium text-[.85rem] hover:text-primary-600 transition duration-300 flex py-.5 {% is_active item.active_urls %}">
                {% trans item.title %}
            </a>
        </li>
    {% endfor %}
</ul>
```

Each `<a>` receives:
- `href` — the item's URL with the current query string preserved
- All key-value pairs from `item.attrs` rendered as HTML attributes (e.g. `hx-target`, `hx-select`, `hx-push-url`)
- Active-state CSS class applied by the `{% is_active %}` tag using `active_urls`
- The translated `title` as the visible link text

---

## ➕ Registering a My Settings menu item

### Step 1 — Define the class in the app's `menu.py`

```python
# horilla_keys/menu.py

from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _
from horilla.menu import my_settings_menu

@my_settings_menu.register
class ShortKeySettings:
    """My Settings entry for Short Keys."""

    title = _("Short Keys")
    url = reverse_lazy("horilla_keys:short_key_view")
    active_urls = [
        "horilla_keys:short_key_view",
    ]
    order = 6
    attrs = {
        "hx-boost": "true",
        "hx-target": "#my-settings-content",
        "hx-push-url": "true",
        "hx-select": "#short-key-view",
        "hx-select-oob": "#my-settings-sidebar",
    }
```

### Step 2 — Add `"menu"` to `auto_import_modules` in `apps.py`

```python
# horilla_keys/apps.py

from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _

class HorillaKeysConfig(AppLauncher):
    """App configuration class for horilla_keys."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_keys"
    verbose_name = _("Keyboard Shortcuts")

    url_prefix = "shortkeys/"
    url_module = "horilla_keys.urls"
    url_namespace = "horilla_keys"

    auto_import_modules = [
        "menu",       # ← triggers @my_settings_menu.register at startup
        "signals",
    ]
```

`AppLauncher.ready()` calls `_auto_import_modules()`, which runs:

```python
importlib.import_module("horilla_keys.menu")
```

This executes the `@my_settings_menu.register` decorator, appending `ShortKeySettings` to the registry before the first request is served.

---

## 🧩 Class reference

### Required attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `title` | `str` or lazy string | Link label — rendered through `{% trans %}` in the template |
| `url` | `str` or `reverse_lazy(...)` | Navigation target URL |

### Optional attributes

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `active_urls` | `list[str]` | `[]` | URL names used by `{% is_active %}` to highlight the current entry |
| `icon` | `str` or `None` | `None` | Static path to an optional icon |
| `order` | `int` or `None` | `100` | Controls sidebar order (see sorting rules) |
| `attrs` | `dict` | `{}` | Extra HTML attributes spread onto the `<a>` element |
| `perm` | `str` or `list[str]` | `None` | Django permission string(s) — item hidden unless user holds **at least one** (`has_any_perms`). `None` skips the check entirely. |
| `condition` | `bool` or `callable` | `True` | Static flag or `def condition(request) -> bool` |

### `attrs` keys (common HTMX pattern)

| Key | Description |
|-----|-------------|
| `hx-target` | CSS selector for the HTMX swap target |
| `hx-select` | CSS selector to extract from the response |
| `hx-select-oob` | Out-of-band selector to also update (e.g. refresh sidebar active state) |
| `hx-push-url` | Push the navigated URL to the browser history |
| `hx-boost` | Enable HTMX boost for anchor |

Any additional key-value pair in `attrs` is rendered verbatim as an HTML attribute on the `<a>`.

---

## 🔐 Filtering in detail

`get_my_settings_menu` applies two independent filters before including an item:

### Condition filter

```python
# Static — always hidden
condition = False

# Static — always shown (default)
condition = True

# Dynamic — shown only when the user is an employee
def condition(self, request):
    return hasattr(request.user, "employee_get")
```

If `condition` is callable and `request` is `None` (e.g. called outside a request context), the item is **excluded**.

### Permission filter

```python
# Single permission (string form)
perm = "keys.view_shortcutkey"

# Multiple — user needs ANY ONE of these (any-of semantics)
perm = ["keys.view_shortcutkey", "keys.view_own_shortcutkey"]
```

`get_my_settings_menu` calls `request.user.has_any_perms(perm)`, so the item is shown when the user holds **at least one** listed permission. If `perm` is absent or `None`, this check is skipped and the item is always shown to authenticated users who passed the condition check.

### Combined filtering table

| `condition` | `perm` | Authenticated | Result |
|-------------|--------|---------------|--------|
| `True` / omitted | `None` / omitted | Any | ✅ Included |
| `True` / omitted | `["app.perm"]` | ✅ Has any perm | ✅ Included |
| `True` / omitted | `["app.perm"]` | ❌ Missing all | ❌ Excluded |
| `False` | Any | Any | ❌ Excluded |
| `callable` → `True` | `None` / omitted | Any | ✅ Included |
| `callable` → `False` | Any | Any | ❌ Excluded |
| Any | Any | ❌ Unauthenticated | ❌ Excluded |

---

## ⚠️ Important guidelines

| Avoid | Prefer |
|-------|--------|
| Hardcoding settings links in the template | Register via `@my_settings_menu.register` in the app's `menu.py` |
| Omitting `"menu"` from `auto_import_modules` | Always include `"menu"` so the decorator runs at startup |
| Bare strings for `title` | Use `_("Title")` / `gettext_lazy` so labels are translatable |
| Omitting `active_urls` | Always list the URL names used by the entry so the active state highlights correctly |
| Leaving `order` at default `100` for all items | Set explicit values to control relative ordering across apps |
| Checking permissions inside the view instead of here | Declare `perm` on the class — keeps filtering in one place |

---

## 🧩 Benefits

- **Decoupled** — apps contribute settings entries without touching shared templates
- **Flexible filtering** — both static `condition` flags and dynamic callables are supported alongside `perm`
- **HTMX-ready** — arbitrary HTMX attributes flow directly from the Python class to the rendered `<a>`
- **Ordered** — explicit `order` values give full control over sidebar layout across all installed apps
- **Accessible** — `title` is passed through `{% trans %}` automatically, supporting full i18n

---

## 📌 Summary

| Feature | Without `my_settings_menu` | With `my_settings_menu` |
|---------|---------------------------|--------------------------|
| Entry definition | Edit core settings template | Define class in app's `menu.py` |
| Permission filtering | Manual `{% if perms... %}` in templates | Declarative `perm` list on class (`has_any_perms`, any-of) |
| Conditional visibility | Ad-hoc template logic | Declarative `condition` (static or callable) |
| Sidebar ordering | Manual HTML position | Declarative `order` integer |
| HTMX attributes | Hardcoded in HTML | Declared in `attrs` dict on class |
| Context availability | Manual view injection | Auto via `menu_context_processor` |
| Translations | Ad-hoc | Built-in via `gettext_lazy` on `title` |

---

## 🏁 Conclusion

The `horilla.menu.my_settings_menu` module:

- Provides a **decorator-based registry** so any app can add entries to the My Settings sidebar without touching shared templates
- Applies **two independent filters** — `condition` for dynamic visibility and `perm` for access control — before an item reaches the template
- Sorts entries by an explicit **`order`** integer, giving full cross-app layout control
- Passes **arbitrary HTML attributes** (including HTMX directives) straight from Python to the rendered `<a>`

Register in `menu.py`, add `"menu"` to `auto_import_modules`, and the entry appears in the correct position in the My Settings sidebar for every user who satisfies the condition and holds the required permissions.
