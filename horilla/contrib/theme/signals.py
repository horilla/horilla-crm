"""
Signals for the theme app
"""

# themes/signals.py
# Define your theme signals here

# Third-party imports (Django)
from django.dispatch import receiver

from horilla.contrib.core.signals import pre_login_render_signal, pre_logout_signal
from horilla.contrib.utils.middlewares import get_active_company

# First party imports (Horilla)
from horilla.db.models.signals import post_migrate

from .models import HorillaColorTheme

# Local imports
from .utils import THEMES_DATA


@receiver(post_migrate, dispatch_uid="create_default_themes")
def create_default_themes(sender, **kwargs):
    """
    Create default color theme after migration
    """
    # Only run for the theme app
    if getattr(sender, "name", None) != "horilla.contrib.theme":
        return

    # Only seed on the first migrate of this app (when its initial migration runs).
    # post_migrate fires on every migrate, but `plan` tells us what actually ran.
    plan = kwargs.get("plan") or []
    ran_initial = any(
        (
            migration.app_label == sender.label
            and migration.name == "0001_initial"
            and not backwards
        )
        for migration, backwards in plan
    )
    if not ran_initial:
        return

    for theme_data in THEMES_DATA:
        HorillaColorTheme.objects.get_or_create(
            name=theme_data["name"], defaults=theme_data
        )


@receiver(pre_logout_signal, dispatch_uid="theme_pre_logout")
def get_theme_data_for_logout(sender, request, **kwargs):
    """
    Signal receiver to get theme data before logout.
    Returns tuple: (storage_key, data_dict) or None

    The storage_key will be used as the localStorage key.
    The data_dict will be JSON stringified and stored.
    """
    if request.user.is_authenticated:
        active_company = get_active_company(request)
        if active_company:
            from .models import CompanyTheme

            company_theme = (
                CompanyTheme.objects.filter(company=active_company)
                .select_related("theme")
                .first()
            )

            if company_theme and company_theme.theme:
                theme = company_theme.theme
                theme_data_dict = {
                    "id": theme.id,
                    "primary_50": theme.primary_50,
                    "primary_100": theme.primary_100,
                    "primary_200": theme.primary_200,
                    "primary_300": theme.primary_300,
                    "primary_400": theme.primary_400,
                    "primary_500": theme.primary_500,
                    "primary_600": theme.primary_600,
                    "primary_700": theme.primary_700,
                    "primary_800": theme.primary_800,
                    "primary_900": theme.primary_900,
                    "dark_50": theme.dark_50,
                    "dark_100": theme.dark_100,
                    "dark_200": theme.dark_200,
                    "dark_300": theme.dark_300,
                    "dark_400": theme.dark_400,
                    "dark_500": theme.dark_500,
                    "dark_600": theme.dark_600,
                    "secondary_50": theme.secondary_50,
                    "secondary_100": theme.secondary_100,
                    "secondary_200": theme.secondary_200,
                    "secondary_300": theme.secondary_300,
                    "secondary_400": theme.secondary_400,
                    "secondary_500": theme.secondary_500,
                    "secondary_600": theme.secondary_600,
                    "secondary_700": theme.secondary_700,
                    "secondary_800": theme.secondary_800,
                    "secondary_900": theme.secondary_900,
                    "surface": getattr(theme, "surface", "#e9edf0ba"),
                }

                # Return tuple: (localStorage key, data to store)
                return ("lastActiveTheme", theme_data_dict)

    return None


@receiver(pre_login_render_signal, dispatch_uid="theme_pre_login_render")
def add_theme_to_login_context(sender, request, context, **kwargs):
    """
    Signal receiver to add theme data to login page context.
    Modifies the context dict directly.
    """
    try:
        default_theme = HorillaColorTheme.get_default_theme()
        context["theme"] = default_theme
    except Exception:
        # If anything goes wrong, theme stays None (not in context)
        pass
