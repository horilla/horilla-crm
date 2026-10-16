"""
A generic class-based view for rendering the home page.
"""

# Standard library imports
import json
import logging
import os
import re
import threading
from html.parser import HTMLParser

# Third-party imports (other)
import pycountry

# Third-party imports (Django)
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.cache import cache
from django.test import RequestFactory
from django.utils._os import safe_join
from django.utils.safestring import mark_safe
from django.views.generic.base import RedirectView
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import UntypedToken

from horilla import settings

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.mail.models import HorillaMailConfiguration
from horilla.menu.settings_menu import get_settings_menu
from horilla.shortcuts import redirect, render
from horilla.urls import resolve, reverse_lazy
from horilla.utils.branding import load_branding
from horilla.utils.choices import BLOCKED_EXTENSIONS
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.html import escape, strip_tags
from horilla.utils.translation import get_language
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView, View
from horilla.web import (
    FileResponse,
    HttpNotFound,
    HttpResponse,
    JsonResponse,
    RedirectResponse,
    safe_url,
)

from ..models import ActiveTab, Company, RecentlyViewed
from ..signals import pre_login_render_signal, pre_logout_signal

# Local imports
from .initialiaze_database import InitializeDatabaseConditionView

logger = logging.getLogger(__name__)


def is_jwt_token_valid(auth_header):
    """Check if the provided JWT token is valid and return the associated user."""
    if not auth_header or not auth_header.startswith("Bearer "):
        return None  # No token

    token = auth_header.split("Bearer ")[1].strip()
    try:
        UntypedToken(token)  # Will raise if invalid
        validated_token = JWTAuthentication().get_validated_token(token)
        user = JWTAuthentication().get_user(validated_token)
        return user
    except (InvalidToken, TokenError):
        return None


def protected_media(request, path):
    """Serve protected media files with access control."""
    try:
        media_path = safe_join(settings.MEDIA_ROOT, path)
    except ValueError as exc:
        raise HttpNotFound("Invalid file path") from exc

    if not os.path.isfile(media_path):
        raise HttpNotFound("File not found")

    # Block dangerous extensions
    _, ext = os.path.splitext(media_path)
    if ext.lower() in BLOCKED_EXTENSIONS:
        raise HttpNotFound("Access denied")

    # Otherwise require authentication
    jwt_user = is_jwt_token_valid(request.META.get("HTTP_AUTHORIZATION", ""))

    if not request.user.is_authenticated and not jwt_user:
        return redirect("core:login")

    response = FileResponse(open(media_path, "rb"))
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private"

    return response


class HomePageView(LoginRequiredMixin, View):
    """
    Redirect to default home page
    """

    def get(self, request, *args, **kwargs):
        """
        Redirect to default home page
        """

        return redirect(settings.DEFAULT_HOME_REDIRECT)


@method_decorator(htmx_required, name="dispatch")
class ReloadMessages(LoginRequiredMixin, TemplateView):
    """
    Reload messages
    """

    template_name = "messages.html"

    def get_context_data(self, **kwargs):
        """
        Get context data for reloading messages.
        """

        context = super().get_context_data(**kwargs)
        return context


@method_decorator(htmx_required, name="dispatch")
class ClearRecentlyViewedView(LoginRequiredMixin, View):
    """
    Clear all recently viewed items for the current user.
    """

    def post(self, request, *args, **kwargs):
        """
        Delete all recently viewed items for the current user.
        """

        RecentlyViewed.objects.filter(user=request.user).delete()
        return render(
            request, "common/recently_viewed_panel.html", {"recently_viewed_items": []}
        )


class SaveActiveTabView(LoginRequiredMixin, View):
    """
    View to save the active tab for a user.
    """

    def post(self, request, *args, **kwargs):
        """
        Save the active tab for the user.
        """
        tab_target = request.POST.get("tab_target")
        path = request.POST.get("path")
        user = request.user if request.user.is_authenticated else None
        company = getattr(request, "active_company", None)

        if user and tab_target and path:
            ActiveTab.objects.update_or_create(
                created_by=user,
                path=path,
                company=company if company else user.company,
                defaults={"tab_target": tab_target},
            )
            return JsonResponse({"status": "success"})

        return JsonResponse({"status": "error", "message": "Invalid data"}, status=400)

    def get(self, request, *args, **kwargs):
        """
        Handle GET requests with an error response.
        """

        return JsonResponse(
            {"status": "error", "message": "Invalid method"}, status=405
        )


