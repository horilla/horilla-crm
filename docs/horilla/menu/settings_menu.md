# Settings Menu

## 🎯 Purpose

The `horilla.menu.settings_menu` module provides:

- **Registration system** — a decorator-based registry for grouped settings sidebar entries
- **Two-level structure** — each registered class represents a collapsible **group** containing one or more **items**
- **Permission-based filtering** — groups are shown only when the user holds at least one permission from within the group's items (`has_any_perms`)
- **Condition-based filtering** — both groups and individual items support static flags or dynamic callables
- **Order-based sorting** — both groups and items within a group are sorted by an explicit `order` value
- **HTMX-compatible navigation** — each item carries arbitrary HTML attributes (e.g. `hx-target`, `hx-select`)
- **Context processor integration** — auto-injected into every template as `settings_menu`

It is the standard way for any Horilla app to add a collapsible group of links to the **Settings** sidebar without modifying core templates.

**Note:** Code examples below use **explicit arguments** (including optional ones) so the full call shape is visible at a glance.

---

## 🧠 Core concept

### ❌ Avoid hardcoding entries in the settings sidebar

```python
# Do not add settings groups or links directly in settings.html or base templates
```

```python
# ✅ Preferred — register via the decorator in the app's menu.py
from horilla.menu import settings_menu

@settings_menu.register
class MySettingsGroup:
    ...
```

**Simple rule:** Every settings group that belongs to a specific app must be defined in that app's `menu.py` and registered with `@settings_menu.register`. The sidebar renders whatever passes filtering — apps never need to touch the settings template directly.

---

## 📦 Module location

```text
horilla/menu/
│
├── settings_menu.py     # Registry, register(), get_settings_menu()
└── ...

<app>/
├── menu.py              # Where apps define and register their settings group
└── apps.py              # Where "menu" is listed in auto_import_modules
```

---

## 🔁 What `horilla.menu.settings_menu` provides

### ➕ Registry & utilities

- `settings_registry` — module-level list holding all registered classes
- `register` — decorator that appends a class to `settings_registry`
- `get_settings_menu` — returns a filtered, order-sorted list of group dicts for the current request

---

## 🗂️ Registry

### 📍 Variable

```python
settings_registry: List[Any] = []
```

### 🎯 Purpose

A module-level list that accumulates every class decorated with `@settings_menu.register`. It is populated at startup when each app's `menu.py` is imported via `auto_import_modules`.

---

## 🏷️ `register`

### 📍 Decorator

```python
def register(cls: Type[Any]) -> Type[Any]:
    ...
```

### 🎯 Purpose

Appends the decorated class to `settings_registry` and returns it unchanged. Works as a **class decorator** — the class itself is not modified.

### 🧪 Example

```python
from horilla.menu import settings_menu

@settings_menu.register
class AutomationSettings:
    """Settings group for the automation module."""
    ...
```

After this runs (at import time), `AutomationSettings` is in `settings_registry`.

---

## 🔍 `get_settings_menu`

### 📍 Function

```python
get_settings_menu(request=None) -> List[Dict]
```

### 🎯 Purpose

Iterates `settings_registry` (pre-sorted by `order`), instantiates each class, applies group-level and item-level filtering, and returns a list of group dicts ready for the template.

### ✅ Behavior — Group level

**Step 1 — Sort registry** by `order` using the three-tier key before iteration.

**Step 2 — Group condition check:**
- If `condition` is a **callable**, it is called with `request`. The group is skipped if it returns falsy or if `request` is `None`.
- If `condition` is a **static value**, the group is skipped when falsy.
- If `condition` is absent (defaults to `True`), the group always passes.

**Step 3 — Item processing:** Each item in `items` is evaluated:
- If an item is a **callable**, it is called with `request`; a falsy return skips that item.
- If the item has a `condition` key (static or callable), it is evaluated; falsy skips the item.
- Surviving items are **sorted by their own `order`** key.

**Step 4 — Group permission check:**
- `perm` values are collected from all surviving items.
- The group is included only if `request.user.has_any_perms(perm_list)` is `True` — the user needs **at least one** permission, not all.
- Unauthenticated users are always excluded.

