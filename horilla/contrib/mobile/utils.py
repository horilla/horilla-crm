"""
Helpers shared by the mobile views, templates and service worker.
"""

# First party imports (Horilla)
from horilla.__version__ import __version__ as PLATFORM_VERSION

from .__version__ import __version__ as MOBILE_VERSION

# Page name the mobile layout passes to ``load_registered_html``. Other apps
# can inject head/body fragments into the phone layout with
# ``register_html(..., page=MOBILE_PAGE)``.
MOBILE_PAGE = "mobile"

# Prefix of every cache the service worker creates, so it can delete the
# caches of older versions without touching anything else on the origin.
CACHE_PREFIX = "horilla-mobile-"


def get_asset_version():
    """
    Return the version stamp added to static URLs on mobile pages.

    The service worker only caches static files whose ``v`` query parameter
    equals this stamp. It changes with every platform or mobile release, so a
    deploy gets a new cache instead of serving the previous release's files.
    """
    return f"{PLATFORM_VERSION}-{MOBILE_VERSION}"