class LoginUserView(View):
    """
    Class-based view to handle user login.

    Subclasses can serve their own login page (e.g. a mobile layout) by
    overriding ``template_name``, ``login_url_name`` (where failed attempts are
    sent back to) and ``default_next_url`` (where a successful login goes when
    no ``next`` is given). Authentication and lockout stay in this class.
    """

    template_name = "login.html"
    login_url_name = "core:login"
    default_next_url = "/"

    def get(self, request):
        """
        Render login page with an optional 'next' param preserved.
        """
        next_url = safe_url(request, request.GET.get("next", self.default_next_url))
        condition_view = InitializeDatabaseConditionView()
        initialize_database = condition_view.get_initialize_condition()
        show_forgot_password = False
        hq_company = Company.objects.filter(hq=True).first()

        if hq_company:
            show_forgot_password = HorillaMailConfiguration.objects.filter(
                company=hq_company
            ).exists()

        context = {
            "next": next_url,
            "initialize_database": initialize_database,
            "show_forgot_password": show_forgot_password,
        }

        _responses = pre_login_render_signal.send(
            sender=self.__class__, request=request, context=context
        )

        return render(request, self.template_name, context=context)

    def post(self, request):
        """
        Handle login attempt
        """
        identifier = request.POST.get("username")
        secret = request.POST.get("password")
        next_url = safe_url(request, request.POST.get("next", self.default_next_url))

        ip = (
            request.META.get(
                "HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "")
            )
            .split(",")[0]
            .strip()
        )
        lockout_key = f"login_lockout_{ip}"
        attempt_key = f"login_attempts_{ip}"

        # Block IP if currently locked out
        if cache.get(lockout_key):
            messages.error(
                request,
                _("Too many failed login attempts. Please try again in 15 minutes."),
            )
            return redirect(reverse_lazy(self.login_url_name) + f"?next={next_url}")

        user = authenticate(request, username=identifier, password=secret)

        if not user:
            attempts = cache.get(attempt_key, 0) + 1
            if attempts >= 5:
                cache.set(lockout_key, True, timeout=900)  # lock for 15 minutes
                cache.delete(attempt_key)
                logger.warning("Brute force lockout triggered for IP %s", ip)
                messages.error(
                    request,
                    _(
                        "Too many failed login attempts. Please try again in 15 minutes."
                    ),
                )
            else:
                cache.set(attempt_key, attempts, timeout=900)
                messages.error(
                    request, _("Invalid credentials. Please check and try again.")
                )
            return redirect(reverse_lazy(self.login_url_name) + f"?next={next_url}")

        if not user.is_active:
            messages.warning(
                request,
                _("This user is archived or blocked. Please contact support."),
            )
            return redirect(reverse_lazy(self.login_url_name) + f"?next={next_url}")

        # Clear failed attempt counters on successful login
        cache.delete(attempt_key)
        cache.delete(lockout_key)

        login(request, user)
        messages.success(request, _("Login successful."))
        next_url = safe_url(request, next_url)
        return redirect(next_url)


class LogoutView(View):
    """
    Class-based view to logout the user and clear local storage.
    All preservation logic is handled by signal receivers.

    Subclasses can send the user to another login page by overriding
    ``redirect_url``.
    """

    redirect_url = "/login"

    def get(self, request, *args, **kwargs):
        """
        Logout the user and clear local storage.
        """

        # Collect data from all registered signal receivers
        storage_data = {}

        if request.user.is_authenticated:
            responses = pre_logout_signal.send(sender=self.__class__, request=request)

            for _receiver, response in responses:
                if response and isinstance(response, tuple) and len(response) == 2:
                    storage_key, data = response
                    if storage_key and data:
                        storage_data[storage_key] = data

        if request.user.is_authenticated:
            logout(request)

        storage_data_json = json.dumps(storage_data) if storage_data else "{}"

        script_content = f"""
        <script>
            // Save theme mode before clearing (always preserved)
            const theme = localStorage.getItem('theme');

            // Clear everything
            localStorage.clear();

            // Always restore theme mode if it existed
            if (theme !== null) {{
                localStorage.setItem('theme', theme);
            }}

            const storageData = {storage_data_json};
            for (const [key, value] of Object.entries(storageData)) {{
                localStorage.setItem(key, JSON.stringify(value));
            }}
        </script>

        <meta http-equiv="refresh" content="0;url={escape(str(self.redirect_url))}">
        """

        response = HttpResponse()
        response.content = script_content
        return response