### 📐 Sort key logic (groups and items)

| `order` value | Sort bucket | Order within bucket |
|--------------|-------------|---------------------|
| `>= 0` (e.g. `1`, `4`) | `0` — first | Ascending by value |
| not present / `None` | `1` — middle | Stable insertion order |
| `< 0` (e.g. `-1`) | `2` — last | Ascending by value |

### 📐 Returned group dict shape

| Key | Source on the class | Description |
|-----|---------------------|-------------|
| `title` | `cls.title` | Collapsible group heading label |
| `icon` | `cls.icon` | Static path to the group's icon |
| `items` | `cls.items` (filtered & sorted) | List of item dicts that passed filtering |

### 📐 Item dict shape

| Key | Type | Description |
|-----|------|-------------|
| `label` | `str` | Visible link text |
| `url` | `str` | HTMX GET target URL |
| `perm` | `str` | Django permission string — used for group-level `has_any_perms` check and template `has_perm` tag |
| `order` | `int` | Controls order within the group |
| `condition` | `bool` or `callable` | Item-level visibility (optional) |
| *(any HTMX key)* | `str` | Rendered verbatim as HTML attributes on the `<a>` element |

### 🧪 Example

```python
from horilla.menu.settings_menu import get_settings_menu

groups = get_settings_menu(request=request)
# → [
#     {
#       "title": "Automations",
#       "icon": "/assets/icons/automation.svg",
#       "items": [
#           {"label": "Message Automations", "url": "/automations/", "perm": "...", ...},
#       ]
#     },
#     ...
#   ]
```

---

## 🌐 Context Processor

`get_settings_menu` is called inside `menu_context_processor` and exposed as `settings_menu` to every template automatically:

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
        "settings_menu": get_settings_menu(request),   # ← injected here
        "floating_menu": get_floating_menu(request),
        "my_settings_menu": get_my_settings_menu(request),
        "current_section": section_param,
        "current_app_label": current_app_label,
    }
