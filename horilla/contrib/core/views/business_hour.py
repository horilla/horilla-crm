"""
Business Hour views for Horilla platform.
"""

# Standard library imports
import logging

from django.contrib import messages

# First-party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import HorillaListView, HorillaSingleFormView
from horilla.urls import reverse, reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.functional import cached_property
from horilla.utils.html import escapejs
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView, View
from horilla.web import HttpResponse, ScriptResponse

# Local imports
from ..forms import BusinessHourForm, BusinessHourHolidayForm
from ..models import BusinessHour, Holiday
from .holiday import HolidayDetailView

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.view_businesshour"), name="dispatch"
)
class BusinessHourView(LoginRequiredMixin, TemplateView):
    """
    Shell template for business + shift hours (Working hours tab).
    """

    template_name = "settings/business_hour/business_hour.html"

    def get_context_data(self, **kwargs):
        """Add the active company's business hour for the Working hours tab shell."""
        context = super().get_context_data(**kwargs)
        company = getattr(self.request, "active_company", None)
        context["company_business_hour"] = None
        if company:
            context["company_business_hour"] = (
                BusinessHour.objects.filter(company_id=company.id)
                .prefetch_related("holidays")
                .first()
            )
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.view_businesshour"), name="dispatch"
)
class BusinessHourCardView(LoginRequiredMixin, TemplateView):
    """Single-company business hour summary card (replaces list on Working hours)."""

    template_name = "settings/business_hour/business_hour_card.html"

    def get_context_data(self, **kwargs):
        """Add the active company's business hour for the summary card."""
        context = super().get_context_data(**kwargs)
        company = getattr(self.request, "active_company", None)
        context["business_hour"] = None
        if company:
            context["business_hour"] = (
                BusinessHour.objects.filter(company_id=company.id)
                .prefetch_related("holidays")
                .first()
            )
        return context


