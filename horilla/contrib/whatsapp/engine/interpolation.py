"""
Variable interpolation for Bot Rule node config: `{{ namespace.path }}`.

Namespaces:
  variables.<key>    - session.variables[key]
  conversation.<field> - a whitelisted field on the linked WhatsAppConversation
  record.<field>     - a field on session.related_to (the linked CRM record)
  now                - current timestamp (bare token, no dot-path)

Unresolvable paths render as an empty string; interpolation never raises.
"""

# Standard library imports
import re

# Third-party imports (Django)
from django.utils import timezone

_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z_][\w.]*)\s*\}\}")

_CONVERSATION_SAFE_FIELDS = {"contact_number", "contact_name", "status"}


def _resolve(path, session):
    """Resolve one dotted path against a session's variables/conversation/record."""
    if path == "now":
        return timezone.now().isoformat()

    namespace, _, rest = path.partition(".")

    if namespace == "variables":
        return (session.variables or {}).get(rest, "")

    if namespace == "conversation":
        if rest not in _CONVERSATION_SAFE_FIELDS:
            return ""
        return getattr(session.conversation, rest, "") or ""

    if namespace == "record":
        record = session.related_to
        if record is None or not rest:
            return ""
        try:
            value = record
            for part in rest.split("."):
                value = getattr(value, part)
            return value if value is not None else ""
        except AttributeError:
            return ""

    return ""


def interpolate(template, session):
    """Substitute every `{{...}}` token in `template` (a string) for `session`."""
    if not isinstance(template, str):
        return template

    def _sub(match):
        value = _resolve(match.group(1), session)
        return str(value)

    return _TOKEN_RE.sub(_sub, template)


def interpolate_value(value, session):
    """Recursively interpolate string leaves within dicts/lists; pass other types through."""
    if isinstance(value, str):
        return interpolate(value, session)
    if isinstance(value, dict):
        return {key: interpolate_value(val, session) for key, val in value.items()}
    if isinstance(value, list):
        return [interpolate_value(item, session) for item in value]
    return value


def interpolate_dict(mapping, session):
    """Interpolate every value in a flat/nested dict of config values."""
    return interpolate_value(mapping or {}, session)
