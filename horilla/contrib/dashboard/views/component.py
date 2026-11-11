"""Views for managing dashboard components, including table data handling, component forms, deletion, and moving components between dashboards."""

# Standard library imports
import logging

# Third-party imports (Django)
from django import forms
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.forms.form_class_mixin import WIDGET_INPUT_CSS_CLASS_NO_PR
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
)
from horilla.contrib.reports.models import Report
from horilla.contrib.utils.middlewares import _thread_local
from horilla.db import transaction
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse, reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.functional import cached_property
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import FormView, View
from horilla.web import HttpResponse, HxTriggerResponse, JsonResponse, ScriptResponse

from ..forms import DashboardCreateForm

# Local imports
from ..models import (
    ComponentCriteria,
    Dashboard,
    DashboardComponent,
    DefaultHomeLayoutOrder,
)
from .dashboard_helper import get_table_data

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["dashboard.view_dashboard", "dashboard.view_own_dashboard"]
    ),
    name="dispatch",
)
class DashboardComponentTableDataView(LoginRequiredMixin, View):
    """
    Handle AJAX requests for table data pagination and search
    """

    def get(self, request, *args, **kwargs):
        """Handle GET request to return table data for a dashboard component."""
        component_id = kwargs.get("component_id")

        try:
            component = DashboardComponent.objects.get(
                id=component_id, component_type="table_data", is_active=True
            )
        except DashboardComponent.DoesNotExist:
            return HttpResponse("Component not found", status=404)

        # Same builder as the first render, so queryset, sorting, columns and bulk
        # options cannot drift between the page load and the pagination/sort calls.
        model, table_context = get_table_data(component, request)
        if not model:
            return HttpResponse("Model not found", status=404)

        if table_context["total_records_count"] == 0:
            return HttpResponse("")

        return render(request, "list_view.html", table_context)

    def post(self, request, *args, **kwargs):
        """Handle bulk operations"""
        self.request = request
        component_id = kwargs.get("component_id")

        try:
            component = DashboardComponent.objects.get(
                id=component_id, component_type="table_data", is_active=True
            )
        except DashboardComponent.DoesNotExist:
            return HttpResponse("Component not found", status=404)

        model, table_context = get_table_data(component, request)

        if model:
            list_view = HorillaListView(
                model=model,
                request=request,
                view_id=f"table_{component.id}",
                search_url=reverse_lazy(
                    "dashboard:component_table_data",
                    kwargs={"component_id": component.id},
                ),
                main_url=reverse_lazy(
                    "dashboard:dashboard_detail_view",
                    kwargs={"pk": component.dashboard_id},
                ),
                columns=table_context.get("columns", []),
                bulk_export_option=True,
            )
            list_view.object_list = table_context.get("queryset", model.objects.none())
            return list_view.post(request, *args, **kwargs)

        return HttpResponse("No table component found to handle export", status=400)


