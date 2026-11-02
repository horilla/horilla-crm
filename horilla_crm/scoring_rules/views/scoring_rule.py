"""
Views for the scoring_rules app.
"""

# Standard library imports
import logging
from urllib.parse import urlencode

# Third-party imports (Django)
from django.contrib import messages

# First-party / Horilla imports
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.methods import get_condition_value_display
from horilla.contrib.generics.views import (
    HorillaDetailView,
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.functional import cached_property
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import HxTriggerResponse, ScriptResponse

# Local imports
from horilla_crm.scoring_rules.filters import ScoringRuleFilter
from horilla_crm.scoring_rules.forms import ScoringCriterionForm, ScoringRuleForm
from horilla_crm.scoring_rules.models import (
    ScoringCondition,
    ScoringCriterion,
    ScoringRule,
)

logger = logging.getLogger(__name__)


@method_decorator(
    permission_required_or_denied(
        "scoring_rules.view_scoringrule", wrapper_id="scoring-rule-view"
    ),
    name="dispatch",
)
class ScoringRuleView(LoginRequiredMixin, HorillaView):
    """Template view for scoring rule page."""

    template_name = "settings/settings_list_shell.html"
    view_id = "scoring-rule-view"
    nav_url = reverse_lazy("scoring_rules:scoring_rule_nav_view")
    list_url = reverse_lazy("scoring_rules:scoring_rule_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        "scoring_rules.view_scoringrule", wrapper_id="scoring-rule-view"
    ),
    name="dispatch",
)
class ScoringRuleNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar for scoring rule."""

    nav_description = _(
        "Define rules that automatically score leads and opportunities."
    )
    search_url = reverse_lazy("scoring_rules:scoring_rule_list_view")
    main_url = reverse_lazy("scoring_rules:scoring_rule_view")
    filterset_class = ScoringRuleFilter
    one_view_only = True
    all_view_types = False
    filter_option = True
    reload_option = False
    model_name = "ScoringRule"
    model_app_label = "scoring_rules"
    nav_width = False
    url_name = "scoring_rule_list_view"
    border_enabled = False

    @cached_property
    def new_button(self):
        """Return new button configuration for scoring rules."""
        if self.request.user.has_perm("scoring_rules.add_scoringrule"):
            return {
                "url": str(reverse_lazy("scoring_rules:scoring_rule_create_form"))
                + "?new=true"
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        "scoring_rules.view_scoringrule", wrapper_id="scoring-rule-view"
    ),
    name="dispatch",
)
class ScoringRuleListView(LoginRequiredMixin, HorillaListView):
    """List view of scoring rule."""

    model = ScoringRule
    view_id = "scoring_rule_list"
    filterset_class = ScoringRuleFilter
    search_url = reverse_lazy("scoring_rules:scoring_rule_list_view")
    main_url = reverse_lazy("scoring_rules:scoring_rule_view")
    bulk_select_option = False
    list_column_visibility = False
    header_attrs = [
        {"description": {"style": "width: 300px;"}},
    ]

    @cached_property
    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        if self.request.user.has_perm("scoring_rules.add_scoringrule"):
            return {
                "url": str(reverse_lazy("scoring_rules:scoring_rule_create_form"))
                + "?new=true",
            }
        return None

    columns = [
        "name",
        "module",
        ("is_active", "is_active_col"),
        "description",
    ]

    @cached_property
    def col_attrs(self):
        """Return column attributes for scoring rule list view."""
        attrs = {}
        if self.request.user.has_perm("scoring_rules.view_scoringrule"):
            attrs = {
                "hx-get": "{get_detail_view_url}",
                "hx-target": "#scoring-rule-view",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "hx-select": "#scoring-rule-view",
            }
        return [
            {
                "name": {
                    "style": "cursor:pointer",
                    "class": "hover:text-primary-600",
                    **attrs,
                }
            }
        ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "scoring_rules.change_scoringrule",
            "attrs": """
                    hx-get="{get_edit_url}?new=true"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    onclick="openModal()"
                    """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "scoring_rules.delete_scoringrule",
            "attrs": """
                hx-post="{get_delete_url}"
                hx-target="#deleteModeBox"
                hx-swap="innerHTML"
                hx-trigger="click"
                hx-vals='{{"check_dependencies": "true"}}'
                onclick="openDeleteModeModal()"
            """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("scoring_rules.add_scoringrule"), name="dispatch")
class ScoringRuleFormView(LoginRequiredMixin, HorillaSingleFormView):
    """Create and update form view for scoring rule."""

    model = ScoringRule
    form_class = ScoringRuleForm
    full_width_fields = ["description"]
    modal_height = False

    @cached_property
    def form_url(self):
        """Return form URL for create or update view."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "scoring_rules:scoring_rule_update_form", kwargs={"pk": pk}
            )
        return reverse_lazy("scoring_rules:scoring_rule_create_form")

    def get(self, request, *args, **kwargs):
        pk = kwargs.get("pk")
        if pk:
            try:
                self.model.objects.get(pk=pk)
            except self.model.DoesNotExist:
                messages.error(request, _("The requested data does not exist."))
                return ScriptResponse(reload=True)

        return super().get(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required("scoring_rules.delete_scoringrule"), name="dispatch"
)
class ScoringRuleDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View for deleting scoring rules."""

    model = ScoringRule

    def get_post_delete_response(self):
        return HxTriggerResponse()


@method_decorator(
    permission_required_or_denied(
        "scoring_rules.view_scoringrule", wrapper_id="scoring-rule-view"
    ),
    name="dispatch",
)
class ScoringRuleDetailView(HorillaDetailView):
    """Detail view for scoring rule."""

    template_name = "scoring_rule/scoring_rule_detail_view.html"
    model = ScoringRule

    def get_context_data(self, **kwargs):
        """Attach current rule details and criteria list for detail rendering."""
        context = super().get_context_data(**kwargs)
        current_obj = self.get_object()
        scoring_criteria = ScoringCriterion.objects.filter(
            rule=current_obj
        ).prefetch_related("conditions")
        model_cls = current_obj.module.model_class()
        for criterion in scoring_criteria:
            for condition in criterion.conditions.all():
                condition.value_display = get_condition_value_display(
                    model_cls, condition.field, condition.value
                )
        context["current_obj"] = current_obj
        context["scoring_criteria"] = scoring_criteria
        context["nav_url"] = reverse_lazy("scoring_rules:scoring_rule_detail_nav_view")
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        "scoring_rules.view_scoringrule", wrapper_id="scoring-rule-view"
    ),
    name="dispatch",
)
class ScoringRuleDetailNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar for scoring rule detail view."""

    search_url = reverse_lazy("scoring_rules:scoring_rule_list_view")
    main_url = reverse_lazy("scoring_rules:scoring_rule_view")
    filterset_class = ScoringRuleFilter
    one_view_only = True
    all_view_types = False
    filter_option = False
    reload_option = False
    model_name = "ScoringRule"
    model_app_label = "scoring_rules"
    nav_width = False
    url_name = "scoring_rule_list_view"
    search_option = False
    navbar_indication = True
    navbar_indication_attrs = {
        "hx-get": reverse_lazy("scoring_rules:scoring_rule_view"),
        "hx-target": "#scoring-rule-view",
        "hx-swap": "outerHTML",
        "hx-push-url": "true",
        "hx-select": "#scoring-rule-view",
    }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj_id = self.request.GET.get("obj", "")
        if obj_id:
            obj_id_clean = obj_id.split("?")[0].strip()
            try:
                obj_id_int = int(obj_id_clean)
                obj = ScoringRule.objects.filter(pk=obj_id_int).first()
                if obj:
                    self.nav_title = obj.name
                    context["nav_title"] = self.nav_title
            except ValueError:
                logger.error("Invalid obj_id parameter: %s", obj_id)
        return context

    @cached_property
    def new_button(self):
        """Return new button configuration for scoring criteria."""
        model_name = self.request.GET.get("model_name")
        obj = self.request.GET.get("obj")
        if self.request.user.has_perm("scoring_rules.add_scoringcriterion"):
            url = (
                str(reverse_lazy("scoring_rules:scoring_rule_criteria_create_form"))
                + f"?model_name={model_name}&obj={obj}"
            )
            return {"url": url, "id": "scoring-criteria-create-form"}
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required("scoring_rules.add_scoringcriterion"), name="dispatch"
)
class ScoringCriterionCreateUpdateView(LoginRequiredMixin, HorillaSingleFormView):
    """View for creating and updating scoring criteria."""

    model = ScoringCriterion
    form_class = ScoringCriterionForm
    condition_fields = ["field", "operator", "value", "logical_operator"]
    condition_model = ScoringCondition
    condition_related_name = "conditions"
    hidden_fields = ["rule"]
    modal_height = False
    save_and_new = False

    def get(self, request, *args, **kwargs):
        """Show an error and reload when the parent scoring rule no longer exists."""
        obj = request.GET.get("obj", "").split("?")[0].strip()
        if (
            not kwargs.get("pk")
            and obj.isdigit()
            and not ScoringRule.objects.filter(pk=obj).exists()
        ):
            messages.error(request, _("The requested data does not exist."))
            return ScriptResponse(msgs=True, close=True, reload=True)
        return super().get(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        model_name = self.request.GET.get("model_name") or self.request.POST.get(
            "model_name"
        )
        if self.object and self.object.rule:
            model_name = self.object.rule.module.model
        if model_name:
            if "initial" not in kwargs:
                kwargs["initial"] = {}
            kwargs["initial"]["model_name"] = model_name
        return kwargs

    def get_initial(self):
        """Prefill selected rule from query params when creating criteria."""
        initial = super().get_initial()
        obj = (
            self.kwargs.get("pk")
            or self.request.GET.get("obj")
            or self.request.POST.get("obj")
        )
        if obj:
            try:
                obj_clean = str(obj).split("?")[0].strip()
                obj_id = int(obj_clean)
                rule = ScoringRule.objects.get(pk=obj_id)
                initial["rule"] = rule
            except (ValueError, ScoringRule.DoesNotExist) as e:
                logger.error("Invalid obj parameter: %s, error: %s", obj, e)
        return initial

    @cached_property
    def form_url(self):
        """Return form URL for create or update view with model parameters."""
        model_name = self.request.GET.get("model_name")
        obj = self.request.GET.get("obj")
        pk = self.kwargs.get("pk")
        if pk:
            base_url = str(
                reverse_lazy(
                    "scoring_rules:scoring_rule_criteria_edit_form", kwargs={"pk": pk}
                )
            )
        else:
            base_url = str(
                reverse_lazy("scoring_rules:scoring_rule_criteria_create_form")
            )
        params = {}
        if model_name:
            params["model_name"] = model_name
        if obj:
            params["obj"] = obj
        if params:
            return base_url + "?" + urlencode(params)
        return base_url


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required("scoring_rules.delete_scoringcriterion"), name="dispatch"
)
class ScoringCriteriaDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View for deleting scoring criteria."""

    model = ScoringCriterion

    def get_post_delete_response(self):
        """Return response after successful deletion."""
        return HxTriggerResponse()


class ScoringActiveToggleView(LoginRequiredMixin, View):
    """Toggle active status for scoring rules via HTMX."""

    def post(self, request, *args, **kwargs):
        """Handle POST request to toggle scoring rule active status."""
        try:
            rule = ScoringRule.objects.get(pk=kwargs["pk"])
            user = request.user
            if user.has_perm("scoring_rules.change_scoringrule"):
                rule.is_active = not rule.is_active
                if rule.is_active:
                    messages.success(request, f"{rule.name} activated successfully")
                else:
                    messages.success(request, f"{rule.name} deactivated successfully")
                rule.save()
            return ScriptResponse(reload=True)
        except Exception as e:
            messages.error(request, str(e))
            return ScriptResponse(reload=True)
