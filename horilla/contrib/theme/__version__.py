"""
Version and metadata information for the theme module.
"""

# First party imports (Horilla)
from horilla.utils.translation import gettext_lazy as _

__version__ = "1.11.6"
__module_name__ = "Theme Manager"
__release_date__ = ""
__description__ = _(
    "Module providing customizable color themes and UI personalization."
)
__icon__ = "theme/assets/icons/theme.svg"

__1_11_6__ = _(
    "The selected Select2 option uses the same highlight as the hovered " "option."
)

__1_11_5__ = _(
    "Apply the theme colours to outline buttons and badges in the dark theme."
)

__1_11_4__ = _("Adopt the shared empty_state partial on theme cards.")

__1_11_3__ = _(
    "Fix dark-mode contrast regressions in the history tab, detail modal, and related "
    "surfaces."
)

__1_11_2__ = _(
    "Restore hover and active text contrast in dark mode. Fix invisible empty-state "
    "text on theme cards."
)

__1_11_1__ = _(
    "Migrated signal imports to the horilla.db.models.signals shim, standardized "
    "first-party import groups, and added docstrings for pylint compliance; "
    "theme behavior unchanged."
)

__1_10_0__ = _(
    "Release 1.10: theme management ships under contrib with app label theme. "
    "Static assets served under theme/ URLs, signals aligned to the core contrib app, "
    "and default-theme seeding coordinated with contrib post_migrate semantics."
)

__1_1_0__ = _(
    "Improved dynamic Tailwind theme integration with adoption of primary_600 "
    "for dynamic theme coloring, improved fallback handling for theme variables, "
    "and brand-aligned icon color updates across modules."
)

__1_0_0__ = _(
    "Introduced fully dynamic Theme Manager with per-company theme customization, "
    "global default theme support, dynamic Tailwind config injection, and "
    "surface color system for advanced UI backgrounds."
)