@method_decorator(htmx_required, name="dispatch")
class DashboardComponentFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Form view to dashboard component
    """

    template_name = "dashboard_component_form.html"
    model = DashboardComponent
    form_class = DashboardCreateForm
    condition_fields = ["field", "operator", "value"]
    condition_model = ComponentCriteria
    condition_related_name = "conditions"
    condition_order_by = ["sequence"]
    content_type_field = (
        "module"  # Enable automatic model_name extraction from module field
    )
    condition_hx_include = (
        "#id_module"  # Include module field when adding condition rows
    )
    hidden_fields = [
        "company",
        "config",
        "is_active",
        "dashboard",
        "sequence",
        "component_owner",
        "reports",
    ]
    full_width_fields = ["name"]
    save_and_new = False

    def get_initial(self):
        """Set initial dashboard, company, and component_owner from request."""
        initial = super().get_initial()
        dashboard_id = self.request.GET.get("dashboard") or self.request.POST.get(
            "dashboard"
        )

        if dashboard_id:
            dashboard = Dashboard.objects.get(id=dashboard_id)
            initial["dashboard"] = dashboard
        company = (
            getattr(_thread_local, "request", None).active_company
            if hasattr(_thread_local, "request")
            else self.request.user.company
        )
        initial["company"] = company
        initial["component_owner"] = self.request.user

        initial.update(self.request.GET.dict())
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        model_name = (
            self.request.GET.get("model_name")
            or self.request.POST.get("model_name")
            or self.request.GET.get("module")
            or self.request.POST.get("module")
        )

        # If module is a HorillaContentType ID, convert it to model_name
        if model_name and model_name.isdigit():
            try:
                content_type = HorillaContentType.objects.get(pk=model_name)
                model_name = content_type.model
            except Exception:
                pass

        if model_name:
            if "initial" not in kwargs:
                kwargs["initial"] = {}
            kwargs["initial"]["model_name"] = model_name

        kwargs["condition_model"] = ComponentCriteria
        kwargs["request"] = self.request

        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        form = context.get("form")
        if form and hasattr(form, "instance") and form.instance.module:
            context["module"] = form.instance.module
        elif self.request.method == "GET" and self.request.GET.get("module"):
            context["module"] = self.request.GET.get("module")
        else:
            context["module"] = ""

        return context

    @cached_property
    def form_url(self):
        """Determine form action URL based on whether creating or updating."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")

        if pk:
            url = reverse_lazy("dashboard:component_update", kwargs={"pk": pk})
        else:
            url = reverse_lazy("dashboard:component_create")

        dashboard_id = self.request.GET.get("dashboard")
        if dashboard_id:
            final_url = f"{url}?dashboard={dashboard_id}"
        else:
            final_url = str(url)

        return final_url

    def get(self, request, *args, **kwargs):
        component_id = self.kwargs.get("pk")
        if not component_id:
            # Create: the component add / add own permission is already enforced by
            # the generic form; here make sure the target dashboard is allowed too.
            if self._can_add_to_requested_dashboard():
                return super().get(request, *args, **kwargs)
            return render(request, "403.html")

        if request.user.has_perm("dashboard.change_dashboard") or request.user.has_perm(
            "dashboard.add_dashboard"
        ):
            return super().get(request, *args, **kwargs)

        component = get_object_or_404(DashboardComponent, pk=component_id)
        if component.component_owner == request.user:
            return super().get(request, *args, **kwargs)

        return render(request, "403.html")

    def post(self, request, *args, **kwargs):
        """Block creating a component on a dashboard the user may not add to."""
        if not self.kwargs.get("pk") and not self._can_add_to_requested_dashboard():
            return render(request, "403.html")
        return super().post(request, *args, **kwargs)

    def _can_add_to_requested_dashboard(self):
        """Every dashboard id sent (URL and body) must allow adding a component."""
        dashboard_ids = {
            value
            for value in (
                self.request.GET.get("dashboard"),
                self.request.POST.get("dashboard"),
            )
            if value
        }
        if not dashboard_ids:
            return False
        for dashboard_id in dashboard_ids:
            try:
                dashboard = Dashboard.objects.filter(pk=dashboard_id).first()
            except (TypeError, ValueError):
                return False
            if not dashboard or not dashboard.can_add_component(self.request.user):
                return False
        return True

    def form_valid(self, form):
        """Handle form submission and ensure proper file path"""
        instance = form.save(commit=False)

        if "icon" in self.request.FILES:
            icon_file = self.request.FILES["icon"]
            instance.icon = icon_file

        return super().form_valid(form)


