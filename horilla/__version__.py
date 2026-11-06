"""Module containing package metadata used by Horilla (version, name, icons)."""

from django.utils.translation import gettext_lazy as _

__version__ = "1.17.2"
__module_name__ = _("Core System")
__release_date__ = ""
__description__ = _(
    "Core system providing authentication, configuration, utilities, and platform-level services."
)
__icon__ = "assets/icons/logo.png"

__1_17_2__ = _(
    "Security: uploaded files require a login; failed sign-ins are limited "
    "on every login path; a shipped SECRET_KEY is refused; HTMX sends the "
    "live CSRF cookie; the user API stays in the requester's company; call "
    "provider webhooks must be verified. Generics: inline Edit Details for "
    "one record; condition rows take a logical operator and multi-select "
    "values, and offer department, role, company and audit fields; lists "
    "and own splits share one owner rule; the filter count updates when a "
    "pill is removed. Core: profile, user, company and branch details edit "
    "inline; fiscal years rebuild only when their structure changes, and "
    "the calendar preview opens in the full-page modal; changing language "
    "keeps the current page; the product name comes from branding. Reports "
    "and dashboards honor view-own, report filters apply to dashboard "
    "components, and a report Detail Table can be placed on a dashboard. "
    "Google Calendar access can be all users, specific roles or specific "
    "users. Workflow, cadences and automations send through registered "
    "delivery channels. Summernote full screen mode works, and long notes "
    "scroll."
)

__1_17_1__ = _(
    "Generics: shared primary and outline buttons; chart axes offer only "
    "relevant fields; one rich-text editor and Insert Fields for mail, "
    "notifications and notes; fiscal period, quarter and year relative date "
    "filters; history uses a date range and keeps link events of related "
    "records; datetime filters match by date; delete reassign stays in the "
    "active company; each list has its own scroll indicator; related lists "
    "show a title and description. Cadences: enrollments with manual Enroll "
    "and Un-enroll, and several first follow-ups. Booking: public pages can "
    "be embedded, explain blocked dates and slots, and reschedule on the "
    "booking page. Also: role hierarchy actions and chart fixes; web-to-lead "
    "spam protection; scoring condition display; mail display names; create "
    "templates from the automation form; pending approvers can Edit Details; "
    "dark-theme outline buttons and badges."
)

__1_17_0__ = _(
    "Mobile: optional phone mode under /m/ with Records, Today, log activity "
    "and Agenda; CRM models opt in from mobile.py. Generics: redesigned "
    "group-by view with bulk actions, and Expand All opens every level. "
    "Core: recycle bin No expiry; edit and delete dated exchange rates; "
    "signed-out HTMX requests go to login; Horilla 404 for missing pages; "
    "block circular roles and removing the last superuser. Also: Calendar "
    "rebuilds after reload and warns when Google sync is already in that "
    "state; Meeting checks that integration is on; Booking shows My "
    "Bookings to view-own users; Activity owner checks include participants "
    "and the meeting host; Cadences require view permission; Calls block "
    "changes when integration is disabled; Mail explains a deleted server "
    "on Test Mail; Reports export lazy labels; Approvals respect the edit "
    "policy."
)

__1_16_0__ = _(
    "Field Management: one Settings app for Custom Fields, Field Requirements "
    "and Form Layouts; Full Width; custom fields in conditions, reports, "
    "dashboards, grouping, filters and import. Generics: a record can list "
    "another record's activities, notes and emails and can be read-only; "
    "Add Column to Split View; detail values wrap with Show more; user-picker "
    "Select All across pages. Leads: assignment rules on create and "
    "email-to-lead; converted leads stay linked and show on the contact, "
    "account and opportunity. Calendar: multi-day events in the all-day row "
    "and an activity assignees modal. Also: Mail inbox owner and open "
    "tracking; Calls log modal; Automations recipient timezones; Activity "
    "related-object permission; notification dropdown and missing-record errors."
)

__1_15_3__ = _(
    "Mail: generic Inbox for fetched incoming mail; Email-to-Record creates Contacts "
    "as well as Leads. Calendar: Team members filter (user picker), status filter, "
    "custom calendars rebuilt around module activities with text colors, all-day date "
    "spanning. Generics/Core: user-picker Select All and Select2 filters; detail "
    "Next/Prev and breadcrumb fixes; hide non-editable detail/filter fields; "
    "condition-builder Operator narrowing; bulk delete/export/update dispatch; GFK "
    "history diffs; company-scoped owner FKs; export column selection; demo-data load "
    "when CRM is disabled; LoginHistory via _inherit_model. Also: Approvals pending-"
    "detail block and Record owner matching; Reviews Create/Edit triggers; Automations "
    "edge-trigger; Activity related-module opt-in and form fixes; Calls history "
    "access; Jalali history timezone."
)

