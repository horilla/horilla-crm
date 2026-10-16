"""
Version and metadata information for the mobile module.
"""

# First party imports (Horilla)
from horilla.utils.translation import gettext_lazy as _

__version__ = "1.0.0"
__module_name__ = "Mobile"
__release_date__ = ""
__description__ = _(
    "Optional installable phone mode under /m/ for quick on-the-go work."
)
__icon__ = "favicons/android-chrome-192x192.png"

__1_0_0__ = _(
    "Installable phone shell under /m/: mobile layout, login and logout, "
    "a web app manifest and a service worker that only caches versioned "
    "static files."
)
