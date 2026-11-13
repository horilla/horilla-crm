"""Version and metadata for the calls app."""

from horilla.utils.translation import gettext_lazy as _

__version__ = "1.11.16"
__module_name__ = _("Calls Integration")
__release_date__ = ""
__description__ = _(
    "Telephony integration for click-to-call from CRM records, multi-provider "
    "support (Twilio, SignalWire(Beta), Telnyx(Beta), Sinch(Beta), Exotel(Beta), call logging, agent "
    "mapping, and company-level access control."
)
__icon__ = "assets/fontawesome/svgs/solid/phone.svg"

__1_11_16__ = _(
    "Call integration settings no longer fail when no company is active, "
    "and the access modals return to that page. Calls are included in "
    "global search, and list search covers call fields."
)

__1_11_15__ = _(
    "Reject provider webhooks that cannot be verified. Limit click-to-call "
    "to users with call access, and handle a missing or disabled provider. "
    "Refresh the call status modal from webhooks and show the real call "
    "outcome. Use one Call Settings card for the enabled and disabled "
    "states, with the feature-disabled empty state when integration is off."
)

__1_11_14__ = _(
    "Use the shared empty states on call integration settings. Access "
    "options show how to activate them and open roles and users in a modal. "
    "The providers tab keeps a labeled Setup Guide, and the provider list "
    "scrolls instead of stretching its empty state."
)

__1_11_13__ = _(
    "Show a success message when call access settings are saved. Block "
    "access and provider changes when call integration is already disabled."
)

__1_11_12__ = _(
    "Open call log details in a modal and clarify the provider setup guides. "
    "Stop the Call History empty state from covering the tab buttons. Show "
    "allowed users and roles as pills. Disable Call Now on a locked record."
)

__1_11_11__ = _(
    "Gate the Call History tab on the related record's own access; stop "
    "registering Call Log as an always-on related activity target."
)

__1_11_10__ = _(
    "Return an empty queryset instead of 500 when Object Call Log list lacks a "
    "valid object_id."
)

__1_11_9__ = _(
    "Replace shared action-list mutation with a MixinExtension for list actions."
)

__1_11_8__ = _(
    "Cache call integration settings per company via the shared company "
    "settings cache helpers."
)

__1_11_7__ = _(
    "Prefer Horilla import shims for apps, signals, and timezone. Close cross-tenant "
    "and privilege-escalation gaps in the Calls API."
)

__1_11_6__ = _(
    "Derive call-log list column labels from model verbose_name instead of hardcoded "
    "translations."
)

__1_11_5__ = _(
    "Raise requests.HTTPError and ValueError instead of bare Exception in Exotel adapter "
    "error handling."
)

__1_11_4__ = _(
    "Apply runtime viewport fit on Calls integration settings and provider tabs."
)

__1_11_3__ = _("Fix TemplateSyntaxError crashing the calls user-settings page.")

__1_11_2__ = _(
    "Lock down the calls API to company members with granted access."
    "Seed default call reports for the report engine."
)

__1_11_1__ = _(
    "Adopted ScriptResponse and HxTriggerResponse for provider and call-log actions. "
    "Preserved exception context when Exotel and SignalWire return non-JSON responses."
)

__1_11_0__ = _(
    "Initial release: multi-provider telephony (Twilio, SignalWire(Beta), Telnyx(Beta), Sinch(Beta), "
    "Exotel(Beta), Mock) with adapter factory; company enable/disable and role/user access "
    "control; Click-to-Call modal with HTMX live status, cancel, and recording toggles; "
    "CallLog history with Activity Timeline integration; agent mapping; secure "
    "credential storage; Settings → Integrations and My Settings UIs; REST API and "
    "webhook/WebSocket consumers."
)
