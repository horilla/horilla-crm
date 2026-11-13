"""
Fiscal Year management views for Horilla Core.
"""

# Standard library imports
import calendar
from datetime import datetime
from functools import cached_property

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import HorillaSingleFormView
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.decorators.wrapper import permission_required_or_denied
from horilla.views.generic import DetailView, TemplateView, View
from horilla.web import HttpNotFound, HttpResponse, ScriptResponse

# Local imports
from ..forms import FiscalYearForm
from ..mixins import FiscalYearCalendarMixin
from ..models import FiscalYear, FiscalYearInstance


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required_or_denied("core.view_company"), name="dispatch")
class CompanyFiscalYearTab(LoginRequiredMixin, TemplateView):
    """
    TemplateView for fiscal year tab.
    """

    template_name = "settings/fiscal_year.html"

    def get_context_data(self, **kwargs):
        """
        Get context data for fiscal year tab.
        """
        context = super().get_context_data(**kwargs)
        company = getattr(self.request, "active_company", None)
        if company:
            cmp = company
        else:
            cmp = self.request.user.company
        if not company:
            context["has_company"] = False
            return context
        obj = cmp.fiscalyear_set.first() if cmp.fiscalyear_set.exists() else None
        start_date = None
        if obj:
            current_fy_instance = obj.year_instances.filter(is_current=True).first()
            if current_fy_instance:
                start_date = current_fy_instance.start_date
        context["obj"] = obj
        context["start_date"] = start_date
        context["has_company"] = True
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["core.add_fiscalyear", "core.change_fiscalyear"],
    ),
    name="dispatch",
)
class FiscalYearFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Form view for creating or editing a Fiscal Year configuration.

    Dynamically renders form fields based on the fiscal year type
    (standard or custom) and calculates preview data for display.
    """

    model = FiscalYear
    form_class = FiscalYearForm
    full_width_fields = [
        "fiscal_year_type",
        "format_type",
        "quarter_based_format",
        "year_based_format",
        "period_display_option",
    ]
    template_name = "settings/fiscal_year_form.html"
    save_and_new = False

    def get_fields(self):
        """Return fields based on fiscal year type"""
        base_fields = ["fiscal_year_type"]

        fiscal_year_type = self.request.GET.get(
            "fiscal_year_type"
        ) or self.request.POST.get("fiscal_year_type")

        if fiscal_year_type == "standard":
            return base_fields + ["start_date_month", "display_year_based_on"]

        if fiscal_year_type == "custom":
            return base_fields + [
                "format_type",
                "quarter_based_format",
                "year_based_format",
                "start_date_month",
                "start_date_day",
                "week_start_day",
                "display_year_based_on",
                "number_weeks_by",
                "period_display_option",
            ]

        return base_fields + ["format_type"]

    @cached_property
    def form_url(self):
        """
        Resolve form submission URL for create or update operation.
        """
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("core:fiscal_year_form_edit", kwargs={"pk": pk})
        return reverse_lazy("core:fiscal_year_form")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get current values for preview calculation
        fiscal_year_type = self.request.GET.get(
            "fiscal_year_type"
        ) or self.request.POST.get("fiscal_year_type")
        format_type = self.request.GET.get("format_type") or self.request.POST.get(
            "format_type"
        )
        year_based_format = self.request.GET.get(
            "year_based_format"
        ) or self.request.POST.get("year_based_format")
        quarter_based_format = self.request.GET.get(
            "quarter_based_format"
        ) or self.request.POST.get("quarter_based_format")
        period_display_option = self.request.GET.get(
            "period_display_option"
        ) or self.request.POST.get("period_display_option")

        # If we have an existing object, get values from it
        if self.object:
            fiscal_year_type = fiscal_year_type or self.object.fiscal_year_type
            format_type = format_type or self.object.format_type
            year_based_format = year_based_format or self.object.year_based_format
            quarter_based_format = (
                quarter_based_format or self.object.quarter_based_format
            )
            period_display_option = (
                period_display_option or self.object.period_display_option
            )

        # Calculate preview data
        preview_data = self.calculate_preview_data(
            fiscal_year_type,
            format_type,
            year_based_format,
            quarter_based_format,
            period_display_option,
        )

        context.update(
            {
                "fiscal_year_type": fiscal_year_type,
                "format_type": format_type,
                "preview_data": preview_data,
                "show_custom_fields": fiscal_year_type == "custom",
                "show_year_based_format": format_type == "year_based",
                "show_quarter_based_format": format_type == "quarter_based",
            }
        )

        return context

    def calculate_preview_data(
        self,
        fiscal_year_type,
        format_type,
        year_based_format,
        quarter_based_format,
        period_display_option,
    ):
        """Calculate preview data for the selected configuration"""
        current_year = datetime.now().year
        if fiscal_year_type != "custom":
            return {}

        preview = {}

        if format_type == "year_based":
            preview["format_preview"] = "13 Periods per Year, 4 Weeks per Period"
            year_based_format = year_based_format or "3-3-3-4"
            periods = year_based_format.split("-")
            periods = [int(p) for p in periods]
            total_periods = sum(periods)

            preview["quarter_breakdown"] = [
                f"Quarter 1 has {periods[0]} Periods",
                f"Quarter 2 has {periods[1]} Periods",
                f"Quarter 3 has {periods[2]} Periods",
                f"Quarter 4 has {periods[3]} Periods",
            ]

            # Period display preview
            if period_display_option == "number_by_year":
                preview["period_display"] = ", ".join(
                    [f"P{i} {current_year}" for i in range(1, total_periods + 1)]
                )
            elif period_display_option == "number_by_quarter":
                period_preview = []
                for q, quarter_periods in enumerate(periods, 1):
                    for p in range(1, quarter_periods + 1):
                        period_preview.append(f"Q{q}-P{p} {current_year}")
                preview["period_display"] = ", ".join(period_preview)

        elif format_type == "quarter_based":
            preview["format_preview"] = "4 Quarters per Year, 13 Weeks per Quarter"
            quarter_based_format = quarter_based_format or "4-4-5"
            weeks = quarter_based_format.split("-")
            weeks = [int(w) for w in weeks]

            preview["quarter_breakdown"] = [
                f"Period 1 has {weeks[0]} Weeks",
                f"Period 2 has {weeks[1]} Weeks",
                f"Period 3 has {weeks[2]} Weeks",
            ]

            if period_display_option == "number_by_year":
                preview["period_display"] = ", ".join(
                    [f"P{i} {current_year}" for i in range(1, 13)]
                )
            elif period_display_option == "number_by_quarter":
                period_preview = []
                for q in range(1, 5):
                    for p in range(1, 4):
                        period_preview.append(f"Q{q}-P{p} {current_year}")
                preview["period_display"] = ", ".join(period_preview)

        return preview

    def form_valid(self, form):
        super().form_valid(form)
        return ScriptResponse(
            extra="htmx.trigger('#tab-fiscal-year-view','click');", close=True
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["core.add_fiscalyear", "core.change_fiscalyear"],
    ),
    name="dispatch",
)
class FiscalYearFieldsView(LoginRequiredMixin, View):
    """
    HTMX GET-only endpoint for dynamically updating fiscal year form fields.
    """

    template_name = "settings/fiscal_year_fields.html"
    http_method_names = ["get", "head", "options"]

    def get(self, request, *args, **kwargs):
        """
        Handle GET request for FiscalYearFieldsView class
        """
        fiscal_year_type = request.GET.get("fiscal_year_type", "")
        format_type = request.GET.get("format_type", "")
        year_based_format = request.GET.get("year_based_format", "")
        quarter_based_format = request.GET.get("quarter_based_format", "")
        period_display_option = request.GET.get("period_display_option", "")

        pk = kwargs.get("pk")
        fiscal_year_obj = None
        if pk:
            try:
                fiscal_year_obj = FiscalYear.objects.get(pk=pk)
            except FiscalYear.DoesNotExist:
                fiscal_year_obj = None

        form_data = {
            "fiscal_year_type": fiscal_year_type,
            "format_type": format_type,
            "year_based_format": year_based_format,
            "quarter_based_format": quarter_based_format,
            "period_display_option": period_display_option,
            "start_date_month": request.GET.get("start_date_month", ""),
            "start_date_day": request.GET.get("start_date_day", ""),
            "week_start_day": request.GET.get("week_start_day", ""),
            "display_year_based_on": request.GET.get("display_year_based_on", ""),
            "number_weeks_by": request.GET.get("number_weeks_by", ""),
        }

        if fiscal_year_obj:
            form = FiscalYearForm(instance=fiscal_year_obj, data=form_data)
        else:
            form = FiscalYearForm(data=form_data if fiscal_year_type else None)

        form.errors.clear()

        preview_data = self.calculate_preview_data(
            fiscal_year_type,
            format_type,
            year_based_format,
            quarter_based_format,
            period_display_option,
        )

        context = {
            "form": form,
            "fiscal_year_type": fiscal_year_type,
            "format_type": format_type,
            "year_based_format": year_based_format,
            "quarter_based_format": quarter_based_format,
            "period_display_option": period_display_option,
            "preview_data": preview_data,
            "show_custom_fields": fiscal_year_type == "custom",
            "show_year_based_format": format_type == "year_based",
            "show_quarter_based_format": format_type == "quarter_based",
            "object": fiscal_year_obj,
            "full_width_fields": [
                "fiscal_year_type",
                "format_type",
                "quarter_based_format",
                "year_based_format",
                "period_display_option",
            ],
        }

        return render(request, self.template_name, context)

    def calculate_preview_data(
        self,
        fiscal_year_type,
        format_type,
        year_based_format,
        quarter_based_format,
        period_display_option,
    ):
        """Calculate preview data for the selected configuration"""
        current_year = datetime.now().year
        if fiscal_year_type != "custom":
            return {}

        preview = {}

        if format_type == "year_based" and year_based_format:
            preview["format_preview"] = "13 Periods per Year, 4 Weeks per Period"
            year_based_format = year_based_format or "3-3-3-4"
            periods = year_based_format.split("-")
            periods = [int(p) for p in periods]
            total_periods = sum(periods)

            preview["quarter_breakdown"] = [
                f"Quarter 1 has {periods[0]} Periods",
                f"Quarter 2 has {periods[1]} Periods",
                f"Quarter 3 has {periods[2]} Periods",
                f"Quarter 4 has {periods[3]} Periods",
            ]

            if period_display_option == "number_by_year":
                preview["period_display"] = ", ".join(
                    [f"P{i} {current_year}" for i in range(1, total_periods + 1)]
                )
            elif period_display_option == "number_by_quarter":
                period_preview = []
                for q, quarter_periods in enumerate(periods, 1):
                    for p in range(1, quarter_periods + 1):
                        period_preview.append(f"Q{q}-P{p} {current_year}")
                preview["period_display"] = ", ".join(period_preview)

        elif format_type == "quarter_based" and quarter_based_format:
            preview["format_preview"] = "4 Quarters per Year, 13 Weeks per Quarter"
            quarter_based_format = quarter_based_format or "4-4-5"
            weeks = quarter_based_format.split("-")
            weeks = [int(w) for w in weeks]

            preview["quarter_breakdown"] = [
                f"Period 1 has {weeks[0]} Weeks",
                f"Period 2 has {weeks[1]} Weeks",
                f"Period 3 has {weeks[2]} Weeks",
            ]

            if period_display_option == "number_by_year":
                preview["period_display"] = ", ".join(
                    [f"P{i} {current_year}" for i in range(1, 13)]
                )
            elif period_display_option == "number_by_quarter":
                period_preview = []
                for q in range(1, 5):
                    for p in range(1, 4):
                        period_preview.append(f"Q{q}-P{p} {current_year}")
                preview["period_display"] = ", ".join(period_preview)

        return preview


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["core.add_fiscalyear", "core.change_fiscalyear"],
    ),
    name="dispatch",
)
class CalculateStartDateDayView(LoginRequiredMixin, View):
    """
    HTMX endpoint to calculate the start_date_day (first matching date in the
    selected start_date_month) for a given week_start_day and update the
    start_date_day input field.
    """

    def get(self, request, *args, **kwargs):
        """
        Return the day input partial with the first day of the selected month
        that falls on the selected week start day.
        """
        start_date_month = request.GET.get("start_date_month")
        week_start_day = (request.GET.get("week_start_day") or "").lower().strip()
        current_year = datetime.now().year
        form = FiscalYearForm()
        day_value = ""

        weekday_mapping = {
            "mon": 0,
            "tue": 1,
            "wed": 2,
            "thu": 3,
            "fri": 4,
            "sat": 5,
            "sun": 6,
        }
        month_names = [m.lower() for m in calendar.month_name if m]

        if start_date_month and week_start_day in weekday_mapping:
            try:
                month_str = start_date_month.lower().strip()
                month = (
                    month_names.index(month_str) + 1
                    if month_str in month_names
                    else int(start_date_month)
                )
                if 1 <= month <= 12:
                    first_weekday = calendar.monthrange(current_year, month)[0]
                    day_value = (
                        (weekday_mapping[week_start_day] - first_weekday) % 7
                    ) + 1
            except ValueError:
                pass

        context = {"form": form, "start_date_day_value": day_value}
        return render(request, "settings/start_date_day_input.html", context)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["core.add_fiscalyear", "core.change_fiscalyear"],
    ),
    name="dispatch",
)
class CalculateWeekStartDayView(LoginRequiredMixin, View):
    """
    HTMX endpoint to calculate the day of the week for a given start_date_month and start_date_day
    and update the week_start_day select field.
    """

    def get(self, request, *args, **kwargs):
        """
        Handle GET request to calculate the week start day for a given start date.

        Returns an HTMX-rendered partial template with the selected week start day.
        """
        start_date_month = request.GET.get("start_date_month")
        start_date_day = request.GET.get("start_date_day")
        current_year = datetime.now().year  # Use current year or allow passing a year
        form = FiscalYearForm()
        selected_day = ""

        month_mapping = {
            "january": 1,
            "february": 2,
            "march": 3,
            "april": 4,
            "may": 5,
            "june": 6,
            "july": 7,
            "august": 8,
            "september": 9,
            "october": 10,
            "november": 11,
            "december": 12,
        }

        if start_date_month and start_date_day:
            try:
                month_str = start_date_month.lower().strip()
                month = month_mapping.get(month_str)
                if not month:
                    month = int(start_date_month)

                day = int(start_date_day)

                if (
                    1 <= month <= 12
                    and 1 <= day <= calendar.monthrange(current_year, month)[1]
                ):
                    date_obj = datetime(current_year, month, day)
                    day_of_week = date_obj.weekday()
                    day_mapping = {
                        0: "mon",
                        1: "tue",
                        2: "wed",
                        3: "thu",
                        4: "fri",
                        5: "sat",
                        6: "sun",
                    }
                    selected_day = day_mapping.get(day_of_week, "")

            except (ValueError, KeyError):
                pass

        context = {"form": form, "week_start_day_value": selected_day}
        return render(request, "settings/week_start_day_select.html", context)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["core.add_fiscalyear", "core.change_fiscalyear"],
    ),
    name="dispatch",
)
class FiscalYearCalendarPreviewView(LoginRequiredMixin, View, FiscalYearCalendarMixin):
    """
    HTMX GET-only endpoint to preview the fiscal year calendar based on user selections.
    """

    template_name = "settings/fiscal_year_calendar_preview.html"
    http_method_names = ["get", "head", "options"]

    def get(self, request, *args, **kwargs):
        """
        Handle GET request
        """
        fiscal_year_data = {
            "fiscal_year_type": request.GET.get("fiscal_year_type", "standard"),
            "format_type": request.GET.get("format_type", ""),
            "year_based_format": request.GET.get("year_based_format", ""),
            "quarter_based_format": request.GET.get("quarter_based_format", ""),
            "number_weeks_by": request.GET.get("number_weeks_by", "year"),
            "period_display_option": request.GET.get(
                "period_display_option", "number_by_year"
            ),
        }
        start_date_month = request.GET.get("start_date_month", "january")
        start_date_day = int(request.GET.get("start_date_day", 1))
        week_start_day = request.GET.get("week_start_day", "monday")

        context = self.get_calendar_data(
            fiscal_year_data, start_date_month, start_date_day, week_start_day
        )
        context.update(
            {
                "view_id": request.GET.get("view_id", "fiscalyear-form-view"),
                "form_url": request.GET.get("form_url", ""),
            }
        )

        return render(request, self.template_name, context)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.view_fiscalyear"),
    name="dispatch",
)
class FiscalYearCalendarView(LoginRequiredMixin, DetailView, FiscalYearCalendarMixin):
    """
    Detailed view for a Fiscal Year and its instances with calendar visualization.
    """

    model = FiscalYear
    template_name = "settings/fiscal_calendar.html"
    context_object_name = "fiscal_year"

    def get(self, request, *args, **kwargs):
        """Return 404 script or delegate to parent get for fiscal year detail."""
        pk = self.kwargs.get("pk")
        try:
            get_object_or_404(FiscalYear, pk=pk)
        except Exception as e:
            messages.error(self.request, str(e))
            return HttpResponse(
                "<script>$('#tab-fiscal-year-view').click();closeCalendarPreviewModal()</script>"
            )
        return super().get(request, *args, **kwargs)

    def get_object(self, queryset=None):
        """Return FiscalYear by pk or raise HttpNotFound."""
        pk = self.kwargs.get(self.pk_url_kwarg)
        try:
            return FiscalYear.objects.get(pk=pk)
        except (FiscalYear.DoesNotExist, ValueError, TypeError) as e:
            raise HttpNotFound(e) from e

    def get_context_data(self, **kwargs):
        """Add fiscal year instances, calendar data, and navigation context."""
        context = super().get_context_data(**kwargs)
        fiscal_year = self.get_object()

        fiscal_year_data = {
            "fiscal_year_type": fiscal_year.fiscal_year_type,
            "format_type": fiscal_year.format_type,
            "year_based_format": fiscal_year.year_based_format,
            "quarter_based_format": fiscal_year.quarter_based_format,
            "number_weeks_by": fiscal_year.number_weeks_by,
            "period_display_option": fiscal_year.period_display_option,
        }
        start_date_month = fiscal_year.start_date_month
        start_date_day = fiscal_year.start_date_day
        week_start_day = fiscal_year.week_start_day
        company = getattr(self.request, "active_company", None)
        fiscal_year_instances = FiscalYearInstance.objects.filter(
            fiscal_year_config=fiscal_year, company=company
        ).order_by("start_date")

        current_instance = fiscal_year_instances.filter(is_current=True).first()

        if not current_instance:
            today = datetime.now().date()
            current_instance = fiscal_year_instances.filter(
                start_date__lte=today, end_date__gte=today
            ).first()

        selected_instance_id = self.request.GET.get(
            "fy_instance"
        ) or self.request.POST.get("fy_instance")
        if selected_instance_id:
            try:
                selected_instance = fiscal_year_instances.get(id=selected_instance_id)
            except FiscalYearInstance.DoesNotExist:
                selected_instance = current_instance
        else:
            selected_instance = current_instance

        if selected_instance:
            actual_start_date = selected_instance.start_date
            calendar_year = actual_start_date.year
            start_date_month = actual_start_date.strftime("%B").lower()
            start_date_day = actual_start_date.day
        else:
            calendar_year = datetime.now().year

        # Determine Previous and Next instances
        previous_instance = None
        next_instance = None
        if current_instance:
            instances_list = list(fiscal_year_instances)
            try:
                current_index = instances_list.index(current_instance)
                if current_index > 0:
                    previous_instance = instances_list[current_index - 1]
                if current_index < len(instances_list) - 1:
                    next_instance = instances_list[current_index + 1]
            except ValueError:
                pass

        calendar_context = self.get_calendar_data(
            fiscal_year_data,
            start_date_month,
            start_date_day,
            week_start_day,
            current_year=calendar_year,
        )

        context.update(calendar_context)
        context.update(
            {
                "fiscal_year_instances": fiscal_year_instances,
                "current_instance": current_instance,
                "selected_instance": selected_instance,
                "previous_instance": previous_instance,
                "next_instance": next_instance,
            }
        )

        return context

    def render_to_response(self, context, **response_kwargs):
        """Render template; return HTML string in HttpResponse for HTMX or full page."""

        return render(self.request, self.template_name, context)
