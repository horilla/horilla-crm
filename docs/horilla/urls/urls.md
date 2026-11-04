# Horilla URLs

## 🎯 Purpose

`horilla/urls/` is a small URL helper package used across Horilla apps.

It has two main parts:
- `horilla/urls/__init__.py`: **safe re-exports** of Django URL utilities (so you can import `path`, `reverse_lazy`, etc. without accidentally importing the whole project URLconf).
- `horilla/urls/project.py`: the Horilla **project-level** `urlpatterns` used as `ROOT_URLCONF`.

---

## 🧠 Core concept

### ✅ Safe imports from `horilla.urls`

Many Horilla modules (views, models, forms) import URL helpers like:
`from horilla.urls import reverse_lazy` or `from horilla.urls import path`.

The `horilla/urls/__init__.py` module is designed to be **safe to import early**, because it only re-exports primitives from `django.urls` and does **not** import the project root URL configuration.

### Convention in app code

Prefer **`horilla.urls`** over direct **`django.urls`** imports in models, views, tasks, menus, and services — even though the symbols are thin re-exports. This keeps imports consistent across contrib apps (booking model helpers, mail tracking pixels, navbar actions, etc.) and avoids accidentally pulling in project URLconf during early startup.

```python
# ✅ Preferred in Horilla apps
from horilla.urls import reverse, reverse_lazy, path

# ❌ Avoid in new Horilla code when horilla.urls exports the symbol
from django.urls import reverse
```

---

## 📦 Module layout

```text
horilla/urls/
├── __init__.py      # re-export: path/re_path/include/reverse/resolve/etc.
└── project.py      # project urlpatterns (ROOT_URLCONF)
```

---

## 🔁 What `horilla.urls` re-exports (`__init__.py`)

These are exported in `__all__`:

| Name | Django original |
|------|------------------|
| `path` | `django.urls.path` |
| `re_path` | `django.urls.re_path` |
| `include` | `django.urls.include` |
| `reverse` | `django.urls.reverse` |
| `reverse_lazy` | `django.urls.reverse_lazy` |
| `resolve` | `django.urls.resolve` |
| `Resolver404` | `django.urls.Resolver404` |
| `get_resolver` | `django.urls.get_resolver` |
| `get_urlconf` | `django.urls.get_urlconf` |
| `clear_url_caches` | `django.urls.clear_url_caches` |

---

## 🧪 Usage examples (with explicit parameters)

### 📍 Example: `path(...)` inside an app `urls.py`

Django signature:
- `path(route, view, kwargs=None, name=None)`

```python
from horilla.urls import path
from horilla_crm.contacts.views import core as views


urlpatterns = [
    path(
        route="contact/create/",
        view=views.ContactCreateView.as_view(),
        kwargs=None,
        name="contact_create",
    ),
]
```

### 📍 Example: `re_path(...)`

Django signature:
- `re_path(route, view, kwargs=None, name=None)`

```python
from horilla.urls import re_path
from horilla_crm.contacts.views import core as views


urlpatterns = [
    re_path(
        route=r"^contact/(?P<pk>\d+)/detail/$",
        view=views.ContactDetailView.as_view(),
        kwargs=None,
        name="contact_detail",
    ),
]
```

### 📍 Example: include another URLconf

Django signature:
- `include(module, namespace=None)`

```python
from horilla.urls import include, path
from horilla_crm.contacts import urls as contacts_urls


urlpatterns = [
    path(
        route="contacts/",
        view=include(contacts_urls, namespace="contacts"),
        kwargs=None,
        name=None,
    ),
]
```

### 🔄 Example: `reverse_lazy(...)` for URLs in code (models/forms/menus)

Django signature:
- `reverse_lazy(viewname, urlconf=None, args=None, kwargs=None, current_app=None)`

```python
from horilla.urls import reverse_lazy

create_url = reverse_lazy(
    viewname="contacts:contact_create_form",
    urlconf=None,
    args=None,
    kwargs=None,
    current_app=None,
)
```

### 🔄 Example: `reverse(...)` for URL generation (non-lazy)

Django signature:
- `reverse(viewname, urlconf=None, args=None, kwargs=None, current_app=None)`

```python
from horilla.urls import reverse

detail_url = reverse(
    viewname="contacts:contact_detail",
    urlconf=None,
    args=None,
    kwargs={"pk": 12},
    current_app=None,
)
```

### 🔎 Example: `resolve(...)`

Django signature:
- `resolve(pathname, urlconf=None)`

```python
from horilla.urls import resolve

match = resolve("/contacts/contact/12/detail/")
resolved_view = match.func  # view callable
```

---

## 🏗️ Project-level `urlpatterns` (`project.py`)

`horilla/settings/base.py` sets:
- `ROOT_URLCONF = "horilla.urls.project"`

In `horilla/urls/project.py`, the module defines:
- `health_check` view: returns `JsonResponse({"status": "ok"}, status=200)`
- `urlpatterns` containing:
  - `health/`
  - `admin/`
  - `i18n/`
  - `jsi18n/` (JavaScriptCatalog)
  - `summernote/`
  - `api/` (includes `horilla.api_urls`)
- Static-file serving when `settings.DEBUG` is enabled. Media is not included; `/media/` is `protected_media`.
- Extension composition: after the patterns, `bootstrap_extensions()` (from `horilla.extension.bootstrap`) is called at import and again once on the first `request_started` signal (then disconnected). The second call is needed because this module is first imported during `AppConfig.ready()`, before later-loading extension apps (e.g. `field_management`) have registered anything.

---

## 🔌 App URLs are auto-appended from app `apps.py`

app routes are dynamically appended via `AppLauncher`.

### 📍 Where this happens

`horilla/apps/__init__.py` → `AppLauncher.ready()` calls `_register_urls()`.

`_register_urls()` logic:

- reads `settings.ROOT_URLCONF`
- imports that module (`horilla.urls.project`)
- appends `path(...)` into its `urlpatterns` using:
  - `url_prefix`
  - `url_module`
  - optional `url_namespace`

So every app config can contribute routes by declaring these in its `apps.py`.

### 🧪 Example (from app config)

```python
class ContactsConfig(AppLauncher):
    url_prefix = "contacts/"
    url_module = "horilla_crm.contacts.urls"
    url_namespace = "contacts"
```

This results in dynamic inclusion equivalent to:

```python
path("contacts/", include(("horilla_crm.contacts.urls", "contacts")))
```

### ✅ Practical meaning

- `project.py` contains base/global routes (`health`, `admin`, `i18n`, `api`, etc.).
- App-specific routes are mostly mounted dynamically from each app’s `apps.py` through `AppLauncher`.
- New apps can join routing by setting `url_prefix` and `url_module` (and optionally `url_namespace`) in their `AppLauncher` subclass.

---

## 📌 Summary

- Import URL helpers from `horilla.urls` (safe re-exports of Django URL utilities).
- Use your app’s `urls.py` for route definitions (`path`, `re_path`, `include`).
- Keep `project.py` as the project-level `ROOT_URLCONF` wiring.