__1_15_2__ = _(
    "Generics: History tab Show full text with full auditlog values, readability/"
    "theming fixes, and stale no-op diff cleanup; quick filters across view types; "
    "list views can opt out of the floating filter panel; drop empty stale filter "
    "rows; preserve return URL after Edit All; scope detail field visibility per "
    "record variant. Core: Holidays search; Import Data navbar; company edit "
    "defaults to single-step; responsive role-members height; Docker wait_for_db; "
    "second-company demo fixtures. Notifications: resilient Channels push. "
    "Calendar: Color by Status, Open Related Record, Google form errors, OAuth "
    "state harden. Also: CRM opportunity-team and forecast empty-state fixes; "
    "Activity Related To and access checks; Calls object-log 500 fix; Custom "
    "Fields hooks/extensions packages; Meeting OAuth harden; Process review-job "
    "scoping; Automations schedule UX; settings nav descriptions."
)

__1_15_1__ = _(
    'Generics: bulk "Edit Details" save on the record detail tab; skip no-op saves; '
    "form_mode for multi/single-step switching; Oldest First list view; cache field/"
    "row permission lookups; atomic form saves; hide no-value condition inputs; "
    "company filter when All Companies is off; export hook instead of a global "
    "QuerySet patch. Core: request-cache bulk field permissions; model verbose_name "
    "in user permission messages. Extension: detect Django cached_property in list "
    "attr merge. Form Layouts: offer saved layouts as a Custom Layout mode on create "
    "and edit. Also: Lead assignment rules match custom fields on create; CRM scoring "
    "O(1) compute; Calls/Process MixinExtensions; booking slot and Join-link fixes; "
    "Mail/Meeting/Activity permission and invite fixes."
)

__1_15_0__ = _(
    "Form Layouts: new Settings app to choose which fields appear on opted-in create "
    "forms (and in what order) per company; Lead and Opportunity open a trimmed "
    "single-page create form when a layout is saved. Extension: _inherit_mixin, "
    "base-class targeting, pre-compose hooks, detail_section composition, and "
    "super() chaining across stacked extensions; Custom Fields, Cadences, and "
    "Duplicates move onto real View/Form/Filter extensions. Generics/Core: cache "
    "related-list parent objects; cut ContentType N+1 in full_histories; attach "
    "related_obj on kanban/detail pipelines; refresh recently viewed and kanban "
    "after settings; per-company settings cache; SITE_URL for public links; "
    "sub-sidebar hx-select-oob. Also: Calendar/Reports/Cadences query reductions, "
    "Dashboard chart resize after HTMX, Activity event due-date and mail backend "
    "fixes, Docker Celery after migrations."
)

__1_14_0__ = _(
    "Custom Fields: new Settings app to define extra fields on Leads and Opportunities "
    "(text, long text, number, choice) and surface them on create/edit forms, detail "
    "views, list columns, filters, and exports. Extension: introduce and wire "
    "_inherit_tab for HorillaTabView composition. Generics: empty permission names "
    "allowed; skip Copy suffix for phone/empty duplicates; extensible custom_layouts "
    "with deduped navbar layout toggle; HTMX on fragment-only endpoints; detail-grid "
    "overflow fix; harden single-form invalid submit. Core: Shift Hour week-day "
    "styling; role users list scroll. Utils: runserver progress bar and Horilla "
    "version banner. Web/Menu: HttpRequest re-export, ScriptResponse reload helper, "
    "floating menu when any required permission is present. API: close cross-tenant "
    "and privilege-escalation gaps in the shared DRF layer. Also: CRM scoring/"
    "stages/web-to-lead hardening, Mail/Activity/Workflow/Duplicates/Booking/Calls/"
    "Reports/Dashboard/Calendar/Keys/Cadences/Field Requirements/Jalali updates."
)

__1_13_8__ = _(
    "Generics: granted (non-owner) record access across list, detail, kanban, search, and "
    "bulk flows; derive list/detail column labels from model verbose_name without extra DB "
    "fetches; shared empty_state and activate_company partials; my_settings_list_shell for "
    "My Settings lists; shared is_active toggle column; stop forcing verbose names to title "
    "case; quieter generic history/audit display with model names and safer non-date diffs; "
    "related-list header restyle; wrap long note text; cursor-pointer on more clickable "
    "controls. Core: cache available companies in the context processor; stream export "
    "generation; indexes on frequently filtered fields; register Field Requirements in "
    "INSTALLED_APPS. UI: reposition overflowing Summernote toolbar dropdowns; history and "
    "layout CSS tweaks."
)

