"""Template tags for optional Calls integration — used by activity templates."""

# T
from django import template

# First party imports (Horilla)
from horilla.apps import apps

register = template.Library()


@register.simple_tag(takes_context=True)
def calls_enabled(context):
    """Return True if the calls app is installed and the current user may use it.

    The integration must be switched on for the company and the user must be
    allowed by its access control (all users, roles or specific users).
    """
    if not apps.is_installed("calls"):
        return False
    from calls.models import CallIntegrationSetting

    return CallIntegrationSetting.user_has_menu_access(context.get("request"))


@register.simple_tag
def get_phone_number(obj):
    """Return the first non-empty phone number found on any CRM model instance."""
    for field in ("contact_number", "phone", "mobile", "phone_number", "mobile_number"):
        val = getattr(obj, field, None)
        if val:
            return val
    return ""
