"""Version information for the horilla mail module."""

# First party imports (Horilla)
from horilla.utils.translation import gettext_lazy as _

__version__ = "1.11.18"
__module_name__ = "Mail"
__release_date__ = ""
__description__ = _(
    "Module for managing incoming and outgoing emails through mail servers and Outlook."
)
__icon__ = "assets/icons/icon1.svg"

__1_11_18__ = _(
    "Add the Mail Server step to Get started. A mail's outcome shows on the "
    "parent record's History. List pages use the field-aware search, and "
    "list search covers mail fields."
)

__1_11_17__ = _(
    "Automation mail is sent through the shared mail delivery channel, so "
    "other apps can add channels without importing Mail. Mail history uses "
    "the product name from branding."
)

__1_11_16__ = _(
    "Use the triggering user's name as the sender only when Dynamic Display "
    "Name is off. Hide Display Name when that setting is off, reject TLS "
    "and SSL both set to Yes, and add help text on the mail configuration "
    "fields. Mail templates use the shared rich-text editor and Insert Fields."
)

__1_11_15__ = _(
    "Show the missing-record message when Test Mail is used on a deleted "
    "mail server."
)

__1_11_14__ = _(
    "Ask for the owner when adding an inbox email as a Lead or Contact, with "
    "rule assignment for leads. Stop counting self-opens and direct visits as "
    "email opens. Require add permission on the outgoing server form and an "
    "HTMX request on inbox delete. Format the inbox received time with the "
    "user's datetime format."
)

__1_11_13__ = _(
    "Add a generic Inbox for fetched incoming mail with preview and row actions; "
    "keep both Inbox row actions visible (disabled when unavailable)."
)

__1_11_12__ = _("Fix outgoing mail picking an unrelated HorillaMailConfiguration.")

__1_11_11__ = _("Fix mail backend issue #39.")

__1_11_10__ = _(
    "Validate outgoing mail configuration before enabling email-dependent features. "
    "Prevent HorillaMail validation crash for system-triggered emails. Fix suggestion-"
    "click race dropping email pill selection. Harden mail config, display-name, and "
    "Outlook paths; close cross-tenant gaps in the Mail API."
)

__1_11_9__ = _(
    "Redirect anonymous users to login on draft actions instead of 403. Add missing "
    "verbose_name on model fields used as list/detail columns; derive column labels from "
    "verbose_name; quieter history/audit display; indexes on frequently filtered fields; "
    "cursor-pointer on clickable controls; wrap remaining strings with gettext."
)

__1_11_8__ = _(
    "Use requests.HTTPError and RuntimeError in Outlook token refresh and send paths. "
    "Fix mail template audit fields, dropdown, and list rendering."
)

__1_11_7__ = _(
    "Apply runtime viewport fit on mail server and mail history settings lists."
)

__1_11_6__ = _(
    "Email pills and suggestions templates accept override URLs so non-Mail callers are "
    "not forced through Mail permission checks. Clear the suggestions dropdown on blur "
    "regardless of whether the typed value is a valid email."
)

__1_11_5__ = _("Registered Mail for export_data.")

__1_11_4__ = _(
    "Added send_by ForeignKey on Mail to record the sending user. Introduced "
    "Mail History settings view with filter, navbar, and list actions for sent, scheduled, "
    "and draft mails. Parent-record access gates mail compose, draft save/discard, and "
    "delete flows. Standardized exception chaining across serializers, backends, and "
    "template views."
)

__1_11_3__ = _(
    "Fixed mail preview context leak, false-positive XSS block, and IDOR access check. "
    "Corrected MailTemplateListView permissions and row-attr shape. Persist rendered "
    "subject and body snapshot at send time. Fixed mail preview modal styling "
    "inconsistencies."
)

__1_11_2__ = _(
    "Fixed mail and notification template creation by assigning created_by and updated_by "
    "before save when _thread_local.request is unavailable. Added mail configuration detail "
    "modal with list row click-through and channel-specific edit and delete URLs. Sanitize "
    "mail subject and body XSS with shared helpers and centralized sanitize_html in preview "
    "and detail views. Clear mail template body on validation errors to prevent re-displaying "
    "rejected content."
)

__1_11_1__ = _(
    "Security: fixed SSTI information disclosure and IDOR in the preview endpoint by "
    "blocking dangerous template paths and adding a per-object permission check. "
    "Mail permissions replaced admin-config perms with correct add/view/change/"
    "delete own-record permissions across all mail views and the activity email tab. "
    "Standardized first-party imports and added docstrings for pylint compliance."
)

__1_10_1__ = _(
    "Mail forms aligned with ModelForm layout: field_order, "
    'Meta.fields = "__all__", Meta.exclude, and keep_on_form on configuration forms.'
)

__1_10_0__ = _(
    "Release 1.10: mail ships under the contrib package tree with Django app label mail. "
    "Imports, API routes, URLs, permissions, templates, and static asset paths "
    "updated to drop the legacy prefixed mail app name."
)

__1_1_2__ = _(
    "Improved mail template standardization, async mail handling with "
    "background thread execution, and enhanced notification and mail "
    "action separation for approval workflows."
)

__1_1_1__ = _(
    "Minor compatibility improvements and internal stability updates "
    "to align with the enhanced generics framework and visualization system."
)
__1_1_0__ = _(
    "Migrated from AppConfig to AppLauncher and and replaced"
    "utilities with utils.decorators, utils.translation, and shortcuts where applicable."
)
