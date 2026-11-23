"""
This view handles the methods for Big deal alert view
"""

# Third-party imports (Django)
from django import forms
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.automations.filters import HorillaAutomationFilter
from horilla.contrib.automations.models import AutomationCondition, HorillaAutomation
from horilla.contrib.automations.views import HorillaAutomationFormView
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.forms.form_class_mixin import WIDGET_INPUT_CSS_CLASS_NO_PR
from horilla.contrib.generics.views import HorillaNavView, HorillaView
from horilla.contrib.mail.models import HorillaMailConfiguration, HorillaMailTemplate
from horilla.contrib.utils.middlewares import get_active_company
from horilla.shortcuts import render
from horilla.urls import reverse_lazy
from horilla.utils import timezone
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.functional import cached_property
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import ScriptResponse

DEFAULT_BIG_DEAL_MAIL_TEMPLATE_TITLE = _("Big Deal Alert")
DEFAULT_BIG_DEAL_MAIL_SUBJECT = _("Big Deal Alert: {{ instance.name }}")
DEFAULT_BIG_DEAL_MAIL_BODY = _(
    "<p>A big deal has landed in the pipeline!</p>"
    "<p><strong>{{ instance.name }}</strong>, owned by {{ instance.owner }}, "
    "is worth <strong>{{ instance.amount }}</strong> and is currently in the "
    "<strong>{{ instance.stage }}</strong> stage.</p>"
)


