"""
Views for managing lead assignment rules, which define how leads are automatically assigned to users or teams based on specified criteria.
"""

# Standard library imports
import logging

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla.contrib.mail.models import HorillaMailConfiguration, HorillaMailTemplate
from horilla.contrib.notifications.models import NotificationTemplate
from horilla.db.models import Q
from horilla.urls import reverse, reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.functional import cached_property
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import DetailView, TemplateView, View
from horilla.web import HttpNotFound, HxTriggerResponse, RefreshResponse, ScriptResponse

# Local imports
from horilla_crm.leads.filters import LeadAssignmentFilter
from horilla_crm.leads.forms import AssignmentRuleConditionForm as ConditionForm
from horilla_crm.leads.models import (
    LeadAssignmentCondition,
    LeadAssignmentMatchCriteria,
    LeadAssignmentRule,
)

logger = logging.getLogger(__name__)


class LeadsAssignmentView(LoginRequiredMixin, HorillaView):
    """
    TemplateView for lead assignment rule.
    """

    template_name = "settings/settings_list_shell.html"
    view_id = "lead-assignment-view"
    nav_url = reverse_lazy("leads:lead_assignment_nav_view")
    list_url = reverse_lazy("leads:lead_assignment_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("leads.view_leadassignmentrule"), name="dispatch")
class LeadAssignmentNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar for Lead assignment rules"""

    nav_description = _("Automatically assign new leads to the right owners.")
    search_url = reverse_lazy("leads:lead_assignment_list_view")
    main_url = reverse_lazy("leads:leads_assignment_view")
    filterset_class = LeadAssignmentFilter
    model_name = "LeadAssignmentRule"
    model_app_label = "leads"
    nav_width = False
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False

    @cached_property
    def new_button(self):
        """New button configuration"""
        if self.request.user.has_perm("leads.add_leadassignmentrule"):
            return {
                "url": f"""{reverse_lazy("leads:lead_assignment_create")}?new=true""",
                "attrs": {"id": "lead-assignment-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.view_leadassignmentrule"), name="dispatch"
)
class LeadAssignmentListView(LoginRequiredMixin, HorillaListView):
    """
    Lead assignment List view
    """

    model = LeadAssignmentRule
    view_id = "lead-assignment-list"
    filterset_class = LeadAssignmentFilter
    search_url = reverse_lazy("leads:lead_assignment_list_view")
    main_url = reverse_lazy("leads:leads_assignment_view")
    save_to_list_option = False
    bulk_select_option = False
    enable_sorting = False

    def no_record_add_button(self):
        """Button to show when no records exist"""
        if self.request.user.has_perm("leads.add_leadassignmentrule"):
            return {
                "url": f"""{reverse_lazy("leads:lead_assignment_create")}?new=true""",
                "attrs": 'id="lead-assignment-create"',
            }
        return None

    columns = [
        "name",
        "description",
        ("is_active", "is_active_col"),
    ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "leads.change_leadassignmentrule",
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
            "permission": "leads.delete_leadassignmentrule",
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

    @cached_property
    def col_attrs(self):
        """Return column attributes for scoring rule list view."""
        attrs = {}
        if self.request.user.has_perm("leads.view_leadassignmentrule"):
            attrs = {
                "hx-get": "{get_detail_url}",
                "hx-target": "#lead-assignment-view",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "hx-select": "#lead-assignment-view",
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


@method_decorator(htmx_required, name="dispatch")
class LeadAssignmentActivateView(LoginRequiredMixin, View):
    """Toggle is_active for a LeadAssignmentRule via HTMX checkbox."""

    def post(self, request, *args, **kwargs):
        """
        Handle POST request to toggle the is_active status of a LeadAssignmentRule. The rule is identified by the 'pk' URL parameter. If the user has permission to change the rule, it toggles the is_active field and saves the rule, then returns an HTMX response to trigger a click on the #reloadButton to refresh the list view and show the updated status. If any exceptions occur, it shows an error message and still triggers the reload.
        """
        try:
            rule = LeadAssignmentRule.objects.get(pk=kwargs["pk"])
            if request.user.has_perm("leads.change_leadassignmentrule"):
                if rule.is_active:
                    rule.is_active = False
                    messages.success(request, f"{rule.name} deactivated successfully.")
                else:
                    rule.is_active = True
                    messages.success(request, f"{rule.name} activated successfully.")
                rule.save()
            return ScriptResponse(reload=True)
        except Exception as e:
            messages.error(request, str(e))
            return ScriptResponse(reload=True)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.add_leadassignmentrule"), name="dispatch"
)
class LeadAssignmentForm(LoginRequiredMixin, HorillaSingleFormView):
    """
    create and update from view for assignment rules."""

    model = LeadAssignmentRule
    fields = ["name", "description", "allow_owner_reassignment", "is_active"]
    full_width_fields = ["name", "description"]
    modal_height = False

    @cached_property
    def form_url(self):
        """Return form URL for create or update view."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("leads:lead_assignment_update", kwargs={"pk": pk})
        return reverse_lazy("leads:lead_assignment_create")

    def form_valid(self, form):
        """
        A new rule starts inactive; the toggle in the list activates it, which
        deactivates the rule that is active now. ``is_active`` is not a form
        field (generic forms exclude it), so the model default would apply.
        """
        if not form.instance.pk:
            form.instance.is_active = False
        return super().form_valid(form)

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
    permission_required_or_denied("leads.delete_leadassignmentrule", modal=True),
    name="dispatch",
)
class LeadAssignmentDelete(LoginRequiredMixin, HorillaSingleDeleteView):
    """View for deleting lead assignment rule."""

    model = LeadAssignmentRule

    def get_post_delete_response(self):
        return HxTriggerResponse()


