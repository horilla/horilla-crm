"""Views for user unavailability."""

# Standard library imports
import datetime

from horilla.auth.mixins import LoginRequiredMixin

# First party imports (Horilla)
from horilla.contrib.generics.views import (
    HorillaSingleDeleteView,
    HorillaSingleFormView,
)
from horilla.contrib.utils.middlewares import get_active_company
from horilla.urls import reverse_lazy
from horilla.utils import timezone
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.functional import cached_property
from horilla.utils.translation import gettext as _
from horilla.web import HxTriggerResponse, ScriptResponse

# Local imports
from ..forms import UserAvailabilityForm
from ..models import UserAvailability


@method_decorator(htmx_required, name="dispatch")
class UserAvailabilityFormView(LoginRequiredMixin, HorillaSingleFormView):
    """View to handle marking user unavailability via a form."""

    model = UserAvailability
    form_class = UserAvailabilityForm
    form_title = _("Mark Unavailability")
    modal_height = False
    hidden_fields = ["user", "company", "is_active", "google_event_id"]
    full_width_fields = ["from_datetime", "to_datetime", "reason"]
    save_and_new = False

    @cached_property
    def form_url(self):
        """Generate the form URL based on whether it's an update or create action."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "calendar:update_mark_unavailability", kwargs={"pk": pk}
            )
        return reverse_lazy("calendar:mark_unavailability")

    def get_initial(self):
        """Set initial form data (company, user, optional start date/time from request)."""
        initial = super().get_initial()
        company = get_active_company()
        initial["company"] = company
        initial["user"] = self.request.user
        initial["company"] = company
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if not pk:
            date_str = self.request.GET.get("start_date_time")
            if date_str:
                try:
                    clicked_datetime = datetime.datetime.fromisoformat(date_str)

                    clicked_date = clicked_datetime.date()
                    clicked_time = clicked_datetime.time()

                    start_datetime = timezone.make_aware(
                        datetime.datetime.combine(clicked_date, clicked_time)
                    )

                    end_datetime = start_datetime + datetime.timedelta(minutes=30)

                    initial["from_datetime"] = start_datetime
                    initial["to_datetime"] = end_datetime

                except ValueError:
                    initial["from_datetime"] = timezone.now()
                    initial["to_datetime"] = timezone.now()
            else:
                now = timezone.now()
                initial["from_datetime"] = now
                initial["to_datetime"] = now + datetime.timedelta(minutes=30)

        return initial

    def form_valid(self, form):
        """
        Handle form submission and save the meeting.
        """

        super().form_valid(form)
        return ScriptResponse(reload=True, close=True)

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("calendar.delete_userunavailability"),
    name="dispatch",
)
class UserAvailabilityDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View to handle deletion of user unavailability records."""

    model = UserAvailability

    def get_post_delete_response(self):
        return HxTriggerResponse()
