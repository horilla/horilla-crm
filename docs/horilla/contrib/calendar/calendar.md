# Horilla Calendar app — deep dive (`horilla.contrib.calendar`)

## What this app does

- **User preferences** for calendar display and sync.
- **Availability** blocks for scheduling.
- **Custom calendars** and **conditions** (org-defined views/filters).
- **Google Calendar** OAuth-style settings and per-user/config rows for sync.
- Exposes **REST API** at `/calendar/` for SPA or integrations.

---

## App startup (`apps.py`)

`CalendarConfig`:

| Setting | Value |
|---------|--------|
| `url_prefix` | `calendar/` |
| `url_namespace` | `calendar` |
| `auto_import_modules` | `registration`, `menu`, `signals` |
| API | `/calendar/` → `horilla.contrib.calendar.api.urls` |

---

## Feature registration (`registration.py`)

- Registers the **`custom_calendar`** feature with registry key **`custom_calendar_models`** (`auto_register_all=False`). Apps opt in models that can participate in custom calendar definitions.

## Menu (`menu.py`)

Registers main / floating entries for the calendar shell view and Google settings (see source for `reverse_lazy` names, icons, and `perm` strings).

---

## Models (`models.py`) — overview

### `UserCalendarPreference`

Per-user defaults: visible calendars, time slot length, week start, sync toggles, etc. (see field definitions in `models.py`).

### `UserAvailability`

Recurring or dated availability windows; used when suggesting meeting times or conflict detection.

### `CustomCalendar` / `CustomCalendarCondition`

Organizations define named calendars and rule rows (similar spirit to report conditions) to filter which activities or events appear.

### `GoogleIntegrationSetting` / `GoogleCalendarConfig`

Store integration credentials/config scopes and mapping between Horilla users and Google calendars. Used by views under `templates/google_calendar/` and sync tasks.

`GoogleIntegrationSetting` is a **company-scoped toggle**. Menu conditions call `google_calendar_enabled(request)`, which resolves the row through request-local cache then the [per-company settings cache](../utils/company_settings_cache.md) (`CACHE_NAMESPACE = "calendar.google_integration"`). Invalidate on `save` / `delete`.

All primary models extend **`HorillaCoreModel`** unless noted otherwise in code—company isolation applies.

---

## Signals (`signals.py`)

Used for:

- Auto-pushing `Activity` and `UserAvailability` creates/updates/deletes to
  Google Calendar (when the user is connected).
- Invalidating caches when preferences change.

Push work is enqueued onto a **single daemon worker thread**
(`_run_in_thread` → `_google_push_queue`) so the request returns immediately.
The worker closes its DB connection around each job to avoid holding a SQLite
lock during Google API I/O.

**Tests:** when `manage.py test` is on `sys.argv`, `_run_in_thread` is a no-op.
Otherwise the background worker races the test transaction and surfaces
`database table is locked: activity_activity` noise (and flaky failures) on
SQLite.

(Read `horilla/contrib/calendar/signals.py` for the authoritative list of senders.)

---

## Google Calendar sync (`google_calendar/sync.py`)

Pull sync maps Google Calendar events into `Activity` rows via `_upsert_activity_from_google(gevent, config)`.

### Datetime handling on pull

| Step | Behavior |
|------|----------|
| Parse | `start_dt` / `end_dt` from Google `start` / `end` via `_parse_google_datetime` |
| All-day | When Google sends date-only start, normalize to `09:00`–`10:00` on that day and treat as timed |
| End guard | `end_dt = max(end_dt, start_dt)` so end is never before start (covers malformed or equal Google payloads) |

Other pull rules in the same helper:

- **Type:** `extendedProperties.private.horilla_event_type` first, else map Google `eventType` (`default` → `event`, `focusTime` / `outOfOffice` / `workingLocation` → `task`).
- **Subject:** strip Horilla push prefixes (`[Task]`, `[Event]`, etc.) from `summary`.
- **Status:** preserve existing Horilla `completed` status; Google events do not carry completion state.
- **Skip:** `birthday`, `fromGmail` event types are not imported (handled by caller).

Push and token refresh logic live in the same module; see source for `_push_activity_to_google` and sync entry points.

---

## Forms (`forms.py`)

### `CustomCalendarForm` (`HorillaModelForm`)

- **`field_order`**: `name`, `color`, `module`, `start_date_field`, `end_date_field`, `display_name_field`, `is_selected`
- **`Meta.fields = "__all__"`**, **`Meta.exclude = ["user"]`** — `user` is set on create in the view, not on the form
- **`htmx_field_choices_url`**: `generics:get_model_field_choices`
- **`__init__`**: HTMX GET reload merges query params into `initial`; date/display field choices rebuilt from selected `module` (unchanged)

### Other forms

- **`GoogleSyncDirectionForm`** / **`GoogleCredentialsUploadForm`** — plain `forms.Form` / `ModelForm`; not part of the `__all__` refactor

See [single-step form base](../generics/forms/single_step.md) for `HORILLA_FORM_EXCLUDE` on `HorillaModelForm`.

