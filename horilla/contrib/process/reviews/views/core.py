"""Views for Review Process settings"""

# Standard library imports
from functools import cached_property
from urllib.parse import urlencode

# Third-party imports (Django)
from django.contrib import messages
from django.core.exceptions import ValidationError

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.forms.condition_fields import get_extension_field_choices
from horilla.contrib.generics.methods import get_condition_value_display
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse, reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView, View
from horilla.web import HxTriggerResponse, ScriptResponse

# Local imports
from ..filters import ReviewProcessFilter
from ..forms import ReviewProcessForm, ReviewProcessRuleForm
from ..models import ReviewCondition, ReviewProcess, ReviewRule, ReviewRuleCondition


class ReviewProcessView(LoginRequiredMixin, HorillaView):
    """Settings page container for Review Processes."""

    template_name = "settings/settings_list_shell.html"
    view_id = "review-process-view"
    nav_url = reverse_lazy("reviews:reviews_navbar_view")
    list_url = reverse_lazy("reviews:reviews_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["reviews.view_reviewprocess"]),
    name="dispatch",
)
class ReviewProcessNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar for Review Process list (with New button)."""

    nav_title = ReviewProcess._meta.verbose_name_plural
    nav_description = _("Define the review cycles and stages your records go through.")
    search_url = reverse_lazy("reviews:reviews_list_view")
    main_url = reverse_lazy("reviews:reviews_view")
    filterset_class = ReviewProcessFilter
    nav_width = False
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False

    @cached_property
    def new_button(self):
        """Add new review process button, shown if user has add permission."""
        if self.request.user.has_perm("reviews.add_reviewprocess"):
            return {
                "url": f"{reverse_lazy('reviews:reviews_create_view')}?new=true",
                "attrs": 'id="review-process-create"',
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["reviews.view_reviewprocess"]),
    name="dispatch",
)
class ReviewProcessDetailNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar for review process detail: back to list, title, Add rule, Edit process."""

    search_url = reverse_lazy("reviews:reviews_list_view")
    main_url = reverse_lazy("reviews:reviews_view")
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
        "hx-get": reverse_lazy("reviews:reviews_view"),
        "hx-target": "#settings-content",
        "hx-swap": "innerHTML",
        "hx-push-url": "true",
        "hx-select": "#review-process-view",
    }

    @cached_property
    def new_button(self):
        """Primary: edit review process (opens modal)."""

        if not self.request.user.has_perm("reviews.change_reviewprocess"):
            return None
        pk = self.request.GET.get("pk")
        if not pk:
            return None
        try:
            process_pk = int(pk)
        except (TypeError, ValueError):
            return None

        return {
            "url": reverse(
                "reviews:review_rule_create_view",
                kwargs={"process_pk": process_pk},
            ),
            "title": _("Add Rule"),
            "attrs": {"id": "review-process-add"},
        }

    @cached_property
    def second_button(self):
        """Secondary: add or edit review rule (opens modal)."""

        if not self.request.user.has_perm("reviews.change_reviewprocess"):
            return None
        pk = self.request.GET.get("pk")
        if not pk:
            return None
        try:
            process_pk = int(pk)
        except (TypeError, ValueError):
            return None

        return {
            "url": reverse(
                "reviews:reviews_update_view",
                kwargs={"pk": process_pk},
            ),
            "title": _("Edit Process"),
            "attrs": {"id": "review-process-edit"},
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pk = self.request.GET.get("pk")
        if pk:
            try:
                process = ReviewProcess.objects.filter(pk=int(pk)).first()
                if process:
                    self.nav_title = process.title
                    context["nav_title"] = self.nav_title
            except ValueError:
                pass
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("reviews.view_reviewprocess"),
    name="dispatch",
)
class ReviewProcessListView(LoginRequiredMixin, HorillaListView):
    """List view for Review Processes."""

    model = ReviewProcess
    view_id = "review-process-list"
    search_url = reverse_lazy("reviews:reviews_list_view")
    main_url = reverse_lazy("reviews:reviews_view")
    filterset_class = ReviewProcessFilter
    save_to_list_option = False
    list_column_visibility = False
    bulk_select_option = False
    enable_sorting = False

    columns = [
        "title",
        "model",
        (_("Execute on"), "get_execute_display"),
        ("is_active", "is_active_col"),
    ]

    @cached_property
    def col_attrs(self):
        """Return column attributes for the review process list view."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {
            "hx-get": f"{{get_detail_url}}?{query_string}",
            "hx-target": "#mainContent",
            "hx-swap": "outerHTML",
            "hx-push-url": "true",
            "hx-select": "#mainContent",
            "permission": "reviews.view_reviewprocess",
            "own_permission": "reviews.view_own_reviewprocess",
            "owner_field": "owner",
        }
        return [
            {
                "title": {
                    **attrs,
                }
            }
        ]

    actions = [
        {
            "action": _("Edit"),
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "reviews.change_reviewprocess",
            "attrs": """
                        hx-get="{get_edit_url}"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        },
        {
            "action": _("Delete"),
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "reviews.delete_reviewprocess",
            "attrs": """
                        hx-get="{get_delete_url}"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        },
    ]

    def no_record_add_button(self):
        """Show add button when no records exist, if user has permission."""
        if self.request.user.has_perm("reviews.add_reviewprocess"):
            return {
                "url": f"{reverse_lazy('reviews:reviews_create_view')}?new=true",
                "attrs": 'id="review-process-create"',
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "reviews.add_reviewprocess",
            "reviews.change_reviewprocess",
        ]
    ),
    name="dispatch",
)
class ReviewProcessFormView(LoginRequiredMixin, HorillaSingleFormView):
    """Create/update ReviewProcess (criteria optional via conditions)."""

    model = ReviewProcess
    form_class = ReviewProcessForm
    template_name = "reviews/review_process_form.html"
    modal_height = False
    full_width_fields = ["title", "model", "review_fields"]

    condition_fields = ["field", "operator", "value", "logical_operator"]
    condition_model = ReviewCondition
    condition_related_name = "conditions"
    condition_order_by = ["order", "created_at"]
    condition_field_title = _("Criteria")
    content_type_field = "model"

    save_and_new = False

    _toggle_field_names = (
        "trigger_on_create",
        "trigger_on_edit",
        "notify_on_submission",
        "notify_on_approval",
        "notify_on_rejection",
        "is_active",
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = context["form"]
        context["review_process_toggle_field_names"] = list(self._toggle_field_names)
        context["review_process_toggle_fields"] = [
            form[name] for name in self._toggle_field_names
        ]
        return context

    @cached_property
    def form_url(self):
        """URL for form submission, differs for create vs update."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("reviews:reviews_update_view", kwargs={"pk": pk})
        return reverse_lazy("reviews:reviews_create_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("reviews.add_reviewprocess"),
    name="dispatch",
)
class ReviewProcessModelDependentFieldsView(ReviewProcessFormView):
    """Return only model-dependent form sections (review fields + conditions)."""

    template_name = "reviews/partials/reviews_model_dependent_fields.html"

    def get(self, request, *args, **kwargs):
        form = self.get_form()
        context = self.get_context_data(form=form)
        return render(request, self.template_name, context)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("reviews.delete_reviewprocess", modal=True),
    name="dispatch",
)
class ReviewProcessDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """Delete view for review process"""

    model = ReviewProcess

    def get_post_delete_response(self):
        return HxTriggerResponse()


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("reviews.delete_reviewrule", modal=True),
    name="dispatch",
)
class ReviewRuleDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """Delete view for review rule."""

    model = ReviewRule

    def get_post_delete_response(self):
        return HxTriggerResponse()