@method_decorator(
    permission_required_or_denied("leads.view_leadassignmentrule"), name="dispatch"
)
class AssignmentRuleDetailView(LoginRequiredMixin, DetailView):
    """Detail view for a LeadAssignmentRule — shows its conditions in an accordion."""

    template_name = "lead_assignment_rule/assignment_rule_detail.html"
    model = LeadAssignmentRule

    def get_context_data(self, **kwargs):
        """
        Get context data for the assignment rule detail view. This includes the rule object itself, the URL for the navbar, and the list of conditions associated with this rule, ordered by their specified order and creation time.
        """
        context = super().get_context_data(**kwargs)
        rule = self.get_object()
        context["obj"] = rule
        context["nav_url"] = reverse_lazy("leads:assignment_rule_detail_nav")
        context["conditions"] = LeadAssignmentCondition.objects.filter(
            rule=rule
        ).order_by("created_at")
        return context

    def dispatch(self, request, *args, **kwargs):
        """
        Override dispatch to handle the case where the requested LeadAssignmentRule does not exist. If the request is an HTMX request, return a RefreshResponse to update the page and show an error message. If it's a regular request, raise HttpNotFound to show a 404 page.
        """
        try:
            self.object = self.get_object()
        except Exception as e:
            if request.headers.get("HX-Request") == "true":
                messages.error(request, e)
                return RefreshResponse(request)
            raise HttpNotFound(e) from e
        return super().dispatch(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.view_leadassignmentrule"), name="dispatch"
)
class AssignmentRuleDetailNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar for the assignment rule detail page: back indicator, Add Condition, Edit Rule."""

    search_url = reverse_lazy("leads:lead_assignment_list_view")
    main_url = reverse_lazy("leads:leads_assignment_view")
    nav_width = False
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False
    search_option = False
    navbar_indication = True
    navbar_indication_attrs = {
        "hx-get": reverse_lazy("leads:leads_assignment_view"),
        "hx-target": "#settings-content",
        "hx-swap": "innerHTML",
        "hx-push-url": "true",
        "hx-select": "#lead-assignment-view",
    }

    @cached_property
    def new_button(self):
        """Add Condition button."""
        if not self.request.user.has_perm("leads.add_leadassignmentcondition"):
            return None
        pk = self.request.GET.get("pk")
        if not pk:
            return None
        return {
            "url": reverse(
                "leads:assignment_condition_create", kwargs={"rule_pk": int(pk)}
            ),
            "title": _("Add Condition"),
            "attrs": {"id": "assignment-condition-add"},
        }

    @cached_property
    def second_button(self):
        """Edit Rule button."""
        if not self.request.user.has_perm("leads.change_leadassignmentrule"):
            return None
        pk = self.request.GET.get("pk")
        if not pk:
            return None
        return {
            "url": reverse("leads:lead_assignment_update", kwargs={"pk": int(pk)}),
            "title": _("Edit Rule"),
            "attrs": {"id": "assignment-rule-edit"},
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pk = self.request.GET.get("pk")
        if pk:
            try:
                rule = LeadAssignmentRule.objects.filter(pk=int(pk)).first()
                if rule:
                    context["nav_title"] = str(rule.name)
            except (ValueError, TypeError):
                pass
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.add_leadassignmentcondition"), name="dispatch"
)
class AssignmentConditionFormView(LoginRequiredMixin, HorillaSingleFormView):
    """Create / update a LeadAssignmentCondition from the assignment rule detail view."""

    model = LeadAssignmentCondition
    form_class = ConditionForm
    condition_fields = ["field", "operator", "value", "logical_operator"]
    condition_model = LeadAssignmentMatchCriteria
    condition_related_name = "criteria"
    hidden_fields = ["rule"]
    modal_height = False
    save_and_new = False

    def get_form_kwargs(self):
        """
        Override get_form_kwargs to set the initial model_name for the dynamic condition form. This ensures that when the form is rendered, it knows to load fields relevant to the 'lead' model for the condition criteria.
        """
        kwargs = super().get_form_kwargs()
        if "initial" not in kwargs:
            kwargs["initial"] = {}
        kwargs["initial"]["model_name"] = "lead"
        return kwargs

    def get_initial(self):
        """
        When creating a new condition from the assignment rule detail view, pre-fill the 'rule' field based on the 'rule_pk' URL parameter. This allows the form to be correctly associated with the parent rule without requiring the user to select it manually.
        """
        initial = super().get_initial()
        rule_pk = self.kwargs.get("rule_pk")
        if rule_pk and not self.kwargs.get("pk"):
            try:
                initial["rule"] = LeadAssignmentRule.objects.get(pk=rule_pk)
            except LeadAssignmentRule.DoesNotExist:
                pass
        return initial

    @cached_property
    def form_url(self):
        """
        Return the form URL for creating or updating a LeadAssignmentCondition. If 'pk' is in kwargs, it's an update view; otherwise, it's a create view that requires 'rule_pk'.
        """
        pk = self.kwargs.get("pk")
        if pk:
            return reverse_lazy("leads:assignment_condition_update", kwargs={"pk": pk})
        return reverse_lazy(
            "leads:assignment_condition_create",
            kwargs={"rule_pk": self.kwargs["rule_pk"]},
        )

    def get_post_save_response(self):
        """
        After saving the condition, trigger a click on the #reloadButton to refresh the assignment rule detail view and show the updated list of conditions.
        """
        return HxTriggerResponse()


@method_decorator(htmx_required, name="dispatch")
class ToggleAssignToFieldView(LoginRequiredMixin, TemplateView):
    """HTMX endpoint to toggle assign_to_users / assign_to_roles containers based on assign_to_type."""

    template_name = "lead_assignment_rule/assign_to_toggle.html"

    def post(self, request, *args, **kwargs):
        """
        Handle POST request to toggle assign_to fields. The selected assign_to_type is passed in the POST data, and the view returns the appropriate form fields for that type (assign_to_users for user, assign_to_roles for role). The context also includes any previously selected users or roles to maintain state.
        """
        return self.get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """
        Get context data for the assign_to toggle view. This includes the selected assign_to_type and any previously selected users or roles to maintain state when toggling between options.
        """
        context = super().get_context_data(**kwargs)
        context["assign_to_type"] = self.request.POST.get(
            "assign_to_type"
        ) or self.request.GET.get("assign_to_type", "user")
        return context


@method_decorator(htmx_required, name="dispatch")
class ToggleNotifyMethodFieldView(LoginRequiredMixin, TemplateView):
    """HTMX endpoint to show/hide mail_template and notification_template based on notify_method."""

    template_name = "lead_assignment_rule/notify_method_toggle.html"

    def post(self, request, *args, **kwargs):
        """
        Handle POST request to toggle notification method fields. The selected notify_method is passed in the POST data, and the view returns the appropriate form fields for that method (mail_template for email, notification_template for in-app notifications). The context also includes the available templates filtered for leads and any previously selected templates to maintain state.
        """
        return self.get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """
        Get context data for the notify method toggle view. This includes the selected notify method and the available mail and notification templates that are applicable to leads (content_type null or leads.lead).
        """

        context = super().get_context_data(**kwargs)
        notify_method = self.request.POST.get("notify_method") or self.request.GET.get(
            "notify_method", ""
        )

        # Email needs an outgoing mail server. Without one, ask the user to set
        # it up (same popup as the cadence email follow-up) and do not keep
        # Email selected: "Both" falls back to the in-app notification.
        show_popup = (
            notify_method
            in (
                "email",
                "both",
            )
            and not HorillaMailConfiguration.objects.filter(
                mail_channel="outgoing", is_active=True
            ).exists()
        )
        if show_popup:
            notify_method = "notification" if notify_method == "both" else ""
            context["show_mail_config_popup"] = True
            context["reset_notify_method"] = notify_method
            context["configure_url"] = reverse("mail:mail_server_view")
        context["notify_method"] = notify_method

        lead_template_qs = Q(content_type__isnull=True) | Q(
            content_type__app_label="leads", content_type__model="lead"
        )
        context["mail_templates"] = HorillaMailTemplate.objects.filter(lead_template_qs)
        context["notification_templates"] = NotificationTemplate.objects.filter(
            lead_template_qs
        )

        context["selected_mail"] = self.request.POST.get("mail_template", "")
        context["selected_notification"] = self.request.POST.get(
            "notification_template", ""
        )
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.delete_leadassignmentcondition", modal=True),
    name="dispatch",
)
class AssignmentConditionDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """Delete a LeadAssignmentCondition."""

    model = LeadAssignmentCondition

    def get_post_delete_response(self):
        return HxTriggerResponse()
