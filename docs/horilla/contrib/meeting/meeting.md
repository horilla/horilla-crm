# Horilla Meeting Integration app — deep dive (`horilla.contrib.meeting`)

## What this app does

- Provides a **Meeting Integration** layer so users can generate video-conference links (Zoom, Google Meet, Microsoft Teams) directly from the CRM.
- Stores a per-company **enable/disable** toggle and **access-control** settings (all users, specific roles, or specific users).
- Holds per-user **OAuth credentials** for Zoom and Microsoft Teams; reuses Google Calendar OAuth for Google Meet.
- Surfaces under **Settings → Integrations** (admin) and **My Settings → Meeting** (end-user).

---

## App startup (`apps.py`)

`MeetingConfig` (`AppLauncher`):

| Setting | Value |
|---------|--------|
| `url_prefix` | `meeting/` |
| `url_namespace` | `meeting` |
| `auto_import_modules` | `menu`, `signals` |

`signals.py` is imported at startup but currently contains **no receivers** (reserved for future hooks).

---

## Menu (`menu.py`)

Two registration points:

- **Settings → Integrations** — `IntegrationsSettings.items.append(...)` adds a **Meeting Integration** item that loads `meeting:meeting_integration_settings` into `#settings-content` via HTMX. Guarded by `perm = "meeting.change_meetingintegrationsetting"`.
- **My Settings sidebar** — `@my_settings_menu.register` class `MeetingUserSettings` at `order = 6`. Its `condition = staticmethod(MeetingIntegrationSetting.user_has_menu_access)` hides the entry entirely when the integration is disabled or the user has no access.

---

## Models (`models.py`)

All models extend **`HorillaCoreModel`** (company FK, audit fields, `is_active`).

### Provider and access choices

Three providers (`zoom`, `google_meet`, `ms_teams`) and three access modes (`all`, `roles`, `users`) are defined as module-level constants and choice tuples.

### `MeetingIntegrationSetting`

Company-level singleton (one row per company) that controls the integration globally.

- **`is_enabled`** — master on/off switch.
- **`access_type`** — who can use the integration (`all` / `roles` / `users`).
- **`allowed_roles`** M2M → `Role`, **`allowed_users`** M2M → `AUTH_USER_MODEL` — active when the matching access type is selected.

Key class methods:

- **`get_for_company(company)`** — `get_or_create`; always returns a row (invalidates cache when a new row is created).
- **`user_has_access(user)`** / **`user_can_access(user, company)`** — evaluate enabled state + access rule.
- **`meeting_enabled(request)`** / **`user_has_menu_access(request)`** — used as menu conditions; resolve company from `_thread_local.request`.

Lookups use request-local cache plus the [per-company settings cache](../utils/company_settings_cache.md) (`CACHE_NAMESPACE = "meeting.integration"`). `save` / `delete` invalidate the entry.

### `UserMeetingConfig`

Per-user, per-provider personal room URL. `unique_together = ("user", "provider", "company")`. Currently used for **Google Meet** — presence of a row means the user has opted in.

### `ZoomOAuthConfig`

One-to-one with `AUTH_USER_MODEL`. Stores `client_id`, `client_secret`, `token` (JSONField), `oauth_state`, and `connected_email`. `has_credentials()` / `is_connected()` used by views and OAuth helpers.

### `MicrosoftTeamsOAuthConfig`

Same shape as `ZoomOAuthConfig` plus `tenant_id` (Azure AD tenant or `"common"`). `has_credentials()` requires all three credential fields.

---

## Forms (`forms.py`)

| Form | Purpose |
|------|---------|
| `MeetingIntegrationSettingForm` | Admin — `access_type`, `allowed_roles`, `allowed_users` with checkbox widgets |
| `MeetingAccessRolesForm` | Modal — Select2 multi-select for roles (plain `forms.Form`, strips `HorillaSingleFormView` kwargs) |
| `MeetingAccessUsersForm` | Modal — Select2 multi-select for users (plain `forms.Form`) |
| `UserMeetingConfigForm` | Per-user personal room URL per provider |
`_pop_single_form_view_kwargs()` strips extra kwargs injected by `HorillaSingleFormView.get_form_kwargs()` before calling `super().__init__()`.

---

## Views (`views.py`)

### Admin views (Settings → Integrations)

**`MeetingIntegrationSettingsView`** — permission-gated (`meeting.change_meetingintegrationsetting`). GET renders the toggle + access panel. POST handles two paths: `is_meeting_enabled=true/false` toggles the integration (disabling clears **all** OAuth credentials for every company user via `_clear_meeting_credentials()`); `access_type=all` immediately sets open access.

**`MeetingAccessRolesView`** / **`MeetingAccessUsersView`** — both extend `HorillaSingleFormView`. On `form_valid`: update `access_type`, sync the M2M, find users losing access, and call `_clear_meeting_credentials()` on them. Return `<script>closeModal(); location.reload();</script>`.

### User / My Settings view