@method_decorator(htmx_required, name="dispatch")
class ComponentDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View to handle deletion of dashboard components."""

    model = DashboardComponent

    def get_post_delete_response(self):
        return HxTriggerResponse()


@method_decorator(htmx_required, name="dispatch")
class AddToDashboardForm(LoginRequiredMixin, HorillaSingleFormView):
    """
    View to handle adding a component to another dashboard.
    """

    model = DashboardComponent
    modal_height = False
    form_title = _("Move to Dashboard")
    fields = ["dashboard"]
    full_width_fields = ["dashboard"]
    save_and_new = False

    def get_form_kwargs(self):
        """
        Pass the request to the form for queryset filtering and validation.
        """
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def get_initial(self):
        """Set initial dashboard from component_id when moving component."""
        initial = super().get_initial()
        component_id = self.kwargs.get("component_id")
        if component_id:
            component = DashboardComponent.objects.filter(pk=component_id).first()
            if component:
                initial["dashboard"] = component.dashboard
            else:
                messages.error(self.request, _("Original component not found."))
        return initial

    def get_form(self, form_class=None):
        """Add widget attrs and restrict dashboard queryset for non-superusers."""
        form = super().get_form(form_class)
        user = getattr(self.request, "user", None)
        if user:
            form.fields["dashboard"].widget.attrs.update(
                {
                    "class": "js-example-basic-single",
                }
            )
            if not user.is_superuser:
                form.fields["dashboard"].queryset = Dashboard.objects.filter(
                    dashboard_owner=user
                )
        return form

    @cached_property
    def form_url(self):
        """Determine the form URL based on whether it's a create or update operation."""
        pk = self.kwargs.get("component_id") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "dashboard:move_to_another_dashboard",
                kwargs={"component_id": pk},
            )
        return None

    def get(self, request, *args, **kwargs):
        try:
            component_id = self.kwargs.get("component_id")
            if request.user.has_perm(
                "dashboard.change_dashboard"
            ) or request.user.has_perm("dashboard.add_dashboard"):
                return super().get(request, *args, **kwargs)

            if component_id:
                dashboard = get_object_or_404(Dashboard, pk=component_id)
                if dashboard.dashboard_owner == request.user:
                    return super().get(request, *args, **kwargs)
        except Exception as e:
            messages.error(request, e)
            return ScriptResponse(reload=True, msgs=True)

        return render(request, "403.html")

    def form_valid(self, form):
        target_dashboard = form.cleaned_data["dashboard"]
        component_id = self.kwargs.get("component_id")

        try:
            original = DashboardComponent.objects.get(pk=component_id)
        except DashboardComponent.DoesNotExist:
            messages.error(self.request, _("Original component not found."))
            return ScriptResponse(close=True, reload=True, msgs=True)

        with transaction.atomic():
            field_names = [
                f.name
                for f in DashboardComponent._meta.fields
                if f.name not in ["id", "pk", "dashboard"]
            ]
            new_component = DashboardComponent(dashboard=target_dashboard)
            for field in field_names:
                setattr(new_component, field, getattr(original, field))

            new_component.save()

            for crit in original.conditions.all():
                crit.pk = None
                crit.component = new_component
                crit.save()

        messages.success(
            self.request, _("Chart successfully added to another dashboard.")
        )
        return ScriptResponse(close=True, reload=True)


@method_decorator(htmx_required, name="dispatch")
class ReportToDashboardForm(LoginRequiredMixin, HorillaSingleFormView):
    """
    View to handle adding a report into a dashboard.
    """

    model = DashboardComponent
    modal_height = False
    form_title = _("Add to Dashboard")
    fields = ["dashboard", "reports"]
    full_width_fields = ["dashboard", "reports"]
    save_and_new = False

    def get_form_kwargs(self):
        """
        Pass the request to the form for queryset filtering and validation.
        """
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def get_initial(self):
        """Set initial reports from report_id in GET when adding report to dashboard."""
        initial = super().get_initial()
        report_id = self.request.GET.get("report_id")
        if report_id:
            initial["reports"] = report_id
        return initial

    def get(self, request, *args, **kwargs):
        """Check change_dashboard/add_dashboard or dashboard ownership; then show form or 403."""
        component_id = self.kwargs.get("component_id")
        if (
            getattr(request.user, "is_superuser", False)
            or request.user.has_perm("dashboard.change_dashboard")
            or request.user.has_perm("dashboard.add_dashboard")
        ):
            return super().get(request, *args, **kwargs)

        if component_id:
            dashboard = get_object_or_404(Dashboard, pk=component_id)
            if dashboard.dashboard_owner == request.user:
                return super().get(request, *args, **kwargs)

        return render(request, "403.html")

    def get_form(self, form_class=None):
        """Add widget attrs and restrict dashboard queryset for non-superusers."""
        form = super().get_form(form_class)
        user = getattr(self.request, "user", None)
        if user:
            form.fields["dashboard"].widget.attrs.update(
                {
                    "class": "js-example-basic-single",
                }
            )
            if not user.is_superuser:
                form.fields["dashboard"].queryset = Dashboard.objects.filter(
                    dashboard_owner=user
                )
        return form

    @cached_property
    def form_url(self):
        """Determine the form URL based on whether it's a create or update operation."""
        return reverse_lazy("dashboard:report_to_dashboard")

    def form_valid(self, form):
        """
        Create a new DashboardComponent entry using the report.
        """
        selected_dashboard = form.cleaned_data["dashboard"]
        report_id = self.request.GET.get("report_id")
        component_type = (
            "table_data"
            if self.request.GET.get("component_type") == "table_data"
            else "chart"
        )

        try:
            report = Report.objects.get(pk=report_id)

            existing_component = DashboardComponent.objects.filter(
                dashboard=selected_dashboard,
                reports=report,
                component_type=component_type,
                is_active=True,
            ).first()

            if existing_component:
                messages.warning(
                    self.request,
                    _(
                        "This report '{}' is already added to the '{}' dashboard."
                    ).format(report.name, selected_dashboard.name),
                )
                return ScriptResponse(reload=True, close=True)

            component_fields = {}
            if component_type == "chart":
                component_fields = {
                    "chart_type": report.chart_type,
                    "grouping_field": report.chart_field,
                    "secondary_grouping": report.chart_field_stacked,
                }
            DashboardComponent.objects.create(
                dashboard=selected_dashboard,
                name=report.name,
                component_type=component_type,
                reports=report,
                module=report.module,
                component_owner=self.request.user,
                company=self.request.user.company,
                **component_fields,
            )

            messages.success(self.request, _("Report added to dashboard successfully."))
            return ScriptResponse(reload=True, close=True)

        except Report.DoesNotExist:
            messages.error(self.request, _("Report not found."))
            return ScriptResponse(reload=True, close=True)


