# Mobile (`horilla.contrib.mobile`)

**Package:** `horilla.contrib.mobile` (installed as `"horilla.contrib.mobile"`)
**Current version:** see [`__version__.py`](../../../../horilla/contrib/mobile/__version__.py)
**URL prefix:** `/m/` · namespace `mobile`

An optional, installable phone mode for short on-the-go work: looking up a
record, logging an activity, checking the day. It is built with Django
templates and HTMX and reuses the existing models, forms, permissions and
company scoping. The desktop app is unchanged; configuration, reports,
dashboards, automations, bulk actions and kanban stay there, and every mobile
page links back to the full version.

This document covers the **shell**: layout, login and logout, the web app
manifest and the service worker. The pages themselves (record page, Records,
log activity, Today, Agenda) are added on top of it.

Background and scope: [horilla/horilla-crm#69](https://github.com/horilla/horilla-crm/issues/69).

---

## Turning it on

The app is **off by default**: it is not in the default `INSTALLED_APPS`, so an
install that doesn't opt in serves nothing under `/m/` and never registers a
service worker. To turn it on, add one line to `horilla/settings/local_settings.py`:

```python
from horilla.settings.base import INSTALLED_APPS

INSTALLED_APPS += ["horilla.contrib.mobile"]
```

The app has no models and no migrations. Removing the line turns it off again;
browsers that installed the app keep the worker until its next update check,
which then fails because `/m/sw.js` no longer exists (see
[Service worker](#service-worker)).

Open `/m/` on a phone and use the browser's **Add to Home Screen** (iOS Safari:
Share → Add to Home Screen; Android Chrome: menu → Install app).

---

## App startup (`apps.py`)

`MobileConfig` (`AppLauncher`):

| Setting | Value |
|---------|-------|
| `name` | `horilla.contrib.mobile` |
| `label` | `mobile` |
| `url_prefix` | `m/` |
| `url_namespace` | `mobile` |
| `auto_import_modules` | `registration` |

`registration.py` registers the core RTL assets (`inject_html/rtl_assets.html`)
for the mobile page, the same fragment the desktop layout and login page get.

---

## URLs (`urls.py`)

| URL | Name | View | Access |
|-----|------|------|--------|
| `/m/` | `mobile:home` | `MobileHomeView` (redirects to the first page) | signed in |
| `/m/login/` | `mobile:login` | `MobileLoginView` | public |
| `/m/logout/` | `mobile:logout` | `MobileLogoutView` | any |
| `/m/more/` | `mobile:more` | `MobileMoreView` | signed in |
| `/m/manifest.webmanifest` | `mobile:manifest` | `ManifestView` | public |
| `/m/sw.js` | `mobile:service_worker` | `ServiceWorkerView` | public |

Signed-out visitors of a mobile page are sent to `/m/login/?next=…`
(`MobileLoginRequiredMixin`), not to the desktop login.

---

## Login and logout

The phone login does **not** reimplement authentication. `MobileLoginView`
subclasses the desktop `LoginUserView` and only changes three class attributes:

| Attribute | Desktop (`LoginUserView`) | Mobile (`MobileLoginView`) |
|-----------|---------------------------|----------------------------|
| `template_name` | `login.html` | `mobile/login.html` |
| `login_url_name` (where failed attempts return) | `core:login` | `mobile:login` |
| `default_next_url` (where a login without `next` goes) | `/` | `/m/` |

Brute-force lockout, inactive-user handling, messages and `safe_url` checks
therefore stay in one place. A signed-in user who opens `/m/login/` goes
straight to `/m/`.

`MobileLogoutView` subclasses `LogoutView` and sets `redirect_url` to
`/m/login/`, so the `pre_logout_signal` receivers and the local-storage cleanup
are shared with the desktop.

Password reset and first-run database setup are not repeated on the phone: the
login page links to the desktop login for both.

---

## Layout

| Template | Role |
|----------|------|
| `mobile/skeleton.html` | `<html>`/`<head>`/`<body>`: language and direction, theme (same `localStorage` `theme` and `body.dark` as the desktop), manifest and icon links, Tailwind/HTMX/Font Awesome and the desktop stylesheets, messages, service-worker registration |
| `mobile/base.html` | Page header, content area and bottom navigation (safe-area insets for notched phones) |
| `mobile/login.html` | Sign-in form (extends the skeleton, no navigation) |
| `mobile/more.html` | Account page: user and active company, language switch (Django `set_language`), **Open full version**, **Log out** |

**Injection slots.** The skeleton calls `load_registered_html` with
`page="mobile"` for `head_start`, `head_end`, `body_start` and `body_end`, so
any app can add fragments to the phone layout without touching it:

```python
from horilla.registry.asset_registry import register_html

register_html("my_app/mobile_head.html", slot="head_end", page="mobile")
```

Desktop JS registered with `js_files` is **not** loaded on mobile pages.

**Bottom navigation.** `navigation.NAV_ITEMS` lists the mobile pages in display
order; `MobilePageMixin` adds them to the context. The bar is hidden while
there is only one page.

**RTL and translations.** Templates use `{% trans %}` and `LANGUAGE_BIDI`
like the rest of the app; Persian strings live in
`horilla/contrib/mobile/locale/fa/LC_MESSAGES/django.po`.

---

## Web app manifest

`ManifestView` returns `application/manifest+json`:

| Key | Value |
|-----|-------|
| `name`, `short_name` | branding `TITLE` (`horilla.utils.branding.load_branding`) |
| `id`, `start_url`, `scope` | `/m/` |
| `display` | `standalone` |
| `lang`, `dir` | the active language and its direction |
| `icons` | `static/favicons/android-chrome-192x192.png` and `-512x512.png` |

It is public on purpose: browsers fetch the manifest without cookies. It only
contains branding, language and the app's own URLs.

---

## Service worker

**Scope.** The worker is served by a view at `/m/sw.js` instead of from
`/static/`. A worker's default scope is the folder it is served from, so this
one controls `/m/` only. Desktop pages are never behind it, even for someone
who opened `/m/` before. The view sends no `Service-Worker-Allowed` header, so
the scope can't be widened. It is registered only from `mobile/skeleton.html`.

**What it caches.** Only `GET` requests for files under `STATIC_URL` whose
`v` query parameter equals the current asset version, and that carry no
`Authorization` header. Everything else (all HTML and HTMX responses, form
posts, media, anything sent with credentials in a header) goes to the network
untouched, so a deploy shows up immediately.

**Asset version.** `utils.get_asset_version()` is
`"<platform version>-<mobile version>"`. Mobile templates build static URLs
with the `{% mobile_static %}` tag (`templatetags/mobile_tags.py`), which
appends `?v=<asset version>`:

```django
{% load mobile_tags %}
<script src="{% mobile_static 'assets/js/htmx/htmx.min.js' %}"></script>
```

The default `STATICFILES_STORAGE` doesn't hash file names, so the version stamp
is what keeps a new release from being served old files: a release changes
the stamp, the worker script changes with it, the browser installs the new
worker, and its `activate` handler deletes every older `horilla-mobile-*`
cache.

Static files changed **between** releases keep the old stamp. Bump
`horilla/contrib/mobile/__version__.py` when shipping such a change.

**Updates.** `/m/sw.js` is sent with `Cache-Control: no-cache`, so browsers
check for a new worker on every navigation. The new worker takes over at once
(`skipWaiting` + `clients.claim`).

**DEBUG.** With `DEBUG = True` the worker caches nothing, so local edits to
static files show up without clearing site data.

**Turning the app off.** When `/m/sw.js` starts returning 404, browsers
unregister the worker on their next update check.

---

## Tests

`horilla/contrib/mobile/tests/` runs only when the app is installed (the
classes are skipped otherwise). Run them with a settings module that adds the
app, e.g.:

```bash
python manage.py test horilla.contrib.mobile
```

with `horilla.contrib.mobile` in `INSTALLED_APPS` (see
[Turning it on](#turning-it-on)). They cover the mobile login and logout
(templates, redirects, failed attempts), the login requirement on mobile
pages, the layout (manifest link, worker registration and scope, versioned
static URLs), the manifest, and the worker (content type, `no-cache`, no
scope-widening header, no redirect for signed-in users, cache name, `DEBUG`
switch).

`horilla/contrib/core/tests.py` (`LoginLogoutPageDefaultsTests`) checks that
the desktop login and logout keep their own template and URLs.