__1_13_7__ = _(
    "Generics: stretch list columns on wide viewports; collapsible day-accordion history tab "
    "with cleaned rich-text and long values in diffs; Add button on empty-state list views; "
    "fix column sort in tab and related-list fragments; show and edit state as subdivision "
    "name not code; fix drag-handle visibility on permissioned columns. Core: shared "
    "settings_list_shell for settings list pages; Initialize Database Go To Home with "
    "default lead and opportunity stages via initialize_database_go_home; view-driven company "
    "and branch detail fields; normalize Title Case verbose_name labels; exclude extension "
    "model classes from permission listings; fix Role init Next Step button wrap; "
    "horilla.views.generic View/FormView/ListView/DetailView re-exports; f-strings in "
    "get_object_or_404. UI: dark-mode contrast fixes in history and detail surfaces; keep "
    "multi-select dropdowns open after selection; djangofmt on shared layout and template "
    "partials."
)

__1_13_6__ = _(
    "Generics: nested multi-level group-by with lazy-loaded subtrees; distinguish empty "
    "list vs no filter matches; restore empty groups, company-scope FK groups, and Group By "
    "Settings; reuse list empty-state markup in chart/split views; restrict quick filters to "
    "plain list layout; viewport-fit list and detail tables; open-in-new-tab only for "
    "previewable attachments; delete-modal Cancel contrast; navbar second_button font size. "
    "Core: Horilla DetailView wrapper and package re-export; TemplateView fieldsets for My "
    "Profile; settings fieldsets via shared includes; user number_format drives currency/"
    "number display; gate Regional Formatting behind can_change_profile; company-scope User "
    "Kanban/Group-By; avoid N+1 in permission utils and role hierarchy; scope import/export "
    "and settings-search spinners; stepper theming and Excel sample-data fixes; demo user "
    "departments; SHORT_TO_DAY_PREFIX in BusinessHourForm. UI: full-page Connection Lost on "
    "HTMX sendError / ERR_CONNECTION_REFUSED with Retry; runtime viewport fit for settings "
    "lists; center read-only field lock icon. I18N: Persian catalog expansion with bulk-update "
    "and RTL breadcrumb fixes."
)

__1_13_5__ = _(
    "Extension: DateTimeFormatter with _inherit_formatter; _inherit_view composition "
    "for View/ListView (including EditFieldView); FormView applies _inherit_form; "
    "fieldsets_insert on _inherit_detail; form fieldsets merge so extensions can "
    "inject fields. Generics: parse edit/list/bulk dates through DateTimeFormatter; "
    "preserve image uploads across single-step validation errors; scope list-view "
    "navigation session keys per model with opt-out; populate Available Fields for "
    "mixed-column views; list-cell-border CSS classes; user detail sections driven "
    "by HorillaDetailView fieldsets. Core: demo fixtures for contrib and CRM apps "
    "(batched password derivation, roles, country-coded phones); AuditlogMiddleware; "
    "Add Column to List on branches; regional formatting rendered from form fieldsets; "
    "shared accent-color default for color inputs; rename Update to Edit; remove "
    "settings-search spinner; fix duplicate Core System version card and Export Data "
    "after Esc or HTMX tab navigation. API: enforce HorillaModelPermissions on "
    "main-table endpoints. UI: RTL foundation and main-shell mirroring."
)

__1_13_4__ = _(
    "Generics: multi-select choice and foreign-key filters; permission-gated user chips for "
    "User FK fields (without leaking raw HTML into the details tab); live avatar preview on "
    "image fields; navbar descriptions; prioritize the full-detail action; deny bulk update "
    "and hard-delete when the user lacks change/delete permission; refine navbar, tab, and "
    "settings layouts. Utils: add horilla.utils.html, text, and functional shims. API: move "
    "shared docs, mixins, and permissions to horilla.api. Core: require permission before "
    "toggling cross-company visibility; prefer profile image in get_avatar; store relative "
    "referer URLs with full-nav fallback; extract template BUILTINS and LOADERS. UI: "
    "mask-image nav/sidebar icons and restore theme-colored hover states in dark mode. "
    "Added Persian (fa) language support."
)

