# Sub-Section Menu

## 🎯 Purpose

The `horilla.menu.sub_section_menu` module provides:

- **Registration system** — a decorator-based registry for sidebar sub-navigation entries
- **Section grouping** — each registered class belongs to a named main section (e.g. `"sales"`, `"people"`)
- **Permission-based filtering** — items are shown only when the user holds at least one of the declared permissions (`any` mode) or all of them (`all_perms = True`)
- **Position-based sorting** — items within a section are sorted by an explicit `position` integer
- **HTMX-compatible navigation** — each item carries arbitrary HTML attributes via `attrs`
- **Unique HTML id support** — each item renders a unique `id` on its `<a>` tag; when two items share the same `app_label`, a separate `id` attribute disambiguates them
- **Context processor integration** — auto-injected into every template as `sub_section_menu`

It is the standard way for any Horilla app to add a link to the **main sidebar sub-navigation** without modifying core templates.

---

## 🧠 Core concept

### ❌ Avoid hardcoding entries in the sidebar template

```python
# Do not add sub-section links directly in sub_sidebar.html
```

```python
# ✅ Preferred — register via the decorator in the app's menu.py
from horilla.menu import sub_section_menu

@sub_section_menu.register
class MySubSection:
    ...
```

**Simple rule:** Every sidebar link that belongs to a specific app must be defined in that app's `menu.py` and registered with `@sub_section_menu.register`. The sidebar renders whatever passes permission filtering — apps never need to touch the sidebar template directly.

---

## 📦 Module location

```text
horilla/menu/
│
├── sub_section_menu.py     # Registry, register(), get_sub_section_menu()
└── ...

<app>/
├── menu.py                 # Where apps define and register their sub-section entries
└── apps.py                 # Where "menu" is listed in auto_import_modules
```

---

## 🔁 What `horilla.menu.sub_section_menu` provides

### ➕ Registry & utilities

- `sub_section_menu` — module-level list holding all registered classes
- `register` — decorator that appends a class to the registry
- `get_sub_section_menu` — returns a filtered, position-sorted dict of sections → item lists for the current request

---

## 🗂️ Registry

### 📍 Variable

```python
sub_section_menu: List[Any] = []
```

### 🎯 Purpose

A module-level list that accumulates every class decorated with `@sub_section_menu.register`. It is populated at startup when each app's `menu.py` is imported via `auto_import_modules`.

---

## 🏷️ `register`

### 📍 Decorator

```python
def register(cls: Type[Any]) -> Type[Any]:
    ...
```

### 🎯 Purpose

Appends the decorated class to `sub_section_menu` and returns it unchanged. Works as a **class decorator** — the class itself is not modified.

### 🧪 Example

```python
from horilla.menu import sub_section_menu

@sub_section_menu.register
class LeadSubSection:
    ...
```

After this runs (at import time), `LeadSubSection` is in the registry.

---

## 🔍 `get_sub_section_menu`

### 📍 Function

```python
get_sub_section_menu(request=None) -> Dict[str, List[Dict]]
```

### 🎯 Purpose

Iterates the registry, instantiates each class, applies permission filtering, groups items by section, and returns a dict ready for the template.

### ✅ Behavior

**Step 1 — Validate section:** The item's `section` must match a registered main section. If not, `ImproperlyConfigured` is raised at startup.

**Step 2 — Permission check:**
- If `all_perms = True`, the user must hold **all** permissions in `perm`.
- If `all_perms` is absent or `False` (default), the user must hold **at least one** permission in `perm`.
- If `perm` is empty, the item is always included.

**Step 3 — Build item dict:** Keys `label`, `icon`, `url`, `class`, `app_label`, `id`, `perm`, `position`, `attrs` are extracted from the class.

**Step 4 — Sort:** Items within each section are sorted by `position` (items without a position come last).

### 📐 Returned dict shape

```python
{
    "sales": [
        {
            "label": "Leads",
            "icon": "/assets/icons/leads.svg",
            "url": "/crm/leads-view/",
            "class": "sidebar-link",
            "app_label": "leads",
            "id": "leads",          # HTML id rendered on the <a> tag
            "perm": {"perms": ["leads.view_lead", "leads.view_own_lead"], "all_perms": False},
            "position": 1,
            "attrs": {...},
        },
        ...
    ],
    "people": [...],
}
```

### 📐 Item dict keys

