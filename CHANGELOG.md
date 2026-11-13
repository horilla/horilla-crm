# Changelog

All notable changes to Horilla CRM are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file starts at **1.13.8**, the first release maintained in this format. Releases
before it are documented on the
[releases page](https://github.com/horilla/horilla-crm/releases) and are not reproduced
here — they predate this convention and back-filling them would misrepresent how they
were recorded at the time.

Each released version corresponds to a git tag of the same name (bare semver, no `v`
prefix) and to the Docker tag `horilla/horilla-crm:<version>`. `horilla/__version__.py`
is the single source of truth for the **whole CRM product** version (not only the
`horilla/` package directory); the release workflow refuses to publish an image whose
tag disagrees with it. See [docs/versioning.md](docs/versioning.md).

Horilla CRM also versions its applications independently — each app carries its own
`__version__.py`, surfaced together by `horilla/utils/version.py`. Those app versions
move on their own cadence and are not tracked in this file.

## [Unreleased]

<!--
Add entries here as you merge, under the headings below. Drop any heading you
do not use. At release time, rename this section to the new version with its
date and open a fresh Unreleased above it.

### Breaking      — requires action from an existing installation before or on upgrade
### Added         — new features
### Changed       — changes to existing behaviour
### Deprecated    — soon-to-be-removed features
### Removed        — features removed in this release
### Fixed         — bug fixes
### Security      — vulnerabilities fixed; link the advisory and credit the reporter
-->

## [1.18.0] — 2026-11-13

### Added

- WhatsApp: a company connects its own WhatsApp Business account in
  **Settings → WhatsApp** and tests the connection before anyone sends. Horilla
  does not ship a provider. The record's Activity tab shows the live
  conversation, and a reply is sent in the background. Templates and flows are
  managed in Settings, and bot rules decide the automatic replies.
- Message Automations: an automation can **Send as WhatsApp Message** through a
  connected account and an approved template. The number comes from the record
  or from a related contact.
- Get started: the home page opens with a setup guide named for the company.
  Each app adds its own steps (company, roles and users, mail server, lead and
  opportunity stages, import leads). It can be skipped, dismissed and brought
  back.
- Search: global search suggests matches as you type and offers quick filters.
  List search filters by field, and the applied filters stay in the navbar.
  Dashboards, reports, mail, calls, booking, approvals and reviews use the
  same search.
- Workflow: a time trigger can repeat while the record still meets the rule,
  and an edit rule can run only when the record enters its criteria (#105,
  #111).
- Cadences: task and call follow-ups can be assigned to the record owner
  (#106).
- Leads: **Round Robin** assignment, and **Allow Owner Reassignment** to lock
  the owner a rule just set.
- Opportunities: a message can go to the primary contact (#109).
- Activity: other apps can add their own tabs on the Activity tab.

### Changed

- The automations settings entry is **Message Automations**. The recipient
  picker follows the selected channels, and each channel keeps its own
  recipients.
- A cadence's automatic run stops when the record no longer meets the
  conditions, and what is still pending is cancelled (#110).
- Boolean fields use a labelled two-segment control, and form labels are
  semi-bold.
- View-own includes the user and their team. Delete-own lets a manager delete a
  subordinate's records, and a delete stays in the active company.
- The company column shows only when all companies is on. Company, call,
  calendar and meeting settings ask for an active company instead of failing.
- A record's History shows a mail's outcome and hides notifications. Merge
  compare hides additional info and company.
- A logged call is labelled **Call**, and the task list loads once so the
  Completed sub-tab stays selected.

### Fixed

- Each ASGI call runs in a fresh context, so a worker no longer keeps the
  previous request's context and deadlocks (#108).
- Converting a lead checks permission, and Select Existing stays in scope.
- Charts show the donut total, and chart values are escaped. User Picker and
  Select2 stay inside the user's permissions and company.
- The selected Select2 option uses the same highlight as the hovered one.
- Timeline and opportunity form tests follow the current code (#112).

### Upgrading

Run the migrations. WhatsApp adds its own tables for accounts, templates,
conversations and bot rules. Existing automations are unchanged until a
WhatsApp channel is selected.

## [1.17.2] — 2026-11-06

### Breaking

- Converting a lead needs **Can Convert Lead** or **Can Convert Own Lead**.
  Grant them to the roles that convert leads.
- Telnyx and SignalWire call providers need a webhook secret. An active
  provider saved without one refuses every callback until the key is added.
  Twilio signs with the Auth Token.
- A blank or placeholder `SECRET_KEY` is replaced by a key stored for the
  install. Set `SECRET_KEY` yourself when more than one server must share it.

### Added

- Edit on the page: company, branch, user and My Profile details show
  read-only sections and switch to the form in place. The user page has
  **Details** and **Login History** tabs.
- Reports and dashboards: a report's **Detail Table** can be added to a
  dashboard with that report's filters, and chart components made from a
  report use its filters. Activities can be report fields and dashboard
  components.
- Google Calendar, Google Meet and Team Selling access can be limited to all
  users, specific roles or specific users. Existing companies stay on **All
  Users**.
- Workflow actions, cadence follow-ups and automations can send through a
  channel another app registers (#97, #98).
- Conditions: rows can join with a logical operator and hold several values.
  Pickers offer a user's department, role and company, and the audit fields.

### Changed

- Rows, exports and dashboard tables in reports follow the list's rule: view
  sees every record, view-own sees owned records and records granted another
  way.
- Only one lead assignment rule stays active per company. The web-to-lead
  builder lists fields when the company has no saved form (#99, #100).
- Opportunities: the email field is on the create and edit forms, and the
  closed-stage popup defaults to Closed Won.
- Fiscal years rebuild only when their structure changes, and the preview
  opens in the full-page calendar.
- Changing language keeps the current page. Mail history, the phone sign-in
  link and the password-reset subject use the product name from branding.
- Short keys search matches the page title, path, key and command.
- Jalali timeline uses Shamsi months and seasons. Form layouts have Cancel in
  the navbar and ask before discarding.

### Fixed

- Call provider webhooks with no verification key, or a signature that does
  not match, are refused. Click-to-call is limited to users who may use calls.
- HTMX sends the CSRF token from the live cookie, so a sign-in in another tab
  does not make every later save fail.

### Security

- Uploaded files require a login. A known media URL is not served to a
  signed-out visitor.
- Failed sign-ins are limited on the page, the admin login and the token API.
  A correct password clears the counters for that username. If the counter
  store cannot be read, the sign-in is refused.
- The user API lists and writes users in the requester's company. A superuser
  still sees every company.

## [1.17.1] — 2026-10-30

### Added

- Cadences: enroll a record in a cadence by hand and un-enroll it from the
  record's Cadence tab; a cadence can have several first follow-ups. Accounts,
  campaigns, contacts, leads and opportunities can all use cadences.
- Mobile: edit a record's fields on the phone (#85), and a **Mine / Team**
  switch on the Agenda (#87).
- Booking: public booking pages can be embedded on any site, explain why a date
  or slot is blocked, and are reused for rescheduling.
- Leads: spam protection on the public web-to-lead form.
- Generics: fiscal period, quarter and year relative date filters, and one
  shared `{% btn %}` tag for primary and outline buttons.
- Automations: **+ Add** creates a mail or notification template from the
  automation form.
- Role: hierarchy actions on the role list, ordered by level.

### Changed

- Generics: the history date filter is now a date-range dropdown, and history
  keeps only the link events of related records. Chart axes offer only
  relevant fields. Mail, notification and note editors share one rich-text
  editor and one Insert Fields view. Related lists show a title and
  description. Datetime filters match by date.
- Buttons and confirm modals use the shared primary and outline styles, with
  **Cancel** instead of a close icon.
- Mail: the sender name logic is corrected, and the server settings explain
  each field.
- Contacts and Opportunities: the relation **Role** is labelled **Customer
  Role**.
- Duplicates: the default rules show separate create and edit messages.
- Approvals: pending approvers can use Edit Details without the change
  permission.

### Fixed

- Generics: owners with change-own access can use Edit Details (#81), and Edit
  Details shows an error under its field right away (#83). Delete reassign
  targets stay in the active company, each list has its own loading indicator,
  and the export spinner stays hidden until an export runs. The `{% btn %}`
  tag works on Django 6.0.
- Mobile: tests no longer hard-code the static URL (#86).
- I18N: Persian translations for the generics messages (#84), and for the
  strings whose capitalisation changed.
- Scoring rules: operators, logical joins and condition values display
  correctly.
- Role: hierarchy chart controls, the View Users modal and company scoping when
  adding users.
- Reports: the close button shows as soon as the edit panel opens.
- CRM: View Hierarchy keeps the parent in the breadcrumb; lead and opportunity
  stage modals use the modal header and theme styling.
- Theme: outline buttons and badges follow the theme colours in the dark theme.
- Core: the fiscal year form updates Start Date Day when Week Start Day changes.

### Upgrading

```bash
docker pull horilla/horilla-crm:1.17.1
```

Migrations run automatically when the container starts. They add the cadence
enrollment table, drop the unique first follow-up constraint on cadence
follow-ups, and update field labels and help text; no existing data is
removed.

Horilla CRM 1.17.1 requires **Django 6.1 or later**. The Docker image already
includes it. If you run from source, reinstall with
`pip install -r requirements.txt`, which also moves `django-timezone-field` to
7.2.2 and `djangorestframework` to 3.18.3, the releases that support Django 6.1.

## [1.17.0] — 2026-10-24

### Added

- Mobile: optional phone mode under `/m/`, **off by default**, with Records,
  Today, log activity and Agenda. Leads, contacts, accounts and opportunities
  opt in from `mobile.py`, and the Jalali date pickers load on the phone layout
  too.
- Generics: group-by bulk actions, matching the list view.
- Core: recycle bin **No expiry**; edit and delete dated exchange rates.

### Changed

- Generics: **Expand All** opens group rows in the viewport and continues as
  the user scrolls, including nested groups one level at a time.
- Activity: `OWNER_FIELDS` includes `participants` and `meeting_host`.
- Business Hours: **Week Start Day** is removed. It had no effect on business
  hours; Fiscal Year keeps its own.
- Auth: a signed-out HTMX request gets **204** and `HX-Redirect` to login.
- Calendar: the grid rebuilds after a reload; toggling Google sync to its
  current state warns instead of saving again.
- Meeting: admin and user actions require integration to be enabled.
- Booking: users with only view-own access see My Bookings and their meeting
  activities.
- Cadences: report and navbar require `cadences.view_cadence`.
- CRM: related forms require change access on the parent record. Scoring
  rules require view permission. List rows show five actions.
- Opportunities: splits, team and contact roles require change access on the
  opportunity.

### Fixed

- Persian translations and RTL layout fixes for the pages added in 1.16.0 (#71).
- Core: Horilla 404 for `Http404`; circular role hierarchy; the last
  superuser cannot be removed from a stale page.
- Calls: access and provider changes are blocked when integration is already
  disabled.
- Mail: Test Mail on a deleted server shows the missing-record message.
- Reports: Excel export converts lazy field labels to strings.
- Approvals: Edit Details follows the edit policy, and the detail page stays
  after a reload.
- Dashboard: **Set to Default** is hidden when the home layout already matches.

### Security

- Dependencies: Pillow is updated from 12.2.0 to **13.0.0**, which fixes five
  critical image-decoding vulnerabilities (CVE-2026-112393, CVE-2026-112398,
  CVE-2026-112403, CVE-2026-112900, CVE-2026-96639). certifi is updated from
  2025.11.12 to **2026.10.23**, which drops the emSign root certificates
  bundled with compromised intermediate CA keys (GHSA-6q48-6c7w-9gw2). The
  release image scan fails on critical findings, so the 1.17.0 image is
  published with these versions.

### Upgrading

```bash
docker pull horilla/horilla-crm:1.17.0
```

Migrations run automatically when the container starts. One drops the Business
Hours **Week Start Day** column, so any value set there is discarded.

The mobile app is not part of the default `INSTALLED_APPS`. To turn it on, add
`horilla.contrib.mobile` to `INSTALLED_APPS` in
`horilla/settings/local_settings.py`; see `docs/horilla/contrib/mobile/mobile.md`.

## [1.16.0] — 2026-10-16

### Breaking

- **Custom Fields, Field Requirements and Form Layouts are now one app, Field
  Management** (`horilla.contrib.field_management`). Existing data, roles and
  permissions move across automatically on `migrate`. Custom code, plugins or
  bookmarks that use the old `custom_fields`, `horilla.contrib.field_requirements`
  or `horilla.contrib.form_layouts` imports, app labels or URL namespaces must switch
  to `field_management`. Settings URLs now live under `field-management/`, and
  custom field URL names are prefixed `custom_fields_`.

### Added

- Field Management: **Full Width** option for custom fields and form layouts;
  the Form Layout page is rebuilt as a list with search and New; custom fields
  now work in conditions, reports, dashboards, grouping, filters and import.
- Leads: **Apply assignment rule** option on lead create forms; Email to Record
  configurations can assign leads using rules and fill the lead name and
  requirements from the mail; the Inbox asks for an owner when an email is added
  as a Lead or Contact.
- Generics: a record can show another record's activities, notes and emails and
  be read-only; per-user **Add Column to Split View**; long values on the details
  tab collapse behind **Show more**; many-to-many user fields show in a dialog
  with pills.
- Calendar: activity **assignees** modal with user pills and search.
- Calls: call log details open in a modal; provider setup guides clarified.
- Extension points for fields that are not model columns, evaluated through a
  generic hook and labelled in rule details.
- Persian translations for 68 new strings (Inbox, Email to Record, calendar
  filters, review triggers and more) and RTL layout fixes for the calendar and
  the Inbox preview (#67).

### Changed

- Settings: one **Field Management** menu with Custom Fields, Form Layout and
  Field Requirements replaces three separate entries.
- Email to Record: "Lead Owner" is now **Owner**; configurations keep the owner
  they had.
- Calendar: multi-day events show in the all-day row and past unavailability is
  blocked; the page script moves to a static file and `views.py` is split into a
  `views/` package.
- Meeting and Calls: allowed users and roles modals show pills with the standard
  search bar.
- Automations: date and time fields in emails and notifications render in each
  recipient's own timezone.
- Core: notification templates can be enabled for Activity.
- Developer: `horilla.auth.mixins` re-exports `LoginRequiredMixin` and the apps
  import it from there; the filter panel toggle moves into `global.js`.

### Fixed

- Generics: deleting a record from its own detail page returns to the list instead
  of a 404 page (#64); the user picker's Select All and filters work across pages;
  selected users stay visible and listed first; the detail modal closes when the
  record no longer exists; checkbox fields span both columns only when full width.
- Notifications: the dropdown stays open on mute and mark-all-read; a missing
  notification shows an error instead of failing.
- Mail: self-opens and direct visits are no longer counted as email opens; the
  outgoing server form needs add permission; Inbox delete requires HTMX.
- Activity: the form's related-object choices are limited to records the user can
  view.
- Calendar: the detail URL and menu section survive a refresh; marking complete
  needs change permission; the assignees modal needs activity view permission.
- Calls: the Call History empty state no longer covers the tab buttons.
- Dashboard: toggling the default dashboard without permission shows the 403 page.
- Leads: assignment rule conditions limit Assign To to the company; conversion
  fields have readable names in History.
- Field Management: Kanban group settings no longer crash without an app label;
  custom layouts are skipped on partial forms that declare their own fields.
- Core and static: the Roles and Permissions view stays inside the settings card;
  settings pages show a scoped loading spinner and no longer highlight a main menu
  item.

### Security

- Dependency: PyJWT is updated to 2.15.1, which fixes GHSA-42vr-xj54-vc7v and
  GHSA-x33g-cr3x-6449 (#65).

### Upgrading

```bash
docker pull horilla/horilla-crm:1.16.0
```

Migrations run automatically when the container starts. Existing Custom Fields,
Field Requirements and Form Layouts are renamed in place into Field Management
with their rows, ids and permissions intact, and a database from before 1.15.2
also gains the date columns custom field values now need. Email to Record keeps
each configuration's owner, and existing configurations keep assignment rules
switched off; new ones default to on.

When running from source, run `python manage.py migrate` and do not delete or
regenerate the migrations: Field Management's initial migration is what carries
existing data across.

## [1.15.3] — 2026-10-09

### Added

- Mail: generic **Inbox** for fetched incoming mail (preview and row actions).
- CRM: Email-to-Record creates **Contacts** as well as Leads via Inbox.
- Calendar: **Mine / Team** toggle, so a manager sees what is scheduled for the
  team (exactly the activities they can already open in All Activities, with no
  new permission); **Team members** filter (user picker), **status** filter, and
  filtered members' unavailability in the Team view.
- Automations: optional **edge-trigger-only** firing for on_update rules;
  Opportunity pre-save amount for amount-edge automations.
- Approvals: block the detail view while a record is pending approval.
- Reviews: **Create/Edit** triggers on review processes.

### Changed

- Calendar: rebuild custom calendars around module activities with event text
  colors; all-day activities are date-based and span whole days.
- Activity: related-record and custom calendar modules limited to opted-in
  models.
- Generics: forms can hide specific condition-row fields; condition Operator
  narrows by field type for content-type field names.
- Core: user-picker Select All selects every filtered user; Select2 on
  boolean/choice value fields; demo-data load when CRM modules are disabled.
- Extensions: LoginHistory uses `_inherit_model` instead of a monkey-patch.
- Booking: settings label renamed to **Booking Pages**.

### Fixed

- Generics: detail Next/Previous when disabled; duplicate breadcrumbs; hide
  non-editable detail/filter fields; cross-company users in owner dropdowns;
  bulk delete/export/update dispatch; GFK History diffs; export column
  selection (including empty selection).
- Generics: users with only `change_own_<model>` can open the edit form on their
  team's records (subordinate roles and `assigned_to` owners) instead of getting
  a 403 page behind a visible Edit button.
- History tab: entries are grouped under the day shown in the viewer's timezone;
  date and time values inside changes follow that timezone; a related record's
  creation row shows its status and type as created; "Updated At" and
  "Updated By" are no longer listed as changes, and empty rows and empty days
  are hidden; empty values show `--` instead of `None`; the actor gets its own
  row after a multi-field edit; edit/create labels are translated into Persian;
  diff arrows point at the new value in RTL.
- Calendar: same activity on both custom and standard calendars; all-day
  creation and navigation; action-button layout; unchecked calendar types and
  **Display This Only** stay as set after a reload; type menus open on screen in
  RTL.
- Activity: Assigned To for all types; Related To save from Edit Details;
  related-record breadcrumbs.
- Automations: blank `created_by` when saving rules.
- Approvals: **Record owner** approver type in step matching.
- Calls: Call History tab gated on related-record access.
- Core: Super Users table scroll; Add User to Role modal title; role list
  description width.
- Utils: legacy table layout attributes through HTML sanitization.
- Jalali: History date-only vs DateTime timezone handling.

### Upgrading

```bash
docker pull horilla/horilla-crm:1.15.3
```

This release adds database migrations for Calendar, Mail, Contacts, Leads and
Reviews. They are additive and run automatically when the container starts.
One change is not additive: custom calendars no longer store a start, end and
display field. They now show the **activities** of the chosen module's records,
filtered by activity type, instead of the records themselves placed by a date
field. The old field settings are dropped, and existing custom calendars start
with every calendar activity type selected.

## [1.15.2] — 2026-10-02

### Added

- Generics: History tab **Show full text** toggle for full auditlog values
  (with Jalali formatting support).
- Generics: list views can opt out of the floating filter panel via
  `filter_panel_option`.
- Calendar: **Color by Type / Status** sidebar toggle; **Open Related Record**
  on activity event popups.
- Core: Holidays tab search in Company Information; Horilla navbar on Import
  Data; Docker `wait_for_db` (reads host/port from Django settings); second-
  company demo fixtures.
- Settings nav descriptions for Cadence, Workflow Rules, Review and Approval
  Processes.

### Changed

- Generics: quick filters work across view types; empty/stale filter rows are
  not rendered; detail field visibility can be scoped per record variant;
  preserve return URL after Edit All Fields.
- Custom Fields: hooks and extensions reorganized into `hooks/` and
  `extensions/` packages.
- Automations: schedule field order and clearer Run Time help text.
- Notifications: Channels push failures no longer break `Notification.save`;
  API nests a slim user serializer for sender/user details.
- CRM: opportunity owners can manage their own team without extra admin
  permissions; record edit actions default to the single-step form; company
  edit defaults to single-step.

### Fixed

- Calendar: Google credentials form validation errors; OAuth callback state
  harden (also Meeting Zoom/Teams); Google push skipped under `manage.py test`.
- Activity: Related To access/visibility; Add Column no longer offers
  unrelated fields.
- Calls: Object Call Log list no longer 500s when `object_id` is missing.
- Process: hide review jobs not assigned to the current user.
- CRM: forecast empty states, navbar, Go To Forecast Type links, and
  `#mainContent` on permission-denied.
- Generics: History tab readability/theming and stale no-op diffs; user-chip
  arrow uses primary theme color.
- Core: responsive role-members table height.

### Security

- Dependency: PyJWT is updated from 2.12.0 to 2.14.0, which fixes
  CVE-2026-102268 (CRITICAL). The vulnerable version was caught by the release
  image scan, so no image was published with it; the `1.15.2` tag points at the
  commit that includes the fix.

### Upgrading

```bash
docker pull horilla/horilla-crm:1.15.2
```

## [1.15.1] — 2026-09-25

### Added

- Generics: bulk **Edit Details** save on the record detail tab (replacing per-field
  pencil inline edit), with extension seams for Custom Fields, Duplicates, Approvals,
  and Jalali parsing.
- Generics: **Oldest First** list view type in the navbar.
- Form Layouts: offer a saved layout as an opt-in **Custom Layout** form mode on
  create and edit (alongside the default form).

### Changed

- Generics: `form_mode` replaces hardcoded multi/single-step URL switchers;
  request-cache field and per-row permission lookups; bulk export uses a hook instead
  of a global QuerySet patch; skip no-op detail/edit-all-fields saves.
- Calls and Process Builder: list-view action/visibility monkey patches replaced with
  MixinExtensions.
- Field Requirements: form overrides via the FormExtension pre-compose hook.

### Fixed

- Lead assignment rules keyed on custom fields now match on **create** (atomic
  `form_valid` so `save_m2m` completes before `on_commit`).
- Core: bulk field-permission queries memoized per request; permission messages use
  model verbose names.
- CRM: scoring `compute_score()` O(1) queries; Lead Delete for full permission;
  booking meeting link on Activity; full-permission Lead Owner and activity tabs.
- Booking: ShiftHour break windows in slots; public date-strip navigation; Join links.
- Mail: outgoing mail no longer picks an unrelated configuration.
- Meeting: Teams guest email display and real Graph errors.
- Activity: TypeError when sending meeting invite emails.
- Automations: scheduled trigger date / Run Time comparison.

### Upgrading

```bash
docker pull horilla/horilla-crm:1.15.1
```

## [1.15.0] — 2026-09-18

### Added

- **Form Layouts app** — administrators can choose, per company, which fields appear on
  the Lead and Opportunity create forms and in what order. Once a layout is saved, the
  create button opens a trimmed single-page form; edit forms are unchanged.
- Extension: `_inherit_mixin`, base-class targeting, pre-compose hooks, and
  `detail_section` composition for stacked view/form/filter extensions.

### Changed

- Custom Fields, Cadences, and Duplicates use real View/Form/Filter extensions instead
  of runtime monkey-patches.
- Related-list and history tabs reuse parent/ContentType lookups; kanban/detail
  pipelines attach `related_obj` for domain stages; per-company settings cache for
  currency and calendar/meeting/calls integration; public links use `SITE_URL`.

### Fixed

- Dashboard chart container resize after HTMX swap; Activity event due-date false
  error; Mail backend issue #39; sub-sidebar replacement when switching main
  sections; Docker Compose starts Celery only after migrations.

### Upgrading

```bash
docker pull horilla/horilla-crm:1.15.0
```

## [1.14.0] — 2026-09-11

Recorded after the fact: 1.14.0 was tagged and published without its entry, and
this section was reconstructed from the commits in the release. It is included
because this file claims to cover every release from 1.13.8 onward, and a
released, tagged, published version with no entry contradicts that.

### Changed

- Outlook token refresh moves from a `flock`-based scheduler to Celery Beat, so it no
  longer depends on a lock file being reachable and shared between processes.
- Scoring rule recalculation is offloaded to Celery instead of running inline on save.
- Outgoing mail configuration is validated before email-dependent features are enabled,
  rather than failing later at send time.

### Fixed

- **Outlook integration could not send mail** ([#37](https://github.com/horilla/horilla-crm/issues/37)).
- Outlook token refresh could race across worker processes and invalidate the token.
- Calendar events and save-preference endpoints returned 500.
- Saving a workflow action or time trigger with an invalid rule raised `NoReverseMatch`.
- Saving a final lead or opportunity stage with no order crashed.
- Adding a default opportunity team with an invalid form crashed.
- Five fragment-only endpoints (settings search, the three user-picker views, and
  dashboard component table data) rendered bare unstyled HTML when opened directly;
  they now require HTMX like the rest of the project's fragment endpoints.
- Reports showed more than one empty-state message when a report had no data.
- Long unbroken values overflowed the detail-view grid.

### Upgrading

```bash
docker pull horilla/horilla-crm:1.14.0
```

## [1.13.8] — 2026-09-05

### Added

- **Field Requirements app** — administrators can configure required and optional fields
  per company for supported CRM models such as Leads and Opportunities.
- Granted-access permission framework: users explicitly granted access to a record can
  act on it according to their assigned permissions without being the owner.
- Opportunity Team permissions gain dedicated read, edit and owner-level handling.
- Shared UI components: My Settings shell, empty-state components, active toggle.

### Changed

- Streaming-based CSV, XLSX and PDF exports.
- Database indexes added on frequently filtered and grouped fields; forecast period
  matching optimised; company list cached.

### Fixed

- Forecast pagination, history rendering, authentication fixes, and Exotel and Outlook
  integration error handling.

### Upgrading

```bash
docker pull horilla/horilla-crm:1.13.8
```

[Unreleased]: https://github.com/horilla/horilla-crm/compare/1.17.1...HEAD
[1.17.1]: https://github.com/horilla/horilla-crm/releases/tag/1.17.1
[1.17.0]: https://github.com/horilla/horilla-crm/releases/tag/1.17.0
[1.16.0]: https://github.com/horilla/horilla-crm/releases/tag/1.16.0
[1.15.3]: https://github.com/horilla/horilla-crm/releases/tag/1.15.3
[1.15.2]: https://github.com/horilla/horilla-crm/releases/tag/1.15.2
[1.15.1]: https://github.com/horilla/horilla-crm/releases/tag/1.15.1
[1.15.0]: https://github.com/horilla/horilla-crm/releases/tag/1.15.0
[1.14.0]: https://github.com/horilla/horilla-crm/releases/tag/1.14.0
[1.13.8]: https://github.com/horilla/horilla-crm/releases/tag/1.13.8
