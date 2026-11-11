"""Views to hide, show and skip steps of the home page onboarding guide."""

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.registry.onboarding import build_onboarding
from horilla.shortcuts import render
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.views.generic import View
from horilla.web import HttpResponse

# Local imports
from ..get_started import get_active_company, get_onboarding_context, skip_step
from ..models import OnboardingState


@method_decorator(htmx_required, name="dispatch")
class OnboardingVisibilityView(LoginRequiredMixin, View):
    """
    Superusers only. Dismiss (``hidden=True``) or show again (``hidden=False``) the
    guide for the company they are working in, and return the guide re-rendered.
    Other companies are never touched.
    """

    hidden = True

    def post(self, request, *args, **kwargs):
        """Store the choice for the active company and re-render the guide."""
        if not request.user.is_superuser:
            return HttpResponse(status=403)

        company = get_active_company(request)
        if company is None:
            return HttpResponse(status=400)

        OnboardingState.set_hidden(company, self.hidden)
        return render(
            request,
            "home/onboarding.html",
            {**get_onboarding_context(request), "part": "both"},
        )


@method_decorator(htmx_required, name="dispatch")
class OnboardingSkipView(LoginRequiredMixin, View):
    """
    Superusers only. "Skip For Now" on a step: the guide moves on to the next
    unfinished step. The skip is kept in the session for the active company, so
    the step is offered again the next time the user signs in.
    """

    def post(self, request, key, *args, **kwargs):
        """Remember the skipped step and re-render the guide."""
        if not request.user.is_superuser:
            return HttpResponse(status=403)

        company = get_active_company(request)
        guide = build_onboarding(request.user, company)
        if guide is None or key not in {step["key"] for step in guide["steps"]}:
            return HttpResponse(status=400)

        skip_step(request, company, key)
        return render(
            request,
            "home/onboarding.html",
            {**get_onboarding_context(request), "part": "both"},
        )
