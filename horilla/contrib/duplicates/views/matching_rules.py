"""Views for matching-rule workflows."""

# Standard library imports
import json
from functools import cached_property

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin

# First party imports (Horilla)
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.forms.condition_fields import get_model_field_choices
from horilla.contrib.generics.views import (
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla.db.models import Prefetch
from horilla.shortcuts import render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.html import escape
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import HttpResponse, ScriptResponse

# Local imports
from ..filters import MatchingRuleFilter
from ..forms import MatchingRuleForm
from ..models import DuplicateRuleCondition, MatchingRule, MatchingRuleCriteria


@method_decorator(
    permission_required_or_denied(
        "duplicates.view_matchingrule", wrapper_id="matching-rule-view"
    ),
    name="dispatch",
)
class MatchingRuleView(LoginRequiredMixin, HorillaView):
    """
    Main view for matching rules page
    """

    template_name = "settings/settings_list_shell.html"
    view_id = "matching-rule-view"
    nav_url = reverse_lazy("duplicates:matching_rule_nav_view")
    list_url = reverse_lazy("duplicates:matching_rule_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("duplicates.view_matchingrule"), name="dispatch")
class MatchingRuleNavView(LoginRequiredMixin, HorillaNavView):
    """
    Navbar view for Matching Rules
    """

    nav_description = _("Define which fields are compared to detect matching records.")
    search_url = reverse_lazy("duplicates:matching_rule_list_view")
    main_url = reverse_lazy("duplicates:matching_rule_view")
    model_name = "MatchingRule"
    model_app_label = "duplicates"
    filterset_class = MatchingRuleFilter
    nav_width = False
    all_view_types = False
    filter_option = False
    reload_option = False
    one_view_only = True

    @cached_property
    def new_button(self):
        """New button configuration for the navbar."""
        if self.request.user.has_perm("duplicates.add_matchingrule"):
            return {
                "url": f"""{reverse_lazy("duplicates:matching_rule_create_view")}?new=true""",
                "attrs": {"id": "matching-rule-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("duplicates.view_matchingrule"),
    name="dispatch",
)
class MatchingRuleListView(LoginRequiredMixin, View):
    """
    Accordion view for Matching Rules
    Shows matching rules in accordion format similar to Big Deal Alerts
    """

    template_name = "duplicates/matching_rule_accordion.html"

    def get_queryset(self):
        """Get all matching rules with their criteria prefetched and ordered."""

        return MatchingRule.objects.all().prefetch_related(
            Prefetch(
                "criteria",
                queryset=MatchingRuleCriteria.objects.order_by("order", "created_at"),
            ),
            "content_type",
        )

    def get(self, request, *args, **kwargs):
        """Render the accordion view."""
        matching_rules = self.get_queryset()
        context = {
            "matching_rules": matching_rules,
            "request": request,
        }
        return render(request, self.template_name, context)


@method_decorator(htmx_required, name="dispatch")
class MatchingRuleFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Form view for creating and updating Matching Rule with criteria
    """

    model = MatchingRule
    form_class = MatchingRuleForm
    modal_height = False
    full_width_fields = ["description"]
    condition_fields = ["field_name", "matching_method", "match_blank_fields"]
    condition_model = MatchingRuleCriteria
    condition_field_title = _("Matching Criteria")
    condition_related_name = "criteria"
    condition_order_by = ["order", "created_at"]
    content_type_field = "content_type"  # Enable automatic model_name extraction
    condition_hx_include = (
        "[name='content_type']"  # Include content_type when adding condition rows
    )
    save_and_new = False

    @cached_property
    def form_url(self):
        """Get the URL for the form view."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "duplicates:matching_rule_update_view", kwargs={"pk": pk}
            )
        return reverse_lazy("duplicates:matching_rule_create_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("duplicates.delete_matchingrule", modal=True),
    name="dispatch",
)
class MatchingRuleDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete view for MatchingRule
    """

    model = MatchingRule

    def get_post_delete_response(self):
        """Return response after successful deletion"""
        return ScriptResponse(reload=True)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "duplicates.add_matchingrule",
            "duplicates.change_matchingrule",
        ]
    ),
    name="dispatch",
)
class MatchingRuleCriteriaFieldChoicesView(LoginRequiredMixin, View):
    """
    View to return matching rule field choices based on selected content type
    """

    def get(self, request, *args, **kwargs):
        """Return matching rules filtered by content type"""

        content_type_id = request.GET.get("content_type")

        if not content_type_id:
            return HttpResponse(
                '<select name="matching_rule" id="id_matching_rule" class="js-example-basic-single headselect w-full"><option value="">---------</option></select>'
            )

        try:
            content_type = HorillaContentType.objects.get(pk=content_type_id)
            matching_rules = MatchingRule.objects.filter(content_type=content_type)

            options = '<option value="">---------</option>'
            for rule in matching_rules:
                options += (
                    f'<option value="{escape(str(rule.pk))}">'
                    f"{escape(str(rule.name))}</option>"
                )

            # Matching rule select (ensure Select2 is re-initialized when swapped)
            select_html = (
                '<select name="matching_rule" id="id_matching_rule" '
                'class="js-example-basic-single headselect w-full" '
                "hx-on::load=\"if(window.jQuery){var $el=jQuery(this);try{if($el.data('select2')){$el.select2('destroy');}}catch(e){} "
                "var next=$el.next(); if(next && next.hasClass && next.hasClass('select2')){next.remove();} "
                'if(jQuery.fn.select2){$el.select2();}}">'
                f"{options}"
                "</select>"
            )

            # Additionally, update DuplicateRule Condition row-0 field choices OOB so conditions reflect module
            model_name = content_type.model
            # Same field list as every other condition builder (editable fields
            # plus the related ones such as owner department/role/company).
            field_options = "".join(
                f'<option value="{escape(value)}">{escape(str(label))}</option>'
                for value, label in get_model_field_choices(None, model_name)
            )

            hx_vals_json = json.dumps(
                {
                    "model_name": model_name,
                    "row_id": "0",
                    "condition_model": (
                        f"{DuplicateRuleCondition._meta.app_label}."
                        f"{DuplicateRuleCondition._meta.model_name}"
                    ),
                }
            )
            field_select_html = (
                '<select name="field_0" id="id_field_0" class="js-example-basic-single headselect w-full" '
                f'hx-get="{reverse_lazy("generics:get_field_value_widget")}" '
                'hx-target="#id_value_0_container" '
                'hx-swap="innerHTML" '
                f'hx-vals="{escape(hx_vals_json)}" '
                "hx-include=\"[name='field_0'],#id_value_0,[name='content_type']\" "
                'hx-trigger="change,load"'
                f">{field_options}</select>"
            )
            # OOB swap for the field container
            oob_container = f'<div id="id_field_0_container" hx-swap-oob="true">{field_select_html}</div>'

            reinit_script = """
            <script>
            (function() {
            if (!window.jQuery) return;
            function rebuildSelect2(selector) {
                var $el = jQuery(selector);
                if (!$el.length) return;
                try {
                if ($el.data('select2')) {
                    $el.select2('destroy');
                }
                } catch (e) {}
                // Remove stale Select2 DOM if any (usually inserted right after the select)
                var next = $el.next();
                if (next && next.hasClass && next.hasClass('select2')) {
                next.remove();
                }
                if (jQuery.fn.select2) {
                $el.select2();
                }
            }
            rebuildSelect2('#id_matching_rule');
            rebuildSelect2('#id_field_0');
            })();
            </script>
            """

            return HttpResponse(select_html + oob_container + reinit_script)
        except HorillaContentType.DoesNotExist:
            return HttpResponse(
                '<select name="matching_rule" id="id_matching_rule" class="js-example-basic-single headselect"><option value="">---------</option></select>'
            )
