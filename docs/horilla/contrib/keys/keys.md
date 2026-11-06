# Horilla Keys app — deep dive (`horilla.contrib.keys`)

## What this app does

- **`ShortcutKey`** persistence: per-user keybinding to navigate to a path or named URL (modifier + key).
- Ships **`keys/assets/js/short_key.js`** via `AppLauncher.js_files` so the browser listens for shortcuts globally.
- **Bootstraps default shortcuts** for every new **`User`** in `signals.py` (`post_save`, `created=True`).
- **REST API** at `keys/` for CRUD on user shortcuts from settings UI.

---

## App startup (`apps.py`)

`KeysConfig`:

| Setting | Value |
|---------|--------|
| `name` | `horilla.contrib.keys` |
| `label` | `keys` |
| `verbose_name` | Keyboard Shortcuts |
| `js_files` | `keys/assets/js/short_key.js` |
| `url_prefix` | `shortkeys/` |
| `url_namespace` | `keys` |
| `auto_import_modules` | `menu`, `signals` |
| API | `keys/` → `horilla.contrib.keys.api.urls` |

Note: HTTP paths use **`shortkeys/`** while API pattern is `keys/`—do not confuse when reverse-engineering routes.

---

## Signals (`signals.py`) — default shortcut matrix

### `DEFAULT_SHORTCUTS`

Static list of `{page, key, command}` entries always inserted for a new user—for example:

- `/` + `H` + `alt`
- `/my-profile-view/` + `P` + `alt`
- `/shortkeys/short-key-view/` + `K` + `alt`
- …

### `OPTIONAL_APP_SHORTCUTS`

Entries may specify:

- **`app`** — if that string is **not** in `INSTALLED_APPS`, the shortcut is skipped (keeps optional contrib apps from breaking URL reverse).
- **`url_name`** — resolved with `reverse_lazy` to populate `page`, or explicit **`page`** path.

Examples in code: dashboard (`D`), reports (`R`), calendar (`I`), activity (`Y`).

### `create_all_default_shortcuts`

- `@receiver(post_save, sender=User)` — only when **`created`**.
- Bulk-creates **`ShortcutKey`** rows after merging predefined + optional lists (`_resolve_shortcut_page`).

For uniqueness rules and conflict handling, see [default_shortcut_registration.md](default_shortcut_registration.md).

---

## Menu (`menu.py`)

`ShortKeySettings` is registered with `@my_settings_menu.register`:

| Attribute | Value |
|-----------|-------|
| `title` | `_("Short Keys")` |
| `url` | `reverse_lazy("keys:short_key_view")` |
| `active_urls` | `["keys:short_key_view"]` |
| `order` | `6` |
| `perm` | `["keys.view_shortcutkey", "keys.view_own_shortcutkey"]` |

The `perm` attribute uses **any-of** semantics (`has_any_perms`): the menu entry is visible when the user holds **either** `view_shortcutkey` **or** `view_own_shortcutkey`. Users without either permission do not see the entry in the My Settings sidebar.

---

## View permissions (`views.py`)

`ShortKeyView` uses the shared [My Settings list shell](../../horilla/contrib/core/settings_list_shell.md#my-settings-list-shell-my_settings_list_shellhtml):

```python
class ShortKeyView(LoginRequiredMixin, HorillaView):
    template_name = "settings/my_settings_list_shell.html"
    view_id = "short-key-view"
    nav_url = reverse_lazy("keys:short_key_nav")
    list_url = reverse_lazy("keys:short_key_list")
```

`ShortKeyView` is protected at the dispatch level:

```python
@method_decorator(
    permission_required_or_denied(
        ["keys.view_shortcutkey", "keys.view_own_shortcutkey"]
    ),
    name="dispatch",
)
class ShortKeyView(View):
    ...
```

Any request from a user who lacks both `view_shortcutkey` and `view_own_shortcutkey` is denied (HTTP 403) before the view body runs. This mirrors the menu-level `perm` filter so the two layers stay consistent.

`ShortKeyListView` exposes the user's keys as a queryset property and does not override `get_queryset`, so the base list view applies search, filters and sorting. `ShortKeyFilter.filter_search` matches the stored page path, the displayed page title, the key and the command.

---

## Models (`models.py`)

Read **`ShortcutKey`** for:

- FK to user, stored path, key character, modifier (`alt`, `ctrl`, …), active flag, ordering.

---

## Typical flows

1. New employee account created → defaults inserted → JS hotkey navigates immediately.
2. User opens **Keyboard shortcuts** settings → HTMX table bound to API → PATCH updates row.
3. Optional app uninstalled → optional shortcuts skipped at user creation time.

---

## Related documentation

- Step-by-step extension guide for other apps: [default_shortcut_registration.md](default_shortcut_registration.md)
- My Settings list shell: [../core/settings_list_shell.md](../core/settings_list_shell.md#my-settings-list-shell-my_settings_list_shellhtml)