```

No manual context passing is needed in individual views — `settings_menu` is always available in templates.

---

## 🎨 Template rendering

The `settings_menu` context variable is consumed in `settings.html`. The entire settings page is **conditionally rendered** — if `settings_menu` is empty (the user has no permitted groups), an error page is shown instead.

Each group renders as a collapsible accordion; items within a group are individually permission-checked again in the template via `{% has_perm %}`.

```django
{# templates/settings.html #}

{% if settings_menu %}
    {% for menu in settings_menu %}
        <div class="border-t border-primary-100">

            {# ── Group header (accordion toggle) ── #}
            <button type="button" onclick="toggleAccordion(this)" ...>
                <img src="{% static menu.icon %}" alt="{% trans 'Icon' %}" width="18" />
                {{ menu.title }}
                <svg class="{% is_open_collapse menu.items %}">...</svg>
            </button>

            {# ── Group body (collapsible item list) ── #}
            <div class="accordion-content {% is_open menu.items %}">
                <ul class="px-4 border-t border-primary-100 pt-3">
                    {% for item in menu.items %}
                        {% has_perm item.perm as can_view_item %}
                        {% if can_view_item %}
                            <li class="py-1">
                                <a role="button"
                                   hx-get="{{ item.url }}"
                                   {% for key, value in item.items %}
                                       {% if key not in "label,url" %}
                                           {{ key }}="{{ value }}"
                                       {% endif %}
                                   {% endfor %}
                                   class="... {% is_active item.url %}">
                                    {{ item.label }}
                                </a>
                            </li>
                        {% endif %}
                    {% endfor %}
                </ul>
            </div>

        </div>
    {% endfor %}
{% else %}
    {% include "error/settings_403.html" with embed=True %}
{% endif %}
```

Key rendering details:
- `{% is_open_collapse menu.items %}` / `{% is_open menu.items %}` — template tags that auto-expand the group whose item URL matches the current page.
- `{% has_perm item.perm %}` — per-item permission check in the template (in addition to the Python-level group check).
- HTMX keys (`hx-target`, `hx-select`, etc.) are iterated from `item.items` and rendered as HTML attributes, excluding `label` and `url`.
- `{% is_active item.url %}` — highlights the currently active settings link.

---

## ➕ Registering a settings group

### Step 1 — Define the class in the app's `menu.py`

```python
# horilla_automations/menu.py

from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _
from horilla.menu import settings_menu

@settings_menu.register
class AutomationSettings:
    """Settings group for the automation module."""

    title = _("Automations")
    icon = "/assets/icons/automation.svg"
    order = 4
    items = [
        {
            "label": _("Message Automations"),
            "url": reverse_lazy("horilla_automations:automation_view"),
            "hx-target": "#settings-content",
            "hx-push-url": "true",
            "hx-select": "#automation-view",
            "hx-select-oob": "#settings-sidebar",
            "perm": "horilla_automation.view_horillaautomation",
        },
    ]
```

### Step 2 — Add `"menu"` to `auto_import_modules` in `apps.py`

```python
# horilla_automations/apps.py

from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _

class HorillaAutomationsConfig(AppLauncher):
    """App configuration class for horilla_automations."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_automations"
    verbose_name = _("Automations")

    url_prefix = "automations/"
    url_module = "horilla_automations.urls"
    url_namespace = "horilla_automations"

    auto_import_modules = [
        "registration",
        "menu",       # ← triggers @settings_menu.register at startup
        "signals",
    ]
```

`AppLauncher.ready()` calls `_auto_import_modules()`, which runs:

```python
importlib.import_module("horilla_automations.menu")
```

This executes the `@settings_menu.register` decorator, appending `AutomationSettings` to `settings_registry` before the first request is served.

---

## 🧩 Class reference

### Group attributes

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `title` | `str` or lazy string | — | Collapsible accordion heading label |
| `icon` | `str` | — | Static path to the group icon |
| `items` | `list` | `[]` | List of item dicts (or callables) for this group |
| `order` | `int` | not set | Controls group ordering in the sidebar |
| `condition` | `bool` or `callable` | `True` | Group-level visibility — static flag or `def condition(request) -> bool` |

### Item dict keys

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `label` | `str` or lazy string | ✅ | Visible link text in the sidebar |
| `url` | `str` or `reverse_lazy(...)` | ✅ | HTMX GET endpoint |
| `perm` | `str` | ✅ | Django permission string — used for both group inclusion and template `{% has_perm %}` |
| `order` | `int` | ❌ | Controls order within the group |
| `condition` | `bool` or `callable` | ❌ | Item-level visibility |
| `hx-target` | `str` | ❌ | CSS selector for HTMX swap target |
| `hx-select` | `str` | ❌ | CSS selector to extract from the response |
| `hx-select-oob` | `str` | ❌ | Out-of-band selector (e.g. refresh sidebar active state) |
| `hx-push-url` | `str` | ❌ | Push the navigated URL to browser history |

Any additional key in the item dict (other than `label` and `url`) is rendered verbatim as an HTML attribute on the `<a>` element.

### Using a callable item

When an item is a **function** rather than a dict, it is called with `request` at render time:

```python
@settings_menu.register
class LeaveSettings:
    title = _("Leave")
    icon = "/assets/icons/leave.svg"
    order = 2
    items = [
        {
            "label": _("Leave Types"),
            "url": reverse_lazy("leave:leave_type_view"),
            "perm": "leave.view_leavetype",
            "hx-target": "#settings-content",
            "hx-select": "#leave-type-view",
            "hx-select-oob": "#settings-sidebar",
            "hx-push-url": "true",
        },
        lambda request: {
            "label": _("Leave Allocation"),
            "url": reverse_lazy("leave:leave_allocation_view"),
            "perm": "leave.view_leaveallocation",
            "hx-target": "#settings-content",
            "hx-select": "#leave-allocation-view",
            "hx-push-url": "true",
        } if request.user.is_superuser else None,
    ]
```

A callable item that returns `None` or a falsy value is silently skipped.

---

## 🔐 Filtering in detail

`get_settings_menu` applies filtering at **two levels**:

### Group-level filtering

```python
# Static — group always hidden
condition = False

# Dynamic — show only for superusers
def condition(self, request):
    return request.user.is_superuser
```

### Item-level filtering

```python
# Static — item always hidden
{
    "label": _("Beta Feature"),
    "condition": False,
    ...
}

# Dynamic — item shown only in debug mode
{
    "label": _("Debug Panel"),
    "condition": lambda request: settings.DEBUG,
    ...
}
```

### Group permission check — `has_any_perms`

After items are filtered, `perm` strings from surviving items are collected and the group is shown only if:

```python
request.user.has_any_perms(perm_list)  # at least ONE perm is held
```

This contrasts with `floating_menu` which uses `has_perms` (ALL perms required). In settings, a user who can access *any one* item in a group sees the group; items they cannot access are then hidden individually by `{% has_perm %}` in the template.

### Combined group filtering table

| `condition` | Has any item `perm` | Authenticated | Group included? |
|-------------|---------------------|---------------|-----------------|
| `True` / omitted | ✅ At least one | ✅ | ✅ Included |
| `True` / omitted | ❌ None | Any | ❌ Excluded |
| `False` | Any | Any | ❌ Excluded |
| `callable` → `True` | ✅ At least one | ✅ | ✅ Included |
| `callable` → `False` | Any | Any | ❌ Excluded |
| Any | Any | ❌ Unauthenticated | ❌ Excluded |

---

## ⚠️ Important guidelines

| Avoid | Prefer |
|-------|--------|
| Hardcoding settings groups in the template | Register via `@settings_menu.register` in the app's `menu.py` |
| Omitting `"menu"` from `auto_import_modules` | Always include `"menu"` so the decorator runs at startup |
| Bare strings for `title` or item `label` | Use `_("Text")` / `gettext_lazy` so labels are translatable |
| Omitting `perm` from item dicts | Always set `perm` — it drives both group visibility and the template `{% has_perm %}` check |
| Leaving `order` unset when position matters | Set explicit integers on both groups and items |
| Using `has_perms` logic (all required) | Settings uses `has_any_perms` — the user only needs one item's permission to see the group |

---

## 🧩 Benefits

- **Two-level structure** — groups with collapsible items map directly to the accordion UI without any template changes
- **Decoupled** — apps contribute their own settings groups; core templates require no changes
- **Flexible filtering** — `condition` (static or callable) at both group and item level, plus `has_any_perms` for group access
- **HTMX-ready** — arbitrary HTMX attributes flow directly from item dicts to the rendered `<a>` elements
- **Double permission safety** — Python filters groups; the template's `{% has_perm %}` tag filters individual items within a visible group

---

## 📌 Summary

| Feature | Without `settings_menu` | With `settings_menu` |
|---------|--------------------------|----------------------|
| Group definition | Edit core settings template | Define class in app's `menu.py` |
| Item definition | Hardcoded HTML links | Dicts in the class `items` list |
| Group permission check | Manual `{% if perms... %}` | `has_any_perms` in `get_settings_menu` |
| Item permission check | Manual `{% if perms... %}` | Declarative `perm` key + template `{% has_perm %}` |
| Conditional visibility | Ad-hoc template logic | Declarative `condition` at group and item level |
| Ordering | Manual HTML position | Declarative `order` on groups and items |
| HTMX attributes | Hardcoded in HTML | Declared in item dicts |
| Context availability | Manual view injection | Auto via `menu_context_processor` |

---

## 🏁 Conclusion

The `horilla.menu.settings_menu` module:

- Provides a **decorator-based registry** so any app can add a collapsible settings group to the sidebar without touching shared templates
- Applies **two-level filtering** — condition and `has_any_perms` at the group level, condition at the item level, and `{% has_perm %}` again in the template
- Sorts both **groups** and **items within groups** by an explicit `order` integer
- Passes **arbitrary HTML attributes** (including HTMX directives) straight from item dicts to the rendered `<a>` elements

Register in `menu.py`, add `"menu"` to `auto_import_modules`, and the settings group appears in the correct position in the sidebar for every user who holds at least one of its item permissions.
