"""
HTML registration for the Tour app.

The tour panel, popover and message card are rendered through the
``body_end`` slot (the same hook the theme and mobile apps use).
"""

# First party imports (Horilla)
from horilla.registry.asset_registry import register_html

register_html("tour/slots/launcher.html", slot="body_end", priority=90)