@method_decorator(htmx_required, name="dispatch")
class BusinessHourFormView(LoginRequiredMixin, HorillaSingleFormView):
    """Business Hour Create/Update View."""

    model = BusinessHour
    form_class = BusinessHourForm
    view_id = "business-hour-form-view"
    full_width_fields = ["timing_type", "week_days", "day_quick_fill"]
    hidden_fields = ["company"]
    save_and_new = False
    return_response = ScriptResponse(
        close=True,
        extra="$('#reloadBusinessHourCardButton').click();$('#detailViewReloadButton').click();",
        msgs=True,
    )

    @cached_property
    def form_url(self):
        """Form URL for business hour"""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("core:business_hour_update_form", kwargs={"pk": pk})
        return reverse_lazy("core:business_hour_create_form")

    def get(self, request, *args, **kwargs):
        """Allow a single business hour per company: block duplicate create."""
        pk = kwargs.get("pk") or request.GET.get("id")
        if not pk:
            company = getattr(request, "active_company", None)
            if company and BusinessHour.objects.filter(company_id=company.id).exists():
                return ScriptResponse(close=True, status=200)
        return super().get(request, *args, **kwargs)

    def get_initial(self):
        """Get initial data for the business hour form."""
        initial = super().get_initial()
        toggle = self.request.GET.get("toggle_data")
        company = getattr(self.request, "active_company", None)
        initial["company"] = company
        if toggle == "true":
            initial["business_hour_type"] = self.request.GET.get(
                "business_hour_type", ""
            )
            initial["timing_type"] = self.request.GET.get("timing_type", "")

        elif hasattr(self, "object") and self.object:
            initial["business_hour_type"] = getattr(
                self.object, "business_hour_type", ""
            )
            initial["timing_type"] = getattr(self.object, "timing_type", "")

        else:
            initial["business_hour_type"] = ""
            initial["timing_type"] = ""

        initial.update(self.request.GET.dict())
        return initial


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required_or_denied("core.view_holiday"), name="dispatch")
class BusinessHourHolidayListView(LoginRequiredMixin, HorillaListView):
    """Generic list view for holidays linked to a specific business hour."""

    model = Holiday
    view_id = "bh-holiday-list-view"
    table_height_as_class = "h-[350px]"
    table_width = False
    list_column_visibility = False
    bulk_select_option = False
    store_ordered_ids = True
    columns = ["name", "start_date", "end_date", "is_recurring"]

    @cached_property
    def search_url(self):
        """Return the holiday list search URL for this business hour."""
        return reverse_lazy(
            "core:business_hour_holiday_list_view", kwargs={"pk": self.kwargs["pk"]}
        )

    def get_queryset(self):
        """Return holidays linked to the business hour and store ordered IDs in session."""
        bh_pk = self.kwargs["pk"]
        try:
            bh = BusinessHour.objects.get(pk=bh_pk)
        except BusinessHour.DoesNotExist:
            queryset = Holiday.objects.none()
        else:
            queryset = bh.holidays.order_by("start_date", "name")

        if self.store_ordered_ids:
            self.request.session[self.ordered_ids_key] = list(
                queryset.values_list("pk", flat=True)
            )

        return queryset

    @cached_property
    def col_attrs(self):
        """Add HTMX attributes to open readonly holiday detail from the list."""
        query_string = self.request.session.get(self.ordered_ids_key, [])
        attrs = {}
        if self.request.user.has_perm("core.view_holiday"):
            attrs = {
                "hx-get": f"{{get_bh_readonly_detail_url}}?instance_ids={query_string}",
                "hx-target": "#detailModalBox",
                "hx-swap": "innerHTML",
                "hx-push-url": "false",
                "hx-on:click": "openDetailModal();",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }
        return [{"name": {**attrs}}]

    @cached_property
    def actions(self):
        """Return remove-holiday action for the business hour holiday list."""
        bh_pk = self.kwargs["pk"]
        remove_base = reverse(
            "core:business_hour_holiday_remove",
            kwargs={"pk": bh_pk, "holiday_pk": 0},
        )
        remove_url = remove_base.rsplit("/0/", 1)[0] + "/{pk}/remove/"
        return [
            {
                "action": "Remove",
                "src": "assets/icons/a4.svg",
                "img_class": "w-4 h-4",
                "permission": "core.change_businesshour",
                "attrs": f"""
                    hx-get="{remove_url}"
                    hx-target="#deleteModeBox"
                    hx-swap="innerHTML"
                    hx-trigger="click"
                    """,
            },
        ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.view_businesshour"), name="dispatch"
)
class BusinessHourHolidayModalView(LoginRequiredMixin, TemplateView):
    """Renders the holiday list inside #contentModalBox."""

    template_name = "settings/business_hour/business_hour_holiday_modal.html"

    def get(self, request, *args, **kwargs):
        """Load the holiday modal or close modals when the business hour is missing."""
        pk = self.kwargs.get("pk")
        try:
            BusinessHour.objects.get(pk=pk)
        except BusinessHour.DoesNotExist:
            messages.error(request, _("The requested record does not exist."))
            return HttpResponse(
                "<script>closeDetailModal();closeContentModal();$('#reloadBusinessHourCardButton').click();</script>"
            )
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Add business hour context for the holiday modal."""
        context = super().get_context_data(**kwargs)
        pk = self.kwargs.get("pk")
        context["business_hour"] = BusinessHour.objects.get(pk=pk)
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.change_businesshour"), name="dispatch"
)
class BusinessHourAddHolidayView(LoginRequiredMixin, HorillaSingleFormView):
    """Modal form to select and link unlinked all-users holidays to a business hour."""

    model = BusinessHour
    form_class = BusinessHourHolidayForm
    view_id = "business-hour-add-holiday-form"
    form_title = _("Add Holidays")
    save_and_new = False
    modal_height = False
    full_width_fields = ["holidays"]

    return_response = ScriptResponse(
        close=True,
        extra="$('#reloadBusinessHourCardButton').click();$('#reloadHolidayModalButton').click();",
        msgs=True,
    )

    @cached_property
    def form_url(self):
        """Return the URL for linking holidays to a business hour."""
        pk = self.kwargs.get("pk")
        return reverse_lazy("core:business_hour_add_holiday", kwargs={"pk": pk})


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required_or_denied("core.view_holiday"), name="dispatch")
class BusinessHourHolidayReadonlyDetailView(HolidayDetailView):
    """Read-only holiday detail view opened from the business hour holiday list."""

    actions = []

    def get(self, request, *args, **kwargs):
        """Open readonly holiday detail or refresh modals when the holiday is missing."""
        response = super().get(request, *args, **kwargs)
        if not self.instance:
            return HttpResponse(
                "<script>"
                "closeDetailModal();"
                "$('#reloadHolidayModalButton').click();"
                "$('#reloadBusinessHourCardButton').click();"
                "$('#reloadMessagesButton').click();"
                "</script>"
            )
        return response


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.change_businesshour"), name="dispatch"
)
class BusinessHourHolidayRemoveView(LoginRequiredMixin, View):
    """Remove a single holiday from a business hour (GET checks and confirms, POST removes)."""

    def _get_linked_holiday(self, request, pk, holiday_pk):
        """Return (business_hour, holiday), or None after queuing an error if it is gone."""
        try:
            bh = BusinessHour.objects.get(pk=pk)
            holiday = bh.holidays.get(pk=holiday_pk)
        except Exception:
            messages.error(request, _("The requested holiday does not exist."))
            return None
        return bh, holiday

    def get(self, request, pk, holiday_pk):
        """Show the confirmation only if the holiday is still linked."""
        if not self._get_linked_holiday(request, pk, holiday_pk):
            return HttpResponse(
                "<script>closeDeleteModeModal();"
                "$('#reloadHolidayModalButton').click();"
                "$('#reloadBusinessHourCardButton').click();"
                "$('#reloadMessagesButton').click();</script>"
            )
        confirm_msg = escapejs(_("Are you sure you want to remove this holiday?"))
        return HttpResponse(
            f"""<span hx-post="{request.path}" hx-target="#deleteModeBox"
            hx-trigger="confirmed" hx-on::load="hxConfirm(this,'{confirm_msg}')"></span>"""
        )

    def post(self, request, pk, holiday_pk):
        """Remove a holiday from the business hour and refresh related UI."""
        linked = self._get_linked_holiday(request, pk, holiday_pk)
        if not linked:
            return HttpResponse(
                "<script>closeDeleteModeModal();$('#reloadMessagesButton').click();</script>"
            )
        bh, holiday = linked
        bh.holidays.remove(holiday)
        messages.success(request, f"{holiday.name} removed from business hour")
        return HttpResponse(
            "<script>"
            "closeDeleteModeModal();"
            "$('#reloadHolidayModalButton').click();"
            "$('#reloadBusinessHourCardButton').click();"
            "$('#reloadMessagesButton').click();"
            "</script>"
        )
