"""
Template tags for the mobile layout.
"""

# Third-party imports (Django)
from django import template
from django.templatetags.static import static
from django.utils.http import urlencode

# Local imports
from ..utils import get_asset_version

register = template.Library()


@register.simple_tag
def mobile_static(path):
    """
    Return the static URL for ``path`` with the mobile asset version appended.

    Only URLs built with this tag are cached by the mobile service worker.
    """
    url = static(path)
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode({'v': get_asset_version()})}"
