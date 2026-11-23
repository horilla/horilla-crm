# Horilla context processors (`horilla.context_processors`)

## Purpose

`horilla/context_processors.py` defines Django **template context processors** that inject shared data into every template render: companies, language picker data, recently viewed records, notifications, navigation menus, multi-currency defaults, and branding.

Processors are plain callables: `(request) -> dict`. Each returned dict is merged into the template context.

---

## Module location

```text
horilla/
└── context_processors.py   # company_list, allowed_languages, …, branding
```

---

## Registration

They are wired in **`horilla/settings/base.py`** via `CONTEXT_PROCESSORS`, which is passed into `TEMPLATES[0]["OPTIONS"]["context_processors"]`.

Order (after Django’s `request`, `auth`, and `messages`):

1. `horilla.context_processors.company_list`
2. `horilla.context_processors.allowed_languages`
3. `horilla.context_processors.recently_viewed_items`
4. `horilla.context_processors.unread_notifications`
5. `horilla.context_processors.menu_context_processor`
6. `horilla.context_processors.currency_context`
7. `horilla.context_processors.branding`

---

## Processors and template variables

### `company_list`

| Context key | Type / notes |
|-------------|----------------|
| `available_companies` | List of `Company` rows from Django cache (`available_companies` key, 300s), loaded via `Company.objects.all()` on miss. |

Invalidated when companies change (see `horilla.contrib.core.signals`).

---

### `allowed_languages`

Builds the language switcher list from **`settings.ALLOWED_LANGUAGES`**.

Each entry in `ALLOWED_LANGUAGES` must be a **3-tuple**: `(code, name, flag)` where `flag` is a static asset filename (for example `"usa.webp"`).

| Context key | Type / notes |
|-------------|----------------|
| `allowed_languages` | List of dicts: `code`, `name`, `flag`, `active` (`active` is `True` when `code` matches `get_language()`). |

---

### `recently_viewed_items`

Only runs for **authenticated** users.

| Context key | Type / notes |
|-------------|----------------|
| `recently_viewed_items` | Up to **6** `RecentlyViewed` rows, newest first. Rows whose `content_object` is missing or broken are skipped; broken rows are **deleted**. |

Unauthenticated requests receive an **empty** dict (no key).

---

### `unread_notifications`

Only for **authenticated** users.

| Context key | Type / notes |
|-------------|----------------|
| `unread_notifications` | Queryset: `Notification` for the user with `read=False`, ordered by `-created_at`. |
| `notification_sound_muted` | Boolean from `NotificationSoundPreference`; `False` if no preference row exists. |

Unauthenticated: empty dict.

---

### `menu_context_processor`

| Context key | Type / notes |
|-------------|----------------|
| `main_section_menu` | From `horilla.menu.main_section_menu.get_main_section_menu`. |
| `sub_section_menu` | From `horilla.menu.sub_section_menu.get_sub_section_menu`. |
| `settings_menu` | From `horilla.menu.settings_menu.get_settings_menu`. |
| `floating_menu` | From `horilla.menu.floating_menu.get_floating_menu`. |
| `my_settings_menu` | From `horilla.menu.my_settings_menu.get_my_settings_menu`. |
| `header_menu` | From `horilla.menu.header_menu.get_header_menu`. One class is one account-dropdown link (`title`, `url`). Extra HTML attributes live in `attrs`. See [header menu](menu/header_menu.md). |
| `current_section` | `request.GET.get("section")` (URL query). |
| `current_app_label` | `request.resolver_match.app_name` if a URL resolved, else `None`. |

Menu item **`condition`** callables often load company-scoped settings (calendar / meeting / calls integration, opportunity team selling, etc.). Those lookups should use the [per-company settings cache](contrib/utils/company_settings_cache.md) so full-page renders do not hit those tables every time.

---

### `currency_context`

Only for **authenticated** users. Imports **`MultipleCurrency`** inside the function (lazy import) to avoid circular import issues at startup.

| Context key | Type / notes |
|-------------|----------------|
| `user_currency` | From `request.user.currency`, else company default. |
| `default_currency` | From `MultipleCurrency.get_default_currency(company)` — **cached per company** (`core.default_currency` namespace via [company_settings_cache](contrib/utils/company_settings_cache.md)). |

Unauthenticated: empty dict.

---

### `branding`

Returns the dict from **`horilla.utils.branding.load_branding()`** as the processor return value, so its keys are merged **at the top level** of the template context (not under a single nested key).

Typical keys (defaults in `horilla.utils.branding.DEFAULTS`; override via **`settings.BRANDING_MODULE`**):

- `TITLE`, `LOGIN_WELCOME_LINE`, `LOGIN_TAG_LINE`, `SIGNUP_TAG_LINE`
- `LOGO_PATH`, `FAVICON_PATH`, `PAGE_HEADER`

---

## Dependencies (imports)

| Area | Module / model |
|------|----------------|
| Menus | `horilla.menu.*` getters |
| Branding | `horilla.utils.branding.load_branding` |
| Core | `Company`, `RecentlyViewed`; `currency_context` uses `MultipleCurrency` |
| Notifications | `Notification`, `NotificationSoundPreference` |

---

## Usage in templates

After registration, any template can read the keys above without each view passing them explicitly—for example `{{ user_currency }}`, `{{ allowed_languages }}`, or branding fields like `{{ TITLE }}` (exact keys depend on `load_branding()` / overrides).

Python code that sends transactional email without a company context (activity meeting reminders/invites, booking confirmation/status mail) also uses `str(load_branding()["TITLE"])` as the fallback display name in templates.

---

## Adding or changing behavior

- **New global context:** add a function in `horilla/context_processors.py` and append its dotted path to **`CONTEXT_PROCESSORS`** in `horilla/settings/base.py` (order can matter if one processor depends on middleware-populated `request` attributes).
- **Performance:** processors run on **every** template render; keep queries cheap or cached where possible. Prefer [company_settings_cache](contrib/utils/company_settings_cache.md) for company-scoped settings used by menus or currency.