**`MeetingAllowedUsersListView`** / **`MeetingAllowedRolesListView`** — `@method_decorator(htmx_required)` so the allowed-users/roles pickers only render as HTMX fragments (not as full-page navigations).

**`MeetingUserSettingsView`** — GET builds provider cards via `_build_provider_cards()` (Zoom, Google Meet, Teams) when the user has access. When meeting integration is off, the page shows `components/empty_state.html` with `feature_disabled=True`. POST dispatches on `provider` + `action`:

| Provider | Action | Effect |
|----------|--------|--------|
| `zoom` | `save_credentials` | Upsert `client_id` / `client_secret` in `ZoomOAuthConfig` |
| `zoom` | `disconnect` | Clear `token` + `connected_email` |
| `google_meet` | `enable` | Create `UserMeetingConfig` (requires Google Calendar already connected) |
| `google_meet` | `disable` | Delete `UserMeetingConfig` for current company |
| `ms_teams` | `save_credentials` | Upsert credentials + `tenant_id` in `MicrosoftTeamsOAuthConfig` |
| `ms_teams` | `disconnect` | Clear `token` + `connected_email` |

### Link generation

**`GenerateMeetingLinkView`** — POST only, called via `fetch()` from the activity form. Returns `{"url": "..."}` or `{"error": "..."}`.

| Provider | Mechanism |
|----------|-----------|
| `zoom` | `oauth.zoom.create_meeting()` → Zoom REST API |
| `ms_teams` | `oauth.teams.create_meeting()` → Microsoft Graph API |
| `google_meet` | (Offered in activity forms only when `UserMeetingConfig` for `google_meet` exists.) Creates a throwaway Google Calendar event with `conferenceDataVersion=1`, extracts `hangoutLink`, then deletes the event |

### OAuth views

`ZoomAuthorizeView` / `ZoomCallbackView` and `TeamsAuthorizeView` / `TeamsCallbackView` each redirect to the provider consent screen and handle the code-exchange callback. All delegates to the helpers in `oauth/`.

Authorize views return the provider URL with **`HttpResponseRedirect`** from **`horilla.web`** (not `django.http`). Callback views and permission-denied paths use **`horilla.shortcuts.redirect`**.

---

## OAuth helpers (`oauth/`)

### `oauth/zoom.py`

`start_oauth(request)` → builds Zoom authorization URL, saves CSRF state to `ZoomOAuthConfig`. `handle_callback(request)` → verifies state, exchanges code for token via `requests_oauthlib`, fetches `/users/me` for email. `create_meeting(config, title, start, end)` → POSTs to `api.zoom.us/v2/users/me/meetings`, returns `join_url` (or structured error details when Zoom rejects the request). Includes `token_updater` callback for auto-refresh.

**Scopes** (`ZOOM_SCOPES`): `meeting:write:meeting`, `user:read:user`.

**Redirect URI** is built by `_get_redirect_uri(request)` so setup instructions and the OAuth client use the same absolute callback URL as the live request (avoids mismatched redirect URI configuration in the Zoom app).

### `oauth/teams.py`

Same pattern. `start_oauth` builds a tenant-aware MS authorization URL (`login.microsoftonline.com/{tenant}/...`). `create_meeting` POSTs to `graph.microsoft.com/v1.0/me/onlineMeetings`. Required scopes: `OnlineMeetings.ReadWrite`, `User.Read`, `offline_access`.

Guest / connected email display prefers Graph `mail`, then `otherMails`, then UPN, stored on `connected_email`. Real Graph error payloads are surfaced to the caller instead of a generic failure string.

> **Note:** Teams meeting creation requires a **Microsoft 365 work or school account** with a Teams license. Personal Microsoft accounts receive `403`.

---

## Typical flows

1. **Admin enables the integration:** Settings → Integrations → Meeting Integration → toggle on → choose access type → save roles or users via modal.
2. **User connects Zoom:** My Settings → Meeting → enter Client ID + Secret → Save → click Connect → Zoom consent → callback stores token.
3. **User generates a meeting from an activity:** Activity form calls `POST meeting/generate-link/` → receives `{"url": "..."}` → pre-fills the meeting URL field.
4. **Admin disables the integration:** Toggle off → all Zoom, Teams, and `UserMeetingConfig` rows for every company user are deleted.
5. **Google Meet:** User connects Google Calendar first (My Settings → Google Calendar). Then My Settings → Meeting → Google Meet → Enable creates a `UserMeetingConfig` row. Link generation uses a throwaway calendar event to obtain the `hangoutLink`.

---

## Related documentation

- Core models and `HorillaCoreModel`: [../core/models.md](../core/models.md)
- Calendar integration (Google OAuth reuse): [../calendar/calendar.md](../calendar/calendar.md)
- Activity app (meeting links used in activities): [../activity/activity.md](../activity/activity.md)
- My Settings menu: [../../menu/my_settings_menu.md](../../menu/my_settings_menu.md)
- Single form view pattern: [../generics/views/single_form.md](../generics/views/single_form.md)
