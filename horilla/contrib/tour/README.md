# Product tour (`horilla.contrib.tour`)

Guided, closable walkthroughs of the CRM screens.

- The shell tour (`app_shell`) **starts by itself once**, the first time each user
  opens Home after logging in. It can be closed at any time (x or Esc).
- After that, any tour starts only when the user asks for it. **Product Tours** in the
  profile dropdown (before Logout) opens a panel that lists the tours for the page you
  are on first, then every other tour. Clicking a card starts it. This is how a tour is
  replayed, from any app.
- **No progress is tracked** (no status, no completion, no resume). The only thing
  remembered is *which tours already started by themselves for a user* (`TourSeen`),
  in the database rather than `localStorage`, which is wiped at logout.

Outside `horilla/contrib/tour/` the app needs the `"horilla.contrib.tour"` entry in
`INSTALLED_APPS` (`horilla/settings/base.py`) and the **Product Tours** item in
`templates/components/header.html`. **Each app owns its own tours** in a
`tour.py` module that it lists in `auto_import_modules`, the same convention as `menu.py`.

## How the pieces fit

| Piece | Where | Role |
|---|---|---|
| Tour definitions | `<app>/tour.py` in each app | Declare that app's tours and steps (today `horilla_crm/leads/tour.py` and `horilla/contrib/dashboard/tour.py`, the Home page only). The one tour that belongs to no app, `app_shell`, lives in this app's own `tour.py`. |
| Registry | `registry.py` | `Tour` / `Step` classes, validation at import time, permission filtering, URL-name matching. |
| Presets | `presets.py` | Ready-made step lists for the screens every CRM app shares: `list_page_steps` and `detail_page_steps`. An app passes its own ids, so adding a CRM app takes a few lines. |
| Launcher | `registration.py` + `templates/tour/slots/launcher.html` | Renders the panel container and the popover and message templates into the framework's `body_end` slot (`horilla.registry.asset_registry.register_html`). |
| Panel | `views.TourPanelView` + `templates/tour/partials/` | HTML fragment loaded into the panel when Product Tours is clicked. |
| Engine | `static/tour/assets/js/tour.js` | Loaded on every page through `js_files`. Runs tours with a vendored [driver.js](https://driverjs.com) (MIT, v1.3.1, `static/tour/assets/vendor/driver/`). |
| Memory | `models.py` | `TourSeen`: one row per user and automatic tour, so it starts by itself only once. |

The app was scaffolded with `python manage.py start_horilla_app`. `admin.py`, `filters.py`,
`forms.py`, `menu.py`, `signals.py`, `__version__.py`, `templatetags/` and `locale/` are
that command's standard (still empty) files; the tour app does not use them yet.

The engine only uses public htmx events (`htmx:afterSettle`), `querySelector`
and `.click()`. It resolves each step's element lazily, so tours survive htmx
swapping `#mainContent`, `#navBar` and `#mainSession`. A step whose element is
missing (no permission, different layout, small screen) is skipped.

## Adding a tour to an app

Create `tour.py` in the app and add `"tour"` to the app's `auto_import_modules`
(in its `apps.py`), exactly as for `menu.py`:

```python
auto_import_modules = ["registration", "menu", "tour"]
```

```python
# horilla_crm/contacts/tour.py
from horilla.contrib.tour.presets import list_page_steps
from horilla.contrib.tour.registry import Tour
from horilla.utils.translation import gettext_lazy as _


class ContactsListTour(Tour):
    key = "contacts_list"                      # unique slug
    title = _("Working with Contacts")
    description = _("Search, filter and act on your contacts.")
    group = _("Contacts")                      # heading in the panel
    order = 210
    match = ("contacts:contacts_view",)        # URL names this tour belongs to
    ready = "#navBar h3"                       # wait for this before step 1
    permission = ["contacts.view_contact", "contacts.view_own_contact"]
    auto_start = False                         # True: start by itself once, on a user's first visit
    steps = list_page_steps(
        view_id="contact-list", create_id="contact-create", record_plural=_("contacts")
    )
```

The presets cover the generic list and detail screens. For a
page of your own, write the `Step` objects directly (see `tour.py` in this app).

Keep the steps next to the templates they point at, so a selector and the markup
it targets change together.

`Tour` attributes: `key`, `title`, `description`, `group`, `order`, `match`,
`open_with`, `ready`, `permission`, `auto_start`,
`steps`. See the docstrings in `registry.py`.

`Step` fields: `title`, `body`, `target` (CSS selector, comma list picks the first
*visible* match; omit for a centred card), `side`, `only_if` (skip at once unless
this is visible), `before` / `after` (click actions, e.g. open and
close a dropdown: `{"click": "#btn", "if_hidden": "#menu"}`).

Use `open_with={"from": "app:list_view", "click": "<selector>"}` for a tour that
lives on a screen reached by a click (the first record, the create form).

## Endpoints (`/tour/`)

| URL | Purpose |
|---|---|
| `GET /tour/?path=` | Panel fragment for the page the browser reports. |
| `GET /tour/current/?path=` | Resolve the page to a URL name and say which tour, if any, should start by itself. |
| `GET /tour/definition/<key>/` | One tour's steps and the UI labels (JSON). |
| `POST /tour/seen/` | Remember `{key}` as already started for the user (idempotent). |

## Tests

```bash
python manage.py test horilla.contrib.tour
```

## Known limits

- Steps use existing ids and CSS selectors, so a later template change can break a
  step. The engine skips a missing target instead of failing. The most fragile
  selectors are the positional ones (first row, row actions, form save button).
- The "Product Tours" item sits in the header profile dropdown, before Logout
  (`templates/components/header.html`). The panel opens at the top right, under the header.
- To enable the screen walkthrough for another CRM app, add a `tour.py` to that app
  (and `"tour"` to its `auto_import_modules`) with its `view_id` and create-button id
  (see `horilla_crm/leads/tour.py`).
