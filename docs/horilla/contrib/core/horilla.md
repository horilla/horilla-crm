# Horilla Package (`horilla/`)

## 🎯 Purpose

The top-level `horilla/` package contains “platform” code that the rest of the project imports for:

- **product / platform version** (`__version__.py` — whole CRM, not this folder only; see [versioning.md](../../../versioning.md))
- shared exports (`__init__.py`)
- ASGI/WSGI entrypoints (`asgi.py`, `wsgi.py`)
- dynamic API URL wiring + Swagger schema (`api_urls.py`)
- global template context via Django context processors (`context_processors.py`)
- Celery configuration (`horilla_celery.py`)


---

## 📦 Module: `horilla/__init__.py`

### ✅ What it exports

`horilla/__init__.py` exposes the Celery app as `celery_app`.

```python
from .horilla_celery import app as celery_app

__all__ = ["celery_app"]
```

### 🎯 Why it exists

So external code (or Celery config) can import:

```python
from horilla import celery_app
```

---

## 🏷️ Module: `horilla/__version__.py`

### 🎯 Purpose

**This file is the Horilla CRM product / platform version for the entire project**
(git tag, Docker tag, About / Modules & Versions). It is **not** limited to code
under the `horilla/` directory — weekly platform changelog entries should cover
project-wide highlights (new apps like Custom Fields, CRM, contrib, etc.).

Full rules: [docs/versioning.md](../../../versioning.md).

Contains Horilla metadata used across the system, including:

- `__version__`
- `__module_name__`
- `__release_date__`
- `__description__`
- `__icon__`
- version-history strings like `__1_5_0__`, `__1_4_0__`, etc.

### Key exported variables

- `__version__ = "1.18.0"`
- `__module_name__ = _("Core System")`
- `__description__ = _("Core system providing authentication, configuration, utilities, and platform-level services.")`
- `__icon__ = "assets/icons/logo.png"`
- Changelog keys such as `__1_18_0__`, `__1_17_2__`, `__1_17_1__`, … (newest first; do not edit older entries)

### Translation note

This file uses `gettext_lazy` (so strings are safe to store on module-level constants).

---

## 🌐 Module: `horilla/api_urls.py`

### 🎯 Purpose

Defines Horilla’s **API routing** and **Swagger/OpenAPI documentation**.

Main responsibilities:
- dynamically collect API endpoints from installed apps (`collect_api_paths`)
- build Swagger schema view with a custom schema generator
- expose `urlpatterns` for:
  - `/api/docs/` (Swagger UI)
  - `/api/redoc/` (ReDoc)
  - `/api/*` endpoints discovered from apps

---

### 🔁 Dynamic API paths

#### `collect_api_paths()`

It scans all installed Django `AppConfig` objects and looks for a `get_api_paths()` method.

Each app returns a list of dicts like:

```python
{
  "pattern": "crm/contacts/",
  "view_or_include": "horilla_crm.contacts.api.urls",
  "name": "horilla_crm_contacts_api",
  "namespace": "horilla_crm_contacts",
}
```

Then `collect_api_paths()`:
- normalizes each `pattern` to a single trailing slash
- mounts the results under the `/api/` prefix (project `horilla/urls/project.py` already includes `horilla.api_urls` at `path("api/", include("horilla.api_urls"))`)
- detects conflicts (same relative pattern used by two apps)
- supports both:
  - `view_or_include` as an include string (`include(view_or_include)`)
  - `view_or_include` as a view callable/class

#### `get_dynamic_api_patterns()`

Helper used by the Swagger schema generation:
- returns `collect_api_paths()`
- if it fails, returns `[]` so schema generation doesn’t crash.

---

### 🏷️ Swagger tags per app

The file defines:
- `get_app_verbose_name_from_view(view)`
- `VerboseNameAutoSchema(SwaggerAutoSchema)`

This custom auto schema tries to map a view back to its app config and uses the app’s `verbose_name` as Swagger “tags”.

---

### 📌 `urlpatterns`

`horilla/api_urls.py` exports:
- a schema UI route:
  - `path("docs/", schema_view.with_ui("swagger", cache_timeout=0), name="schema-swagger-ui")`
- a schema route:
  - `path("redoc/", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc")`
- plus `collect_api_paths()` appended to the urlpatterns list.

---

### 🧪 Example: how an app supplies API routes

In an app’s `apps.py`:

```python
from horilla.apps import AppLauncher


class ContactsConfig(AppLauncher):
    url_prefix = "contacts/"
    url_module = "horilla_crm.contacts.urls"
    url_namespace = "contacts"

    def get_api_paths(self):
        return [
            {
                "pattern": "crm/contacts/",
                "view_or_include": "horilla_crm.contacts.api.urls",
                "name": "horilla_crm_contacts_api",
                "namespace": "horilla_crm_contacts",
            }
        ]
```

