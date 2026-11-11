"""Onboarding step owned by the mail app: the outgoing mail server."""

# First party imports (Horilla)
from horilla.registry.onboarding import OnboardingSteps
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import HorillaMailConfiguration


class MailServerOnboarding(OnboardingSteps):
    """Done once the company has an active outgoing mail configuration."""

    key = "mail_server"
    headline = _("Connect your mail server")
    description = _("Send emails on behalf of {company} straight from the app.")
    url_name = "mail:mail_server_view"
    icon = "fa-envelope"
    order = 40
    model = HorillaMailConfiguration

    def get_queryset(self, company):
        """Only active outgoing configurations count: they are the ones that can send mail."""
        return super().get_queryset(company).filter(mail_channel="outgoing")