@method_decorator(
    permission_required_or_denied(["reviews.view_reviewprocess"]),
    name="dispatch",
)
class ReviewProcessDetailView(LoginRequiredMixin, TemplateView):
    """Detail view to configure fields-to-review, conditions, approver, notifications."""

    template_name = "reviews/reviews_detail_view.html"

    def get_context_data(self, **kwargs):
        """Build context with the review process, its rules, and field data."""
        context = super().get_context_data(**kwargs)
        obj = get_object_or_404(ReviewProcess, pk=self.kwargs["pk"])
        context["obj"] = obj
        context["nav_url"] = reverse_lazy("reviews:reviews_detail_navbar_view")
        rules = list(obj.rules.all().order_by("created_at"))
        for rule in rules:
            rule.rule_criteria = list(
                rule.conditions.all().order_by("order", "created_at")
            )
        context["rules"] = rules
        entry_criteria = list(obj.conditions.all().order_by("order", "created_at"))
        context["entry_criteria"] = entry_criteria

        # Map model field names -> verbose labels for nicer display
        field_label_map = {}
        model_name = (
            getattr(obj.model, "model", None) if getattr(obj, "model", None) else None
        )
        if model_name:
            model_class = None
            for app_config in apps.get_app_configs():
                try:
                    model_class = apps.get_model(app_config.label, model_name.lower())
                    break
                except Exception:
                    continue
            if model_class:
                fields_and_m2m = list(model_class._meta.fields) + list(
                    model_class._meta.many_to_many
                )
                for f in fields_and_m2m:
                    verbose = (
                        getattr(f, "verbose_name", None)
                        or f.name.replace("_", " ").title()
                    )
                    field_label_map[f.name] = str(verbose).title()
                # Fields contributed by other apps (e.g. custom fields)
                for ext_name, ext_label in get_extension_field_choices(model_class):
                    field_label_map.setdefault(ext_name, str(ext_label))

                for c in entry_criteria:
                    c.value_display = get_condition_value_display(
                        model_class, getattr(c, "field", ""), getattr(c, "value", None)
                    )
                for rule in rules:
                    for c in rule.rule_criteria:
                        c.value_display = get_condition_value_display(
                            model_class,
                            getattr(c, "field", ""),
                            getattr(c, "value", None),
                        )
        context["field_label_map"] = field_label_map
        return context