Result:
- Horilla mounts it under `/api/crm/contacts/`.

---

## 🔌 Module: `horilla/context_processors.py`

### 🎯 Purpose

Provides global context for templates using Django **context processors**.

Your `horilla/settings/base.py` includes (among others):
- `horilla.context_processors.company_list`
- `horilla.context_processors.allowed_languages`
- `horilla.context_processors.recently_viewed_items`
- `horilla.context_processors.unread_notifications`
- `horilla.context_processors.menu_context_processor`
- `horilla.context_processors.currency_context`
- `horilla.context_processors.branding`

---

## 🧩 Context processors implemented here

### `company_list(request)`

Returns:
- `available_companies`: `Company.objects.all()`

### `allowed_languages(request)`

Returns:
- `allowed_languages`: built from `settings.ALLOWED_LANGUAGES`
  - each entry includes `code`, `name`, `flag`, and `active`

### `recently_viewed_items(request)`

If `request.user.is_authenticated`, returns:
- `recently_viewed_items`: last 6 `RecentlyViewed` records for that user

It also tries to validate references:
- if `rv.content_object` access fails, it deletes invalid rows.

### `unread_notifications(request)`

If authenticated, returns:
- `unread_notifications`: notifications where `read=False`, newest first.

### `menu_context_processor(request)`

Returns navigation/menu variables for templates:
- `main_section_menu`
- `sub_section_menu`
- `settings_menu`
- `floating_menu` (this is `get_floating_menu(request)`)
- `my_settings_menu`
- `current_section` (from `request.GET["section"]`)
- `current_app_label` (from `request.resolver_match.app_name`)


### `currency_context(request)`

If authenticated and the user has a company:
- computes `user_currency`
- computes `default_currency` via `MultipleCurrency.get_default_currency` (**per-company cached** — see [company_settings_cache](../contrib/utils/company_settings_cache.md))

Exposes:
- `user_currency`
- `default_currency`

If not authenticated, returns `{}`.

### `branding(request)`

Returns:
- branding configuration loaded by `horilla.utils.branding.load_branding()`

---

## ⚙️ Module: `horilla/horilla_celery.py`

### 🎯 Purpose

Defines the Celery app instance for the project.

### Key parts

- sets `DJANGO_SETTINGS_MODULE = horilla.settings`
- creates:

```python
app = Celery("horilla")
```

- configures from Django settings under `CELERY` namespace:

```python
app.config_from_object("django.conf:settings", namespace="CELERY")
```

- autodiscovers tasks:

```python
app.autodiscover_tasks()
```

---

## 🧩 Module: `horilla/asgi.py`

### 🎯 Purpose

ASGI entrypoint used by ASGI servers (e.g. Daphne/Uvicorn).

Exports:
- `application` callable at module level.

### What it routes

It uses `ProtocolTypeRouter`:
- `"http"` → `get_asgi_application()`
- `"websocket"` → `AuthMiddlewareStack(URLRouter(horilla_notifications.routing.websocket_urlpatterns))`

So HTTP traffic uses Django ASGI, and WebSockets are handled by the channels routing for Horilla notifications.

The router is wrapped in `FreshContextMiddleware` (`horilla/utils/asgi.py`), which runs every ASGI call in an empty `contextvars.Context`. uvicorn starts a keep-alive or pipelined request from inside the previous request's task, so without the wrapper a request can inherit the previous request's Django `ThreadSensitiveContext` and deadlock the worker (python/cpython#140947). Keep the wrapper outermost if you add other ASGI middleware.

---

## 🏗️ Module: `horilla/wsgi.py`

### 🎯 Purpose

WSGI entrypoint for production WSGI servers (e.g. Gunicorn).

Exports:
- `application = get_wsgi_application()`

---

## 📌 Summary (quick mapping)

| File | What it does |
|------|---------------|
| `horilla/__init__.py` | exports `celery_app` |
| `horilla/__version__.py` | metadata: version, name, icon, descriptions |
| `horilla/api_urls.py` | dynamic API collection + Swagger docs (`urlpatterns`) |
| `horilla/asgi.py` | ASGI routing for HTTP + WebSockets |
| `horilla/context_processors.py` | global template context (menus, floating menu, currency, branding, etc.) |
| `horilla/horilla_celery.py` | Celery app config (`app`) |
| `horilla/wsgi.py` | WSGI application (`application`) |
| `horilla/web/` | HTTP re-exports and helpers — **`horilla.web`** (`RedirectResponse`, `RefreshResponse`, `safe_url`, `HttpNotFound`); see [web/web.md](../web/web.md) |
