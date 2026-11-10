"""
Horilla html - re-exports django.utils.html for consistent imports.

Use: from horilla.utils.html import format_html
     from horilla.utils.html import escape, strip_tags, ...
"""

import json

from django.utils.html import (
    avoid_wrapping,
    conditional_escape,
    escape,
    escapejs,
    format_html,
    format_html_join,
    html_safe,
    json_script,
    linebreaks,
    strip_spaces_between_tags,
    strip_tags,
    urlize,
)
from django.utils.safestring import mark_safe

__all__ = [
    "js_json",
    "avoid_wrapping",
    "conditional_escape",
    "escape",
    "escapejs",
    "format_html",
    "format_html_join",
    "html_safe",
    "json_script",
    "linebreaks",
    "strip_spaces_between_tags",
    "strip_tags",
    "urlize",
]


_JS_JSON_ESCAPES = {
    ord("<"): "\\u003c",
    ord(">"): "\\u003e",
    ord("&"): "\\u0026",
    0x2028: "\\u2028",
    0x2029: "\\u2029",
}


def js_json(value, **kwargs):
    """
    Serialize ``value`` to JSON that is safe to embed inside an inline
    ``<script>`` block (e.g. ``var x = {{ x_json }};``).

    ``<``, ``>``, ``&`` and the JS line separators are escaped so user data
    such as ``</script><img onerror=...>`` can never close the script tag.
    """
    return mark_safe(json.dumps(value, **kwargs).translate(_JS_JSON_ESCAPES))