class BigDealAlertView(LoginRequiredMixin, HorillaView):
    """
    Template view for Big deal alert page
    """

    template_name = "settings/settings_list_shell.html"
    view_id = "big-deal-alert-view"
    nav_url = reverse_lazy("opportunities:big_deal_alert_nav")
    list_url = reverse_lazy("opportunities:big_deal_alert_list")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("automations.view_horillaautomation"),
    name="dispatch",
)
class BigDealAlertNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar for big deal alert
    """

    nav_title = _("Big Deal Alerts")
    nav_description = _(
        "Get notified automatically when a high-value opportunity is created."
    )
    search_url = reverse_lazy("opportunities:big_deal_alert_list")
    main_url = reverse_lazy("opportunities:big_deal_alert_view")
    filterset_class = HorillaAutomationFilter
    one_view_only = True
    all_view_types = False
    filter_option = False
    reload_option = False
    nav_width = False
    search_option = False
    border_enabled = False

    @cached_property
    def new_button(self):
        """Return the 'Big Deal Create' button if the user has add permission."""
        if self.request.user.has_perm("automations.add_horillaautomation"):
            return {
                "url": reverse_lazy("opportunities:big_deal_automation_create"),
                "attrs": {"id": "big-deal-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("automations.view_horillaautomation"),
    name="dispatch",
)
class BigDealAlertListView(LoginRequiredMixin, View):
    """
    Accordion view for Big Deal Alerts
    Shows only automations with additional_info['big_deal'] = True in accordion format
    """

    template_name = "big_deal_alert_accordion.html"

    def get_queryset(self):
        """Filter automations to show only big deal alerts."""
        return HorillaAutomation.objects.filter(additional_info__big_deal=True)

    def get(self, request, *args, **kwargs):
        """Render the accordion view."""
        automations = self.get_queryset()
        context = {
            "automations": automations,
            "request": request,
        }
        return render(request, self.template_name, context)


@method_decorator(htmx_required, name="dispatch")
class BigDealAutomationFormView(HorillaAutomationFormView):
    """
    Form view for creating automation for Big Deal Alert.
    Inherits from HorillaAutomationFormView and sets initial model to opportunity.
    """

    hidden_fields = [
        "model",
        "trigger",
        "delivery_channel",
        "mail_template",
        "mail_server",
    ]
    full_width_fields = ["title"]

    # The generic condition-row UI (field/operator/value/logical_operator
    # selects) is replaced below with a single plain "Threshold Value"
    # number field; disable the generic condition machinery entirely.
    condition_fields = []
    condition_model = None

    @cached_property
    def form_title(self):
        """Return form title based on whether we're creating or updating."""
        if self.kwargs.get("pk"):
            return _("Edit Big Deal Alert")
        return _("Create Big Deal Alert")

    @cached_property
    def form_url(self):
        """Override form_url to use big deal automation URLs."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "opportunities:big_deal_automation_update", kwargs={"pk": pk}
            )
        return reverse_lazy("opportunities:big_deal_automation_create")

    def dispatch(self, request, *args, **kwargs):
        """Override dispatch."""
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        """Override post."""
        return super().post(request, *args, **kwargs)

    def get_form_kwargs(self):
        """Return keyword arguments for initializing the form."""
        kwargs = super().get_form_kwargs()

        # Ensure hidden_fields is always passed to the form
        kwargs["hidden_fields"] = self.hidden_fields

        if not self.kwargs.get("pk"):
            try:
                opportunity_content_type = HorillaContentType.objects.get(
                    model="opportunity"
                )
                if "initial" not in kwargs:
                    kwargs["initial"] = {}
                kwargs["initial"]["model"] = opportunity_content_type.pk
                kwargs["initial"]["model_name"] = "opportunity"
            except HorillaContentType.DoesNotExist:
                pass

            if "initial" not in kwargs:
                kwargs["initial"] = {}
            # Pre-fill defaults so the user only has to enter the title and
            # the trigger amount - trigger/mail_to/delivery_channel are
            # sensible defaults for a "big deal" rather than choices the
            # user needs to make every time.
            kwargs["initial"].setdefault("trigger", "on_create_or_update")
            kwargs["initial"].setdefault("mail_to", "instance.owner")
            kwargs["initial"].setdefault("delivery_channel", "mail")

        return kwargs

    def get_form(self, form_class=None):
        """Add a plain 'Threshold Value' field in place of the generic condition row."""
        form = super().get_form(form_class)
        form.fields["threshold_value"] = forms.DecimalField(
            label=_("Threshold Value"),
            required=True,
            min_value=0,
            help_text=_(
                "Alert when the opportunity amount is greater than this value."
            ),
            widget=forms.NumberInput(
                attrs={
                    "class": WIDGET_INPUT_CSS_CLASS_NO_PR,
                    "placeholder": _("Enter Threshold Value"),
                }
            ),
        )
        if self.kwargs.get("pk") and self.object:
            existing_condition = self.object.conditions.filter(field="amount").first()
            if existing_condition:
                form.fields["threshold_value"].initial = existing_condition.value

        # Delivery channel/mail template/mail server are hidden from the
        # user, so resolve their defaults into cleaned_data before Django's
        # ModelForm._post_clean() builds the instance and runs
        # HorillaAutomation.clean() (which requires a mail_template when
        # delivery_channel == "mail"). Wrap the form's own clean() so this
        # still works as plain Python attribute access when it's called.
        original_clean = form.clean

        def clean_with_mail_defaults():
            cleaned_data = original_clean()
            if cleaned_data is None:
                cleaned_data = form.cleaned_data

            if not cleaned_data.get("delivery_channel"):
                cleaned_data["delivery_channel"] = "mail"

            if cleaned_data.get("delivery_channel") == "mail":
                company = get_active_company()
                if not cleaned_data.get("mail_template"):
                    opportunity_content_type = HorillaContentType.objects.filter(
                        model="opportunity"
                    ).first()
                    mail_template, _created = HorillaMailTemplate.objects.get_or_create(
                        title=DEFAULT_BIG_DEAL_MAIL_TEMPLATE_TITLE,
                        company=company,
                        defaults={
                            "subject": DEFAULT_BIG_DEAL_MAIL_SUBJECT,
                            "body": DEFAULT_BIG_DEAL_MAIL_BODY,
                            "content_type": opportunity_content_type,
                            "created_by": self.request.user,
                            "updated_by": self.request.user,
                        },
                    )
                    cleaned_data["mail_template"] = mail_template
                if not cleaned_data.get("mail_server"):
                    mail_server = HorillaMailConfiguration.objects.filter(
                        company=company,
                        mail_channel="outgoing",
                        is_primary=True,
                    ).first()
                    if not mail_server:
                        mail_server = HorillaMailConfiguration.objects.filter(
                            company=company,
                            mail_channel="outgoing",
                        ).first()
                    if mail_server:
                        cleaned_data["mail_server"] = mail_server

            return cleaned_data

        form.clean = clean_with_mail_defaults
        return form

    def form_invalid(self, form):
        """Handle invalid form submission and ensure hidden fields stay hidden."""
        for field_name in self.hidden_fields:
            if field_name in form.fields:
                form.fields[field_name].widget = forms.HiddenInput()
                form.fields[field_name].widget.attrs.update({"class": "hidden-input"})
        return super().form_invalid(form)

    def form_valid(self, form):
        """Override form_valid to set additional_info['big_deal'] = True before saving."""

        if self.condition_fields and not self.condition_model:
            created_instances = self.save_multiple_main_instances(form)
            if created_instances is False:
                return self.form_invalid(form)
            if created_instances:
                self.request.session["condition_row_count"] = 0
                messages.success(
                    self.request,
                    f"Created {len(created_instances)} {self.model._meta.verbose_name.lower()}(s) successfully!",
                )
                return ScriptResponse(reload=True, close=True)
            if created_instances == []:
                form.add_error(
                    None,
                    "At least one instance must be created with all required fields.",
                )
                return self.form_invalid(form)

        # Get object like parent does
        self.object = form.save(commit=False)

        # Handle file fields like parent
        for field_name, field in form.fields.items():
            if isinstance(field, forms.FileField) or isinstance(
                field, forms.ImageField
            ):
                clear_flag = self.request.POST.get(f"id_{field_name}_clear", "false")
                if clear_flag == "true":
                    setattr(self.object, field_name, None)

        # Set timestamps and company like parent
        if self.kwargs.get("pk") and not self.duplicate_mode:
            self.object.updated_at = timezone.now()
            self.object.updated_by = self.request.user
        else:
            self.object.created_at = timezone.now()
            self.object.created_by = self.request.user
            self.object.updated_at = timezone.now()
            self.object.updated_by = self.request.user
        self.object.company = form.cleaned_data.get("company") or get_active_company()

        # Delivery channel, mail template and mail server are hidden from the
        # user - auto-provision a per-company "Big Deal Alert" mail template
        # and fall back to the company's primary outgoing mail server, so
        # the user only has to provide the title and the threshold amount.
        if not self.object.delivery_channel:
            self.object.delivery_channel = "mail"
        if self.object.delivery_channel == "mail" and not self.object.mail_template_id:
            opportunity_content_type = HorillaContentType.objects.filter(
                model="opportunity"
            ).first()
            mail_template, _created = HorillaMailTemplate.objects.get_or_create(
                title=DEFAULT_BIG_DEAL_MAIL_TEMPLATE_TITLE,
                company=self.object.company,
                defaults={
                    "subject": DEFAULT_BIG_DEAL_MAIL_SUBJECT,
                    "body": DEFAULT_BIG_DEAL_MAIL_BODY,
                    "content_type": opportunity_content_type,
                },
            )
            self.object.mail_template = mail_template
        if self.object.delivery_channel == "mail" and not self.object.mail_server_id:
            mail_server = HorillaMailConfiguration.objects.filter(
                company=self.object.company,
                mail_channel="outgoing",
                is_primary=True,
            ).first()
            if not mail_server:
                mail_server = HorillaMailConfiguration.objects.filter(
                    company=self.object.company,
                    mail_channel="outgoing",
                ).first()
            if mail_server:
                self.object.mail_server = mail_server

        # Tag this automation as a Big Deal Alert (identifies it for the
        # opportunities-specific list/filter views), and opt it into the
        # generic engine's edge-trigger behavior so it only re-fires when the
        # amount newly crosses the threshold, not on every subsequent edit to
        # an opportunity that already qualified.
        if not self.object.additional_info:
            self.object.additional_info = {}
        self.object.additional_info["big_deal"] = True
        self.object.additional_info["edge_trigger_only"] = True

        # Now manually save and handle the rest (can't use super() because it would save without our change)
        try:
            self.object.save()
            form.save_m2m()

            # Replace any existing "amount" condition with the submitted
            # threshold value (the only condition this form manages).
            AutomationCondition.objects.filter(
                automation=self.object, field="amount"
            ).delete()
            AutomationCondition.objects.create(
                automation=self.object,
                field="amount",
                operator="gt",
                value=str(form.cleaned_data["threshold_value"]),
                company=self.object.company,
                created_by=self.request.user,
                updated_by=self.request.user,
            )

            self.request.session["condition_row_count"] = 0
            self.request.session.modified = True
            action = (
                _("duplicated")
                if self.duplicate_mode
                else (
                    _("updated")
                    if self.kwargs.get("pk") and not self.duplicate_mode
                    else _("created")
                )
            )

            messages.success(
                self.request,
                _("%(model)s %(action)s successfully!")
                % {
                    "model": self.model._meta.verbose_name,
                    "action": action,
                },
            )

            if (
                "save_and_new" in self.request.POST
                and not self.kwargs.get("pk")
                and not self.duplicate_mode
            ):
                create_url = self.get_create_url()
                return render(
                    self.request,
                    "big_deal_alert_reload_fragment.html",
                    {"load_url": create_url, "close_modal": False},
                )

            if (
                self.detail_url_name
                and not self.kwargs.get("pk")
                and not self.duplicate_mode
            ):
                detail_url = reverse_lazy(
                    self.detail_url_name, kwargs={"pk": self.object.pk}
                )
                return render(
                    self.request,
                    "big_deal_alert_reload_fragment.html",
                    {"load_url": detail_url, "close_modal": True},
                )

            return render(
                self.request,
                "big_deal_alert_reload_fragment.html",
                {"load_url": None, "close_modal": True},
            )
        except Exception as e:
            messages.error(self.request, f"Error saving: {str(e)}")
            return self.form_invalid(form)
