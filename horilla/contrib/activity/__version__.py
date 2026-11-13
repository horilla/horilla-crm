"""Version information for the horilla.contrib.activity module."""

from horilla.utils.translation import gettext_lazy as _

__version__ = "1.11.21"
__module_name__ = "Activity"
__release_date__ = ""
__description__ = _(
    "Module for tracking and managing activities such as tasks,calls, events, and emails."
)
__icon__ = "activity/assets/icons/activity-red.svg"

__1_11_21__ = _(
    "Other apps can add tabs on the Activity tab. The task list loads once, "
    "so the saved Completed sub-tab stays selected. The log-call type is "
    "labelled Call. Activities are included in global search, and list "
    "search covers activity fields."
)

__1_11_20__ = _(
    "Offer activities as report fields and dashboard components. "
    "Click-to-call on an activity follows call access."
)

__1_11_19__ = _(
    "Treat participants and the meeting host as owners, so view-own, "
    "change-own and delete-own include them and meeting activities match "
    "the calendar."
)

__1_11_18__ = _(
    "Limit related-object choices to records the user can view. Enable "
    "notification templates for Activity. Show a Related To cell and plain "
    "status on rows listed from another record. Use the field label when a "
    "date cannot be in the past."
)

__1_11_17__ = _(
    "Limit related-record and custom calendar modules to opted-in models; fix "
    "Assigned To for all activity types, Related To save from Edit Details, and "
    "detail breadcrumbs; all-day form and date handling with calendar."
)

__1_11_16__ = _(
    "Add Related To tab and related-object list column; tighten field visibility "
    "and row-access checks; stop Add Column from offering unrelated fields."
)

__1_11_15__ = _(
    "Let users with full model permission list Task/Meeting/Call/Event tabs on a "
    "record. Fix TypeError when sending meeting invite emails."
)

__1_11_14__ = _(
    'Stop a false "Due Date cannot be in the past" error on Event creation. '
    "Use datetime.timedelta directly in the meeting reminder task."
)

__1_11_13__ = _(
    "Reject past dates for task due date and meeting/event start-end. Fix email pill "
    "suggestion-click race on activity and meeting forms. Gate email features on "
    "outgoing mail configuration; close cross-tenant gaps in the Activity API."
)

__1_11_12__ = _(
    "Derive list column labels from model verbose_name; stop forcing create-view labels "
    "to title case; wrap remaining user-facing strings with gettext; quieter history/"
    "audit display for activity models."
)

__1_11_11__ = _("Stop duplicate HTMX loads and excess requests on activity tabs.")

__1_11_10__ = _("Apply runtime viewport fit on activity tabs and type-tab list views.")

__1_11_9__ = _(
    "Prioritize the Duplicate list action on global and tab activity list views."
)

__1_11_8__ = _(
    "Fix TaskCreateForm refresh targeting #TaskTab so new tasks appear without a full "
    "reload; enable table_auto on activity tab list views so sticky Actions columns are "
    "not clipped. Meeting create: harden invite permissions, timezones, and Meet link "
    "handling. Clear email suggestions on blur for activity and meeting forms."
)

__1_11_7__ = _(
    "Registered Activity for export_data. Improved activity tab hover styles and replaced "
    "fixed viewport list widths with flex-based layout."
)

__1_11_6__ = _(
    "Optional Calls integration without a hard dependency: calls_enabled and "
    "get_phone_number template tags gate Call Now in the activity tab when the Calls "
    "app is installed. CallListView excludes telephony-purpose logs from the manual "
    "call history list. Activity create form excludes call_duration_display."
)

__1_11_5__ = _(
    "Simplified mail visibility so can_send_mail and can_view_mail follow parent-record "
    "change and view access. Activity tab Edit/Delete actions and email Send/Cancel/Snooze "
    "actions are gated on parent-record change/delete access with subordinate-aware "
    "ownership via get_allowed_user_ids()."
)

__1_11_4__ = _(
    "Constrained activity tab list table height for consistent scrolling. Added "
    "cursor-pointer to Pending and Completed Calls sub-tabs."
)

__1_11_3__ = _(
    "Disabled base owner_filtration on EmailListView. Centralised get_main_url in the "
    "list-view mixin and fixed tab-calls typo in status update and activity tab template. "
    "Task and activity creates now navigate directly to the correct tab instead of "
    "reverting to the first tab after reload; aligned task-create reload trigger with "
    "project-wide jQuery convention. Fixed delete and bulk-action views that reverted "
    "to the wrong tab."
)

__1_11_2__ = _(
    "Fixed call duration field ordering and removed redundant validation; history tab now "
    "correctly identifies CallLog entries and displays call status. Use load_branding() TITLE "
    "as the fallback company name in meeting invitation emails. Allow ActivityView for users "
    "with view_own_activity as well as view_activity. Added meeting provider choices (Zoom, "
    "Google Meet, Microsoft Teams) on the Activity model."
)

__1_11_1__ = _(
    "Email-tab permissions corrected to add/view/change/delete own-record checks. "
    "Removed redundant fields attributes from create-view forms superseded by form_class. "
    "Adopted the utils.timezone shim, standardized first-party imports, and added "
    "class and method docstrings for pylint compliance."
)

__1_10_2__ = _(
    "Activity forms aligned with ModelForm layout: field_order, "
    'Meta.fields = "__all__", and Meta.exclude; save logic and HTMX behavior unchanged.'
)

__1_10_1__ = _(
    "Meeting integration in activities: schedule meetings from activities, send invites "
    "and reminders, and display generated Zoom/Teams meeting links on activity records."
)

__1_10_0__ = _(
    "Release 1.10: activity ships under contrib with app label activity. "
    "AppLauncher, imports, namespaces, registrations, templates, and metadata "
    "references updated from the legacy activity package name to the contrib layout."
)

__1_2_1__ = _(
    "Reduced redundant history entries, improved Many-to-Many field representation, "
    "and added cleaner labels for mail events and activity creation with "
    "new template filters for better rendering."
)

__1_2_0__ = _(
    "Improved activity workflow behavior. The Pending tab now shows all incomplete activities"
    "regardless of status label, and activity type configuration handling was enhanced "
    "for improved workflow accuracy."
)


__1_1_0__ = _(
    "Migrated from AppConfig to AppLauncher and replaced utilities with"
    "utils.decorators, utils.translation, and shortcuts where applicable."
)
