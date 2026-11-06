# Horilla Calls Integration app — deep dive (`calls`)

## What this app does

- Provides a **Telephony Integration** layer so CRM agents can make outbound calls directly from any Lead, Contact, or Account record.
- Manages multiple **telephony providers** per company (Twilio, SignalWire, Telnyx, Sinch, Exotel, and a Mock provider for testing).
- Records every call — inbound and outbound — as a **CallLog**, automatically linked to the related CRM object and surfaced in the History tab via an Activity record.
- EStoresxposes a **Click-to-Call** modal with real-time status polling (HTMX, 3-second interval) and a cancel-call flow.
- Stores per-company **enable/disable** and **access-control** settings (all users, specific roles, or specific users).
- Maps CRM users to their telephony **agent credentials** per provider via `AgentMapping`.
- Provides an extensible **adapter pattern** — adding a new provider means subclassing `BaseCallAdapter` with no changes to the service layer.

---

## App startup (`apps.py`)

`CallsConfig` (`AppLauncher`):

| Setting | Value |
|---------|--------|
| `url_prefix` | `calls/` |
| `url_namespace` | `calls` |
| `auto_import_modules` | `menu`, `signals`, `registration`, `extensions` |
| API paths | `calls/` → `calls.api.urls` (namespace `horilla_calls`) |

---

## Menu (`menu.py`)

Two registration points:

- **Settings → Integrations** — `IntegrationsSettings.items.append(...)` adds a **Call Integration** item that loads `calls:integration_settings` into `#settings-content` via HTMX. Guarded by `perm = "calls.change_callintegrationsetting"`.
- **My Settings sidebar** — `@my_settings_menu.register` class `CallsUserSettings` at `order = 7`. Its `condition = staticmethod(CallIntegrationSetting.user_has_menu_access)` hides the entry entirely when the integration is disabled or the user has no access.

## Extensions (`extensions.py`)

**`CallListActionsExtension`** (`MixinExtension` on `CallListView`) prepends the
**Call Now** action to the activity call tab's action list, replacing the earlier
shared action-list monkey patch. **`ActivityCallExtension`** (`_inherit_model` on
`Activity`) adds `get_call_now_url()`.

---

## Models (`models.py`)

All models extend **`HorillaCoreModel`** (company FK, audit fields, `is_active`).

### `CallIntegrationSetting`

Company-level singleton (one row per company) that controls the integration globally.

- **`is_enabled`** — master on/off switch.
- **`access_type`** — who can initiate calls (`all` / `roles` / `users`).
- **`allowed_roles`** M2M → `Role`, **`allowed_users`** M2M → `AUTH_USER_MODEL` — active when the matching access type is selected.

Key class methods:

- **`get_for_company(company)`** — `get_or_create`; always returns a row (invalidates cache when a new row is created).
- **`user_has_access(user)`** — evaluates enabled state + access rule.
- **`user_can_access(user, company)`** — class method wrapper used by views and menu conditions.
- **`calls_enabled(request)`** / **`user_has_menu_access(request)`** — menu conditions; resolve company from `_thread_local.request`.

Lookups use request-local cache plus the [per-company settings cache](../utils/company_settings_cache.md) (`CACHE_NAMESPACE = "calls.integration"`). `save` / `delete` invalidate the entry.

### `CallProvider`

Registry of telephony provider configurations per company. Each row is one configured provider instance.

| Field | Purpose |
|-------|---------|
| `name` | Human-readable label |
| `provider_type` | `twilio`, `signalwire`, `telnyx`, `sinch`, `exotel`, `mock` |
| `status` | `active`, `inactive`, `testing` |
| `account_sid` | Encrypted — AccountSID / App ID |
| `api_key` | Encrypted |
| `api_secret` | Encrypted — Auth Token |
| `api_base_url` | Optional URL override for custom endpoints |
| `caller_id` | Default outbound phone number / SIP Caller ID |
| `recording_enabled` | Toggle call recording |
| `webhook_secret` | Encrypted — validates incoming webhook signatures |
| `extra_config` | JSONField for provider-specific extra settings |

