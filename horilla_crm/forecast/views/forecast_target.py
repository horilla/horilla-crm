"""
Views for managing Forecast Targets, including creation, update, deletion,
and dynamic UI handling for role-based and condition-based forecasting.
"""

# Standard library imports
from functools import cached_property

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.auth.models import User
from horilla.contrib.core.models import Period, Role
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla.shortcuts import render
from horilla.urls import reverse_lazy
from horilla.utils import timezone
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView, View
from horilla.web import HttpResponseRedirect, HxTriggerResponse

# Local imports
from horilla_crm.forecast.filters import ForecastTargetFilter
from horilla_crm.forecast.forms import ForecastTargetForm
from horilla_crm.forecast.models import ForecastTarget, ForecastType


class ForecastTargetView(LoginRequiredMixin, HorillaView):
    """Main forecast target settings page."""

    template_name = "forecast_target/forecast_target_view.html"
    nav_url = reverse_lazy("forecast:forecast_target_nav_view")
    list_url = reverse_lazy("forecast:forecast_target_list_view")
    main_url = reverse_lazy("forecast:forecast_target_view")
    filters_url = reverse_lazy("forecast:forecast_target_filters_view")

    def get(self, request, *args, **kwargs):
        """Validate filter query params and redirect when invalid values are supplied."""
        raw_forecast_type = request.GET.get("forecast_type")
        raw_period = request.GET.get("period")

        def to_int(value):
            try:
                return int(value)
            except (TypeError, ValueError):
                return False

        invalid_params = []
        if raw_forecast_type is not None:
            ft_id = to_int(raw_forecast_type)
            if ft_id is False:
                invalid_params.append(_("Forecast Type"))
            elif not ForecastType.objects.filter(pk=ft_id).exists():
                invalid_params.append(_("Forecast Type"))

        if raw_period is not None:
            p_id = to_int(raw_period)
            if p_id is False:
                invalid_params.append(_("Period"))
            elif not Period.objects.filter(pk=p_id).exists():
                invalid_params.append(_("Period"))

        if invalid_params:
            messages.error(
                request,
                _("Invalid value for: %(params)s.")
                % {"params": ", ".join(str(p) for p in invalid_params)},
            )
            clean_params = {}
            if request.GET.get("section"):
                clean_params["section"] = request.GET["section"]
            query_string = (
                "?" + "&".join(f"{k}={v}" for k, v in clean_params.items())
                if clean_params
                else ""
            )
            return HttpResponseRedirect(str(self.main_url) + query_string)

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Build filter context with default forecast type and period selections."""

        context = super().get_context_data(**kwargs)
        company = getattr(self.request, "active_company", None)

        context["company"] = company
        context["forecast_types"] = ForecastType.objects.all()
        context["has_company"] = bool(company)
        context["has_forecast_types"] = context["forecast_types"].exists()
        context["nav_url"] = self.nav_url
        context["list_url"] = self.list_url
        context["main_url"] = self.main_url
        context["filters_url"] = self.filters_url

        if not company or not context["has_forecast_types"]:
            return context

        forecast_type_id = self.request.GET.get("forecast_type")
        period_id = self.request.GET.get("period")

        if forecast_type_id:
            context["default_forecast_type"] = (
                context["forecast_types"].filter(pk=forecast_type_id).first()
            )
        else:
            context["default_forecast_type"] = context["forecast_types"].first()

        context["periods"] = Period.objects.all()
        current_date = timezone.now().date()

        if period_id:
            context["default_period"] = context["periods"].filter(pk=period_id).first()
        else:
            context["default_period"] = (
                context["periods"]
                .filter(start_date__lte=current_date, end_date__gte=current_date)
                .first()
                or context["periods"].first()
            )

        default_ft = context["default_forecast_type"]
        default_p = context["default_period"]
        context["current_forecast_type_id"] = default_ft.pk if default_ft else None
        context["current_period_id"] = default_p.pk if default_p else None

        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("forecast.view_forecasttarget"), name="dispatch")
class ForecastTargetFiltersView(LoginRequiredMixin, TemplateView):
    """Load forecast type and period filter dropdowns dynamically."""

    template_name = "forecast_target/forecast_target_filters.html"
    main_url = reverse_lazy("forecast:forecast_target_view")
    list_url = reverse_lazy("forecast:forecast_target_list_view")

    def get_context_data(self, **kwargs):
        """Populate forecast-target filter dropdown context and defaults."""

        context = super().get_context_data(**kwargs)

        forecast_types = ForecastType.objects.all()
        forecast_type_id = self.request.GET.get("forecast_type")
        period_id = self.request.GET.get("period")

        if forecast_type_id:
            default_forecast_type = forecast_types.filter(pk=forecast_type_id).first()
        else:
            default_forecast_type = forecast_types.first()

        periods = Period.objects.all()
        current_date = timezone.now().date()

        if period_id:
            default_period = periods.filter(pk=period_id).first()
        else:
            default_period = (
                periods.filter(
                    start_date__lte=current_date, end_date__gte=current_date
                ).first()
                or periods.first()
            )

        context.update(
            {
                "forecast_types": forecast_types,
                "periods": periods,
                "default_forecast_type": default_forecast_type,
                "default_period": default_period,
                "current_forecast_type_id": forecast_type_id,
                "current_period_id": period_id,
                "main_url": self.main_url,
                "list_url": self.list_url,
            }
        )

        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("forecast.view_forecasttarget"), name="dispatch")
class ForecastTargetNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Render the forecast target navigation bar with role and condition filters.
    """

    nav_description = _("Set sales targets for your team's forecasts.")
    search_url = reverse_lazy("forecast:forecast_target_list_view")
    main_url = reverse_lazy("forecast:forecast_target_view")
    filterset_class = ForecastTargetFilter
    model_name = "ForecastTarget"
    model_app_label = "forecast"
    nav_width = False
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False

    @cached_property
    def new_button(self):
        """
        Return a button element for creating a new forecast target.
        """
        if (
            self.request.user.has_perm("forecast.add_forecasttarget")
            and ForecastType.objects.exists()
        ):
            return {
                "url": f"""{reverse_lazy("forecast:forecast_target_form_view")}""",
                "attrs": {"id": "target-create"},
                "title": "Set Target",
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("forecast.view_forecasttarget"), name="dispatch"
)
class ForecastTargetListView(LoginRequiredMixin, HorillaListView):
    """
    Foreacst Target List view
    """

    model = ForecastTarget
    view_id = "forecast-target-list"
    filterset_class = ForecastTargetFilter
    search_url = reverse_lazy("forecast:forecast_target_list_view")
    main_url = reverse_lazy("forecast:forecast_target_view")
    save_to_list_option = False
    bulk_select_option = False
    enable_sorting = False

    @cached_property
    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        if self.request.user.has_perm("forecast.add_forecasttarget"):
            return {
                "url": f"""{reverse_lazy("forecast:forecast_target_form_view")}""",
                "attrs": 'id="target-create"',
                "title": "Set Target",
            }
        return None

    def get_queryset(self):
        queryset = super().get_queryset()
        forecast_type_id = self.request.GET.get("forecast_type")
        period_id = self.request.GET.get("period")

        if forecast_type_id:
            queryset = queryset.filter(forcasts_type=forecast_type_id)
        if period_id:
            queryset = queryset.filter(period=period_id)

        return queryset

    @cached_property
    def columns(self):
        """
        Return the table column headers and their corresponding model fields.
        """

        instance = self.model()
        user_model = instance._meta.get_field("assigned_to").related_model
        return [
            (instance._meta.get_field("assigned_to").verbose_name, "assigned_to"),
            (user_model._meta.get_field("role").verbose_name, "assigned_to__role"),
            (instance._meta.get_field("target_amount").verbose_name, "target_amount"),
        ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "forecast.change_forecasttarget",
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
            "permission": "forecast.delete_forecasttarget",
            "attrs": """
                            hx-get="{get_delete_url}"
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            onclick="openModal()"
                            """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("forecast.add_forecasttarget"), name="dispatch"
)
class ForecastTargetFormView(LoginRequiredMixin, HorillaSingleFormView):
    """Form view for creating/updating ForecastTarget with dynamic conditions."""

    model = ForecastTarget
    form_class = ForecastTargetForm
    template_name = "forecast_target/forecast_target_form.html"
    form_url = reverse_lazy("forecast:forecast_target_form_view")
    condition_fields = ["assigned_to", "period", "forcasts_type", "target_amount"]
    condition_field_title = _("Select User")
    modal_height = False
    save_and_new = False

    def _calculate_dynamic_condition_fields(self, request_or_data):
        """Calculate condition_fields based on checkbox values"""
        is_period_same = request_or_data.get("is_period_same", "off") == "on"
        is_target_same = request_or_data.get("is_target_same", "off") == "on"
        is_forecast_type_same = (
            request_or_data.get("is_forecast_type_same", "off") == "on"
        )
        fields = ["assigned_to"]
        if not is_period_same:
            fields.append("period")
        if not is_forecast_type_same:
            fields.append("forcasts_type")
        if not is_target_same:
            fields.append("target_amount")
        return fields

    def get_form_kwargs(self):
        """Dynamically set condition_fields based on checkboxes"""
        kwargs = super().get_form_kwargs()
        kwargs["condition_fields"] = self._calculate_dynamic_condition_fields(
            self.request.POST
        )
        return kwargs

    def get_context_data(self, **kwargs):
        """Add custom context data"""
        context = super().get_context_data(**kwargs)
        if self.request.method == "POST":
            is_role_based = self.request.POST.get("is_role_based", "off") == "on"
            role_id = self.request.POST.get("role")
            if is_role_based:
                users = (
                    User.objects.filter(role_id=role_id)
                    if role_id
                    else User.objects.none()
                )
            else:
                users = User.objects.all()
        else:
            users = User.objects.all()
        context["users"] = users

        if self.request.method == "POST":
            context["condition_fields"] = self._calculate_dynamic_condition_fields(
                self.request.POST
            )
            context["form_submitted"] = True
        else:
            context["form_submitted"] = False

        context["roles"] = Role.objects.all()
        context["period_choices"] = [(p.id, p.name) for p in Period.objects.all()]
        context["forecast_type_choices"] = [
            (f.id, f.name) for f in ForecastType.objects.all()
        ]
        return context

    def add_condition_row(self, request):
        """Override to handle dynamic condition_fields and custom context"""
        original_fields = self.condition_fields
        self.condition_fields = self._calculate_dynamic_condition_fields(request.GET)
        try:
            # Calculate new_row_id
            row_id = request.GET.get("row_id", "0")
            if row_id == "next":
                current_count = request.session.get("condition_row_count", 0)
                current_count += 1
                request.session["condition_row_count"] = current_count
                new_row_id = str(current_count)
            else:
                try:
                    new_row_id = str(int(row_id) + 1)
                except ValueError:
                    new_row_id = "1"

            # Temporarily set request for get_form_kwargs
            original_request = self.request
            self.request = request
            form_kwargs = self.get_form_kwargs()
            form_kwargs["row_id"] = new_row_id
            form_kwargs["condition_fields"] = self.condition_fields
            if "pk" in self.kwargs:
                try:
                    form_kwargs["instance"] = self.model.objects.get(
                        pk=self.kwargs["pk"]
                    )
                except self.model.DoesNotExist:
                    pass
            form = self.get_form_class()(**form_kwargs)
            self.request = original_request

            # Filter users
            is_role_based = request.GET.get("is_role_based", "off") == "on"
            role_id = request.GET.get("role")
            users = (
                User.objects.filter(role_id=role_id)
                if is_role_based and role_id
                else (User.objects.none() if is_role_based else User.objects.all())
            )

            context = {
                "form": form,
                "condition_fields": self.condition_fields,
                "row_id": new_row_id,
                "submitted_condition_data": self.get_submitted_condition_data(),
                "users": users,
                "period_choices": [(p.id, p.name) for p in Period.objects.all()],
                "forecast_type_choices": [
                    (f.id, f.name) for f in ForecastType.objects.all()
                ],
            }
            return render(request, "forecast_target/condition_row.html", context)
        finally:
            self.condition_fields = original_fields

    def process_row_data_before_create(self, row_data, row_id, form):
        """Process row_data to handle 'same' checkbox logic"""
        if not row_data.get("assigned_to"):
            form.add_error(None, f"User assignment is required for row {row_id}.")
            return False

        cleaned = form.cleaned_data
        is_period_same = cleaned.get("is_period_same", False)
        is_target_same = cleaned.get("is_target_same", False)
        is_forecast_type_same = cleaned.get("is_forecast_type_same", False)

        # Handle period
        if is_period_same:
            if not cleaned.get("period"):
                form.add_error(
                    "period",
                    "Period is required when 'Same Period for All' is selected.",
                )
                return False
            row_data["period"] = str(cleaned.get("period").id)
        elif not row_data.get("period"):
            form.add_error(
                None,
                f"Period is required for row {row_id} when 'Same Period for All' is not selected.",
            )
            return False

        # Handle target_amount
        if is_target_same:
            if cleaned.get("target_amount") is None:
                form.add_error(
                    "target_amount",
                    "Target amount is required when 'Same Target for All' is selected.",
                )
                return False
            row_data["target_amount"] = str(cleaned.get("target_amount"))
        elif not row_data.get("target_amount"):
            form.add_error(
                None,
                f"Target amount is required for row {row_id} when 'Same Target for All' is not selected.",
            )
            return False

        # Handle forcasts_type
        if is_forecast_type_same:
            if not cleaned.get("forcasts_type"):
                form.add_error(
                    "forcasts_type",
                    "Forecast type is required when 'Same Forecast Type for All' is selected.",
                )
                return False
            row_data["forcasts_type"] = str(cleaned.get("forcasts_type").id)
        elif not row_data.get("forcasts_type"):
            form.add_error(
                None,
                f"Forecast type is required for row {row_id} when 'Same Forecast Type for All' is not selected.",
            )
            return False

        return row_data  # Return processed row_data

    def check_duplicate_instance(self, row_data, unique_cache, form):
        """Check for duplicate combinations"""
        assigned_to_id = int(row_data.get("assigned_to"))
        period_id = int(row_data.get("period"))
        forcasts_type_id = int(row_data.get("forcasts_type"))

        combination = (assigned_to_id, period_id, forcasts_type_id)
        if combination in unique_cache:
            try:
                user = User.objects.get(id=assigned_to_id)
                return _("Duplicate entry found for user '%(user)s'.") % {"user": user}
            except Exception:
                return str(_("Duplicate entry found."))

        if ForecastTarget.objects.filter(
            assigned_to_id=assigned_to_id,
            period_id=period_id,
            forcasts_type_id=forcasts_type_id,
        ).exists():
            try:
                user = User.objects.get(id=assigned_to_id)
                return _("Forecast target already exists for user '%(user)s'.") % {
                    "user": user
                }
            except Exception:
                return str(_("Forecast target already exists."))

        unique_cache.add(combination)
        return None

    def update_unique_check_cache(self, row_data, unique_cache, instance):
        """Update cache after creating instance"""
        combination = (
            instance.assigned_to_id,
            instance.period_id,
            instance.forcasts_type_id,
        )
        unique_cache.add(combination)

    def modify_create_kwargs(self, create_kwargs, row_data, row_id, form):
        """Modify create_kwargs to handle role based on is_role_based"""
        is_role_based = form.cleaned_data.get("is_role_based", False)
        if not is_role_based:
            create_kwargs["role"] = None
        return create_kwargs