@method_decorator(htmx_required, name="dispatch")
class ReviewRuleFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Modal form to configure the Review Rule using the generic single-form UI.
    This gives us: rule conditions + properly styled boolean toggles.
    """

    model = ReviewRule
    form_class = ReviewProcessRuleForm
    modal_height = False
    save_and_new = False
    hidden_fields = ["reviews"]
    full_width_fields = ["approver_type", "approver_users", "approver_roles"]

    condition_fields = ["field", "operator", "value", "logical_operator"]
    condition_model = ReviewRuleCondition
    condition_related_name = "conditions"
    condition_order_by = ["order", "created_at"]
    condition_field_title = _("Condition")

    def dispatch(self, request, *args, **kwargs):
        """
        Resolve review process / rule; on missing or bad id,
        message + reload detail + close modal.
        """
        self.rule_obj = None
        process_pk = self.kwargs.get("process_pk")
        rule_pk = self.kwargs.get("pk")
        try:
            if rule_pk:
                self.rule_obj = get_object_or_404(ReviewRule, pk=rule_pk)
                self.reviews = self.rule_obj.reviews
            else:
                if not process_pk:
                    process_pk = (
                        request.POST.get("reviews")
                        or request.GET.get("reviews")
                        or request.GET.get("reviews_id")
                    )
                self.reviews = get_object_or_404(ReviewProcess, pk=process_pk)
        except Exception as e:
            messages.error(request, str(e))
            return ScriptResponse(
                reload=True,
                close=True,
            )
        return super().dispatch(request, *args, **kwargs)

    def get_approver_visibility(self, form):
        """
        Determine which approver fields to show based on
        approver type from form data, GET params, or instance.
        """
        approver_type = ""
        if getattr(form, "is_bound", False):
            approver_type = form.data.get("approver_type", "")
        if not approver_type:
            approver_type = self.request.GET.get("approver_type", "")
        if not approver_type:
            approver_type = form.initial.get("approver_type") or getattr(
                form.instance, "approver_type", ""
            )
        approver_type = str(approver_type or "").lower()
        return {
            "show_users": approver_type == "user",
            "show_roles": approver_type == "role",
        }

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        # Needed for field list population (for `review_fields`)
        if "initial" not in kwargs:
            kwargs["initial"] = {}
        kwargs["initial"]["model_name"] = self.reviews.model.model
        kwargs["initial"]["reviews"] = self.reviews.pk
        return kwargs

    @cached_property
    def form_url(self):
        """URL for form submission, differs for create vs update."""
        if self.rule_obj:
            return reverse_lazy(
                "reviews:review_rule_update_view",
                kwargs={"pk": self.rule_obj.pk},
            )
        return reverse_lazy(
            "reviews:review_rule_create_view",
            kwargs={"process_pk": self.reviews.pk},
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = context.get("form")
        if form is not None:
            context.update(self.get_approver_visibility(form))
        return context


@method_decorator(htmx_required, name="dispatch")
class ReviewProcessToggleActiveView(LoginRequiredMixin, View):
    """Toggle is_active status for a ReviewProcess via HTMX."""

    def post(self, request, *args, **kwargs):
        """Flip ``is_active`` on the review process and trigger an HTMX UI reload."""
        try:
            process = ReviewProcess.objects.get(pk=kwargs["pk"])
            if not request.user.has_perm("reviews.change_reviewprocess"):
                return ScriptResponse(reload=True)
            process.is_active = not process.is_active
            process.save(update_fields=["is_active"])
            status = _("activated") if process.is_active else _("deactivated")
            messages.success(request, f"{process.title} {status} successfully")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        except Exception:
            messages.error(request, _("Unable to update the review process status."))
        return ScriptResponse(reload=True)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "reviews.add_reviewprocess",
            "reviews.change_reviewprocess",
        ]
    ),
    name="dispatch",
)
class ReviewProcessApproverFieldsToggleView(ReviewRuleFormView):
    """Return only approver fields section based on approver type."""

    template_name = "reviews/partials/approver_fields_toggle.html"

    def get(self, request, *args, **kwargs):
        form = self.get_form()
        context = self.get_context_data(form=form)
        return render(request, self.template_name, context)
