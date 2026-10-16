"""
Views for the mobile shell: layout pages, login/logout, manifest and service worker.
"""

# Standard library imports
import json

# Third-party imports (Django)
from django.conf import settings
from django.templatetags.static import static

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.views.core import LoginUserView, LogoutView
from horilla.shortcuts import redirect
from horilla.urls import reverse, reverse_lazy
from horilla.utils.branding import load_branding
from horilla.utils.translation import get_language, get_language_bidi
from horilla.views.generic import TemplateView, View
from horilla.web import HttpResponse

# Local imports
from .navigation import get_nav_items
from .utils import CACHE_PREFIX, get_asset_version


class MobileLoginRequiredMixin(LoginRequiredMixin):
    """Send signed-out visitors to the mobile login page instead of the desktop one."""

    login_url = reverse_lazy("mobile:login")


class MobilePageMixin(MobileLoginRequiredMixin):
    """Shared context for pages that use the mobile layout."""

    def get_context_data(self, **kwargs):
        """Add the bottom navigation entries."""
        context = super().get_context_data(**kwargs)
        context["mobile_nav_items"] = get_nav_items(self.request)
        return context


class MobileHomeView(MobileLoginRequiredMixin, View):
    """Entry point of the installed app (the manifest ``start_url``)."""

    def get(self, request, *args, **kwargs):
        """Open the first mobile page."""
        return redirect("mobile:more")


class MobileMoreView(MobilePageMixin, TemplateView):
    """Account page: active company, language, full version link and logout."""

    template_name = "mobile/more.html"


class MobileLoginView(LoginUserView):
    """Desktop login logic (authentication, lockout, messages) on a phone layout."""

    template_name = "mobile/login.html"
    login_url_name = "mobile:login"
    default_next_url = reverse_lazy("mobile:home")

    def get(self, request):
        """Skip the form for a user who is already signed in."""
        if request.user.is_authenticated:
            return redirect("mobile:home")
        return super().get(request)


class MobileLogoutView(LogoutView):
    """Desktop logout (signal receivers, local storage cleanup) back to the mobile login."""

    redirect_url = reverse_lazy("mobile:login")


class ManifestView(View):
    """
    Web app manifest for "Add to Home Screen".

    Public on purpose: browsers fetch the manifest without cookies. It only
    holds the install's branding, the language and the app's URLs.
    """

    def get(self, request, *args, **kwargs):
        """Return the manifest as JSON."""
        branding = load_branding()
        title = str(branding["TITLE"])
        home = reverse("mobile:home")
        manifest = {
            "id": home,
            "name": title,
            "short_name": title,
            "start_url": home,
            "scope": home,
            "display": "standalone",
            "lang": get_language(),
            "dir": "rtl" if get_language_bidi() else "ltr",
            "background_color": "#ffffff",
            "theme_color": "#ffffff",
            "icons": [
                {
                    "src": static("favicons/android-chrome-192x192.png"),
                    "sizes": "192x192",
                    "type": "image/png",
                },
                {
                    "src": static("favicons/android-chrome-512x512.png"),
                    "sizes": "512x512",
                    "type": "image/png",
                },
            ],
        }
        response = HttpResponse(
            json.dumps(manifest, ensure_ascii=False),
            content_type="application/manifest+json; charset=utf-8",
        )
        response["Cache-Control"] = "no-cache"
        return response


class ServiceWorkerView(TemplateView):
    """
    Service worker script, served from /m/sw.js.

    Serving it under /m/ gives it the /m/ scope, so it never controls desktop
    pages. It only answers versioned /static/ requests from its cache; see
    ``templates/mobile/sw.js``.
    """

    template_name = "mobile/sw.js"
    content_type = "application/javascript; charset=utf-8"

    def get_context_data(self, **kwargs):
        """Pass the cache name and static URL the worker needs."""
        context = super().get_context_data(**kwargs)
        version = get_asset_version()
        context.update(
            {
                "asset_version": json.dumps(version),
                "cache_prefix": json.dumps(CACHE_PREFIX),
                "cache_name": json.dumps(f"{CACHE_PREFIX}{version}"),
                "static_url": json.dumps(settings.STATIC_URL),
                # Caching stale files while editing them locally is confusing.
                "cache_enabled": json.dumps(not settings.DEBUG),
            }
        )
        return context

    def render_to_response(self, context, **response_kwargs):
        """Ask the browser to check for a new worker on every page load."""
        response = super().render_to_response(context, **response_kwargs)
        response["Cache-Control"] = "no-cache"
        return response