__1_13_3__ = _(
    "Generics: AND/OR logic between filter rows; default new-record time zone to the user's "
    "zone; CheckboxGridSelect for weekday/multi-option grids; stop hidden multi-step fields "
    "from reappearing on other steps; cap form modal body height with max-h instead of fixed "
    "h-[500px]. Settings: content search over the Settings sidebar; fiscal year modal body "
    "can shrink below its max height; Business Hour per-day times grouped into day cards. "
    "UI: move header notification/theme script into global.js; stop Select2 multi-select "
    "clipping of wrapped choices; realign viewport-height offsets with the 60px header."
)

__1_13_2__ = _(
    "Export: added export/export_own permissions with optional column selection for one-off and "
    "scheduled exports, plus get_export_queryset and is_exportable_field helpers used by core, "
    "bulk, list, and report export paths. Generics: relative date filter operators (Today, "
    "Yesterday, This Week, This Month); PhoneField validation; inline edit validation errors; "
    "preserve export modal content on Escape; keep MultiWidget structure on hidden multi-step "
    "fields; replace delete-view alert() with the message framework; fix related-list "
    "no-else-continue; update split-view detail tab width. UI: compact header to 60px with "
    "refined search and action buttons; replace dots.svg menus with consistent SVG icons. "
    "Core: wrap form placeholders with gettext_lazy."
)

__1_13_1__ = _(
    "Added ScriptResponse and HxTriggerResponse for shared HTMX modal, reload, and "
    "htmx.trigger script returns. Generics: show a loading spinner on the Save & New button. "
    "Core: guard missing model on field-permission save, validate recycle-bin retention days, "
    "and return 405 for POST on fiscal-year HTMX field endpoints."
)

__1_13_0__ = _(
    "Registered the Calls app in INSTALLED_APPS and wired calls WebSocket routes into ASGI. "
    "Generics: inline edit supports phone fields with the country-code widget. "
    "Trusted X-Forwarded-Proto and X-Forwarded-Host so request.is_secure() and "
    "build_absolute_uri() work behind reverse proxies and dev tunnels."
)

__1_12_4__ = _(
    "Core: added get_allowed_user_ids() for subordinate-aware ownership and fixed "
    "sync_role_permissions_on_role_change to assign role permissions to new users via "
    "transaction.on_commit. Generics: unified record-level access with check_record_access(), "
    "check_record_change_access(), and check_record_delete_access(); extended view_own "
    "filtering to global search, detail tabs, mail compose and drafts, notes and attachments, "
    "related lists, and activity sections. Parent-record change and delete access now gates tab "
    "actions, add buttons, and col_attr row links; callable action labels, icons, and hidden_if "
    "supported in render_action_button. HorillaModelForm skips ownership filtering when the user "
    "has global view permission. Fixed HorillaSingleDeleteView model resolution, "
    "ColumnSelectionForm self.data access, sanitize_html font-colour passthrough, and "
    "related-list add-column permission and URL handling."
)

__1_12_3__ = _(
    "Redesigned sidebar to a fixed-width icon-nav with text labels and corrected the "
    "sub-sidebar toggle button position when collapsed. Extension framework: renamed "
    "model _inherit to _inherit_model across metaclass, registry, and migration ops. "
    "Core: auto-sync user permissions when a role changes via signals; filter "
    "allowed_users by active company in OwnerQuerysetMixin. Generics: fixed Add Column "
    "to List in tabbed list views."
)

__1_12_2__ = _(
    "Added IP-based brute-force lockout on login and uniform forgot-password responses to "
    "prevent user enumeration. Fixed local settings to apply after app extensions. "
    "Generics: fixed filter-panel toggle in tabbed views with duplicate element IDs; "
    "sanitized notes-and-attachments fields against XSS and updated delete-button styling "
    "with themed icons. Menu: improved sub-sidebar active-link detection and unique item IDs."
)

__1_12_1__ = _(
    "Extension tests now use contrib.core examples instead of CRM-specific modules. Added "
    "centralized sanitize_html and sanitize_plain_text helpers with bleach CSS allowlisting, "
    "Summernote DOMPurify mirroring, CSV/XLSX cell sanitization against formula injection, "
    "and notification template XSS sanitization with validation-error field clearing. Fixed "
    "generics Select2 edit-mode FK filtering by loading parent instances via all_objects and "
    "scoping request.active_company to the record tenant; fixed navbar search losing focus by "
    "removing hx-select-oob/hx-preserve. Core: restricted login history to the current user, "
    "improved role empty state, refined User and RegionalFormatting forms, showed company on "
    "ChangeUserCompanyForm, debounced saveActiveTab for SQLite, and rendered readable user-agent "
    "details in login history. Registered static, i18n, and horilla_tags as template builtins."
)