Methods: `get_edit_url()`, `get_delete_url()`, `get_test_url()`, `status_col()` (renders inline status dropdown template).

### `AgentMapping`

Maps a CRM user to their telephony agent credentials for a given provider.

| Field | Purpose |
|-------|---------|
| `provider` | FK → `CallProvider` |
| `user` | FK → `AUTH_USER_MODEL` |
| `extension` | SIP extension or internal number |
| `agent_id` | Provider-internal agent / caller identifier |

- `unique_together = [("provider", "user")]`
- `OWNER_FIELDS = ["user"]` — row-level access via four-layer permission model.

### `CallLog`

CRM-side record of every telephony call — outbound or inbound.

| Field | Purpose |
|-------|---------|
| `provider` | FK → `CallProvider` (SET_NULL on delete) |
| `agent` | FK → `AgentMapping` (SET_NULL on delete) |
| `direction` | `inbound` / `outbound` |
| `status` | See status lifecycle below |
| `from_number` / `to_number` | E.164 phone numbers |
| `duration_seconds` | `None` until call ends |
| `started_at` / `ended_at` | Timestamps |
| `provider_call_id` | Twilio CallSID, Telnyx call_control_id, etc. (indexed) |
| `recording_url` | URL to call recording (nullable) |
| `related_model_name` | `"lead"`, `"contact"`, etc. |
| `related_object_id` | PK of the related object |

**Status lifecycle:**

```
initiated → ringing → in_progress → completed
                    ↘ no_answer
                    ↘ busy
                    ↘ failed
                    ↘ cancelled
```

Terminal statuses: `completed`, `no_answer`, `busy`, `failed`, `cancelled`.

**Key indexes:** `provider_call_id`, `status`, `from_number`, `to_number`, `started_at`, `(company, started_at)`, `(company, status)`.

Key methods:

- **`get_duration_display()`** — returns `"MM:SS"` string or `"—"` if no duration.
- **`get_related_object()`** — resolves the related CRM object using `_CALLABLE_MODEL_REGISTRY` first, then falls back to a generic `ContentType` lookup.
- **`get_delete_url()`** — returns `calls:call_log_delete` URL.

---

## Adapter pattern (`adapters/`)

### `BaseCallAdapter` (`adapters/base.py`)

Abstract base class every provider adapter must implement.

| Method | Required | Purpose |
|--------|----------|---------|
| `initiate_call(from_number, to_number, callback_url, **kwargs)` | Yes | Start outbound call. Returns `{"call_id": str, "status": str}`. Raises on failure. |
| `validate_webhook(request)` | Yes | Validate incoming webhook signature. Returns `bool`. Never raises. |
| `parse_webhook_payload(request)` | Yes | Normalise provider POST to canonical dict (see below). |
| `cancel_call(provider_call_id)` | No | Cancel a ringing or in-progress call. |
| `fetch_status(provider_call_id)` | No | Fetch live call status from provider API. Returns canonical status string or `None`. |
| `test_connection()` | No | Returns `{"success": True}` or `{"success": False, "error": str}`. |
| `get_agent_for_user(user)` | No | Returns `AgentMapping` for this provider + user, or `None`. |

**Canonical webhook dict:**
```python
{
    "call_id":       str,
    "direction":     "inbound" | "outbound",
    "status":        str,   # CallLog.STATUS_* constant
    "from_number":   str,
    "to_number":     str,
    "duration":      int | None,
    "recording_url": str | None,
}
```

Credentials stored via `EncryptedCharField` are decrypted via `_decrypt()` / `self._val(field_name)` inside adapters — never access raw field values directly.

### Provider adapters

| File | Provider | Notes |
|------|----------|-------|
| `twilio_adapter.py` | Twilio | Uses TwiML `<Dial>` for bridging; returns TwiML URL during initiation |
| `signalwire_adapter.py` | SignalWire | Compatible with Twilio API; shares TwiML flow |
| `telnyx_adapter.py` | Telnyx (Beta) | Uses `call_control_id` as `provider_call_id` |
| `sinch_adapter.py` | Sinch (Beta) | |
| `exotel_adapter.py` | Exotel (Beta) | Bridges via agent's phone (uses `agent_id` as from_number) |
| `mock_adapter.py` | Mock (Testing) | In-memory; excluded from Settings provider cards |

