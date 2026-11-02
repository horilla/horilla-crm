"""Views for managing multiple currencies and conversion rates."""

# Standard library imports
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from functools import cached_property

# Third-party imports (Django)
from django.contrib import messages
from django.utils.dateparse import parse_date

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
)
from horilla.db import transaction
from horilla.shortcuts import render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import FormView, TemplateView, View
from horilla.web import HttpResponseBadRequest, HxTriggerResponse, ScriptResponse

# Local imports
from ..forms import ConversionRateForm, CurrencyForm, DatedConversionRateForm
from ..models import DatedConversionRate, MultipleCurrency
from ..utils import fetch_exchange_rate_from_api

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.view_multiplecurrency"), name="dispatch"
)
class CompanyMultipleCurrency(LoginRequiredMixin, TemplateView):
    """
    TemplateView for multiple currency view.
    """

    template_name = "settings/multiple_currency.html"

    def get_context_data(self, **kwargs):
        """
        Get context data for multiple currency view.
        """
        context = super().get_context_data(**kwargs)
        company = getattr(self.request, "active_company", None)
        if company:
            cmp = company
        else:
            cmp = self.request.user.company
        context["has_company"] = bool(cmp)
        if not cmp:
            return context
        currencies = MultipleCurrency.objects.filter(company=cmp)
        obj = currencies.filter(company=cmp, is_default=True).first()
        context["obj"] = obj
        context["cmp"] = cmp
        context["currencies"] = currencies
        context["currency_count"] = currencies.count()
        start_dates = (
            DatedConversionRate.objects.values_list("start_date", flat=True)
            .distinct()
            .order_by("start_date")
        )
        date_ranges = []
        current_date = datetime.now().date()
        selected_start_date = None

        for i, start_date in enumerate(start_dates):
            end_date = None
            if i < len(start_dates) - 1:
                end_date = start_dates[i + 1] - timedelta(days=1)
                date_ranges.append(
                    {
                        "start_date": start_date,
                        "end_date": end_date,
                        "display": f"{start_date.strftime('%d-%m-%Y')} to {end_date.strftime('%d-%m-%Y')}",
                    }
                )
                if start_date <= current_date <= end_date:
                    selected_start_date = start_date
            else:
                date_ranges.append(
                    {
                        "start_date": start_date,
                        "end_date": None,
                        "display": f"{start_date.strftime('%d-%m-%Y')} and After",
                    }
                )
                if start_date <= current_date:
                    selected_start_date = start_date

        context["date_ranges"] = date_ranges
        if selected_start_date is None and start_dates:
            selected_start_date = start_dates[0]
        context["selected_start_date"] = selected_start_date
        return context

    def post(self, request, *args, **kwargs):
        """Handle HTMX toggle for multiple currency activation"""
        company = getattr(request, "active_company", None)
        if company:
            cmp = company
        else:
            cmp = request.user.company

        if not request.user.has_perm("core.change_company"):
            return render(request, "403.html")

        requested = request.POST.get("enable")
        if requested in ("true", "false"):
            enable = requested == "true"
        else:
            enable = not cmp.activate_multiple_currencies

        if enable == cmp.activate_multiple_currencies:
            # Another tab/user already changed it; the page is stale.
            if enable:
                messages.info(request, _("Multiple currency is already enabled."))
            else:
                messages.info(request, _("Multiple currency is already disabled."))
        else:
            cmp.activate_multiple_currencies = enable
            cmp.save()
            if enable:
                messages.success(request, _("Multiple currency enabled successfully."))
            else:
                messages.success(request, _("Multiple currency disabled successfully."))

        context = self.get_context_data(**kwargs)
        response = render(request, self.template_name, context)
        response.content += b"<script>$('#reloadMessagesButton').click();</script>"
        return response


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.view_multiplecurrency"), name="dispatch"
)
class CurrencyNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar for the currency management tab.
    """

    nav_title = _("Currency Management")
    nav_description = _("Set your default currency and manage exchange rates.")
    search_url = reverse_lazy("core:currency_list_view")
    main_url = reverse_lazy("core:multiple_currency")
    model_name = "MultipleCurrency"
    model_app_label = "core"
    nav_width = False
    one_view_only = True
    all_view_types = False
    filter_option = False
    reload_option = False
    search_option = False
    search_push_url = False
    enable_actions = True

    @cached_property
    def new_button(self):
        """
        Get the configuration for the "Add Currency" button.
        """
        company = (
            getattr(self.request, "active_company", None) or self.request.user.company
        )
        if (
            company
            and company.activate_multiple_currencies
            and self.request.user.has_perm("core.add_multiplecurrency")
        ):
            return {
                "url": reverse_lazy("core:add_currency"),
                "title": _("Add"),
                "attrs": {"id": "add-currency-btn"},
            }
        return None

    @cached_property
    def actions(self):
        """
        Menu actions for changing the default currency and managing rates.
        """
        user = self.request.user
        company = getattr(self.request, "active_company", None) or user.company
        if not company or not company.activate_multiple_currencies:
            return []
        if MultipleCurrency.objects.filter(company=company).count() < 2:
            return []
        modal_attrs = """
            hx-get="{url}"
            hx-target="#modalBox"
            hx-swap="innerHTML"
            hx-on:click="openModal();"
        """
        actions = []
        if user.has_perm("core.change_multiplecurrency") and user.has_perm(
            "core.change_company"
        ):
            actions.append(
                {
                    "action": _("Change Default Currency"),
                    "attrs": modal_attrs.format(
                        url=reverse_lazy("core:change_default_currency_view")
                    ),
                }
            )
        if user.has_perm("core.change_multiplecurrency"):
            actions.append(
                {
                    "action": _("Edit Conversion Rates"),
                    "attrs": modal_attrs.format(
                        url=reverse_lazy("core:conversion_rate_view")
                    ),
                }
            )
        if user.has_perm("core.view_datedconversionrate"):
            actions.append(
                {
                    "action": _("Dated Exchange Rates"),
                    "attrs": f"""
                        hx-get="{reverse_lazy("core:multiple_currency")}?dated_exchange=true"
                        hx-target="#inner-tab-currency-view-content"
                        hx-swap="innerHTML"
                        hx-push-url="?dated_exchange=true"
                    """,
                }
            )
        return actions


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["core.add_multiplecurrency", "core.change_multiplecurrency"],
    ),
    name="dispatch",
)
class FetchExchangeRateView(LoginRequiredMixin, View):
    """
    HTMX endpoint to fetch exchange rate when currency is selected.
    Returns the exchange rate value to auto-populate the conversion_rate field.
    """

    def get(self, request, *args, **kwargs):
        """Handle GET request to fetch exchange rate for selected currency."""
        currency_code = request.GET.get("currency")
        company = getattr(request, "active_company", None) or request.user.company

        # Get the default currency for the company
        default_currency = MultipleCurrency.objects.filter(
            company=company, is_default=True
        ).first()

        # Render conversion_rate input via template engine (value auto-escaped, XSS-safe)
        def _conversion_input_response(value):
            return render(
                request,
                "settings/conversion_rate_input.html",
                {"value": value},
            )

        # If currency or default not available, keep the input and let user type manually
        if not currency_code or not default_currency:
            return _conversion_input_response("")

        # Don't fetch rate if selecting the same as default currency
        if currency_code == default_currency.currency:
            return _conversion_input_response("1.0000")

        # Fetch exchange rate from free API
        rate = fetch_exchange_rate_from_api(default_currency.currency, currency_code)

        if rate:
            return _conversion_input_response(rate)

        logger.warning(
            "Exchange rate not available for %s to %s",
            default_currency.currency,
            currency_code,
        )
        # Keep an empty input so the user can manually enter the rate
        return _conversion_input_response("")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.view_multiplecurrency"),
    name="dispatch",
)
class CurrencyListView(LoginRequiredMixin, HorillaListView):
    """
    List View for currency list.
    """

    model = MultipleCurrency
    view_id = "currency-list-view"
    table_auto = True
    bulk_select_option = False
    search_url = reverse_lazy("core:currency_list_view")
    main_url = reverse_lazy("core:currency_list_view")
    enable_sorting = False
    list_column_visibility = False

    @cached_property
    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        if self.request.user.has_perm("core.add_multiplecurrency"):
            return {
                "url": f"""{reverse_lazy("core:add_currency")}?new=true""",
                "attrs": 'id="currency-create"',
            }
        return None

    def get_queryset(self):
        queryset = super().get_queryset()
        return (
            queryset
            if self.request.GET.get("sort")
            else queryset.order_by("-is_default")
        )

    @cached_property
    def columns(self):
        """
        Define columns for the currency list view.
        """
        instance = self.model()
        return [
            (_("Currency Code"), "get_currency_code"),
            "currency",
            (instance._meta.get_field("is_default").verbose_name, "is_default_col"),
            "conversion_rate",
            "is_active",
            "decimal_places",
        ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4 flex gap-4",
            "permission": "core.change_multiplecurrency",
            "attrs": """
                        hx-get="{get_edit_url}"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "core.delete_multiplecurrency",
            "disabled_if": lambda obj: obj.is_default,
            "disabled_title": _("Default currency can't be deleted"),
            "attrs": """
                            hx-post="{get_delete_url}"
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            hx-trigger="click"
                            onclick="openModal()"
                            """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["core.change_multiplecurrency", "core.change_company"],
        modal=True,
    ),
    name="dispatch",
)
class ChangeDefaultCurrencyView(LoginRequiredMixin, View):
    """
    View to change the default currency for a company and update conversion rates.
    """

    def post(self, request, *args, **kwargs):
        """Handle the POST request to change the default currency."""
        currency_id = kwargs.get("pk")
        if not currency_id:
            return HttpResponseBadRequest("Currency ID is required.")

        try:
            company = getattr(request, "active_company", None) or request.user.company
            new_default_currency = MultipleCurrency.objects.get(
                id=currency_id, company=company
            )
            with transaction.atomic():
                current_default = MultipleCurrency.objects.filter(
                    company=company, is_default=True
                ).first()

                if current_default and current_default.id == new_default_currency.id:
                    messages.info(request, _("Currency is already the default."))
                    return HxTriggerResponse(id="tab-currency-view")

                original_new_default_rate = (
                    new_default_currency.conversion_rate or Decimal("1.0")
                )

                currencies_to_update = []
                for curr in MultipleCurrency.objects.filter(company=company):
                    if curr.id == new_default_currency.id:
                        curr.conversion_rate = Decimal("1.0")
                        curr.is_default = True
                    else:
                        current_rate = curr.conversion_rate or Decimal("1.0")
                        curr.conversion_rate = current_rate / original_new_default_rate
                        curr.is_default = False
                    currencies_to_update.append(curr)
                MultipleCurrency.objects.bulk_update(
                    currencies_to_update, ["conversion_rate", "is_default"]
                )
                MultipleCurrency.invalidate_default_currency_cache(company.pk)

                new_default_dated_rates = {}
                existing_dated_rates = DatedConversionRate.objects.filter(
                    company=company, currency=new_default_currency
                )
                for rate in existing_dated_rates:
                    new_default_dated_rates[rate.start_date] = rate.conversion_rate

                DatedConversionRate.objects.filter(
                    company=company, currency=new_default_currency
                ).delete()

                dated_rates = list(DatedConversionRate.objects.filter(company=company))
                if current_default:
                    start_dates = {r.start_date for r in dated_rates}
                    existing_default_rates = {
                        r.start_date: r
                        for r in DatedConversionRate.objects.filter(
                            company=company,
                            currency=current_default,
                        )
                    }
                    rates_to_create = []
                    rates_to_update = []
                    for start_date_value in start_dates:
                        old_default_new_rate = 1 / new_default_dated_rates.get(
                            start_date_value, original_new_default_rate
                        )
                        existing_rate = existing_default_rates.get(start_date_value)
                        if existing_rate:
                            existing_rate.conversion_rate = old_default_new_rate
                            rates_to_update.append(existing_rate)
                        else:
                            rates_to_create.append(
                                DatedConversionRate(
                                    company=company,
                                    currency=current_default,
                                    conversion_rate=old_default_new_rate,
                                    start_date=start_date_value,
                                    created_by=self.request.user,
                                    updated_by=self.request.user,
                                )
                            )
                    if rates_to_update:
                        DatedConversionRate.objects.bulk_update(
                            rates_to_update, ["conversion_rate"]
                        )
                    if rates_to_create:
                        DatedConversionRate.objects.bulk_create(rates_to_create)

                other_dated_rates_to_update = []
                for rate in dated_rates:
                    if rate.currency != current_default:
                        current_rate = rate.conversion_rate or Decimal("1.0")
                        divisor_rate = new_default_dated_rates.get(
                            rate.start_date, original_new_default_rate
                        )
                        rate.conversion_rate = current_rate / divisor_rate
                        other_dated_rates_to_update.append(rate)
                if other_dated_rates_to_update:
                    DatedConversionRate.objects.bulk_update(
                        other_dated_rates_to_update, ["conversion_rate"]
                    )

                company.currency = new_default_currency.currency
                company.save()

            messages.success(request, _("Default currency changed successfully."))
            return HxTriggerResponse(id="tab-currency-view")

        except MultipleCurrency.DoesNotExist:
            messages.error(
                self.request,
                "Invalid currency ID or currency doesn't belong to your company.",
            )
            return ScriptResponse(reload=True)
        except ValueError as e:
            messages.error(self.request, f"Failed to update conversion rates: {e}")
            return ScriptResponse(reload=True)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["core.change_multiplecurrency", "core.change_company"],
        modal=True,
    ),
    name="dispatch",
)
class ChangeDefaultCurrencyFormView(LoginRequiredMixin, FormView):
    """
    HTMX endpoint to change the default currency and update conversion rates.
    """

    model = MultipleCurrency
    template_name = "settings/change_default_currency.html"
    form_class = CurrencyForm
    success_url = reverse_lazy("settings:currency_list")

    def get_form_kwargs(self):
        """Pass the current company to the form."""
        kwargs = super().get_form_kwargs()
        company = getattr(self.request, "active_company", None)
        kwargs["company"] = company if company else self.request.user.company
        return kwargs

    def form_valid(self, form):
        """Handle the form submission to update the default currency and conversion rates."""
        currency = form.cleaned_data["currency"]
        company = (
            getattr(self.request, "active_company", None) or self.request.user.company
        )

        try:
            new_default_currency = MultipleCurrency.objects.get(
                pk=currency.pk, company=company
            )

            with transaction.atomic():
                current_default = MultipleCurrency.objects.filter(
                    company=company, is_default=True
                ).first()

                if current_default and current_default.id == new_default_currency.id:
                    messages.info(self.request, _("Currency is already the default."))
                    return ScriptResponse(
                        extra="htmx.trigger('#tab-currency-view','click');",
                        close=True,
                    )

                original_new_default_rate = (
                    new_default_currency.conversion_rate or Decimal("1.0")
                )

                currencies_to_update = []
                for curr in MultipleCurrency.objects.filter(company=company):
                    if curr.id == new_default_currency.id:
                        curr.conversion_rate = Decimal("1.0")
                        curr.is_default = True
                    else:
                        current_rate = curr.conversion_rate or Decimal("1.0")
                        curr.conversion_rate = current_rate / original_new_default_rate
                        curr.is_default = False
                    currencies_to_update.append(curr)
                MultipleCurrency.objects.bulk_update(
                    currencies_to_update, ["conversion_rate", "is_default"]
                )
                MultipleCurrency.invalidate_default_currency_cache(company.pk)

                new_default_dated_rates = {}
                existing_dated_rates = DatedConversionRate.objects.filter(
                    company=company,
                    currency=new_default_currency,
                )
                for rate in existing_dated_rates:
                    new_default_dated_rates[rate.start_date] = rate.conversion_rate

                DatedConversionRate.objects.filter(
                    company=company,
                    currency=new_default_currency,
                ).delete()

                dated_rates = list(DatedConversionRate.objects.filter(company=company))
                if current_default:
                    start_dates = {r.start_date for r in dated_rates}
                    existing_default_rates = {
                        r.start_date: r
                        for r in DatedConversionRate.objects.filter(
                            company=company,
                            currency=current_default,
                        )
                    }
                    rates_to_create = []
                    rates_to_update = []
                    for start_date_value in start_dates:
                        old_default_new_rate = 1 / new_default_dated_rates.get(
                            start_date_value, original_new_default_rate
                        )
                        existing_rate = existing_default_rates.get(start_date_value)
                        if existing_rate:
                            existing_rate.conversion_rate = old_default_new_rate
                            rates_to_update.append(existing_rate)
                        else:
                            rates_to_create.append(
                                DatedConversionRate(
                                    company=company,
                                    currency=current_default,
                                    conversion_rate=old_default_new_rate,
                                    start_date=start_date_value,
                                    created_by=self.request.user,
                                    updated_by=self.request.user,
                                )
                            )
                    if rates_to_update:
                        DatedConversionRate.objects.bulk_update(
                            rates_to_update, ["conversion_rate"]
                        )
                    if rates_to_create:
                        DatedConversionRate.objects.bulk_create(rates_to_create)

                other_dated_rates_to_update = []
                for rate in dated_rates:
                    if rate.currency != current_default:
                        current_rate = rate.conversion_rate or Decimal("1.0")
                        divisor_rate = new_default_dated_rates.get(
                            rate.start_date, original_new_default_rate
                        )
                        rate.conversion_rate = current_rate / divisor_rate
                        other_dated_rates_to_update.append(rate)
                if other_dated_rates_to_update:
                    DatedConversionRate.objects.bulk_update(
                        other_dated_rates_to_update, ["conversion_rate"]
                    )

                company.currency = new_default_currency.currency
                company.save()
            messages.success(self.request, _("Default currency changed successfully."))
            return ScriptResponse(
                extra="htmx.trigger('#tab-currency-view','click');", close=True
            )

        except MultipleCurrency.DoesNotExist:
            return HttpResponseBadRequest(
                "Invalid currency ID or currency doesn't belong to your company."
            )
        except ValueError as e:
            logger.error("Error updating DatedConversionRate: %s", e)
            return HttpResponseBadRequest("Failed to update conversion rates.")

    def form_invalid(self, form):
        """Handle invalid form submission."""
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        """Provide context data for the template."""
        context = super().get_context_data(**kwargs)
        company = (
            getattr(self.request, "active_company", None) or self.request.user.company
        )
        currencies = MultipleCurrency.objects.filter(company=company)
        context["currencies"] = currencies.filter(is_default=False)
        context["current_currency"] = currencies.filter(is_default=True).first()
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["core.add_multiplecurrency", "core.change_multiplecurrency"],
        modal=True,
    ),
    name="dispatch",
)
class AddCurrencyView(LoginRequiredMixin, HorillaSingleFormView):
    """
    View to add a new currency.
    """

    model = MultipleCurrency
    form_title = _("Create Currency")
    modal_height = False
    fields = ["currency", "conversion_rate", "decimal_places", "company"]
    hidden_fields = ["company"]
    return_response = ScriptResponse(
        close=True, extra="$('#tab-currency-view').click();"
    )

    def dispatch(self, request, *args, **kwargs):
        """
        Adjust fields based on whether editing or adding a currency before form creation.
        """
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if not pk:
            company = getattr(request, "active_company", None) or request.user.company
            if not company or not company.activate_multiple_currencies:
                messages.error(
                    request, _("Multiple currencies are disabled for this company.")
                )
                return ScriptResponse(
                    msgs=True, close=True, extra="$('#tab-currency-view').click();"
                )
        if pk:
            is_default = MultipleCurrency.objects.filter(
                pk=pk, is_default=True
            ).exists()
            if is_default:
                self.fields = ["decimal_places", "company"]
                self.full_width_fields = ["decimal_places"]
            else:
                self.fields = ["conversion_rate", "decimal_places", "company"]
                self.full_width_fields = []
            self.form_title = _("Update Currency")
        return super().dispatch(request, *args, **kwargs)

    def get_form(self, form_class=None):
        """
        Add HTMX attributes to the currency field for auto-fetching exchange rates.
        """
        form = super().get_form(form_class)
        pk = self.kwargs.get("pk") or self.request.GET.get("id")

        # Only add HTMX attributes when adding a new currency (not editing)
        if not pk and "currency" in form.fields and "conversion_rate" in form.fields:
            # Attach HTMX behavior to currency field
            form.fields["currency"].widget.attrs.update(
                {
                    "hx-get": reverse_lazy("core:fetch_exchange_rate"),
                    "hx-trigger": "change",
                    "hx-target": "#id_conversion_rate",
                    "hx-swap": "outerHTML",
                    "hx-include": "[name='currency']",
                    "hx-indicator": "#conversion-rate-spinner",
                }
            )
            # Mark the conversion_rate field so the generic template can show an indicator
            form.fields["conversion_rate"].widget.attrs.update(
                {
                    "data_show_conversion_indicator": "true",
                    "data_indicator_text": str(_("Fetching conversion rate...")),
                }
            )
        return form

    def get_initial(self):
        """Set initial company from request active_company or user company."""
        initial = super().get_initial()
        initial["company"] = getattr(self.request, "active_company", None)
        if not initial["company"]:
            initial["company"] = self.request.user.company
        return initial

    @cached_property
    def form_url(self):
        """Determine the form URL for adding or editing a currency."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("core:edit_currency", kwargs={"pk": pk})
        return reverse_lazy("core:add_currency")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.change_multiplecurrency", modal=True),
    name="dispatch",
)
class ConversionRateFormView(LoginRequiredMixin, FormView):
    """
    HTMX endpoint to update conversion rates for multiple currencies.
    """

    template_name = "settings/conversion_rates.html"
    form_class = ConversionRateForm
    success_url = reverse_lazy("settings:currency_list")

    def get_form_kwargs(self):
        """Pass current company to the conversion rate form."""
        kwargs = super().get_form_kwargs()
        company = getattr(self.request, "active_company", None)
        kwargs["company"] = company if company else self.request.user.company
        return kwargs

    def form_valid(self, form):
        """Update default currency and conversion rates; return tab trigger script."""
        company = getattr(self.request, "active_company", None)
        new_default = form.cleaned_data.get("new_default_currency")

        if new_default:
            MultipleCurrency.objects.filter(company=company).update(is_default=False)
            new_default_instance = MultipleCurrency.objects.get(
                pk=new_default.pk, company=company
            )
            new_default_instance.is_default = True
            new_default_instance.save()

        current_default = MultipleCurrency.objects.filter(
            company=company, is_default=True
        ).first()
        for currency in MultipleCurrency.objects.filter(company=company).exclude(
            pk=current_default.pk
        ):
            field_name = f"conversion_rate_{currency.currency}"
            if field_name in form.cleaned_data:
                currency.conversion_rate = form.cleaned_data[field_name]
                currency.save()

        if company and current_default:
            company.currency = current_default.currency
            company.save()

        return ScriptResponse(
            extra="htmx.trigger('#tab-currency-view','click');", close=True
        )

    def form_invalid(self, form):
        """Re-render conversion rate form with validation errors."""
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        """Add current_default and other_currencies for the company to context."""
        context = super().get_context_data(**kwargs)
        company = getattr(self.request, "active_company", None)
        if company:
            context["current_default"] = MultipleCurrency.objects.filter(
                company=company, is_default=True
            ).first()
            context["other_currencies"] = MultipleCurrency.objects.filter(
                company=company
            ).exclude(is_default=True)
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.add_datedconversionrate", modal=True),
    name="dispatch",
)
class DatedConversionRateFormView(LoginRequiredMixin, FormView):
    """
    HTMX endpoint to add dated conversion rates for multiple currencies.
    """

    template_name = "settings/dated_conversion_rates.html"
    form_class = DatedConversionRateForm
    success_url = reverse_lazy("settings:dated_conversion_rate_list")

    def get_form_kwargs(self):
        """Pass current company to the dated conversion rate form."""
        kwargs = super().get_form_kwargs()
        company = getattr(self.request, "active_company", None)
        kwargs["company"] = company if company else self.request.user.company
        return kwargs

    def form_valid(self, form):
        """Create DatedConversionRate for each non-default currency; return tab trigger script."""
        company = (
            getattr(self.request, "active_company", None) or self.request.user.company
        )
        start_date = form.cleaned_data["start_date"]

        # Save dated conversion rates for each non-default currency
        _current_default = MultipleCurrency.objects.filter(
            company=company, is_default=True
        ).first()
        for currency in MultipleCurrency.objects.filter(company=company).exclude(
            is_default=True
        ):
            field_name = f"conversion_rate_{currency.currency}"
            if field_name in form.cleaned_data:
                DatedConversionRate.objects.create(
                    company=company,
                    currency=currency,  # Use the MultipleCurrency object
                    conversion_rate=form.cleaned_data[field_name],
                    start_date=start_date,
                    created_by=self.request.user,
                    updated_by=self.request.user,
                )

        return ScriptResponse(close=True, extra="$('#reloadCurrencyButton').click();")

    def form_invalid(self, form):
        """Re-render dated conversion rate form with validation errors."""
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        """Add current_default and other_currencies for the company to context."""
        context = super().get_context_data(**kwargs)
        company = (
            getattr(self.request, "active_company", None) or self.request.user.company
        )
        context["current_default"] = MultipleCurrency.objects.filter(
            company=company, is_default=True
        ).first()
        context["other_currencies"] = MultipleCurrency.objects.filter(
            company=company
        ).exclude(is_default=True)
        context["dated_rates"] = DatedConversionRate.objects.filter(
            company=company
        ).order_by("currency", "start_date")
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.view_datedconversionrate"),
    name="dispatch",
)
class DatedCurrencyListView(LoginRequiredMixin, HorillaListView):
    """
    List View for currency list.
    """

    model = DatedConversionRate
    view_id = "dated-currency-list-view"
    bulk_select_option = False
    search_url = reverse_lazy("core:dated_currency_list_view")
    main_url = reverse_lazy("core:dated_currency_list_view")
    enable_sorting = False

    @cached_property
    def columns(self):
        """
        Define columns for the dated currency list view.
        """
        instance = self.model()
        return [
            (_("Currency Code"), "currency__currency"),
            (
                instance._meta.get_field("currency").verbose_name,
                "currency__get_currency_display",
            ),
            (instance._meta.get_field("start_date").verbose_name, "start_date"),
            (
                instance._meta.get_field("conversion_rate").verbose_name,
                "conversion_rate",
            ),
        ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4 flex gap-4",
            "permission": "core.change_datedconversionrate",
            "attrs": """
                        hx-get="{get_edit_url}"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "core.delete_datedconversionrate",
            "attrs": """
                            hx-post="{get_delete_url}"
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            hx-trigger="click"
                            onclick="openModal()"
                            """,
        },
    ]

    def get_queryset(self):
        """
        Filter queryset based on the selected start_date from GET parameters.
        """
        queryset = super().get_queryset()
        start_date = self.request.GET.get("start_date", None)
        if start_date:
            try:
                parsed_date = parse_date(start_date)
                if parsed_date:
                    return queryset.filter(start_date=parsed_date)
                return queryset.none()
            except Exception:
                return queryset.none()

        return queryset


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.delete_multiplecurrency", modal=True),
    name="dispatch",
)
class CurrencyDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    HTMX endpoint to delete a currency.
    """

    model = MultipleCurrency

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.is_default:
            messages.error(self.request, _("Default Currency can not delete"))
            response = ScriptResponse(
                extra="$('#reloadCurrencyButton').click();", close=True
            )
            response["HX-Retarget"] = "#currency-list-view"
            return response
        return super().delete(request, *args, **kwargs)

    def get_post_delete_response(self):
        return HxTriggerResponse(
            id="reloadCurrencyButton",
            extra="closeDeleteModeModal();",
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.change_datedconversionrate", modal=True),
    name="dispatch",
)
class DatedConversionRateEditView(LoginRequiredMixin, HorillaSingleFormView):
    """
    View to edit the conversion rate of a dated exchange rate.
    """

    model = DatedConversionRate
    form_title = _("Update Dated Conversion Rate")
    modal_height = False
    fields = ["conversion_rate", "company"]
    hidden_fields = ["company"]
    full_width_fields = ["conversion_rate"]
    return_response = ScriptResponse(
        close=True, extra="$('#reloadCurrencyButton').click();"
    )

    @cached_property
    def form_url(self):
        """Form URL for editing the dated conversion rate."""
        return reverse_lazy(
            "core:edit_dated_conversion_rate", kwargs={"pk": self.kwargs.get("pk")}
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.delete_datedconversionrate", modal=True),
    name="dispatch",
)
class DatedConversionRateDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    HTMX endpoint to delete a dated conversion rate.
    """

    model = DatedConversionRate

    def get_post_delete_response(self):
        return ScriptResponse(
            msgs=True,
            extra="$('#reloadCurrencyButton').click();closeDeleteModeModal();",
        )
