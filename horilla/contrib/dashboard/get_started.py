"""
Request side of the home page "Get started" guide: the company the user is working
in, the steps skipped in the session, and the template context.

The guide itself is built by ``build_onboarding`` in ``horilla.registry.onboarding``.
"""

# First party imports (Horilla)
from horilla.registry.onboarding import build_onboarding

SKIPPED_SESSION_KEY = "onboarding_skipped"  # session: {company id: [skipped step keys]}


def get_active_company(request):
    """The company the user is working in (company switcher aware)."""
    return getattr(request, "active_company", None) or getattr(
        request.user, "company", None
    )


def get_skipped_steps(request, company):
    """Keys of the steps skipped for ``company`` in this session."""
    return list(request.session.get(SKIPPED_SESSION_KEY, {}).get(str(company.pk), []))


def skip_step(request, company, key):
    """Remember in the session that ``key`` was skipped for ``company``."""
    skipped = request.session.get(SKIPPED_SESSION_KEY, {})
    keys = skipped.get(str(company.pk), [])
    if key not in keys:
        skipped[str(company.pk)] = keys + [key]
        request.session[SKIPPED_SESSION_KEY] = skipped


def get_onboarding_context(request):
    """Template context for ``home/onboarding.html``, for the active company."""
    from .models import OnboardingState  # pylint: disable=import-outside-toplevel

    company = get_active_company(request)
    guide = build_onboarding(
        request.user, company, get_skipped_steps(request, company) if company else ()
    )
    return {
        "onboarding": guide,
        "onboarding_hidden": bool(guide) and OnboardingState.is_hidden_for(company),
    }