### `factory.py`

`get_adapter(provider: CallProvider) -> BaseCallAdapter` — maps `provider.provider_type` to the concrete adapter class and returns an instance.

---

## Views (`views/`)

### Admin views (`views/core.py`) — Settings → Integrations

**`CallIntegrationSettingsView`** — permission-gated (`calls.change_callintegrationsetting`). GET renders the enable/disable toggle + access control panel. POST handles:
- `is_calls_enabled=true/false` — toggles the integration.
- Access type and role/user updates via sub-views.

**`CallAccessRolesView`** / **`CallAccessUsersView`** — both extend `HorillaSingleFormView`. On `form_valid`: update `access_type`, sync the M2M, return `<script>closeModal(); location.reload();</script>`.

**`CallAccessRolesDetailView`** / **`CallAccessUsersDetailView`** — read-only panels listing currently allowed roles/users.

**`CallSettingsTabView`** / **`CallAccessControlTabContent`** / **`CallProvidersTabContent`** — tabbed settings layout via `HorillaTabView`.

### Provider management views (`views/provider.py`)

**`CallProviderListView`** — HTMX list of configured providers (columns: name, type, status, test).

**`CallProviderFieldsView`** — returns provider-specific credential fields as an HTMX fragment when the provider type dropdown changes.

**`CallProviderFormView`** — handles both create and update of a `CallProvider`. Detects `pk` in URL kwargs to switch between modes.

**`CallProviderDeleteView`** — single delete via `HorillaSingleDeleteView`.

**`CallProviderTestConnectionView`** — calls `adapter.test_connection()` and returns a JSON + toast response.

**`CallProviderStatusUpdateView`** — inline status toggle from the provider list (active / inactive / testing). Returns updated `status_col()` fragment.

**`TwilioTwiMLView`** — CSRF-exempt, returns `<Response><Dial>...</Dial></Response>` XML for Twilio/SignalWire outbound bridging.

**`ProviderWebhookView`** — CSRF-exempt. Routes incoming webhooks to the correct provider adapter. A provider with no verification key, or a request whose signature does not validate, gets **403** and is not applied. Recording URLs must be `https`. A webhook does not overwrite the duration or recording of a call that has already finished. A valid payload upserts the matching `CallLog`, pushes a `call_status` message to the caller's calls group, and triggers the Activity signal path. The mock provider rejects every webhook. Twilio signs with the Auth Token; Telnyx and SignalWire need the webhook secret, and an active provider saved without that key returns 403 until it is set.

### Call log views (`views/call_log.py`)

**`CallLogNavView`** — HTMX nav bar with search, filter (`CallLogFilter`), and layout switcher.

**`CallLogView`** — main Call Logs page; renders nav + list layout.

**`CallLogListView`** — HTMX list. Columns: `direction`, `from_number`, `to_number`, `status`, `get_duration_display`, `started_at`, `provider`.

**`CallLogDeleteView`** — single delete; on success triggers `htmx.trigger('#reloadButton','click')`.

### Click-to-call & status views (`views/call_log.py`)

**`ClickToCallView`**

The view, the activity-tab call button and the list **Call Now** action require call-integration access (`CallIntegrationSetting.user_has_menu_access`) and `calls.add_calllog`. A user without that access gets an error and no Call Now button. One active provider is preselected and locked; none leaves a message and no Call Now button.

- **GET** — renders `calls/click_to_call_modal.html` with active providers and pre-filled phone number / related object from query params.
- **POST** — resolves provider, validates related object ownership via `_validate_related_object()`, resolves `from_number` via `AgentMapping.agent_id` → `provider.caller_id`, calls `adapter.initiate_call()`, creates `CallLog(status='initiated')`, and returns `calls/call_status_modal.html`. A connection error or timeout is reported as "Could not reach the calling provider".

