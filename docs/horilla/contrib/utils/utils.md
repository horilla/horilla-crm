# Horilla contrib Utils app — deep dive (`horilla.contrib.utils`)

## What this app is (and is not)

- **`horilla.contrib.utils`** is a **Django app** used for **cross-app Python helpers**, **middleware**, and **management commands**.
- It is **not** the top-level **`horilla.utils`** package (branding, choices, decorators—see [../../utils/utils.md](../../utils/utils.md)).

`UtilsConfig` is intentionally minimal: only `name`, `label`, and `default_auto_field`—**no URLs** in `apps.py`. The app exists so Django loads `default_app_config` modules and discovers `management/commands`.

---

## Modules

### `middlewares.py`

- **`ThreadLocalMiddleware`** — stores `request` on **`_thread_local`** so code running deep inside signals (e.g. **automations**) can recover `request.user` and `request.active_company` without threading the request through every call stack.
- Must appear in **`MIDDLEWARE`** after auth/company middleware—see [../core/Settings/base.md](../core/Settings/base.md) ordering in project settings.
- **`get_current_request()`** — the thread-local request, or `None`.
- **`get_active_company(request=None)`** — the one way Python code reads the active company (company-switcher aware). `ActiveCompanyMiddleware` is the only writer of `request.active_company`. The helper returns it and falls back to the user's own company when the middleware could not resolve one (DRF JWT/Basic auth, `RequestFactory`, fake requests). With no argument it uses the thread-local request, so models, managers, signals and forms can call `get_active_company()`. It returns `None` when there is no request. Templates keep using `{{ request.active_company }}`. `core/tests.py` (`ActiveCompanySingleReaderTests`) fails if Python code reads `request.active_company` or `getattr(request, "active_company", ...)` directly.

### `methods.py`

Large utility surface, including:

- **`get_horilla_model_class(app_label, model)`** — resolves ORM class via **`HorillaContentType`** rows (not Django stock ContentType).
- **Template helpers** — `render_template` used across dashboard, activity columns, duplicates, etc.
- **Queryset helpers** — `apply_conditions`, `get_queryset_for_module`, and related functions consumed by dashboards, reports, and generics filter pipeline.
- **`sanitize_html` / `sanitize_plain_text`** — bleach-based sanitizers used by notes/attachments (`HorillaAttachment.save`), mail preview, and other user-content surfaces. Prefer these over ad-hoc escaping when persisting rich or plain text from users.

Import paths typically look like:

```python
from horilla.contrib.utils.methods import render_template, get_horilla_model_class
from horilla.contrib.utils.methods import sanitize_html, sanitize_plain_text
```

### `company_settings_cache.py`

Generic **per-company settings cache** (`get_or_set_company_setting` / `invalidate_company_setting`). Apps pass their own namespace; used so context processors and menu conditions do not re-query the same company settings row on every page render.

See [company_settings_cache.md](company_settings_cache.md).

### `views.py`

Small/supporting HTTP endpoints if present (read file for current exports).

### `management/commands/start_horilla_app.py`

Scaffolds a new Horilla CRM app with `AppLauncher`, `registration.py`, `menu.py`, etc.—the recommended starting point for modules.

### `models.py`

Empty placeholder—no migrations required for models today.

### `tests.py`

App-level unit tests for utilities.

---

## Why automations depend on this app

`horilla.contrib.automations.signals` reads **`_thread_local.request`** set by **`ThreadLocalMiddleware`**. Removing the middleware breaks recipient resolution for `mail_to` patterns referencing `self` or `instance.owner`.

---

## Related documentation

- Core `HorillaContentType`: [../core/models.md](../core/models.md)
- Automations signal flow: [../automations/automations.md](../automations/automations.md)
- Per-company settings cache: [company_settings_cache.md](company_settings_cache.md)
- Context processors: [../../context_processors.md](../../context_processors.md)