@method_decorator(
    permission_required_or_denied("core.can_view_horilla_settings"),
    name="dispatch",
)
class SettingView(LoginRequiredMixin, TemplateView):
    """
    TemplateView for settings page.
    """

    template_name = "settings/settings.html"


def highlight_match(text, query):
    """Wrap the first matched substring of query in <strong>, HTML-escaped."""
    if not text or not query:
        return escape(text)
    escaped_text = escape(str(text))
    escaped_query = escape(query)
    return mark_safe(
        re.sub(
            f"({re.escape(escaped_query)})",
            r"<strong>\1</strong>",
            escaped_text,
            count=1,
            flags=re.IGNORECASE,
        )
    )


@method_decorator(
    permission_required_or_denied("core.can_view_horilla_settings"),
    name="dispatch",
)
@method_decorator(htmx_required, name="dispatch")
class SettingsSearchView(LoginRequiredMixin, View):
    """
    Returns a floating dropdown of settings items whose label or rendered
    page content matches the query, grouped by their sidebar section.

    The full content index (which crawls every settings page, including
    nested tabs) is slow to build cold, so it's warmed in a background
    thread the first time it's needed. Until it's ready, matches fall
    back to sidebar labels only; the next search after warming completes
    picks up full-content matches automatically.
    """

    MAX_RESULTS = 8

    def get(self, request):
        """Search settings menu items by query and return grouped HTMX results."""
        query = request.GET.get("q", "").strip()
        if not query:
            return render(
                request,
                "settings/_settings_search_results.html",
                {"groups": [], "search_query": ""},
            )

        settings_menu = get_settings_menu(request)

        index = get_or_warm_settings_search_index(request)
        if index is None:
            index = [
                {
                    "label": item.get("label", ""),
                    "url": item.get("url"),
                    "text": f"{item.get('label', '')} {menu.get('title', '')}".lower(),
                }
                for menu in settings_menu
                for item in menu.get("items", [])
            ]

        query_lower = query.lower()
        matched_urls = {entry["url"] for entry in index if query_lower in entry["text"]}

        groups = []
        result_count = 0
        for menu in settings_menu:
            if result_count >= self.MAX_RESULTS:
                break
            matched_items = [
                item
                for item in menu.get("items", [])
                if item.get("url") in matched_urls
            ]
            if not matched_items:
                continue
            remaining = self.MAX_RESULTS - result_count
            matched_items = matched_items[:remaining]
            result_count += len(matched_items)
            groups.append(
                {
                    "title": menu.get("title", ""),
                    "icon": menu.get("icon", ""),
                    "items": [
                        {
                            **item,
                            "display_label": highlight_match(
                                item.get("label", ""), query
                            ),
                        }
                        for item in matched_items
                    ],
                }
            )

        return render(
            request,
            "settings/_settings_search_results.html",
            {"groups": groups, "search_query": query},
        )


def get_or_warm_settings_search_index(request):
    """Return the cached settings search index, or None if it isn't ready
    yet. On a miss, starts a single background build (guarded by a short
    lock key so concurrent requests don't each start their own crawl)."""
    cache_key = f"settings_search_index_{request.user.pk}_{get_language()}"
    index = cache.get(cache_key)
    if index is not None:
        return index

    lock_key = f"{cache_key}_building"
    if cache.add(lock_key, True, 60):
        user = request.user
        session = request.session
        active_company = getattr(request, "active_company", None)

        def _warm():
            fake_request = RequestFactory().get("/")
            fake_request.user = user
            fake_request.session = session
            fake_request.active_company = active_company
            try:
                built_index = build_settings_search_index(fake_request)
                cache.set(cache_key, built_index, 300)
            finally:
                cache.delete(lock_key)

        threading.Thread(target=_warm, daemon=True).start()

    return None


