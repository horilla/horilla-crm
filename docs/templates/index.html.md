# Base layout: `templates/index.html`

This document describes the **root HTML shell** for authenticated Horilla CRM pages. Almost every in-app template ultimately extends this file (directly or via `modelcontent_layout.html`).

## Location

```text
templates/
└── index.html          # Root layout (this document)
```

Related files:

| File | Role |
|------|------|
| `templates/components/header.html` | Top navigation bar |
| `templates/components/sidebar.html` | Left icon sidebar |
| `templates/components/horilla_modals.html` | Shared modal containers |
| `templates/components/empty_state.html` | Shared empty-state image + message partial — see [components/empty_state.md](components/empty_state.md) |
| `templates/messages.html` | Django messages toast area |
| `templates/components/modelcontent_layout.html` | Standard inner layout (sidebar + `#mainContent`) |

---

## Purpose

`index.html` is the **application shell**. It owns:

- Document structure (`<html>`, `<head>`, `<body>`)
- Global CSS and JavaScript libraries (Tailwind, HTMX, jQuery, Flowbite, ECharts, etc.)
- Theme initialization (light/dark via `localStorage`)
- Fixed chrome: header, sidebar, modals, messages
- HTMX CSRF header wiring
- **Extension slots** for apps to inject HTML/JS without editing this file

Page templates should **not** duplicate this shell. They should `{% extends "index.html" %}` (or extend `modelcontent_layout.html`) and fill the `content` block.

---

## Layout structure

```text
<html>
  <head>
    [head_start slot] → theme init → core scripts → styles → extra_css → [head_end slot]
  </head>
  <body>
    [body_start slot]
    <div class="ml-[4.8rem] h-screen">
      #header          → components/header.html
      {% block content %}
      horilla_modals   → components/horilla_modals.html
    </div>
    #sidebar           → components/sidebar.html
  #reloadMessagesButton (hidden HTMX trigger)
  #reloadMessages      → messages.html
    HTMX CSRF script
    global JS + registered JS + extra_js
    [body_end slot]
  </body>
</html>
```

The main content area lives inside `{% block content %}`. Most CRM list/detail pages use `modelcontent_layout.html`, which extends `index.html` and adds the `modelcontent` flex row, sub-sidebar, and `#mainContent`.

---

## Template tags and loads

At the top of `index.html`:

```django
{% load static i18n horilla_tags %}
```

| Tag / load | Usage in this template |
|------------|-------------------------|
| `{% static %}` | All asset URLs |
| `{% trans %}` | Available for child templates via `i18n` |
| `{% load_registered_html slot %}` | Inject registered HTML fragments into layout slots |
| `{% load_registered_js %}` | Inject app-registered JavaScript files |

---

## Available blocks

Child templates can override these blocks:

| Block | Location | Typical use |
|-------|----------|-------------|
| `extra_css` | `<head>` | Page-specific stylesheets |
| `content` | Body, inside main wrapper | **Primary page body** (required for most pages) |
| `extra_js` | Before `body_end` slot | Page-specific scripts after globals |

There is no `title` block; the document title uses the branding context variable `{{ TITLE }}` (from `horilla.context_processors.branding`).

### Extending for page content

**Minimal page (full-width inside shell):**

```django
{% extends "index.html" %}
{% load i18n %}

{% block content %}
    <div class="p-4">
        <h1>{% trans "My Page" %}</h1>
    </div>
{% endblock content %}
```

**Standard CRM page (sidebar + main area):**

```django
{% extends "components/modelcontent_layout.html" %}
{% load i18n %}

{% block main %}
    {# Your page markup #}
{% endblock %}
```

See also: [Modelcontent layout migration guide](components/modelcontent_layout.html.md).

---

## Fixed includes (do not duplicate)

These are always rendered by `index.html`:

| Include | DOM id / notes |
|---------|----------------|
| `components/header.html` | `#header` |
| `components/sidebar.html` | `#sidebar` |
| `components/horilla_modals.html` | Shared modal targets for HTMX |
| `messages.html` | Inside `#reloadMessages` |

When building HTMX partials, target existing containers (e.g. `#mainContent`, modal ids from `horilla_modals.html`) instead of re-including the header or sidebar.

---

## Global context variables

Available in every template that extends `index.html` (via Django context processors). See [context_processors.md](../horilla/context_processors.md) for full detail.

| Variable | Source | Used for |
|----------|--------|----------|
| `TITLE` | `branding` | `<title>` |
| `available_companies` | `company_list` | Company switcher |
| `allowed_languages` | `allowed_languages` | Language picker |
| `recently_viewed_items` | `recently_viewed_items` | Header recents |
| `unread_notifications` | `unread_notifications` | Notification bell |
| `main_section_menu`, `floating_menu`, … | `menu_context_processor` | Navigation |
| `user_currency`, `default_currency` | `currency_context` | Money display |
| Branding keys | `branding` | Logo, login copy, etc. |

Session:

- `request.session.theme` — when `"dark"`, adds `dark` class on `<html>` at server render time (complements client-side `localStorage` theme).

---

## Theme (light / dark)

Two mechanisms work together:

1. **Server:** `{% if request.session.theme == 'dark' %}dark{% endif %}` on `<html>`
2. **Client (blocking, in `<head>`):** reads `localStorage.getItem("theme")` and sets `html` class and `color-scheme`
3. **Client (body):** adds `dark` class to `<body>` when `localStorage` theme is `"dark"`

Child templates should use Tailwind `dark:` variants and existing CSS (`assets/css/dark.css`) rather than custom theme logic.

---

## Asset registry: HTML injection slots

