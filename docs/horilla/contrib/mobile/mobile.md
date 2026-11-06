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

This document covers the shell (layout, login and logout, the web app manifest
and the service worker), how a model opts in (`mobile.py`), the **Records**
tab and the **record page**. Log activity, Today and Agenda are added on top
of these.

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

`registration.py` registers the `mobile` feature
(`register_feature("mobile", "mobile_models", auto_register_all=False)`) and
the core RTL assets (`inject_html/rtl_assets.html`) for the mobile page, the
same fragment the desktop layout and login page get.

`MobileConfig.ready()` then loads every installed app's `mobile.py` (see
[Opting a model in](#opting-a-model-in)). It runs outside `AppLauncher`'s own
error handling, so a broken `mobile.py` stops startup instead of hiding a
model on the phone.

---

## URLs (`urls.py`)

| URL | Name | View | Access |
|-----|------|------|--------|
| `/m/` | `mobile:home` | `MobileHomeView` (redirects to Today) | signed in |
| `/m/today/` | `mobile:today` | `MobileTodayView` (`?tab=overdue`, `today`, `upcoming`) | signed in |
| `/m/agenda/` | `mobile:agenda` | `MobileAgendaView` (`?date=`) | signed in |
| `/m/agenda/new/<kind>/` | `mobile:agenda_activity` | `log_activity.agenda_activity` (`kind`: `meeting`, `event`, `task`; `?date=`) | may add activities |
| `/m/activities/<pk>/status/` | `mobile:activity_status` | `status.MobileActivityStatusView` (POST: mark done / undo) | may change the activity, one of the user's own |
| `/m/records/` | `mobile:records` | `MobileRecordsView` | signed in |
| `/m/records/<app_label>/<model_name>/<pk>/` | `mobile:record` | `MobileRecordView` | signed in, may view the record |
| `/m/records/<app_label>/<model_name>/<pk>/edit/` | `mobile:edit_record` | `edit_record.MobileEditRecordView` | may view the record and edit its fields (desktop Edit Details rule) |
| `/m/records/<app_label>/<model_name>/<record_pk>/log/<kind>/` | `mobile:log_activity` | `log_activity.log_activity` (`kind`: `call`, `task`, `meeting`, `event`) | may change the record |
| `/m/records/<app_label>/<model_name>/<record_pk>/note/` | `mobile:add_note` | `MobileNoteView` | may change the record |
| `/m/activities/<pk>/` | `mobile:activity_detail` | `MobileActivityDetailView` | may view the activity |
| `/m/activities/<pk>/edit/` | `mobile:edit_activity` | `log_activity.edit_activity` | may change the activity |
| `/m/notes/<pk>/` | `mobile:note_detail` | `MobileNoteDetailView` | may view the note's record |
| `/m/notes/<pk>/edit/` | `mobile:edit_note` | `MobileEditNoteView` | may change the note |
| `/m/login/` | `mobile:login` | `MobileLoginView` | public |
| `/m/logout/` | `mobile:logout` | `MobileLogoutView` | any |
| `/m/more/` | `mobile:more` | `MobileMoreView` (Account page) | signed in |
| `/m/manifest.webmanifest` | `mobile:manifest` | `ManifestView` | public |
| `/m/sw.js` | `mobile:service_worker` | `ServiceWorkerView` | public |

Signed-out visitors of a mobile page are sent to `/m/login/?next=…`
(`MobileLoginRequiredMixin`), not to the desktop login.

---

## Opting a model in

A model shows on the phone when its app does two things, neither of which
imports `horilla.contrib.mobile`:

1. **Feature.** `features=["mobile"]` in the app's `registration.py`:

   ```python
   register_model_for_feature(app_label="leads", model_name="Lead", features=[..., "mobile"])
   ```

   The feature is registered with `auto_register_all=False`, so models
   registered with `all=True` are **not** opted in by it. When the mobile app
   is not installed, the registry simply keeps the unknown feature name.

2. **Display settings.** A `mobile.py` module next to it, holding plain data:

   ```python
   MOBILE_MODELS = {
       "Lead": {
           "title_field": "title",
           "subtitle_fields": ["first_name", "last_name"],
           "phone_fields": ["contact_number"],
           "email_field": "email",
           "status_field": "lead_status",
           "row_fields": ["lead_owner"],
           "search_fields": ["first_name", "last_name", "lead_company"],
           "filter_fields": ["lead_source"],
       },
   }
   ```

   `MobileConfig.ready()` walks the installed apps and imports
   `{app}.mobile` when that module exists (`registry.discover_mobile_modules`).
   The keys are model names of that app. `mobile` is **not** in the app's
   `auto_import_modules`, so nothing loads `mobile.py` while the phone app is
   off.

| Option | Meaning |
|--------|---------|
| `title_field` | Field shown as the record's name. Empty: `str(obj)`. |
| `subtitle_fields` | Fields joined with a space on one line under the title, on rows and the record page (e.g. a lead's first and last name). |
| `phone_fields` | Fields behind the **Call** (`tel:`) button and the call icon on list rows. More than one: the phone asks which. |
| `email_field` | Field behind the **Email** (`mailto:`) button. |
| `status_field` | Status shown on rows and the record page, and offered as a filter. It can be changed on the phone when it is the desktop detail view's `pipeline_field`. |
| `row_fields` | Up to two extra fields on each list row, the same for every user. |
| `search_fields` | Text fields searched besides the title and email. |
| `filter_fields` | Choice, foreign-key or boolean fields offered as filters. |
| `header_fields` | Record-page key fields for a model **without** a desktop detail view. |
| `order` | The model's place among the record types (the Records chips), lowest first. Models without one follow, in registration order (the order of `INSTALLED_APPS`). |

Each entry is validated when it is loaded (`registry.build_config`): unknown
options, unknown fields, more than two row fields, or a filter without values
to pick from raise `ImproperlyConfigured`.

A model with the feature but no `MOBILE_MODELS` entry is skipped with a
warning; an entry without the feature is ignored.

---

## Who sees what (`access.py`)

The phone applies the desktop rules, not its own:

- **Lists and search** (`scope_queryset`): the same owner filtration as
  `HorillaListView`. `view_<model>` shows every record; `view_own_<model>`
  shows records whose `OWNER_FIELDS` point at the user or a subordinate, plus
  rows granted through the model's `granted_access_filter`; nothing else
  shows. Model managers keep the active-company scoping.
- **Opening a record** (`can_open`): `check_record_access`, the rule of the
  desktop detail page and its tabs.
- **Fields**: fields with the field permission "Don't show" are left out of
  rows, filters, key fields, All fields, Call and Email.
- **Editing fields** (`can_edit_all_fields`): the desktop Edit Details rule,
  see [Edit details](#edit-details-edit_recordpy).

---

## My work (`today.py`, `MobileTodayView`)

The first tab ("My work") and the page `/m/` opens. Under the top bar it
shows the date (weekday, day and month, in the user's calendar), then the
signed-in user's own
tasks, meetings and events, by the rule of the desktop calendar's **Mine**:
activities they own, are assigned to, take part in or host (`my_activities`).
Logged calls are not listed. "Today" and the day boundaries follow the user's
time zone (their profile's, else the server's).

| Tab | Shows |
|-----|-------|
| **Overdue** | not completed or cancelled, due (tasks) or starting (meetings, events) before today, oldest first; meetings and events included |
| **Today** (default) | the same, due or starting today; a **Next** card with the nearest timed one still ahead (today or in the next 7 days); a collapsed **Done today** list |
| **Upcoming** | the next 7 days, grouped by day, then a link to the [Agenda](#agenda-agendapy-mobileagendaview) for later dates |

Each row shows the type label in the user's calendar color, the time (late
ones in red), the title and the related record's name, a done checkbox, and
a **Call** button when the record is on the phone, the user may open it and
it has a number in its `phone_fields`. Tapping a row opens the
[details sheet](#record-page-recordspy-mobilerecordview), with an **Open the
record** link. The tabs switch in place (`hx-get`, the content partial) and
keep `?tab=` in the address bar.

**Mark as done** has no confirmation. The checkbox posts `status=completed` to
`mobile:activity_status`, with the page's state (`#activity-state`: `view`
and its `tab` or `date`); the answer is that page's refreshed content and an
`HX-Trigger` toast (`mobileToast`) with **Undo**, which posts the previous
status back. The Agenda's rows work the same way. Unticking a row in Done today reopens it with its type's
starting status. The view takes only activities from the user's own list,
needs change access to the activity (`check_record_change_access`) and
refuses locked records, then saves the status as the desktop status update
does (with `updated_at`, which Done today reads).

---

## Agenda (`agenda.py`, `MobileAgendaView`)

The second tab: the user's activities day by day, cancelled ones aside, Mine
or Team (below). `?date=` picks the day (ISO, or the user's own
calendar through the date formatter); today without it.

- **Day title** with **Today** (on another day), **Go to date** (an inline
  date field: a calendar extension's picker, e.g. Jalali, opens outside the
  page's sheets) and, with the calendar app, the type filter.
- **Week strip:** the picked day's week, starting on the active language's
  first day (`FIRST_DAY_OF_WEEK`: Saturday in Persian), with the weekday's
  initial, the day number in the user's calendar and a dot per activity type
  that day; arrows move a week. The day and week links swap the content in
  place (`hx-get`, the content partial) and keep `?date=` in the address bar.
- **The day:** all-day items and those running over from an earlier day
  ("Until 10:00") first, then the rest by time (meetings and events with
  their end time), with the user's unavailability (`UserAvailability`) in
  grey. Rows are those of My work.
- **Type filter** (with the calendar app): meetings, events, tasks and
  unavailability. It reads the desktop calendar's rule (a type with an
  unselected `UserCalendarPreference` row is hidden) and saves through its
  endpoint (`calendar:save_calendar_preferences`), keeping the user's selected
  custom calendars, so both show the same.
- **Mine / Team**, as on the desktop calendar, for users with a team
  (`team_available`, the desktop's rule: `view_activity`, or
  `view_own_activity` with subordinate roles or a granted-access filter).
  Mine: the user's own activities, the rule of My work. Team: those and the
  ones the All Activities list shows the user (`scope_queryset`), each row
  naming its owner ("You" for the user's own). The filter sheet then lists
  the team members (`team_members`: the active company with `view_activity`,
  else the user and their subordinates); ticked ones narrow Team to the
  activities they own, are assigned to, take part in or host, nobody ticked
  shows everyone. The choice and the members stay in the session
  (`?scope=mine|team`, `?members_set=1&members=…`); My work stays the user's
  own. On a teammate's activity the done circle works only with change
  access to it (`can_edit_activity`), otherwise it is shown read-only.
  Unavailability stays the user's own.
- **Add** (users with `add_activity` or `add_own_activity`): a sheet with
  **New meeting**, **New event** and **New task**, whose forms start on the
  picked day (the next full hour today, else 09:00; meetings and events last
  an hour). They belong to no record; saving returns to the activity's day.

---

## Records tab (`records.py`, `MobileRecordsView`)

**Browsing** lists one model at a time: chips to switch model (the last one
is remembered in the session), a **Filter** button, the active filters as
removable chips, **Recently viewed** (the user's last opened records of that
model they can still open, from the existing `RecentlyViewed` rows), and the
rows in the model's own `Meta.ordering` (newest first when it has none).

- **Rows** show the title, the `subtitle_fields` line, the status and the
  `row_fields` with their labels, plus a call icon when the record has a phone
  number.
- **Filters**: the status field and `filter_fields`, as a bottom sheet of
  chips. The **Show results** count updates as values are picked
  (`?partial=count`). Unknown values in the URL are ignored.
- **Pagination**: 20 rows at a time. The next page loads when the end of the
  list scrolls into view (`hx-trigger="revealed"`, `?partial=rows`).

**Searching** (two characters or more) looks in every opted-in model at once
and groups the matches by type, five per type with **Show all** to narrow to
one (`?in=`). The results update as the user types (`?partial=results`), and
the query is kept in the address bar so **Back** from a record returns to it.
Matching (`search.py`):

- Text is matched case-insensitively against the title, email and
  `search_fields`, also with the Arabic and Persian forms of `ی`/`ک` swapped.
- A query that is a phone number (Persian, Arabic or Latin digits, with
  spaces, dashes, dots or brackets) is matched against `phone_fields` with
  those separators ignored, whether the stored number uses Latin or Persian
  digits.

---

## Record page (`records.py`, `MobileRecordView`)

| Part | Source |
|------|--------|
| Name, status, owner | `title_field` (with the `subtitle_fields` line), `status_field`, the first visible foreign key in `OWNER_FIELDS` |
| **Call** / **Email** | `phone_fields` (a sheet when more than one has a number) and `email_field`; `tel:` values are normalized to Latin digits |
| Key fields | the desktop detail page's header grid, see below |
| **All fields** | the desktop **Details** tab, see below |
| **Edit** | the record's fields, see [Edit details](#edit-details-edit_recordpy) |
| Open activities | tasks, meetings and events not completed or cancelled, soonest first |
| Interactions | logged calls, completed activities and notes, newest first |
| Open in full version | the record's `get_detail_url()` |

Each field shows its label and value on one line; a value longer than 40
characters (notes, requirements) goes under its label at full width.
Values are formatted by the desktop's `display_field_value`, so dates follow
the user's timezone and calendar (Jalali when `horilla_jalali` is installed
and the user picked it), and users are shown by name.

**Fields follow the desktop** (`desktop.py`, `DesktopLayout`). The desktop
keys a user's field choice (`DetailFieldVisibility`) by its own detail URL
name, so the phone runs the model's desktop views (with their extensions,
e.g. custom fields) against a copy of the request that carries the desktop
detail path:

- key fields: `HorillaDetailView.get_body()` without its first entry (the
  title), i.e. the user's `header_fields`, or the view's `body` defaults;
- All fields: the Details tab view's context `body`, i.e. the user's
  `details_fields`, or the tab's defaults.

The phone only reads `DetailFieldVisibility`; it never writes a row. A model
without a desktop detail view uses `header_fields` from `mobile.py` and the
generic Details defaults.

**Status changes** go through the desktop stage update. When the desktop
detail view's `pipeline_field` is the `status_field`, the status pill opens a
sheet with the stages from `get_pipeline_choices()`. Picking one asks for
confirmation, then posts the same form the desktop stage bar posts to
`generics:update_pipeline`, so the permission check (`change` or
`change_own`, locked records) is the desktop's. A stage the desktop handles
with its own action (`final_stage_action`, e.g. converting a lead) shows as
**Full version only**. The sheet is not shown when
`check_update_permission()` is false.

**Activities and notes** (`activities.py`) are the rows the desktop tabs show:
attached to the record or one of its history sources (`history_q`), with
activities limited by the same owner filtration as lists. Activity type
labels use the user's calendar colors when the calendar app is installed.
New ones are added from [Log activity](#log-activity-log_activitypy); marking activities done comes with the Today page.

Each row shows its type, date, title, its status (unless it is the starting
one: `pending`, `not_started`, `scheduled`) and the first three lines of its
text: `notes` for a logged call, `description` otherwise. The rest is in the
details sheet.

**Details sheet** (`details.py`). Tapping a row opens a bottom sheet with
everything saved on it (`hx-get` into `#detail-sheet-body`; opened directly,
the same URL renders as a page):

- **Activity**: the fields of the desktop activity **Details** tab for its
  type (`ActivityDetailTab`, with the user's field choice there), run through
  `DesktopLayout` like a record's All fields. The status, which the desktop
  shows as its stage bar, leads the list. Fields left empty are skipped.
  Access: the activity must be in the user's `scope_queryset`, the rule of
  the activity lists.
- **Note**: the full text, the attachment link, who added it and when.
  Access: `can_open` on the note's record.

Anything else gets the "unavailable" page (404), the same whether the item is
gone or not the user's. Yes/no fields read **Yes** / **No**.

**Edit.** The sheet shows a pencil when the user may change the item. It
opens the phone form the item was added with, filled in; saving returns to
where the sheet was opened (the record, a My work tab or an Agenda day,
passed as a `next` phone URL). Delete stays on the desktop.

- **Activity** (`MobileEditActivityView`, `MobileEditMeetingView`): the
  desktop form of its type with the activity, the same short field list as
  when adding. A meeting is saved by the desktop meeting view, which sends
  the invitations again, as on the desktop.
  Every other field is disabled in the form, so it keeps its saved value and
  posted values for it are ignored (including the record, the type and the
  owner). Who: `check_record_change_access` on the activity
  (`change_activity`, or `change_own_activity` on one's own; not locked).
- **Note** (`MobileEditNoteView`): title and text with the desktop notes
  form; an attached file is kept. Who: the desktop note rule, change access to
  the record and, without the model's full change permission, only notes
  added by the user or a subordinate.

---

## Edit details (`edit_record.py`)

The record page's **Information** heading has an **Edit** link when the user
may edit the record's fields. It opens a phone form with them; saving returns
to the record with "Changes saved."

**Who:** the desktop Edit Details rule, `can_edit_all_fields`
(`HorillaDetailView.check_update_permission`: an owner with
`change_own_<model>`, or anyone with `change_<model>`; never a locked record),
when the desktop Details tab allows editing (`edit_field`). Anyone else gets
the "unavailable" page.

**Fields:** those of the desktop Details tab (`get_effective_body()`: the
user's own choice on the desktop detail page, or the tab's defaults, run
through `DesktopLayout` like All fields), without the stage bar's field, the
fields whose field permission isn't `readwrite` and the tab's
`non_editable_fields`; then the custom fields the user may change
(`ExtraFieldsProvider`). Each input is built from the desktop's
`FieldInfoResolver.get_field_info()` and posts what the desktop form posts:

| Desktop field | Phone input |
|---------------|-------------|
| foreign key, many-to-many | a sheet with a search box over the desktop's select2 endpoint (`generics:model_select2`), a page at a time; one record, or several for many-to-many |
| choices, yes/no, state | a select; a stored value the choices don't list stays selectable, and a required field with a value has no empty choice |
| phone number | the country code (the record's company country first: the phone's list has no search box) and a phone keypad input |
| text, number, email, URL, date, date and time | the matching native input (the Jalali pickers with `horilla_jalali`) |
| long text | a text box |
| custom multiple choice | check boxes |

**Saving** is the desktop's: `save_all_fields`, the body of
`UpdateAllFieldsView.post`, with that view's hooks and their `_inherit_view`
extensions (`get_update_all_fields_view()`). Values are applied with
`FieldInfoResolver.apply_field_value` (so Jalali dates parse as on the
desktop) and custom fields through `ExtraFieldsProvider`, then
`check_before_save`, `obj.save()` and `handle_save_error` run. The desktop
HTMX views are not called.

- Only the fields the user changed are posted (`mobile.js`), so a value they
  didn't touch is never written back over a newer one, nor rejected by the
  save (e.g. a phone number stored without a country code).
- A value that can't be applied shows under its field; the record itself isn't
  saved then.
- When a desktop check stops the save, or takes over a failed one, its
  response (desktop markup) isn't shown: the form says the changes weren't
  saved, with the message the check left or the save's error, and links to
  the full version.

---

## Log activity (`log_activity.py`)

The record page's **Log activity** button opens a sheet with **Log a call**,
**New task**, **New meeting**, **New event** and **New note**. Each opens a
phone form page; saving returns to the record with the desktop's success
message. The Agenda adds meetings, events and tasks with the same views,
without a record.

**Who:** the button and the forms follow the desktop activity tab's rule:
change access to the record (`check_record_change_access`, which also refuses
locked records, e.g. a converted lead). Anyone else gets the "unavailable"
page.

**Calls, tasks and events** use the desktop forms (`LogCallForm`, `TaskForm`,
`EventForm`) in `HorillaSingleFormView`s with the phone template
(`ActivityFormMixin`). Validation, the form's own rules (no date in the
past), field permissions, company and `created_by` and the success message
are therefore the desktop's; the desktop HTMX views are not called.

**Meetings** use `MeetingsForm` in a view built on the desktop meeting view
itself (`DesktopMeetingSave`, a `MeetingsCreateForm`): its save creates the
online meeting link (when a provider is picked) and sends the invitations to
the host, the participants and the guests. Its HTMX-only dispatch and the
desktop modal's GET checks are skipped; the phone views check access first.

- The record (`object_id`, `content_type`) and `activity_type` come from the
  URL, never from the posted form; the owner is the signed-in user, as the
  desktop views pre-fill it.
- The phone shows a short field list per kind (call: subject, call type,
  purpose, status, notes; task: subject, due date, priority, status,
  description; meeting: subject, start, end, all day, online, location, link
  provider, participants, reminder, status; event: subject, start, end, all
  day, location, status) plus any other field the form requires. The link
  provider shows for an online meeting when the user connected one.
- **All day** and **Online** redraw the form (posted back with
  `mobile_toggle`, re-rendered unbound from the typed values, nothing saved),
  so the form's own rules decide the fields: date-only inputs for all day, no
  location online.
- **Participants** is a checklist in a sheet with a search box; guests'
  emails go in a text field the desktop form reads
  (`external_participants_email`).
- The desktop forms' HTMX hooks (which post to the desktop modal) are
  dropped, and their switch-styled checkboxes show as plain boxes.
- Date and time fields are the form's native inputs; with `horilla_jalali`
  installed, its pickers replace them on `/m/` as on the desktop.

**Note** uses the desktop `HorillaAttachmentForm` in `MobileNoteView`, saved
like `HorillaNotesAttachmentCreateView` (record, company, `created_by`): a
title and a plain text box (the desktop rich-text editor isn't loaded on the
phone). File uploads come later.

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
login page links to the desktop login for both. That link uses the product
name from the branding module (`Set up {{ product }} on the full version`).

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

**Bottom navigation.** `navigation.NAV_ITEMS` lists the main tabs in display
order (My work, Agenda, Records); `MobilePageMixin` adds them to the context. The bar is
hidden while there is only one page.

**Top bar.** The main tabs share one top bar that stays put between them
(`partials/main_header.html`): the user's photo, name and active company,
which open the **Account** page (`mobile:more`: language, full version,
logout). The bottom bar shows which tab is open. Inner pages (a record, a
form) show a back arrow and their title instead.

**Sheets and dialogs** use the native `<dialog>` element
(`static/mobile/mobile.css` and `mobile.js`): `data-open-dialog="<id>"` opens
one, `data-close-dialog` or a tap on the backdrop closes it.

**Direction-safe styling.** Mobile templates use logical utilities
(`ps-`/`pe-`, `start-`/`end-`, `text-align: start`) instead of left/right
classes, because the desktop `rtl.css` mirrors physical classes such as
`.absolute.left-0` on its own. Record data is wrapped in `<bdi>`, so a value
in another language than the page (a Persian note in the English UI, an email
address in the Persian UI) keeps its punctuation in place while the line keeps
the page's alignment.

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
`"<platform version>-<mobile version>-<hash>"`, where the hash covers the
names and contents of this app's own static files (`static/mobile/`).
Mobile templates build static URLs
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

A change to `mobile.css` or `mobile.js` changes the hash, so phones that
already cached the previous files get the new ones without a version bump.
Desktop static files changed **between** releases keep the old stamp; bump
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
[Turning it on](#turning-it-on)).

The records and record-page tests use a test-only model,
`tests/models.py::MobileTestRecord`, opted in the way an app opts in
(feature plus settings), with a desktop detail view and URL in
`tests/desktop_views.py` and `tests/urls.py`. The mobile package itself still
has no models: because it has no models module, Django's test database does
not sync the test model, so `tests/base.py` creates and drops its table
around each test class. The tests never import `horilla_crm`.

They cover the mobile login and logout
(templates, redirects, failed attempts), the login requirement on mobile
pages, the layout (manifest link, worker registration and scope, versioned
static URLs), the manifest, and the worker (content type, `no-cache`, no
scope-widening header, no redirect for signed-in users, cache name, `DEBUG`
switch), plus:

- registry: settings validation, feature and settings both required, models
  registered for all features not opted in, `mobile.py` discovery;
- search: digit and letter normalization, phone matching against Latin and
  Persian stored numbers;
- Records: what an admin, an owner with `view_own` and a user without
  permission see, filters and their count, pagination, recently viewed
  limited to records the user can still open, grouped search;
- record page: access (owner, someone else's record, missing record, unknown
  model), key and All fields from the user's desktop choice (a choice saved
  under another URL name ignored, no row written), Call and Email, status
  changes through the desktop stage update for an owner and refused for a
  read-only user, open activities and interactions with activities the user
  can't view left out;
- edit details: who may edit (an owner with `change_own`, `change`, a
  view-only user, someone else's record, a locked record), the Details tab
  fields without the stage, non-editable, read-only and hidden fields, the
  inputs per field type, saving back to the record, only posted fields
  changing, a value that can't be applied, a check that stops the save and
  a save error;
- log activity and edit: who gets the forms, the record and type taken from
  the URL, the forms' own rules, fields the phone doesn't show kept on edit,
  returning to My work or the Agenda;
- My work: which tab lists what, rows, mark as done and undo, permissions;
- Agenda: a day's order (all day and running over first, then by time),
  cancelled and other users' activities left out, the week strip, the user's
  own unavailability, the desktop type filter, the first weekday per
  language; adding a task, an event and a meeting (through the desktop
  meeting save, with participants and guests), the add permission, the
  all-day and online redraws, meetings and events on a record page and
  editing a meeting.

`horilla/contrib/core/tests.py` (`LoginLogoutPageDefaultsTests`) checks that
the desktop login and logout keep their own template and URLs.