class _FragmentByIdParser(HTMLParser):
    """Extracts the inner HTML of the first element with a given id, using
    the stdlib HTML parser so void elements (input, br, img, ...) and
    unquoted/self-closing attributes are handled correctly (a hand-rolled
    regex tag-balance scan gets this wrong on real-world markup)."""

    VOID_ELEMENTS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self, element_id):
        super().__init__(convert_charrefs=False)
        self.element_id = element_id
        self.depth = 0
        self.chunks = []
        self.done = False

    def _reconstruct_tag(self, tag, attrs, closing=False, self_close=False):
        if closing:
            return f"</{tag}>"
        attr_str = "".join(
            f' {k}="{v}"' if v is not None else f" {k}" for k, v in attrs
        )
        return f"<{tag}{attr_str}{'/' if self_close else ''}>"

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if self.depth == 0 and dict(attrs).get("id") == self.element_id:
            self.depth = 1
            return
        if self.depth > 0:
            self.chunks.append(self._reconstruct_tag(tag, attrs))
            if tag not in self.VOID_ELEMENTS:
                self.depth += 1

    def handle_startendtag(self, tag, attrs):
        if self.done:
            return
        if self.depth == 0 and dict(attrs).get("id") == self.element_id:
            self.done = True
            return
        if self.depth > 0:
            self.chunks.append(self._reconstruct_tag(tag, attrs, self_close=True))

    def handle_endtag(self, tag):
        if self.done or self.depth == 0:
            return
        self.depth -= 1
        if self.depth == 0:
            self.done = True
        else:
            self.chunks.append(self._reconstruct_tag(tag, [], closing=True))

    def handle_data(self, data):
        if self.depth > 0 and not self.done:
            self.chunks.append(data)


def extract_fragment_by_id(html, element_id):
    """Return the inner HTML of the first element with the given id."""
    parser = _FragmentByIdParser(element_id)
    parser.feed(html)
    return "".join(parser.chunks) if parser.chunks or parser.done else None


def render_internal_url(base_request, url):
    """Render a URL in-process as htmx would (with the HX-Request header),
    reusing the current user/session/company context, and return the
    decoded HTML body."""
    factory = RequestFactory()
    internal_request = factory.get(url, HTTP_HX_REQUEST="true")
    internal_request.user = base_request.user
    internal_request.session = base_request.session
    internal_request.active_company = getattr(base_request, "active_company", None)

    resolver_match = resolve(url)
    response = resolver_match.func(
        internal_request, *resolver_match.args, **resolver_match.kwargs
    )
    content = (
        response.render().content if hasattr(response, "render") else response.content
    )
    return content.decode("utf-8", errors="ignore")


def find_nested_tab_urls(html):
    """Return the hx-get URLs embedded in a rendered fragment (tab bars,
    lazy-loaded sub-sections), so the crawler can follow them recursively."""
    return set(re.findall(r'hx-get=["\']([^"\'?]+)', html))


def build_settings_search_index(request, max_depth=2):
    """Render every visible settings item's target page (and any nested
    tabs/sub-sections it lazy-loads) and extract their text.

    Nested tab content is indexed under the top-level sidebar item's own
    URL (`item_url`), since that's the only URL the sidebar can navigate
    to or reveal a match for."""
    index = []

    def crawl(url, item_url, label, menu_title, select_id=None, depth=0, visited=None):
        if visited is None:
            visited = set()
        if url in visited or depth > max_depth:
            return
        visited.add(url)

        try:
            html = render_internal_url(request, url)
        except Exception:
            return

        fragment_html = extract_fragment_by_id(html, select_id) if select_id else html
        text = strip_tags(fragment_html or "")
        text = re.sub(r"\s+", " ", text).strip()

        index.append(
            {
                "label": str(label),
                "url": item_url,
                "menu_title": str(menu_title),
                "text": f"{label} {menu_title} {text}".lower(),
            }
        )

        for nested_url in find_nested_tab_urls(fragment_html or ""):
            crawl(
                nested_url,
                item_url,
                label,
                menu_title,
                depth=depth + 1,
                visited=visited,
            )

    for menu in get_settings_menu(request):
        for item in menu.get("items", []):
            url = item.get("url")
            select_id = item.get("hx-select", "").lstrip("#")
            if not url:
                continue
            crawl(url, url, item.get("label", ""), menu.get("title", ""), select_id)

    return index