**`CallStatusView`** — the status modal refreshes when the provider webhook pushes `call_status`, and HTMX polls every 3 seconds as a fallback. Before the timeouts, it asks the provider for the live status so an active call is not closed early.

1. Ringing / initiated > 30 s with no answer → `no_answer`.
2. Any non-terminal call > 5 min → `no_answer`.

Returns updated `calls/call_status_modal.html`; includes auto-close logic when terminal.

**`CancelCallView`** — POST only. Marks the call cancelled only when the provider confirms. Otherwise it stores the status the provider reports, or shows "Could not cancel the call. Please try again." A call that is already finished is left as it is.

**`ObjectCallLogView`** — `HorillaListView` of `CallLog` records filtered by `related_model_name` + `related_object_id`. Used in the Call History sub-tab on any record detail page. Columns: direction, provider, status, duration, agent, date & time. Direction cell is clickable (opens call log detail). The tab is shown only when the viewer can access the related record. When `object_id` / related identifiers are missing or invalid, the view returns an **empty queryset** instead of raising (avoids a 500 on the Call History tab). The empty state does not cover the tab buttons.

**`CallLogDetailView`** — `HorillaModalDetailView` (`calls.view_calllog`, HTMX). Opening a log from the list or the History tab shows direction, numbers, provider, agent and start/end in a modal instead of a full page. Allowed users and roles on the integration settings use the same pill modals as Meeting.

### Per-user settings (`views/core.py`) — My Settings → Calls

**`CallUserSettingsView`** — GET shows the user's current agent mappings per provider. POST allows updating `extension` and `agent_id` for each provider the user has access to.

Call Settings is one card for the enabled and disabled states. Integration settings use the shared empty states: feature-disabled when call integration is off, and the standard empty state when no providers are configured. Access options that are not active show how to select them and open roles and users in a modal. The providers tab labels **Setup Guide**, and `CallProviderListView` sets `no_record_fit_height = False` so the empty state does not stretch over the tab.

---

## Signals (`signals.py`)

### `track_call_in_history` — `post_save` on `CallLog`

Maintains a linked `Activity` so call events appear in the History tab of the related object.

- **On creation**: creates an `Activity(activity_type="log_call")` with subject, direction, duration, and GFK pointing to the related object. Stores `linked_activity_id` in `CallLog.additional_info`.
- **On terminal status change**: updates the linked Activity's `status`, `call_duration_seconds`, and `call_duration_display`.
- Skips live / in-progress status changes to avoid polluting history.
- Skips `CallLog` records with no `related_model_name` / `related_object_id`.

**Status → Activity status mapping:**

| Call status | Activity status |
|-------------|----------------|
| `initiated` / `ringing` | `scheduled` |
| `in_progress` | `in_progress` |
| `completed` | `completed` |
| `cancelled` / `failed` / `no_answer` / `busy` | `cancelled` |

---

## Feature registration (`registration.py`)

| Model | Features |
|-------|---------|
| `CallProvider` | `global_search`, `export_data` |
| `CallLog` | All (import, export, global search, permissions) |
| `AgentMapping` | `import_data`, `export_data` |

### Callable model registry

`_CALLABLE_MODEL_REGISTRY: list[tuple[str, str, str]]` — any app can call `register_callable_model(app_label, model_name, phone_field)` to make its objects linkable to calls. Used by `CallLog.get_related_object()` for phone-number matching on inbound calls and object validation on outbound calls.

---

## URL map (`urls.py`)

`app_name = "calls"` — all URL names must be reversed as `calls:<name>`.

