# Header Menu

## Purpose

The `horilla.menu.header_menu` module provides:

- **Registration system** — a decorator-based registry for the account dropdown in the header
- **One class, one link** — the same shape as a My Settings entry: `title` and `url` on the class
- **Permission and condition filtering** — a link is hidden when its `perm` or `condition` fails
- **Order-based sorting** — links sort by `order`, and a negative order stays last
- **`attrs` for extra HTML** — `id`, `aria-*`, `hx-*`, and any other attribute live in `attrs` and are written onto the `<a>`
- **Context processor integration** — auto-injected into every template as `header_menu`

It is the standard way for any Horilla app to add a link to the header account dropdown (My Settings, Product Tours, Logout) without editing `templates/components/header.html`.

---

## Core concept

```python
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _
from horilla.menu import header_menu


@header_menu.register
class HelpLink:
    """Header account-menu entry for Help."""

    title = _("Help")
    url = reverse_lazy("help:index")
    order = 30
    perm = "help.view_article"
    attrs = {
        "hx-target": "#mainContent",
        "hx-push-url": "true",
    }
```

**Simple rule:** Define the class in the app's `menu.py` and register it with `@header_menu.register`. Put `title` and `url` on the class. Put any extra `<a>` attribute in `attrs`.

---

## Module location

```text
horilla/menu/
│
├── header_menu.py       # Registry, register(), get_header_menu()
└── ...

<app>/
├── menu.py              # Where apps define and register their header entries
└── apps.py              # Where "menu" is listed in auto_import_modules
```

---

## What `horilla.menu.header_menu` provides

- `header_registry` — module-level list holding all registered classes
- `register` — decorator that appends a class to `header_registry`
- `get_header_menu` — returns a filtered, order-sorted list of row dicts for the current request

---

## Class fields

| Field | Required | Role |
|-------|----------|------|
| `title` | yes | Link text. Pass a `gettext_lazy` value. The template prints `{{ item.title }}`. |
| `url` | no | `href`. `"#"` stays `href="#"`. Empty or missing renders a `<button type="button">`. |
| `order` | no | Default `100`. `>= 0` sorts first, missing stays in the middle, `< 0` sorts last. |
| `perm` | no | String or list. Hidden unless `request.user.has_any_perms(...)`. |
| `condition` | no | `True`, or `(request) -> bool`. |
| `attrs` | no | Dict copied onto the `<a>` or `<button>`. Do not put `class` here. The template owns the class. |

Logout uses `order = -1`, so an app entry with `order = 30` still sits above it.

### Returned row

| Key | Description |
|-----|-------------|
| `title` | Link text |
| `url` | `href`, or `""` when the row is a button |
| `order` | Resolved sort value |
| `attrs` | The class `attrs` dict, or `{}` |

---

## Built-in entries

| Class | App | `order` | Notes |
|-------|-----|---------|--------|
| `MySettingsLink` | `horilla/contrib/core/menu.py` | `10` | `url` is `core:my_settings_view`. No `attrs`. |
| `ProductTours` | `horilla/contrib/tour/menu.py` | `20` | `url` is `"#"`. Launcher `id`, `aria-*`, and `hx-*` are in `attrs`. `tour` lists `"menu"` in `auto_import_modules`. |
| `LogoutLink` | `horilla/contrib/core/menu.py` | `-1` | Stays last. `url` is `core:logout`. |

```python
@header_menu.register
class ProductTours:
    """Header account-menu entry that opens the product tour panel."""

    title = _("Product Tours")
    url = "#"
    order = 20
    attrs = {
        "id": "horilla-tour-launcher",
        "aria-haspopup": "dialog",
        "aria-expanded": "false",
        "aria-controls": "horilla-tour-panel",
        "hx-get": reverse_lazy("tour:panel"),
        "hx-vals": "js:{path: window.location.pathname}",
        "hx-target": "#tour-panel-content",
        "hx-indicator": "#tour-panel-loading",
    }
```

---

## Context processor

`get_header_menu` is called inside `menu_context_processor` and exposed as `header_menu`:

```python
def menu_context_processor(request):
    return {
        "main_section_menu": get_main_section_menu(request),
        "sub_section_menu": get_sub_section_menu(request),
        "settings_menu": get_settings_menu(request),
        "floating_menu": get_floating_menu(request),
        "my_settings_menu": get_my_settings_menu(request),
        "header_menu": get_header_menu(request),
        "current_section": section_param,
        "current_app_label": current_app_label,
    }
```

---

## Template rendering

`templates/components/header.html` loops `header_menu` inside the account dropdown. The profile button stays in the template.

```django
<ul class="text-sm">
    {% for item in header_menu %}
        <li>
            {% if item.url %}
                <a href="{{ item.url }}"
                   class="px-4 py-1.5 hover:text-primary-600 transition duration-300 text-sm gap-4 items-center flex w-full"
                   {% for attr, value in item.attrs.items %}{{ attr }}="{{ value }}" {% endfor %}>
                    {{ item.title }}
                </a>
            {% else %}
                <button type="button"
                        class="px-4 py-1.5 hover:text-primary-600 transition duration-300 text-sm gap-4 items-center flex w-full"
                        {% for attr, value in item.attrs.items %}{{ attr }}="{{ value }}" {% endfor %}>
                    {{ item.title }}
                </button>
            {% endif %}
        </li>
    {% endfor %}
</ul>
```

`{{ value }}` escapes the attribute value. Do not mark `attrs` safe.