| Key | Source on the class | Description |
|-----|---------------------|-------------|
| `label` | `verbose_name` | Visible sidebar link text |
| `icon` | `icon` | Static path to the item's icon |
| `url` | `url` | Navigation target URL |
| `class` | `css_class` (default: `"sidebar-link"`) | CSS class on the `<a>` element |
| `app_label` | `app_label` | Django app label — used for section mapping and JS URL matching |
| `id` | `id` (falls back to `app_label`) | **HTML `id` rendered on the `<a>` tag** — must be unique across all items |
| `perm` | `perm` | Dict with `perms` list and `all_perms` flag |
| `position` | `position` | Controls order within the section |
| `attrs` | `attrs` | Dict of extra HTML attributes (HTMX, data, etc.) |

---

## 🌐 Context Processor

`get_sub_section_menu` is called inside `menu_context_processor` and exposed as `sub_section_menu` to every template automatically:

```python
# horilla/menu/context_processors.py

def menu_context_processor(request):
    return {
        "main_section_menu": get_main_section_menu(request),
        "sub_section_menu": get_sub_section_menu(request),   # ← injected here
        "settings_menu": get_settings_menu(request),
        "floating_menu": get_floating_menu(request),
        "my_settings_menu": get_my_settings_menu(request),
        "header_menu": get_header_menu(request),
        "current_section": request.GET.get("section"),
        "current_app_label": request.resolver_match.app_name if request.resolver_match else None,
    }
```

No manual context passing is needed in individual views.

---

## 🎨 Template rendering

The `sub_section_menu` context variable is consumed in `templates/components/sub_sidebar.html`:

```django
{# templates/components/sub_sidebar.html #}

{% with current_items=sub_section_menu|get_item:current_section %}
    {% if current_items %}
        <ul class="flex flex-col gap-[5px] p-5 pt-8" id="subSidebar">
            {% for item in current_items %}
                {% if not item.perm or request.user|has_super_user:item.perm %}
                    <li class="subSidebarItem">
                        <a
                            id="{{ item.id }}"
                            href="{{ item.url }}?section={{ current_section }}"
                            data-section="{{ current_section }}"
                            {% for attr, value in item.attrs.items %}
                                {{ attr }}="{{ value }}"
                            {% endfor %}
                            class="sidebar-link group flex items-center gap-3 ..."
                        >
                            {% if item.icon %}
                                <img src="{% static item.icon %}" ...>
                            {% endif %}
                            {{ item.label }}
                        </a>
                    </li>
                {% endif %}
            {% endfor %}
        </ul>
    {% endif %}
{% endwith %}
```

Key rendering details:
- `id="{{ item.id }}"` — renders the unique HTML id used by `SidebarManager` in JS for active-state tracking. This is **`item.id`**, not `item.app_label`.
- `href="{{ item.url }}?section={{ current_section }}"` — appends the current section as a query param so page reloads restore the correct sidebar state.
- `data-section="{{ current_section }}"` — used by JS to group links by section.
- `attrs` — arbitrary key/value pairs rendered as HTML attributes (e.g. `hx-get`, `hx-target`).

---

## ➕ Registering a sub-section entry

### Step 1 — Define the class in the app's `menu.py`

```python
# horilla_crm/leads/menu.py

from horilla.menu import MAIN_CONTENT_HX_ATTRS, sub_section_menu
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _

@sub_section_menu.register
class LeadSubSection:
    """Registers the Leads link in the Sales sidebar."""

    section = "sales"
    app_label = "leads"
    position = 1

    verbose_name = _("Leads")
    icon = "/assets/icons/leads.svg"

    url = reverse_lazy("leads:leads_view")
    attrs = MAIN_CONTENT_HX_ATTRS

    perm = ["leads.view_lead", "leads.view_own_lead"]
```

### Step 2 — Add `"menu"` to `auto_import_modules` in `apps.py`

```python
# horilla_crm/leads/apps.py

from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _

class LeadsConfig(AppLauncher):
    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_crm.leads"
    verbose_name = _("Leads")

    url_prefix = "crm/"
    url_module = "horilla_crm.leads.urls"

    auto_import_modules = [
        "registration",
        "menu",       # ← triggers @sub_section_menu.register at startup
        "signals",
    ]
```

`AppLauncher.ready()` imports `menu.py`, which executes the decorator and appends the class to the registry before the first request.

---

## 🧩 Class reference

### Required attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `section` | `str` | Main section this item belongs to (must match a registered `main_section_menu` entry) |
| `app_label` | `str` | Django app label — used for JS URL-to-sidebar matching |
| `verbose_name` | `str` or lazy string | Visible sidebar link text |
| `url` | `str` or `reverse_lazy(...)` | Navigation target URL |