@method_decorator(
    permission_required_or_denied("forecast.change_forecasttarget"), name="dispatch"
)
class ToggleRoleBasedView(View):
    """View to toggle role-based user filtering for forecast target conditions."""

    def post(self, request, *_args, **_kwargs):
        """
        Handle POST request to filter users based on role selection and update condition fields.
        """
        is_role_based = request.POST.get("is_role_based", "off") == "on"
        role_id = request.POST.get("role")
        is_period_same = request.POST.get("is_period_same", "off") == "on"
        is_target_same = request.POST.get("is_target_same", "off") == "on"
        is_forecast_type_same = request.POST.get("is_forecast_type_same", "off") == "on"
        users = User.objects.all()
        if is_role_based:
            if role_id:
                users = users.filter(role_id=role_id)
            else:
                users = User.objects.none()
        form = ForecastTargetForm(request.POST)

        condition_fields = ["assigned_to"]
        if not is_period_same:
            condition_fields.append("period")
        if not is_forecast_type_same:
            condition_fields.append("forcasts_type")
        if not is_target_same:
            condition_fields.append("target_amount")

        context = {
            "form": form,
            "condition_fields": condition_fields,
            "users": users,
            "roles": Role.objects.all(),
            "period_choices": [(p.id, p.name) for p in Period.objects.all()],
            "forecast_type_choices": [
                (f.id, f.name) for f in ForecastType.objects.all()
            ],
            "submitted_condition_data": self.get_condition_data(request),
            "condition_row_count": request.session.get("condition_row_count", 0),
            "is_role_based": is_role_based,
            "form_submitted": False,
        }
        return render(
            request,
            "forecast_target/toggle_role_based_response.html",
            context,
        )

    def get_condition_data(self, request):
        """Extract and return condition row data from POST request."""

        possible_condition_fields = [
            "assigned_to",
            "period",
            "target_amount",
            "forcasts_type",
        ]
        condition_data = {}
        for key, value in request.POST.items():
            for field_name in possible_condition_fields:
                if key.startswith(f"{field_name}_") and key != field_name:
                    try:
                        row_id = key.replace(f"{field_name}_", "")
                        if row_id not in condition_data:
                            condition_data[row_id] = {}
                        condition_data[row_id][field_name] = value
                    except Exception:
                        continue
        return condition_data


