"""
Version and metadata information for the keys module.
"""

# First party imports (Horilla)
from horilla.utils.translation import gettext_lazy as _

__version__ = "1.11.6"
__module_name__ = "Short Keys"
__release_date__ = ""
__description__ = _("Module providing customizable keyboard shortcuts.")
__icon__ = "keys/assets/icons/icon3.svg"

__1_11_6__ = _(
    "Short key search matches the page title, path, key and command, and "
    "the list applies that search."
)

__1_11_5__ = _(
    "Close cross-tenant and privilege-escalation gaps in the Short Keys API."
)

__1_11_4__ = _(
    "Unify short-keys settings on my_settings_list_shell. Derive list column labels from "
    "model verbose_name; wrap remaining form strings with gettext; add indexes on "
    "frequently filtered fields."
)

__1_11_3__ = _("Apply runtime viewport fit on the short-keys settings list.")

__1_11_2__ = _(
    "Tie shortcut keys to the user's company with all_objects lookups and sync company on "
    "user company change so shortcuts stay visible across active company switches."
)

__1_11_1__ = _(
    "Migrated signal and timezone imports to the horilla shims, standardized first-party "
    "import groups, and added docstrings for pylint compliance; shortcuts unchanged."
)

__1_10_0__ = _(
    "Release 1.10: keyboard shortcuts ship under contrib with app label keys. "
    "URLs, registrations, shortcuts metadata, templates, and static paths "
    "updated from the legacy keys package layout."
)

__1_1_0__ = _(
    "Migrated from Django AppConfig to Horilla AppLauncher and replaced Django"
    "utilities with horilla.utils.decorators, horilla.utils.translation, and horilla.shortcuts where applicable."
)
