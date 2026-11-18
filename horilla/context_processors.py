"""
Context processors for the Horilla application.

Provides sidebar, company, language, recently viewed items, notifications,
and menu context for templates.
"""

from django.conf import settings
from django.core.cache import cache
from django.utils.translation import get_language

from horilla.contrib.core.models import Company, HorillaContentType, RecentlyViewed
from horilla.contrib.notifications.methods import get_user_notifications
from horilla.contrib.notifications.models import NotificationSoundPreference
from horilla.menu.floating_menu import get_floating_menu
from horilla.menu.main_section_menu import get_main_section_menu
from horilla.menu.my_settings_menu import get_my_settings_menu
from horilla.menu.settings_menu import get_settings_menu
from horilla.menu.sub_section_menu import get_sub_section_menu
from horilla.utils.branding import load_branding

COMPANY_LIST_CACHE_KEY = "available_companies"


def company_list(request):
    """Return all available companies, cached to avoid a query on every request."""
    companies = cache.get(COMPANY_LIST_CACHE_KEY)
    if companies is None:
        companies = list(Company.objects.all())
        cache.set(COMPANY_LIST_CACHE_KEY, companies, timeout=300)
    return {"available_companies": companies}


def allowed_languages(request):
    """
    Return only languages defined in ALLOWED_LANGUAGES.
    """
    return {
        "allowed_languages": [
            {
                "code": code,
                "name": name,
                "flag": flag,
                "active": (code == get_language()),
            }
            for code, name, flag in settings.ALLOWED_LANGUAGES
        ]
    }


def recently_viewed_items(request):
    """
    Return the user's 6 most recently viewed items, cleaning invalid references.

    Rows can point at different models via a GenericForeignKey, so resolving
    ``content_object`` one row at a time (as this loop renders/checks each
    row) runs one query per row. Batch-fetch by content type first and
    pre-populate each row's cached GenericForeignKey value so the template's
    later ``item.content_object``/``item.get_detail_url`` access is free.
    """
    if request.user.is_authenticated:
        rows = list(
            RecentlyViewed.objects.filter(user=request.user).order_by("-viewed_at")[:6]
        )
        if not rows:
            return {"recently_viewed_items": []}

        ids_by_content_type = {}
        for rv in rows:
            ids_by_content_type.setdefault(rv.content_type_id, set()).add(rv.object_id)

        objects_by_content_type = {}
        for content_type_id, object_ids in ids_by_content_type.items():
            content_type = HorillaContentType.objects.get_for_id(content_type_id)
            model = content_type.model_class()
            if model is None:
                continue
            objects_by_content_type[content_type_id] = {
                str(obj.pk): obj for obj in model.objects.filter(pk__in=object_ids)
            }

        items = []
        stale_ids = []
        for rv in rows:
            obj = objects_by_content_type.get(rv.content_type_id, {}).get(
                str(rv.object_id)
            )
            if obj is None:
                stale_ids.append(rv.pk)
                continue
            rv.content_object = obj
            items.append(rv)

        if stale_ids:
            RecentlyViewed.objects.filter(pk__in=stale_ids).delete()

        return {"recently_viewed_items": items}
    return {}


def unread_notifications(request):
    """Return unread notifications and sound preference for the current user."""
    if request.user.is_authenticated:
        try:
            sound_muted = request.user.notification_sound_preference.sound_muted
        except NotificationSoundPreference.DoesNotExist:
            sound_muted = False
        return {
            "unread_notifications": get_user_notifications(request.user)
            .filter(read=False)
            .order_by("-created_at"),
            "notification_sound_muted": sound_muted,
        }
    return {}


def menu_context_processor(request):
    """Return context for various menus."""

    current_app_label = (
        request.resolver_match.app_name if request.resolver_match else None
    )
    section_param = request.GET.get("section")

    return {
        "main_section_menu": get_main_section_menu(request),
        "sub_section_menu": get_sub_section_menu(request),
        "settings_menu": get_settings_menu(request),
        "floating_menu": get_floating_menu(request),
        "my_settings_menu": get_my_settings_menu(request),
        "current_section": section_param,
        "current_app_label": current_app_label,
    }


def currency_context(request):
    """
    Add currency information to all templates automatically
    This makes user_currency and default_currency available in ALL templates
    """
    if not request.user.is_authenticated:
        return {}

    from horilla.contrib.core.models import MultipleCurrency

    company = getattr(request.user, "company", None)
    default_currency = (
        MultipleCurrency.get_default_currency(company) if company else None
    )

    user_currency = getattr(request.user, "currency", None) or default_currency

    return {
        "user_currency": user_currency,
        "default_currency": default_currency,
    }


def branding(request):
    """
    Django context processor function that retrun
    dictionary containing branding configuration values such as
    TITLE, LOGIN_WELCOME_LINE, LOGO_PATH, etc.
    """
    return load_branding()
