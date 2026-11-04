# `base.py` (Django settings)

## 🎯 Purpose

`horilla/settings/base.py` is the main settings file.
It configures:
- environment variable reading (including optional `.env`)
- `INSTALLED_APPS`, middleware, templates
- REST framework + JWT + throttling
- database configuration (supports `DATABASE_URL`)

## 🌍 Environment & configuration

The file uses `environ.Env(...)` to define expected variables with defaults:

- `DEBUG` (default `True`)
- `ENVIRONMENT` (default `"development"`)
- `SECRET_KEY` (no usable default: a blank value or a shipped placeholder is replaced by a generated key stored at `SECRET_KEY_FILE`, default `.secret_key`)
- `TRUSTED_PROXIES` (default empty — forwarded client headers are ignored)
- `REDIS_URL` (default empty — login counters stay in the per-process cache; set this so workers share them)
- `ALLOWED_HOSTS` (default `["*"]`)
- `CSRF_TRUSTED_ORIGINS` (default `["http://localhost:8000"]`) — must include every origin the browser uses (scheme + host + port); add both `localhost` and `127.0.0.1` in local dev if you switch between them.

If a `.env` file exists under `BASE_DIR`, it loads it:
- `env.read_env(str(env_file), overwrite=False)`

An environment variable already set on the process wins over `.env`. Typical usage:
- set values in `.env` for local/dev
- or export environment variables in production

## 📦 Installed apps + middleware

`base.py` defines large lists:
- `INSTALLED_APPS`: core Django apps + third-party apps + Horilla apps
- `MIDDLEWARE`: security, session/auth, Horilla middlewares, locale, CSRF, messages, etc.

**CSRF failure page** (production-friendly, when `DEBUG=False`):

```python
CSRF_FAILURE_VIEW = "horilla.contrib.core.views.error_pages.csrf_failure"
```

Renders `templates/csrf_failure.html` (extends `error.html`, same layout as `403.html` / `404.html` / `405.html`). When `DEBUG=True`, the same setting still points at `csrf_failure`, but that view delegates to Django’s technical CSRF help page. See [contrib core app — Custom error pages](../contrib/core/core_app.md#custom-error-pages-templates--viewserror_pagespy).

Note: `horilla/settings/horilla_apps.py` extends `INSTALLED_APPS` further .

## 🌐 Templates context processors

`TEMPLATES[0]["OPTIONS"]["context_processors"]` includes Horilla context processors, such as:
- `horilla.context_processors.menu_context_processor` (menus, floating menu, etc.)
- `horilla.context_processors.branding`
- `horilla.context_processors.recently_viewed_items`

This is why template variables like `floating_menu`, `main_section_menu`, etc. appear automatically.

## 🏷️ Template builtins

`TEMPLATES[0]["OPTIONS"]["builtins"]` auto-loads these tag libraries into every template — no `{% load %}` tag required:

| Library | Provides |
|---|---|
| `django.templatetags.static` | `{% static %}` tag |
| `django.templatetags.i18n` | `{% trans %}`, `{% blocktrans %}` tags |
| `horilla.contrib.generics.templatetags.horilla_tags` | Horilla-specific tags and filters (permissions, formatting, `empty_add_message`, etc.) |

Do not re-add `{% load static %}`, `{% load i18n %}`, or `{% load horilla_tags %}` in templates. See [coding_rule.md](../../coding_rule.md#django-templates--built-in-tag-libraries). For shared empty-state markup, see [empty_state.md](../../templates/components/empty_state.md).

## 🔌 REST Framework / JWT

The settings define:
- `DEFAULT_AUTHENTICATION_CLASSES` using `rest_framework_simplejwt.authentication.JWTAuthentication` plus session auth. Basic auth is not enabled, because DRF checks a password before throttles.
- `SIMPLE_JWT["SIGNING_KEY"]` is `SECRET_KEY` after placeholder rejection
- `DEFAULT_PERMISSION_CLASSES` defaults to `IsAuthenticated`
- pagination + throttling rates
- `SIMPLE_JWT` header type configuration
- `SWAGGER_SETTINGS` auto schema class

## 🗄️ Database configuration

It supports two modes:
- If `DATABASE_URL` is set: uses `env.db()`
- Else: uses individual env vars with sqlite defaults (`DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, etc.)

Also sets:
- `CONN_MAX_AGE` based on `DB_CONN_MAX_AGE` (default `60`)

## 🔌 Channels (`CHANNEL_LAYERS`)

`base.py` configures Django Channels for WebSocket / real-time features (notifications, etc.):

```python
CHANNEL_LAYERS = {
    "default": {
        # "BACKEND": "channels.layers.InMemoryChannelLayer",
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        # "CONFIG": {
        #     "hosts": [("127.0.0.1", 6379)],  # Redis server
        # },
    },
}
```

| Backend | When to use |
|---------|-------------|
| **`RedisChannelLayer`** (default in repo) | Production / multi-worker — uncomment `CONFIG["hosts"]` (or set them in `local_settings.py`) |
| **`InMemoryChannelLayer`** (commented) | Local development without Redis, single-process ASGI |

In-memory layers do **not** share messages across processes. For horizontal scaling, keep Redis and set hosts in `local_settings.py` or your deployment overlay rather than editing `base.py` when possible.

Notification create still succeeds if Redis is down: the notifications `post_save` signal logs channel errors instead of failing the save. API tests override `CHANNEL_LAYERS` to the in-memory backend so `manage.py test` does not need Redis.

See also [notifications app — Channels](../contrib/notifications/notifications.md#channels--real-time).

## ✅ Override strategy

Do not edit `base.py` for deployment-specific changes.
Instead:
- put overrides in `horilla/settings/local_settings.py`
- keep `base.py` stable so upgrades are easier