class _ChartViewDashboardPickForm(forms.Form):
    """Form: component name + dashboard to add chart-view component to."""

    name = forms.CharField(
        max_length=255,
        label=_("Component name"),
        required=True,
        widget=forms.TextInput(
            attrs={
                # Match single_form_view.html text inputs (form_class_mixin)
                "class": WIDGET_INPUT_CSS_CLASS_NO_PR,
                "placeholder": _("Enter Component Name"),
            }
        ),
    )
    dashboard = forms.ModelChoiceField(
        queryset=Dashboard.objects.filter(is_active=True),
        label=_("Dashboard"),
        widget=forms.Select(attrs={"class": "js-example-basic-single"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        # Only pass Django Form–supported kwargs (HorillaSingleFormView injects extras).
        kwargs.pop("full_width_fields", None)
        kwargs.pop("dynamic_create_fields", None)
        kwargs.pop("condition_fields", None)
        kwargs.pop("condition_model", None)
        kwargs.pop("condition_field_choices", None)
        kwargs.pop("condition_related_name", None)
        kwargs.pop("condition_related_name_candidates", None)
        kwargs.pop("hidden_fields", None)
        kwargs.pop("condition_hx_include", None)
        kwargs.pop("field_permissions", None)
        kwargs.pop("duplicate_mode", None)
        kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        if user and not user.is_superuser:
            self.fields["dashboard"].queryset = Dashboard.objects.filter(
                dashboard_owner=user, is_active=True
            )
        # single_form_view.html expects form.instance.pk (ModelForm); plain Form has no instance.
        self.instance = type("DummyInstance", (), {"pk": None})()


@method_decorator(htmx_required, name="dispatch")
class ChartViewToDashboardForm(LoginRequiredMixin, FormView):
    """
    Add current chart-view configuration as a dashboard chart component
    (no Report required; uses module + grouping_field like get_chart_data).

    Uses FormView instead of HorillaSingleFormView: no model, and the generic
    single-form injects kwargs that plain forms.Form does not accept.
    """

    form_class = _ChartViewDashboardPickForm
    template_name = "single_form_view.html"
    view_id = "chart-view-to-dashboard"

    def dispatch(self, request, *args, **kwargs):
        """Require dashboard add/change permission or superuser before dispatch."""
        if not getattr(request.user, "is_superuser", False) and not (
            request.user.has_perm("dashboard.change_dashboard")
            or request.user.has_perm("dashboard.add_dashboard")
        ):
            return render(request, "403.html", {"modal": True})
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        """Pass the current user into the dashboard pick form."""
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        """Build single-form modal context for adding a chart view to a dashboard."""
        context = super().get_context_data(**kwargs)
        form_url = reverse("dashboard:chart_view_to_dashboard")
        query_string = ""
        if self.request.GET:
            query_string = f"?{self.request.GET.urlencode()}"
        context.update(
            {
                "form_title": _("Add to Dashboard"),
                "view_id": self.view_id,
                "header": True,
                "modal_height": False,
                "modal_height_class": None,
                "full_width_fields": ["name", "dashboard"],
                "condition_fields": [],
                "field_permissions": {},
                "duplicate_mode": False,
                "form_mode": [],
                "save_and_new": False,
                "form_url": f"{form_url}{query_string}",
                "hx_attrs": {
                    "hx-post": f"{form_url}{query_string}",
                    "hx-swap": "outerHTML",
                    "hx-target": f"#{self.view_id}-container",
                    "enctype": "multipart/form-data",
                },
            }
        )
        return context

    def form_valid(self, form):
        """Create DashboardComponent with module + grouping from GET params."""
        module_id = self.request.GET.get("module_id")
        grouping_field = self.request.GET.get("grouping_field")
        chart_type = (self.request.GET.get("chart_type") or "column").lower()
        secondary_grouping = (
            self.request.GET.get("secondary_grouping")
            or self.request.GET.get("chart_stack_by")
            or ""
        )

        if not module_id or not grouping_field:
            messages.error(
                self.request,
                _("Missing module or grouping field; reload the chart and try again."),
            )
            return ScriptResponse(reload=True, close=True)

        try:
            content_type = HorillaContentType.objects.get(pk=module_id)
        except HorillaContentType.DoesNotExist:
            messages.error(self.request, _("Invalid module."))
            return ScriptResponse(reload=True, close=True)

        valid_chart_types = [c[0] for c in DashboardComponent.CHART_TYPES]
        if chart_type not in valid_chart_types:
            chart_type = "column"

        selected_dashboard = form.cleaned_data["dashboard"]
        name = (form.cleaned_data.get("name") or "").strip()
        if not name:
            messages.error(self.request, _("Please enter a component name."))
            return self.form_invalid(form)

        DashboardComponent.objects.create(
            dashboard=selected_dashboard,
            name=name[:255],
            component_type="chart",
            chart_type=chart_type,
            reports=None,
            module=content_type,
            grouping_field=grouping_field,
            secondary_grouping=secondary_grouping or None,
            component_owner=self.request.user,
            company=getattr(self.request.user, "company", None),
        )

        messages.success(self.request, _("Chart added to dashboard successfully."))
        return ScriptResponse(reload=True, close=True)


@method_decorator(
    permission_required_or_denied("dashboard.change_dashboard"), name="dispatch"
)
class ReorderComponentsView(LoginRequiredMixin, View):
    """
    Handle the final save of component reordering (both regular components and KPIs)
    """

    def post(self, request, *args, **kwargs):
        """Reorder components based on the provided order in the POST data."""
        dashboard_id = kwargs.get("dashboard_id")

        try:
            dashboard = get_object_or_404(Dashboard, id=dashboard_id)

            component_order = request.POST.getlist("component_order")
            reorder_type = request.POST.get("reorder_type", "components")

            if not component_order:
                messages.error(
                    self.request,
                    _("No component order provided. Please try reordering again."),
                )
                return JsonResponse(
                    {
                        "success": False,
                        "message": str(_("No component order provided.")),
                    }
                )

            if reorder_type == "kpi":
                valid_components = DashboardComponent.objects.filter(
                    dashboard=dashboard, id__in=component_order, component_type="kpi"
                )
            else:
                valid_components = DashboardComponent.objects.filter(
                    dashboard=dashboard,
                    id__in=component_order,
                    component_type__in=["chart", "table_data"],  # All non-KPI types
                )

            valid_component_ids = list(valid_components.values_list("id", flat=True))

            valid_component_ids = [str(id) for id in valid_component_ids]

            invalid_ids = set(component_order) - set(valid_component_ids)
            if invalid_ids:
                messages.error(
                    self.request,
                    _("Invalid component order. Please refresh and try again."),
                )
                return JsonResponse(
                    {"success": False, "message": str(_("Invalid component order."))}
                )

            # Save per-user layout order in the same model as default home
            with transaction.atomic():
                layout_order, _created = DefaultHomeLayoutOrder.objects.get_or_create(
                    user=request.user,
                    dashboard=dashboard,
                    defaults={"order": {"kpi": [], "components": []}},
                )
                order_dict = (
                    layout_order.order if isinstance(layout_order.order, dict) else {}
                )
                order_dict = dict(order_dict)
                if reorder_type == "kpi":
                    order_dict["kpi"] = [int(x) for x in component_order]
                else:
                    order_dict["components"] = [int(x) for x in component_order]
                layout_order.order = order_dict
                layout_order.save(update_fields=["order"])

            messages.success(request, _("Components reordered successfully."))

            return JsonResponse({"success": True})

        except Exception as e:
            messages.error(self.request, e)
            return JsonResponse({"success": False, "message": str(e)})