@method_decorator(
    permission_required_or_denied("forecast.change_forecasttarget"), name="dispatch"
)
class ToggleConditionFieldsView(View):
    """View to dynamically toggle visibility of forecast target condition fields."""

    def post(self, request, *_args, **_kwargs):
        """
        Handle POST request to update visible condition fields based on user selections.
        """
        is_period_same = request.POST.get("is_period_same", "off") == "on"
        is_target_same = request.POST.get("is_target_same", "off") == "on"
        is_forecast_type_same = request.POST.get("is_forecast_type_same", "off") == "on"
        is_role_based = request.POST.get("is_role_based", "off") == "on"
        role_id = request.POST.get("role")
        form = ForecastTargetForm(request.POST)

        condition_fields = ["assigned_to"]
        if not is_period_same:
            condition_fields.append("period")
        if not is_forecast_type_same:
            condition_fields.append("forcasts_type")
        if not is_target_same:
            condition_fields.append("target_amount")

        users = User.objects.all()
        if is_role_based:
            if role_id:
                users = users.filter(role_id=role_id)
            else:
                users = User.objects.none()

        # Extract condition data
        possible_condition_fields = [
            "assigned_to",
            "period",
            "target_amount",
            "forcasts_type",
        ]
        condition_data = {}
        for key, value in request.POST.items():
            for field_name in possible_condition_fields:
                if key.startswith(f"{field_name}_") and key != field_name:
                    try:
                        row_id = key.replace(f"{field_name}_", "")
                        if row_id not in condition_data:
                            condition_data[row_id] = {}
                        condition_data[row_id][field_name] = value
                    except Exception:
                        continue

        context = {
            "form": form,
            "condition_fields": condition_fields,
            "users": users,
            "period_choices": [(p.id, p.name) for p in Period.objects.all()],
            "forecast_type_choices": [
                (f.id, f.name) for f in ForecastType.objects.all()
            ],
            "submitted_condition_data": condition_data,
            "condition_row_count": request.session.get("condition_row_count", 0),
            "is_period_same": is_period_same,
            "is_target_same": is_target_same,
            "is_forecast_type_same": is_forecast_type_same,
            "form_submitted": False,
        }
        return render(
            request,
            "forecast_target/toggle_condition_fields_response.html",
            context,
        )


