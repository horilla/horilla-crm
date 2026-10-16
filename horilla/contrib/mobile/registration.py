"""
Asset registration for the mobile app.
"""

# First party imports (Horilla)
from horilla.registry.asset_registry import register_html

from .utils import MOBILE_PAGE

# Same RTL font and stylesheet the desktop layout and login page get.
register_html(
    "inject_html/rtl_assets.html",
    slot="head_end",
    priority=90,
    page=MOBILE_PAGE,
)