### Optional attributes

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `id` | `str` | `app_label` | **HTML `id` on the `<a>` tag.** Set this when two items in the same section share the same `app_label` to avoid duplicate ids |
| `icon` | `str` | `None` | Static path to the SVG icon |
| `position` | `int` | `None` | Controls order within the section — items without a position appear last |
| `perm` | `str` or `list[str]` | `[]` | Required permission(s). Empty list = always shown |
| `all_perms` | `bool` | `False` | `True` = user must hold ALL permissions; `False` = at least one |
| `css_class` | `str` | `"sidebar-link"` | CSS class on the `<a>` element |
| `attrs` | `dict` | `{}` | Extra HTML attributes rendered on the `<a>` (HTMX, data attributes, etc.) |

---

## 🆔 The `id` attribute — disambiguation

The HTML `id` on each sidebar `<a>` element is what `SidebarManager` (in `global.js`) uses to track which link is active. It **must be unique** across all items rendered in the same sidebar.

By default `id` falls back to `app_label`. This is fine when every sub-section item has a distinct `app_label`. When two items belong to the same Django app (same `app_label`), you must explicitly set `id` on at least one of them:

```python
# Both items are in the "leads" Django app

@sub_section_menu.register
class LeadSubSection:
    section = "sales"
    app_label = "leads"       # id defaults to "leads"
    position = 1
    verbose_name = _("Leads")
    url = reverse_lazy("leads:leads_view")
    attrs = MAIN_CONTENT_HX_ATTRS
    perm = ["leads.view_lead", "leads.view_own_lead"]


@sub_section_menu.register
class LeadTestBlankSubSection:
    section = "sales"
    app_label = "leads"           # same Django app
    id = "leads-test-blank"       # ← explicit unique id prevents duplicate HTML ids
    position = 2
    verbose_name = _("Test Blank")
    url = reverse_lazy("leads:leads_test_blank")
    attrs = MAIN_CONTENT_HX_ATTRS
```

Without the explicit `id`, both `<a>` elements would render with `id="leads"`, causing `SidebarManager` to activate both simultaneously when navigating to either URL.

---

## 🔐 Permission filtering in detail

```python
# Any one permission is enough (default)
perm = ["leads.view_lead", "leads.view_own_lead"]

# User must hold ALL permissions
perm = ["leads.view_lead", "leads.view_own_lead"]
all_perms = True

# Always visible (no permission check)
perm = []
```

### Filtering table

| `perm` | `all_perms` | User state | Item included? |
|--------|-------------|------------|----------------|
| `[]` (empty) | Any | Any | ✅ Always |
| `["a", "b"]` | `False` | Has `a` OR `b` | ✅ |
| `["a", "b"]` | `False` | Has neither | ❌ |
| `["a", "b"]` | `True` | Has both | ✅ |
| `["a", "b"]` | `True` | Has only `a` | ❌ |
| Any | Any | Unauthenticated | ❌ |

---

## ⚠️ Important guidelines

| Avoid | Prefer |
|-------|--------|
| Hardcoding sidebar links in `sub_sidebar.html` | Register via `@sub_section_menu.register` in the app's `menu.py` |
| Omitting `"menu"` from `auto_import_modules` | Always include `"menu"` so the decorator runs at startup |
| Bare strings for `verbose_name` | Use `_("Text")` / `gettext_lazy` so labels are translatable |
| Two items with the same `app_label` and no explicit `id` | Set `id = "unique-slug"` on the second item to prevent duplicate HTML ids |
| Omitting `section` | Every item must declare which main section it belongs to |
| Referencing a section not in `main_section_menu` | Register the section first via `@main_section_menu.register` |

---

## 📌 Summary

| Feature | Without `sub_section_menu` | With `sub_section_menu` |
|---------|---------------------------|------------------------|
| Link definition | Edit `sub_sidebar.html` | Define class in app's `menu.py` |
| Permission check | Manual `{% if perms... %}` | Declarative `perm` on the class |
| Ordering | Manual HTML position | Declarative `position` integer |
| HTMX attributes | Hardcoded in HTML | Declared in `attrs` dict |
| HTML id uniqueness | Manual | `id` attribute (falls back to `app_label`) |
| Section grouping | Template conditionals | Declarative `section` attribute |
| Context availability | Manual view injection | Auto via `menu_context_processor` |

---

## 🏁 Conclusion

The `horilla.menu.sub_section_menu` module:

- Provides a **decorator-based registry** so any app can add a link to the main sidebar without touching shared templates
- Applies **per-item permission filtering** — `any` mode by default, `all` mode with `all_perms = True`
- Sorts items within each section by an explicit `position` integer
- Passes **arbitrary HTML attributes** (including HTMX directives) straight from `attrs` to the rendered `<a>` elements
- Renders a **unique HTML `id`** per item via the `id` attribute (falls back to `app_label`) so `SidebarManager` can track the active state correctly — set `id` explicitly whenever two items share the same `app_label`

Register in `menu.py`, add `"menu"` to `auto_import_modules`, and the sidebar link appears in the correct section and position for every permitted user.