__1_12_0__ = _(
    "Expanded extension framework with _inherit_form, _inherit_list, _inherit_card, "
    "_inherit_filter, _inherit_nav, _inherit_kanban, and _inherit_detail composition with "
    "caching and per-request resolution. Introduced PhoneWidget and PhoneField for "
    "international phone numbers. Fixed generics bulk-delete Prefetch slicing, action button "
    "text wrapping, and HolidayForm user-selection defaults. Centralized horilla.db "
    "transaction and connection imports and standardized first-party import groups."
)

__1_11_1__ = _(
    "Custom CSRF failure view and csrf_failure.html for DEBUG=False. CSRF protection "
    "restored on state-mutating stage and calendar-preference views. FiscalYear, "
    'RegionalFormatting, Company, and User forms switched to fields="__all__" with '
    "field_order and keep_on_form so HorillaModelForm base fields are no longer dropped, "
    "with sensitive user fields excluded. Business Hour add-button hides without reload, "
    "and BusinessHourHolidayModalView is guarded for deleted records. Generics skip M2M "
    "relations in bulk-delete to avoid ProtectedError and add cursor-pointer to note, "
    "attachment, and related-list actions. Added horilla.utils.timezone and "
    "horilla.db.models.signals shims, standardized first-party import groups, and broad "
    "docstring coverage for pylint compliance."
)

__1_11_0__ = _(
    "Workflow automation engine (rules, conditions, actions, Celery time triggers, "
    "execution history). Public booking platform with slots, public pages, reminders, "
    "and booking/activity integration. ERP-style _inherit model extensions with "
    "InjectField and extension-owned migrations. ShiftHour scheduling and BusinessHour "
    "enhancements with holiday support. HTMX-first UX, multi-step form refactors, "
    "django-countries subdivisions, permission inheritance fixes, activity/booking mail "
    "templates, and Django 6.0 generics stability improvements."
)

__1_10_1__ = _(
    "Meeting Integration contrib app (Zoom/Teams OAuth, meeting links, activity hooks). "
    "Generics export and JSONField display improvements. My Profile panel scrolls within "
    "a fixed viewport. Calendar Google settings respect active company on POST. "
    "Scheduled automations use corrected Celery task paths."
)

__1_10_0__ = _(
    "Major platform 1.10 layout: support apps consolidated under the contrib namespace with "
    "short Django app labels (activity, core, mail, theme, and related modules). "
    "AppLauncher configs, imports, URL namespaces, static paths, and permission "
    "or content-type strings updated to match the new labels. "
    "Added sync tooling to align migration records, content types, audit "
    "log references, and related data when upgrading existing databases."
)


__1_9_0__ = _(
    "Added Google Calendar integration with sync, service, and settings support. "
    "Implemented cadence signals for runtime activities. Centralized HorillaView "
    "layout resolution with get_layout_url() for backend-driven layout selection."
)


__1_8_1__ = _(
    "Switched Channels backend from InMemoryChannelLayer to RedisChannelLayer. "
    "Moved Holiday model to dedicated holidays.py. Improved branch list layout, "
    "business hour and holiday bulk select, and viewport-based table heights. "
    "Added SECURITY.md documentation."
)


__1_8_0__ = _(
    "Introduced unified Process Builder system combining reviews and approvals. "
    "Added async notification and mail handling with background thread execution. "
    "Improved health check endpoint and version changelog modal system. "
    "Updated assign_first_company_to_all_users signal to use User model directly."
)


__1_7_0__ = _(
    "Strengthened core validation with strict enforcement of include_models during "
    "feature registration, validation of subsection-to-section mappings, and export "
    "of StreamingHttpResponse via Horilla HTTP utilities."
)


__1_6_0__ = _(
    "Added health check endpoint, synced fiscal year and period logic, "
    "improved version changelog modal system, and switched Django Channels "
    "backend to Redis for better performance and reliability."
)


__1_5_0__ = _(
    "Improved global search model registry loading, standardized error handling "
    "with dedicated 403, 404, 405, and 500 templates, strengthened authentication "
    "flow using Django authenticate(), and applied multiple security and "
    "stability improvements across internal views."
)


__1_4_0__ = _(
    "Introduced the Horilla AppLauncher system for dynamic application "
    "registration. Added horilla.shortcuts, horilla.urls, and horilla.utils "
    "utilities. Refactored project URL handling and improved internal "
    "framework architecture for modular applications."
)


__1_2_0__ = _(
    "Improved system configuration handling, strengthened dashboard layout "
    "validation, enhanced filter processing reliability, and added multiple "
    "defensive validation improvements across core components."
)


__1_1_0__ = _(
    "Added an 'All Companies' option to the company dropdown, allowing users "
    "to view data irrespective of company selection."
)
