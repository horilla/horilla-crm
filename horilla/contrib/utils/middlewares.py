"""Thread-local request storage and language-switching middleware."""

# Standard library imports
import threading

# Third-party imports (Django)
from django.conf import settings

# First party imports (Horilla)
from horilla.utils import translation

_thread_local = threading.local()


class ThreadLocalMiddleware:
    """Middleware that stores the current request in thread-local storage."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Store the request in thread local storage
        _thread_local.request = request

        # Process the request
        response = self.get_response(request)

        # Clean up after the request is processed
        if hasattr(_thread_local, "request"):
            del _thread_local.request

        return response


# Helper function to get the current request
def get_current_request():
    """Return the current HTTP request stored in thread-local storage, or None if unavailable."""
    return getattr(_thread_local, "request", None)


def get_active_company(request=None):
    """Return the company the user is working in (company switcher aware).

    ``ActiveCompanyMiddleware`` is the only place that decides the company and
    stores it on ``request.active_company``; this is the single way for Python
    code to read it (templates keep using ``request.active_company``).

    Without ``request`` the thread-local request is used, so models, managers,
    signals and forms can call it with no arguments. Falls back to the user's own
    company when the middleware could not resolve one (DRF JWT/Basic auth,
    ``RequestFactory`` and fake requests). Returns ``None`` when there is no
    request or the user has no company.
    """
    request = request or get_current_request()
    if request is None:
        return None
    company = getattr(request, "active_company", None)
    if company:
        return company
    # AnonymousUser has no ``company``, so no authentication check is needed.
    return getattr(getattr(request, "user", None), "company", None)


class LanguageSwitchMiddleware:
    """Middleware that activates a language based on session, user preference, or settings."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Priority order:
        # 1. Session language (when user actively changes language)
        # 2. User's preferred language (from profile)
        # 3. Default language from settings

        lang = None

        # First check if there's a session language (user actively selected)
        session_lang = request.session.get("django_language")

        if session_lang:
            # User has actively selected a language, use it
            lang = session_lang
        elif request.user.is_authenticated:
            # No session language, check user's profile preference
            user_lang = getattr(request.user, "language", None)
            if user_lang:
                lang = user_lang
                # Save user's preference to session for consistency
                request.session["django_language"] = lang

        # If no language found, fall back to settings default
        if not lang:
            lang = settings.LANGUAGE_CODE

        # Activate the language
        translation.activate(lang)
        request.LANGUAGE_CODE = lang

        response = self.get_response(request)
        return response
