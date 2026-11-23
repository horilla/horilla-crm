"""
Tour menu registrations.

The product tour opens from the header account dropdown.
"""

from horilla.menu import header_menu
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _


@header_menu.register
class ProductTours:
    """Header account-menu entry that opens the product tour panel."""

    title = _("Product Tours")
    url = "#"
    order = 20
    attrs = {
        "id": "horilla-tour-launcher",
        "aria-haspopup": "dialog",
        "aria-expanded": "false",
        "aria-controls": "horilla-tour-panel",
        "hx-get": reverse_lazy("tour:panel"),
        "hx-vals": "js:{path: window.location.pathname}",
        "hx-target": "#tour-panel-content",
        "hx-indicator": "#tour-panel-loading",
    }