@method_decorator(
    permission_required_or_denied("forecast.change_forecasttarget"), name="dispatch"
)
class UpdateTargetHelpTextView(View):
    """View to update the help text for the target amount based on forecast type."""

    template_name = "forecast_target/target_amount_help_text.html"

    def post(self, request, *_args, **_kwargs):
        """
        Update and return the help text for the target amount based on forecast type.
        """
        row_id = request.GET.get("row_id", "0")
        forecast_type_id = (
            request.POST.get("forcasts_type")
            or request.POST.get(f"forcasts_type_{row_id}")
            or request.POST.get("forcasts_type_0")
        )
        help_text = _("Enter the target amount")

        if forecast_type_id:
            try:
                forecast_type = ForecastType.objects.get(id=forecast_type_id)
                if forecast_type.is_quantity_based:
                    help_text = _("Enter the quantity")
                elif forecast_type.is_revenue_based:
                    help_text = _("Enter the revenue amount")
            except ForecastType.DoesNotExist:
                pass

        context = {
            "help_text": help_text,
            "row_id": row_id,
        }
        return render(request, self.template_name, context)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("forecast.change_forecasttarget"), name="dispatch"
)
class UpdateForecastTarget(LoginRequiredMixin, HorillaSingleFormView):
    """View to update the target amount for a specific ForecastTarget."""

    model = ForecastTarget
    fields = ["target_amount"]
    full_width_fields = ["target_amount"]
    modal_height = False

    @cached_property
    def form_url(self):
        """
        Return the URL for the update form of the specific ForecastTarget instance.
        """
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "forecast:forecast_target_update_form_view", kwargs={"pk": pk}
            )
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("forecast.delete_forecasttarget", modal=True),
    name="dispatch",
)
class ForecastTargetDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View to delete a ForecastTarget and handle the post-delete response."""

    model = ForecastTarget

    def get_post_delete_response(self):
        return HxTriggerResponse()