---

## Templates and UX

- Main shell calendar: `horilla/contrib/calendar/templates/calendar.html` (extends project layout; HTMX loads events).
- Google settings partials: `templates/google_calendar/`.

### Activity popup actions

Clicking an activity opens a popup with **Mark as Complete**, **Edit**, **Delete** and **Info** (activity detail), each shown per the user's activity permissions. **Open Related Record** (external-link icon) opens the record in `Activity.related_object` (e.g. the Lead) on its own detail page, so the user can add a note, log a call or create a follow-up activity there.

- The URL comes from the event's `relatedUrl` key. `GetCalendarEventsView` builds it via `_related_record_url()`, which calls `get_related_record_url()` in `horilla.contrib.activity.methods` (the same helper behind the activity's **Related To** tab and list column). It is set only when the user passes `check_record_access` on the related record and the record is in the active company. Otherwise it is `""` and the action is not rendered.
- The calendar only knows the generic `related_object`. It doesn't import any related model (e.g. `horilla_crm` leads), so it works for any model registered under `activity_related` that has `get_detail_url()`.
- The link uses the same HTMX navigation as the Related To link (`hx-select-oob="#sideMenuContainer"` so the record's module opens in the side menu). `showPopup()` calls `htmx.process()` on the popup content so the `hx-*` attributes work.
- Keep `relatedUrl` and the popup action in sync with **Color by: Status** changes: that feature must not drop the related-record key or the Open Related Record markup when editing the event payload / popup.

### Color by: Type / Status

The sidebar has a **Color by** toggle. **Type** (the default) keeps each event in its calendar's color and shows the **My Calendars** list. **Status** colors activities (task, event, meeting) by whether their status is `completed` (default green `#10B981`) or anything else (default orange `#F97316`), and swaps the list for a **Status colors** legend with a color picker for each.

- Unavailability and custom calendar events have no status, so they keep their calendar color in both modes.
- Coloring is client-side in `eventDidMount`, from the `status` key that `GetCalendarEventsView` already returns; month-view event dots are recolored too. Switching mode or picking a color calls `refetchEvents()` instead of reloading the page, and **Mark as Complete** recolors through its existing `#reloadMainContent` reload.
- The mode is saved per browser in `localStorage` (`calendarColorBy`).
- The two status colors are saved per user like the type colors, as `UserCalendarPreference` rows with `calendar_type` `status_completed` / `status_pending` (defaults in `DEFAULT_STATUS_COLORS`) and `is_selected=False`: they hold a color only and are never fetched as a calendar.

### My Calendars selection

Which standard types (`task`, `event`, `meeting`, `unavailability`) are checked is saved per user and company in `UserCalendarPreference.is_selected`. A type with no row counts as checked, so a new user sees all four.

- `SaveCalendarPreferencesView` unselects the user's rows, then selects the checked types. An unchecked type without a row gets one with `is_selected=False` and its color from `DEFAULT_CALENDAR_TYPE_COLORS` (`_save_unchecked_calendar_types()`); otherwise it would show as checked again after the reload.
- **Display This Only** saves the same way, so the choice is still applied the next time the calendar opens.
- `GetCalendarEventsView` called without `calendar_types[]` applies the same rule. Unchecking everything (the **My Calendars** box) fetches no events.
- The status color rows are not calendar types. Saving a selection never adds, selects or recolors them.

## Query behavior

`CalendarView` loads the user's standard calendar preferences once and builds a
`calendar_type` map in memory. Do not call `preferences.filter(...).first()`
inside the four-calendar loop because each filtered queryset issues another
database query.

`GetCalendarEventsView` prefetches `Activity.assigned_to` for the combined
activity queryset and serializes `assigned_to.all()` from the prefetch cache.
Using `activity.assigned_to.values(...)` in the event loop bypasses that cache
and creates one user query per activity. Keep the response keys unchanged when
optimizing this path: `id`, `first_name`, `last_name`, and `email`.

It also prefetches `Activity.related_object` (one query per related model) for
`relatedUrl`, and caches that URL per related record, so activities on the same
record run the access check once.

These optimizations target the calendar shell and its AJAX event request. Use
`python manage.py check` and inspect both `/calendar/calendar-view/` and
`/calendar/calendar-events/` when changing related-object loading.

---

## Typical flows

1. User opens **Calendar** from the menu → week/month view loads activities whose datetimes fall in range.
2. User connects **Google** in settings → OAuth flow writes `GoogleCalendarConfig` → sync jobs create/update **`Activity.google_event_id`** rows on the activity app.
3. Mobile or SPA hits **`/calendar/`** API → serializers return JSON blocks consistent with web filters.

---

## Related documentation

- Activity model (events/tasks tied to Google IDs): [../activity/activity.md](../activity/activity.md)
- Dashboard home may embed calendar widgets: [../dashboard/dashboard.md](../dashboard/dashboard.md)
- Module version metadata: `horilla/contrib/calendar/__version__.py`
