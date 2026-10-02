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

- The URL comes from the event's `relatedUrl` key. `GetCalendarEventsView` builds it via `_related_record_urls()`, which calls `get_related_record_urls()` in `horilla.contrib.activity.methods` (the batch form of `get_related_record_url()`, the helper behind the activity's **Related To** tab and list column). It is set only when the user passes `check_record_access` on the related record and the record is in the active company. Otherwise it is `""` and the action is not rendered.
- The calendar only knows the generic `related_object`. It doesn't import any related model (e.g. `horilla_crm` leads), so it works for any model registered under `activity_related` that has `get_detail_url()`.
- The link uses the same HTMX navigation as the Related To link (`hx-select-oob="#sideMenuContainer"` so the record's module opens in the side menu). `showPopup()` calls `htmx.process()` on the popup content so the `hx-*` attributes work.
- Keep `relatedUrl` and the popup action in sync with **Color by: Status** changes: that feature must not drop the related-record key or the Open Related Record markup when editing the event payload / popup.

### Color by: Type / Status

The sidebar has a **Color by** toggle. **Type** (the default) keeps each event in its calendar's color and shows the **My Calendars** list. **Status** colors activities (task, event, meeting) by whether their status is `completed` (default green `#10B981`) or anything else (default orange `#F97316`), and swaps the list for a **Status colors** legend with a color picker for each.

- Unavailability and custom calendar events have no status, so they keep their calendar color in both modes.
- Coloring is client-side in `eventDidMount`, from the `status` key that `GetCalendarEventsView` already returns; month-view event dots are recolored too. Switching mode or picking a color calls `refetchEvents()` instead of reloading the page, and **Mark as Complete** recolors through its existing `#reloadMainContent` reload.
- The mode is saved per browser in `localStorage` (`calendarColorBy`).
- The two status colors are saved per user like the type colors, as `UserCalendarPreference` rows with `calendar_type` `status_completed` / `status_pending` (defaults in `DEFAULT_STATUS_COLORS`) and `is_selected=False`: they hold a color only and are never fetched as a calendar.

### Show: Mine / Team

The sidebar's **Show** toggle switches between **Mine** (the default) and **Team**, so a manager can see what was scheduled for their team and for whom. It only changes which activities are loaded: events are drawn the same way, and the popup shows the same details.

- **Mine** is unchanged: the activities the user is assigned to, takes part in (`participants`), owns or hosts (`meeting_host`).
- **Team** adds the activities the user may see in the **All Activities** list, by the same rule as `HorillaListView.get_queryset` (`_calendar_activities()`):
  - `activity.view_activity`: every activity in the active company.
  - `activity.view_own_activity`: those whose `owner` or `assigned_to` (`Activity.OWNER_FIELDS`) is the user or anyone in a subordinate role (`get_allowed_user_ids()`, through `Role.parent_role`), plus any `granted_access_filter`.
- The toggle is rendered only when Team shows more than Mine (`_team_scope_available()`): with `view_activity`, or with `view_own_activity` and at least one subordinate. Every non-superuser gets `view_own_activity` by default, so a manager whose role has sub-roles gets the toggle with no extra setup; seeing the whole company needs `view_activity`.
- `GetCalendarEventsView` checks this again on every request: `scope=team` from a user the toggle isn't rendered for gets Mine.
- In Team, activity events also carry `canChange` (`check_record_change_access()`: `change_activity`, or `change_own_activity` on the user's or a subordinate's record) and `canDelete` (`activity.delete_activity`, which `ActivityDeleteView` requires). The popup hides **Mark as Complete** and **Edit** without `canChange`, and **Delete** without `canDelete`, matching the All Activities list's row actions. Mine sends neither key, so its popup is unchanged.
- Unavailability and custom calendars are the same in both.
- The choice is saved per browser in `localStorage` (`calendarScope`). It is restored before the calendar is created, because FullCalendar loads its first events in its constructor.

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
`relatedUrl`, and checks all related records of the response together with
`get_related_record_urls()`. Per related model that is one visibility query,
plus one query per owner field for a `view_own` user (the `OWNER_FIELDS` that
`check_record_access` reads are prefetched), instead of a few queries per
record. Do not call `get_related_record_url()` per event. The one remaining
per-record query is a model's optional `has_granted_access` hook (e.g.
Opportunity team members), reached only for records the user doesn't own.

A month view can hold over a thousand events, so per-event work adds up even
without queries. The loop reads `activity_type_display` / `status_display` from
label maps built once per request (`_choice_labels()`), because
`get_<field>_display()` rebuilds and translates the choice labels on every call.
It builds `url`, `deleteUrl` and `detailUrl` with `_pk_url()`, which reverses
each Activity URL method once for a placeholder pk and puts each event's pk in
its place. Both return exactly what the Activity methods return, so the JSON
payload doesn't change.

It loads only the activities in FullCalendar's visible range, sent as `start`
and `end` (ISO 8601) by the event source and by the two calendar-checkbox
handlers (`calendarEventsQuery()` adds them, plus `scope=team` in the Team
view). `_requested_range()` widens the range by a day on each side, because
FullCalendar gives events without a usable end a default length and snaps
all-day events to whole days. The overlap uses the same
`start_datetime` → `due_datetime` → `created_at` fallbacks as the event payload.
A missing, malformed or reversed range loads every activity, as before.

In the Team view, `select_related("owner")` lets `check_record_change_access()`
read each owner without a query per activity (`assigned_to` is prefetched).

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
