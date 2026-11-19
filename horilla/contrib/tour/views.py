"""
Views for the tour app.

``TourPanelView`` renders the panel opened from the profile menu. The other
views are small endpoints used by ``static/tour/assets/js/tour.js``.
"""

# Standard library imports
import json

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.shortcuts import render
from horilla.utils.translation import gettext as _
from horilla.views.generic import View
from horilla.web import HttpResponseBadRequest, JsonResponse

# Local imports
from .models import TourSeen
from .registry import get_tours_for, get_visible_tour, resolve_view_name


def ui_labels():
    """Translated UI strings used by the browser engine (``tour.js``)."""
    return {
        "finish": _("Finish"),
        "step_of": _("Step {current} of {total}"),
        "panel_error": _("The tours could not be loaded."),
        "cannot_open": _(
            "There is nothing to open here yet. Create a record first, then start this tour again."
        ),
        "not_ready": _(
            "This tour could not find the page it needs. Open the page and try again."
        ),
    }


def build_panel_context(user, raw_path=""):
    """
    Everything the panel template needs.

    Tours that belong to the page the user is on (``raw_path``) are listed first
    under "On this page"; every other tour is grouped by area below.
    """
    view_name = resolve_view_name(raw_path)

    on_page_name = _("On this page")
    groups = {on_page_name: []}  # first key, so it is listed first
    for tour in get_tours_for(user):
        card = {
            "key": tour.key,
            "title": tour.title,
            "description": tour.description,
            "icon": tour.icon,
            "steps_total": len(tour.steps),
            "start_url": tour.start_link(),
        }
        on_page = bool(view_name) and (
            view_name in tour.match
            or bool(tour.open_with and tour.open_with["from"] == view_name)
        )
        groups.setdefault(on_page_name if on_page else str(tour.group), []).append(card)

    return {
        "groups": [
            {"name": name, "tours": cards} for name, cards in groups.items() if cards
        ]
    }


class TourPanelView(LoginRequiredMixin, View):
    """
    The panel fragment opened from the profile menu: the tours for the current page
    (``?path=``) first, then every other tour, each with a Start button.
    """

    def get(self, request, *args, **kwargs):
        """Render the panel fragment for the page the browser reports."""
        return render(
            request,
            "tour/partials/panel_body.html",
            build_panel_context(request.user, request.GET.get("path", "")),
        )


class TourCurrentView(LoginRequiredMixin, View):
    """
    Tell the browser which page it is on and which tours should start by themselves.

    The browser sends its pathname; the server resolves it to a URL name so
    pages with arguments (record detail pages) are recognised.
    """

    def get(self, request, *args, **kwargs):
        """Return the view name for ``?path=`` and the automatic tours still to show."""
        view_name = resolve_view_name(request.GET.get("path", ""))

        auto = []
        if view_name:
            seen = set(
                TourSeen.objects.filter(user=request.user).values_list(
                    "tour_key", flat=True
                )
            )
            auto = [
                tour.key
                for tour in get_tours_for(request.user)
                if tour.auto_start and view_name in tour.match and tour.key not in seen
            ]
        return JsonResponse(
            {"view_name": view_name, "auto": auto, "labels": ui_labels()}
        )


class TourDefinitionView(LoginRequiredMixin, View):
    """Return one tour (steps included) as JSON."""

    def get(self, request, key, *args, **kwargs):
        """Return the definition for ``key`` or 404 if unknown / not allowed."""
        tour = get_visible_tour(key, request.user)
        if tour is None:
            return JsonResponse({"error": "Unknown tour"}, status=404)
        data = tour.to_dict(request.user)
        data["labels"] = ui_labels()
        return JsonResponse(data)


class TourSeenView(LoginRequiredMixin, View):
    """Remember that a tour has started by itself, so it does not start again."""

    def post(self, request, *args, **kwargs):
        """Record ``{key}`` for the user (idempotent)."""
        try:
            data = json.loads(request.body or b"{}")
            key = data["key"]
        except (KeyError, TypeError, ValueError):
            return HttpResponseBadRequest("Invalid payload")

        if get_visible_tour(key, request.user) is None:
            return JsonResponse({"error": "Unknown tour"}, status=404)

        TourSeen.objects.get_or_create(user=request.user, tour_key=key)
        return JsonResponse({"ok": True})
