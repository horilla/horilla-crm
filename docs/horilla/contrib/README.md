# `docs/horilla/contrib` — Horilla contrib apps

This tree mirrors **`horilla/contrib/`** Django apps. Each subfolder holds documentation for that app.

## Recent updates (31 Oct–6 Nov 2026, v1.17.2)

Platform version is **1.17.2** ([core/horilla.md](core/horilla.md)). Module versions stay on their own lines.

| Topic | Doc |
|-------|-----|
| Inline Edit Details for one record | [generics/views/details.md](generics/views/details.md#edit-details-one-record) |
| Lists, reports and dashboards share one view-own rule | [generics/views/list.md](generics/views/list.md#step-g-ownership-permission-filtration) · [reports/reports.md](reports/reports.md) · [dashboard/dashboard.md](dashboard/dashboard.md) |
| Condition rows: logical operator, multi-select, related user fields, audit fields | [generics/forms/condition_fields.md](generics/forms/condition_fields.md#related-user-fields-audit-fields-and-row-values) |
| HTMX sends the live CSRF cookie | [../../templates/index.html.md](../../templates/index.html.md#htmx-and-csrf) |
| Google Calendar access, and Google Meet follows it | [calendar/calendar.md](calendar/calendar.md) · [meeting/meeting.md](meeting/meeting.md) |
| Report Detail Table on a dashboard | [reports/reports.md](reports/reports.md) · [dashboard/dashboard.md](dashboard/dashboard.md) |
| One active lead assignment rule; Team Selling access | [../../horilla_crm/leads/assignment_rule.md](../../horilla_crm/leads/assignment_rule.md) · [../../horilla_crm/opportunities/opportunity_team.md](../../horilla_crm/opportunities/opportunity_team.md) |
| Call webhooks must be verified | [calls/calls.md](calls/calls.md) |

Also in this release: profile, user, company and branch details edit inline, and a user's login history is a tab on the user page. Fiscal years rebuild only when their structure changes, and the calendar preview opens in the full-page modal. Failed sign-ins stay limited, and the user API stays in the requester's company. Activities can be report fields and dashboard components. Workflow, cadences and automations send through registered delivery channels; the workflow email action explains a missing mail configuration. Short key search matches the page title. The phone sign-in page uses the branding product name. The timeline can use Shamsi months and seasons. Opportunity forms include email, the closed-stage popup defaults to Closed Won, and a user with only view-own on splits sees their own splits. Converting a lead needs the convert or convert-own permission. The web-to-lead builder lists fields when the company has no saved form.

## Recent updates (24–30 Oct 2026, v1.17.1)

Platform version is **1.17.1** ([core/horilla.md](core/horilla.md)). Module versions stay on their own lines.

| Topic | Doc |
|-------|-----|
| Cadence enrollments with manual Enroll / Un-enroll | [cadences/cadences.md](cadences/cadences.md) |
| Chart axes offer only relevant fields | [generics/views/chart.md](generics/views/chart.md) |
| Fiscal period, quarter and year date filters | [generics/filters.md](generics/filters.md) · [field_management/custom_fields.md](field_management/custom_fields.md) |
| Public booking pages can be embedded | [booking/booking.md](booking/booking.md#embedding-blocked-slots-and-reschedule) |
| Mail display name, TLS/SSL, and the shared editor | [mail/mail.md](mail/mail.md) |
| Create a mail or notification template from the automation form | [automations/automations.md](automations/automations.md) · [mail/mail.md](mail/mail.md) |
| Pending approvers can Edit Details | [generics/views/helpers/edit_field.md](generics/views/helpers/edit_field.md) |

Also in this release: shared primary and outline buttons; history uses a date range and keeps link events of related records; datetime filters match by date; delete reassign stays in the active company; each list has its own scroll indicator; related lists show a title and description. Role hierarchy actions and chart fixes. Web-to-lead spam protection. Scoring conditions match operators and logical joins and show readable values. Customer Role on contact and opportunity relations. Cadences allow several first follow-ups. Booking explains blocked dates and slots, and reschedule uses the booking page. Call and meeting settings use the shared empty states. The dashboard detail page uses the generic navbar. Reports show the close button when the edit panel opens. The dark theme colours outline buttons and badges.

## Recent updates (16–23 Oct 2026, v1.17.0)

Platform version is **1.17.0** ([core/horilla.md](core/horilla.md)). Module versions stay on their own lines.

| Topic | Doc |
|-------|-----|
| Phone mode under `/m/` (Records, Today, log activity, Agenda) | [mobile/mobile.md](mobile/mobile.md) · [../../horilla_crm/mobile.md](../../horilla_crm/mobile.md) |
| Group-by bulk actions and viewport **Expand All** | [generics/views/groupby.md](generics/views/groupby.md) |
| Activity owners include **participants** and **meeting host** | [activity/activity.md](activity/activity.md) |
| Signed-out HTMX requests redirect to login (`HX-Redirect`) | [../../coding_rule.md](../../coding_rule.md) |

Also in this release: recycle bin **No expiry**; edit and delete dated exchange rates; Horilla 404 for `Http404`; circular roles and the last superuser are blocked. Calendar rebuilds after reload and warns when Google sync is already in that state. Meeting actions require integration to be on. Booking **view-own** users see My Bookings. Cadences require `view_cadence` and 404 a missing report. Calls block changes when integration is already off. Mail explains Test Mail on a deleted server. Reports stringify lazy labels on Excel export. Approvals respect the edit policy. CRM related forms require change access on the parent record.

## Recent updates (21–28 Aug 2026, v1.13.7)

| Topic | Doc |
|-------|-----|
| Initialize Database **Go To Home** + default CRM stages signal | [core/initialize_database.md](core/initialize_database.md) |
| Shared **settings list shell** (`#navBar` / `#mainSession`) | [core/settings_list_shell.md](core/settings_list_shell.md) |
| Company / branch **view-driven detail** fields | [core/core_app.md](core/core_app.md#view-driven-company-and-branch-detail) |
| **`horilla.views.generic`** import path | [../views/generic.md](../views/generic.md) · [coding_rule.md](../../coding_rule.md) |
| Lead / opportunity **default stage constants** | [../horilla_crm/leads/lead_stages.md](../horilla_crm/leads/lead_stages.md) · [../horilla_crm/opportunities/opportunity_stages.md](../horilla_crm/opportunities/opportunity_stages.md) |

## App index (deep dives)

| App | Primary doc |
|-----|-------------|
| **activity** | [activity/activity.md](activity/activity.md) |
| **automations** | [automations/automations.md](automations/automations.md) |
| **booking** | [booking/booking.md](booking/booking.md) |
| **cadences** | [cadences/cadences.md](cadences/cadences.md) |
| **calendar** | [calendar/calendar.md](calendar/calendar.md) |
| **core** | [core/core_app.md](core/core_app.md) (index) · [core/horilla.md](core/horilla.md) · [core/models.md](core/models.md) · … |
| **dashboard** | [dashboard/dashboard.md](dashboard/dashboard.md) · [dashboard/default_dashboard_generator.md](dashboard/default_dashboard_generator.md) |
| **duplicates** | [duplicates/duplicates.md](duplicates/duplicates.md) |
| **field_management** (custom fields) | [field_management/custom_fields.md](field_management/custom_fields.md) |
| **field_management** (field requirements) | [field_management/field_requirements.md](field_management/field_requirements.md) |
| **field_management** (form layouts) | [field_management/form_layouts.md](field_management/form_layouts.md) |
| **generics** | [generics/generics_app.md](generics/generics_app.md) · [generics/views/views_init.md](generics/views/views_init.md) · … |
| **keys** | [keys/keys.md](keys/keys.md) · [keys/default_shortcut_registration.md](keys/default_shortcut_registration.md) |
| **mail** | [mail/mail.md](mail/mail.md) |
| **mobile** (optional, off by default) | [mobile/mobile.md](mobile/mobile.md) |
| **notifications** | [notifications/notifications.md](notifications/notifications.md) |
| **process** (approvals + reviews) | [process/process.md](process/process.md) |
| **reports** | [reports/reports.md](reports/reports.md) |
| **theme** | [theme/theme.md](theme/theme.md) |
| **workflow** | [workflow/workflow.md](workflow/workflow.md) |
| **utils** (`horilla.contrib.utils`) | [utils/utils.md](utils/utils.md) |

Top-level **`horilla.utils`** (Python package, not this Django app) is documented under [../utils/utils.md](../utils/utils.md).