class MySettingView(LoginRequiredMixin, TemplateView):
    """
    TemplateView for settings page.
    """

    template_name = "settings/my_settings.html"


@method_decorator(
    permission_required_or_denied("core.can_switch_company"), name="dispatch"
)
class SwitchCompanyView(LoginRequiredMixin, View):
    """
    View to switch active company for the user.
    """

    def post(self, request, company_id):
        """
        Switch the active company for the user.
        """
        if request.user.is_authenticated and (
            request.user.has_perm("core.can_switch_company")
            or request.user.company_id == company_id
        ):
            request.session["active_company_id"] = company_id
        return RedirectResponse(self.request)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.can_switch_company"), name="dispatch"
)
class ToggleAllCompaniesView(LoginRequiredMixin, View):
    """
    View to toggle "show all companies" mode globally via session.
    """

    def post(self, request):
        """
        Toggle the all_companies setting in session.
        """
        current_value = request.session.get("show_all_companies", False)
        request.session["show_all_companies"] = not current_value
        request.session.save()

        # Return HX-Redirect to refresh the page
        referer = request.META.get("HTTP_REFERER", "/")
        response = HttpResponse(status=200)
        response["HX-Redirect"] = referer
        return response


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required_or_denied("core.view_company"), name="dispatch")
class CompanyDetailsTab(LoginRequiredMixin, TemplateView):
    """
    TemplateView for company details tab.
    """

    template_name = "settings/company_details_tab.html"
    model = Company
    # (field_name, icon_class)
    body = (
        ("name", "fa-solid fa-building"),
        ("contact_number", "fa-solid fa-phone"),
        ("fax", "fa-solid fa-fax"),
        ("website", "fa-solid fa-globe"),
        ("email", "fa-solid fa-envelope"),
        ("city", "fa-solid fa-location-dot"),
        ("state", "fa-solid fa-map"),
        ("country", "fa-solid fa-flag"),
        ("zip_code", "fa-solid fa-location-dot"),
        ("time_zone", "fa-regular fa-clock"),
        ("language", "fa-solid fa-language"),
        ("currency", "fa-solid fa-coins"),
        ("no_of_employees", "fa-solid fa-users"),
        ("annual_revenue", "fa-solid fa-chart-line"),
    )

    def get_context_data(self, **kwargs):
        """Add company object and flattened detail rows for the template."""
        context = super().get_context_data(**kwargs)
        obj = getattr(self.request, "active_company", None) or self.request.user.company
        context["obj"] = obj
        context["detail_fields"] = [
            (obj._meta.get_field(name).verbose_name, name, icon)
            for name, icon in self.body
        ]
        return context


@method_decorator(htmx_required, name="dispatch")
class GetCountrySubdivisionsView(LoginRequiredMixin, View):
    """
    View to get country subdivisions (states/provinces) based on country code.
    """

    def get(self, request, *args, **kwargs):
        """
        Get HTML options for country subdivisions based on country code.

        Args:
            request: The HTTP request object.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Returns:
            HttpResponse: HTML string containing option elements for subdivisions.
        """
        country_code = request.GET.get("country")
        options = mark_safe('<option value="">Select State</option>')

        if country_code:
            subdivisions = pycountry.subdivisions.get(country_code=country_code.upper())
            if subdivisions:
                for subdivision in subdivisions:
                    options += (
                        f'<option value="{escape(subdivision.code)}">'
                        f"{escape(subdivision.name)}</option>"
                    )

        return HttpResponse(options)


class FaviconRedirectView(RedirectView):
    """Redirect to the configured favicon."""

    branding = load_branding()
    favicon_path = branding.get("FAVICON_PATH", "favicon.ico")
    url = staticfiles_storage.url(favicon_path)