| Name | Path | View |
|------|------|------|
| `integration_settings` | `calls/settings/` | `CallIntegrationSettingsView` |
| `user_settings` | `calls/user-settings/` | `CallUserSettingsView` |
| `call_access_roles` | `calls/call-access-roles/` | `CallAccessRolesView` |
| `call_access_users` | `calls/call-access-users/` | `CallAccessUsersView` |
| `call_access_roles_detail` | `calls/call-access-roles-detail/` | `CallAccessRolesDetailView` |
| `call_access_users_detail` | `calls/call-access-users-detail/` | `CallAccessUsersDetailView` |
| `settings_tabs` | `calls/settings-tabs/` | `CallSettingsTabView` |
| `settings_access_control` | `calls/settings-access-control/` | `CallAccessControlTabContent` |
| `settings_providers` | `calls/settings-providers/` | `CallProvidersTabContent` |
| `provider_list` | `calls/provider-list/` | `CallProviderListView` |
| `provider_fields` | `calls/provider-fields/` | `CallProviderFieldsView` |
| `provider_create` | `calls/provider-create/` | `CallProviderFormView` |
| `provider_update` | `calls/provider-update/<pk>/` | `CallProviderFormView` |
| `provider_delete` | `calls/provider-delete/<pk>/` | `CallProviderDeleteView` |
| `provider_test` | `calls/provider-test/<pk>/` | `CallProviderTestConnectionView` |
| `provider_status_update` | `calls/provider-status/<pk>/` | `CallProviderStatusUpdateView` |
| `call_log_view` | `calls/call-log-view/` | `CallLogView` |
| `call_log_nav` | `calls/call-log-nav/` | `CallLogNavView` |
| `call_log_list` | `calls/call-log-list/` | `CallLogListView` |
| `call_log_delete` | `calls/call-log-delete/<pk>/` | `CallLogDeleteView` |
| `click_to_call` | `calls/click-to-call/` | `ClickToCallView` |
| `object_call_logs` | `calls/object-call-logs/` | `ObjectCallLogView` |
| `call_status` | `calls/call-status/<pk>/` | `CallStatusView` |
| `cancel_call` | `calls/cancel-call/<pk>/` | `CancelCallView` |
| `twilio_twiml` | `calls/twilio/twiml/<provider_pk>/` | `TwilioTwiMLView` |
| `provider_webhook` | `calls/webhook/<provider_type>/<provider_pk>/` | `ProviderWebhookView` |

---

## Typical flows

1. **Admin enables the integration:** Settings → Integrations → Call Integration → toggle on → choose access type → save roles or users via modal.
2. **Admin configures a provider:** Settings → Integrations → Call Integration → Providers tab → Add Provider → select type → enter credentials → Save → Test Connection.
3. **Agent makes an outbound call:** Click-to-Call button on any Lead/Contact detail page → modal pre-fills phone number → agent selects provider → clicks Call → status modal appears and polls every 3 seconds → auto-closes on completion.
4. **Inbound webhook arrives:** Provider POSTs to `calls/webhook/<type>/<pk>/` → `ProviderWebhookView` validates signature, parses payload → upserts `CallLog` → `track_call_in_history` signal creates or updates linked Activity.
5. **Viewing call history:** Activity tab → Call History sub-tab loads `ObjectCallLogView` filtered to the current record's `model_name` + `object_id`.
6. **User maps their agent ID:** My Settings → Calls → enter Extension / Agent ID per provider → Save.

---

## Adding a new provider

1. Create `calls/adapters/<name>_adapter.py` subclassing `BaseCallAdapter`. Implement `initiate_call`, `validate_webhook`, `parse_webhook_payload`. Optionally override `cancel_call`, `fetch_status`, `test_connection`.
2. Add a `PROVIDER_<NAME>` constant and tuple to `CallProvider.PROVIDER_CHOICES`.
3. Register the adapter in `calls/adapters/factory.py` — map the new `provider_type` string to the adapter class.
4. Add provider-specific credential fields to the provider form template fragment (loaded by `CallProviderFieldsView`).

---

## Related documentation

- Core models and `HorillaCoreModel`: [../core/models.md](../core/models.md)
- Activity app (call events appear in History): [../activity/activity.md](../activity/activity.md)
- Meeting integration (video conferencing links): [../meeting/meeting.md](../meeting/meeting.md)
- My Settings menu: [../../menu/my_settings_menu.md](../../menu/my_settings_menu.md)
- Single form view pattern: [../generics/views/single_form.md](../generics/views/single_form.md)
- Four-layer permission model: [../core/permissions.md](../core/permissions.md)