Apps register HTML fragments with `horilla.registry.asset_registry.register_html`. `index.html` renders them in four slots:

| Slot | Position in `index.html` | Typical content |
|------|--------------------------|-----------------|
| `head_start` | Start of `<head>` | Early blocking scripts |
| `head_end` | End of `<head>` | Dynamic Tailwind config, meta, extra CSS hooks |
| `body_start` | Start of `<body>` | Analytics, early body init |
| `body_end` | End of `<body>` | Deferred bindings, feature scripts |

**Allowed slots** are defined in `horilla/registry/asset_registry.py` (`INJECT_ALLOWED_SLOTS`).

### Register from an app

Call from a module loaded at startup (e.g. `registration.py`):

```python
from horilla.registry.asset_registry import register_html

register_html(
    "my_app/inject_html/custom_head.html",
    slot="head_end",
    priority=50,       # Lower = earlier within the slot
    page="base",       # Default layout; use "login" for login-only fragments
)
```

**Real example** (`horilla.contrib.theme.registration`):

```python
register_html("inject_html/tailwind_dynamic_config.html", slot="head_end", priority=100)
register_html("inject_html/tailwind_dynamic_config_login.html", slot="head_end", priority=50, page="login")
```

Fragments must be valid HTML partials (no full document). They are included with `{% include tpl %}`.

---

## Asset registry: JavaScript registration

Apps register JS paths via `AppLauncher` or directly:

**Via `apps.py` (preferred):**

```python
class MyAppConfig(AppLauncher):
    js_files = ["my_app/assets/js/my_feature.js"]
    # or js_files = ["path1.js", "path2.js"]
```

`AppLauncher.ready()` calls `register_js()` automatically.

**Rendered in `index.html` (after global scripts):**

```django
{% load_registered_js as register_js %}
{% for js_file in register_js %}
    <script src="{% static js_file %}"></script>
{% endfor %}
```

Prefer `js_files` / `register_js` over editing `index.html` when adding app-specific scripts.

---

## Bundled libraries (reference)

Loaded globally from `index.html` (paths under `static/assets/`):

| Category | Libraries |
|----------|-----------|
| Styling | Tailwind (runtime + config), Flowbite, Font Awesome, `style.css`, `dark.css`, Select2, Summernote, animate |
| Interaction | HTMX (+ download extension), Hyperscript, jQuery, Select2, SortableJS, SweetAlert2 |
| Charts / export | Chart.js, ECharts, jsPDF |
| App globals | `global.js`, `action_tooltip.js`, `horilla_charts.js`, `calendar.js`, `full_calendar.js` |
| i18n | `{% url 'javascript-catalog' %}` |

Page-specific assets belong in `{% block extra_css %}` / `{% block extra_js %}`, or in the asset registry—not by patching `index.html`.

---

## HTMX and CSRF

All HTMX requests from pages using this layout send `X-CSRFToken`. The handler
reads the live `csrftoken` cookie, so a token rendered when the page loaded
does not go stale after the CSRF secret rotates (for example a sign-in in
another tab). When the cookie is missing, it falls back to the token rendered
in the page:

```javascript
document.body.addEventListener("htmx:configRequest", (event) => {
    const cookie = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    event.detail.headers["X-CSRFToken"] = cookie
        ? decodeURIComponent(cookie[1])
        : "{{ csrf_token }}";
});
```

Server-side HTMX helpers (`RefreshResponse`, `RedirectResponse`) live in **`horilla.web`** (`horilla/web/response.py`). Import them from the package entry point when possible:

```python
from horilla.web import RedirectResponse, RefreshResponse
```

Use those instead of hand-rolling `HX-Refresh` / `HX-Redirect` headers in views when possible.

### Messages reload

A hidden button reloads Django messages via HTMX:

```django
<button id="reloadMessagesButton"
        hx-get="{% url 'core:reload_messages' %}"
        hx-swap="afterend"
        hx-target="#reloadMessages"
        hidden>
</button>
```

Trigger `#reloadMessagesButton` from JS after actions that set messages and need a toast refresh without full page reload.

---

## When to extend what

| Scenario | Extend |
|----------|--------|
| Login, standalone, or custom full-page layout | `index.html` → override `content` |
| Standard CRM module (list, detail, settings with sub-nav) | `components/modelcontent_layout.html` → override `main`, `navbar`, etc. |
| HTMX partial (row, form fragment, modal body) | **Do not extend** `index.html`; return a partial template only |
| Inject config/scripts for all pages | `register_html` / `AppLauncher.js_files` |

---

## Best practices

1. **Never copy the shell** — extend `index.html` or `modelcontent_layout.html`.
2. **HTMX partials stay small** — no `<html>`, header, or sidebar in fragment responses.
3. **Register assets, don’t fork the base template** — use `register_html`, `register_js`, and `js_files`.
4. **Use `extra_css` / `extra_js` sparingly** — prefer shared static bundles for one-off pages only.
5. **Respect `#mainContent`** — primary HTMX swap target for in-app navigation (via modelcontent layout).
6. **Keep slot fragments valid** — `register_html` templates must render complete, safe HTML for their slot (scripts in `head_*` or `body_*` as appropriate).

---

## Related documentation

- [Modelcontent layout migration guide](components/modelcontent_layout.html.md)
- [AppLauncher / apps configuration](../horilla/apps/apps.md)
- [Asset registry](../horilla/contrib/core/Registry/asset_registry.md) (if present) or `horilla/registry/asset_registry.py`
- [Context processors](../horilla/context_processors.md)
- [Asset template tags](../horilla/contrib/generics/templatetags/horilla_tags/asset_tags.md)
