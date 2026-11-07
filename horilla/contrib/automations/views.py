"""
Views for the automations app
"""

# Standard library imports
import json
from functools import cached_property

from horilla.apps import apps
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.models import HorillaContentType

# Local imports
from horilla.contrib.generics.forms.condition_fields import (
    CONDITION_EXCLUDED_FIELDS,
    get_model_field_choices,
)
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaModalDetailView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla.contrib.mail.models import HorillaMailConfiguration, HorillaMailTemplate
from horilla.contrib.notifications.models import NotificationTemplate

# First party imports (Horilla)
from horilla.db.models import Q
from horilla.registry.delivery import get_delivery_channel
from horilla.shortcuts import render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import ScriptResponse

from .filters import HorillaAutomationFilter
from .forms import HorillaAutomationForm, get_model_class, get_recipient_choices
from .models import AutomationCondition, HorillaAutomation, split_delivery_channels


@method_decorator(
    permission_required_or_denied(
        ["automations.view_horillaautomation"], wrapper_id="automation-view"
    ),
    name="dispatch",
)
class HorillaAutomationView(LoginRequiredMixin, HorillaView):
    """
    TemplateView for automation page.
    """

    template_name = "settings/settings_list_shell.html"
    view_id = "automation-view"
    nav_url = reverse_lazy("automations:automation_navbar_view")
    list_url = reverse_lazy("automations:automation_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["automations.view_horillaautomation"]),
    name="dispatch",
)
class HorillaAutomationNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar view for automation
    """

    nav_description = _(
        "Automate messages across your delivery channels based on events in your workflow."
    )
    search_url = reverse_lazy("automations:automation_list_view")
    main_url = reverse_lazy("automations:automation_view")
    model_name = "HorillaAutomation"
    model_app_label = "automations"
    filterset_class = HorillaAutomationFilter
    nav_width = False
    all_view_types = False
    filter_option = False
    reload_option = False
    one_view_only = True
    border_enabled = False
    enable_actions = True
    column_selector_exclude_fields = ["method_title"]

    @cached_property
    def new_button(self):
        """New button configuration for the navbar."""
        if self.request.user.has_perm("automations.add_horillaautomation"):
            return {
                "url": f"""{reverse_lazy("automations:automation_create_view")}?new=true""",
                "attrs": {"id": "automation-create"},
            }
        return None

    @cached_property
    def actions(self):
        """Add Column to List (from the generic navbar) plus Load Automation"""
        actions = [
            action
            for action in super().actions
            if action["action"] == _("Add Column to List")
        ]
        if self.request.user.has_perm("automations.add_horillaautomation"):
            actions.append(
                {
                    "action": _("Load Automation"),
                    "attrs": f"""
                            id="automation-load"
                            hx-get="{reverse_lazy("automations:load_automation")}"
                            hx-on:click="openModal();"
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            """,
                }
            )
        return actions


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["automations.view_horillaautomation"]),
    name="dispatch",
)
class HorillaAutomationListView(LoginRequiredMixin, HorillaListView):
    """
    List view of automation
    """

    model = HorillaAutomation
    view_id = "automation-list"
    search_url = reverse_lazy("automations:automation_list_view")
    main_url = reverse_lazy("automations:automation_view")
    filterset_class = HorillaAutomationFilter
    bulk_update_two_column = True
    bulk_delete_enabled = False
    bulk_select_option = False

    columns = [
        "title",
        "trigger",
        "model",
        (_("Choose Delivery Channel"), "get_delivery_channel_display"),
    ]
    store_ordered_ids = True

    @cached_property
    def col_attrs(self):
        """Open the detail modal when clicking the title column."""
        query_string = self.request.session.get(self.ordered_ids_key, [])
        attrs = {}
        if self.request.user.has_perm("automations.view_horillaautomation"):
            attrs = {
                "hx-get": f"{{get_detail_url}}?instance_ids={query_string}",
                "hx-target": "#detailModalBox",
                "hx-swap": "innerHTML",
                "hx-push-url": "false",
                "hx-on:click": "openDetailModal();",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }
        return [{"title": {**attrs}}]

    def get_queryset(self):
        """Exclude Big Deal Alert automations, which have their own dedicated list."""
        queryset = super().get_queryset()
        big_deal_ids = set(
            queryset.filter(additional_info__big_deal=True).values_list("pk", flat=True)
        )
        # The parent stored the ordered ids before this exclusion; drop the
        # Big Deal ones so the detail modal's next/previous never lands on them.
        if big_deal_ids:
            self.request.session[self.ordered_ids_key] = [
                pk
                for pk in self.request.session.get(self.ordered_ids_key, [])
                if pk not in big_deal_ids
            ]
        return queryset.exclude(additional_info__big_deal=True)

    def no_record_add_button(self):
        """Return configuration for the 'no records' Load Automation button when permitted."""
        if self.request.user.has_perm("automations.add_horillaautomation"):
            return {
                "url": f"""{reverse_lazy("automations:load_automation")}?new=true""",
                "attrs": 'id="automation-load"',
                "title": _("Load Automation"),
            }
        return None

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "automations.change_horillaautomation",
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
            "permission": "automations.delete_horillaautomation",
            "attrs": """
                    hx-get="{get_delete_url}"
                    hx-target="#deleteModeBox"
                    hx-swap="innerHTML"
                    hx-trigger="click"
                    hx-vals='{{"check_dependencies": "false"}}'
                    onclick="openDeleteModeModal()"
                """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
class HorillaAutomationFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Form view for creating and updating automation
    """

    model = HorillaAutomation
    form_class = HorillaAutomationForm
    modal_height = False
    condition_fields = ["field", "operator", "value", "logical_operator"]
    condition_model = AutomationCondition
    condition_field_title = _("Condition")
    condition_hx_include = "#id_model"
    condition_related_name = "conditions"
    condition_order_by = ["order", "created_at"]
    content_type_field = "model"
    save_and_new = False
    dynamic_create_fields = ["mail_template", "notification_template"]
    dynamic_create_field_mapping = {
        "mail_template": {
            "fields": ["title", "subject", "content_type", "body"],
            "full_width_fields": ["title", "subject", "content_type", "body"],
            "rich_text_fields": ["body"],
            "permission": ["mail.add_horillamailtemplate"],
        },
        "notification_template": {
            "fields": ["title", "content_type", "message"],
            "full_width_fields": ["title", "content_type", "message"],
            "rich_text_fields": ["message"],
            "permission": ["notifications.add_notificationtemplate"],
        },
    }

    def get_existing_conditions(self):
        """Return existing conditions excluding any that use excluded fields (e.g. password)."""
        qs = super().get_existing_conditions()
        if qs is None:
            return None
        return qs.exclude(field__in=CONDITION_EXCLUDED_FIELDS)

    @cached_property
    def form_url(self):
        """Get the URL for the form view."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("automations:automation_update_view", kwargs={"pk": pk})
        return reverse_lazy("automations:automation_create_view")

    def get_initial(self):
        """Preserve filled values on HTMX reload; pass trigger/model for scheduled UI."""
        initial = super().get_initial()
        if self.request.method == "GET":
            # Preserve common form fields (HTMX trigger reload includes closest form)
            preserved_fields = [
                "title",
                "model",
                "mail_to",
                "also_sent_to",
                "trigger",
                "schedule_date_field",
                "schedule_offset_direction",
                "schedule_offset_amount",
                "schedule_offset_unit",
                "schedule_run_time",
                "delivery_channel",
                "mail_template",
                "notification_template",
                "mail_server",
            ]

            for name in preserved_fields:
                if name in self.request.GET:
                    values = self.request.GET.getlist(name)
                    initial[name] = values if len(values) > 1 else values[0]
        return initial

    def get_form_kwargs(self):
        """Pass form_url and HTMX target so trigger dropdown can reload form to show/hide schedule fields."""
        kwargs = super().get_form_kwargs()
        form_url = self.get_form_url()
        if hasattr(form_url, "url"):
            form_url = form_url.url
        kwargs["form_url"] = self.request.build_absolute_uri(form_url)
        view_id = (
            getattr(self, "view_id", None) or f"{self.model._meta.model_name}-form-view"
        )
        kwargs["htmx_trigger_target"] = f"#{view_id}-container"
        return kwargs

    def get_context_data(self, **kwargs):
        """Add form errors to delivery_channel hx-vals so get-template-fields returns them on load."""
        context = super().get_context_data(**kwargs)
        form = context.get("form")
        if (
            form
            and self.request.method == "POST"
            and not form.is_valid()
            and "delivery_channel" in form.fields
        ):
            mail_errors = form.errors.get("mail_template")
            notif_errors = form.errors.get("notification_template")
            mail_server_errors = form.errors.get("mail_server")
            if mail_errors or notif_errors or mail_server_errors:
                vals = {"automation_id": ""}
                if form.instance and form.instance.pk:
                    vals["automation_id"] = str(form.instance.pk)
                if mail_errors:
                    vals["mail_template_errors"] = list(mail_errors)
                if notif_errors:
                    vals["notification_template_errors"] = list(notif_errors)
                if mail_server_errors:
                    vals["mail_server_errors"] = list(mail_server_errors)
                form.fields["delivery_channel"].widget.attrs["hx-vals"] = json.dumps(
                    vals
                )
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "automations.add_horillaautomation",
            "automations.change_horillaautomation",
        ]
    ),
    name="dispatch",
)
class AutomationFieldChoicesView(LoginRequiredMixin, View):
    """
    Class-based view to return field choices for a selected model via HTMX.
    """

    def get_extra_field_choices(self, model):
        """
        Extra ``(value, label)`` field choices that aren't model columns.
        Extensions override this.
        """
        return []

    def get(self, request, *args, **kwargs):
        """
        Handle GET request to return a <select> element with field choices.
        """
        model_id = request.GET.get("model")
        row_id = request.GET.get("row_id", "0")
        if not row_id.isdigit():
            row_id = "0"

        field_name = f"field_{row_id}"
        field_id = f"id_field_{row_id}"

        if model_id and model_id.isdigit():
            try:
                content_type = HorillaContentType.objects.get(pk=model_id)
                model_name = content_type.model
            except HorillaContentType.DoesNotExist:
                model_name = None
        else:
            model_name = None

        if not model_name:
            return render(
                request,
                "partials/field_select_empty.html",
                {"field_name": field_name, "field_id": field_id},
            )

        try:
            model = None
            for app_config in apps.get_app_configs():
                try:
                    model = apps.get_model(
                        app_label=app_config.label, model_name=model_name.lower()
                    )
                    break
                except LookupError:
                    continue
            if not model:
                return render(
                    request,
                    "partials/field_select_empty.html",
                    {"field_name": field_name, "field_id": field_id},
                )
        except Exception:
            return render(
                request,
                "partials/field_select_empty.html",
                {"field_name": field_name, "field_id": field_id},
            )

        field_choices = get_model_field_choices(None, model_name)
        field_choices.extend(self.get_extra_field_choices(model))

        condition_model_str = (
            f"{AutomationCondition._meta.app_label}."
            f"{AutomationCondition._meta.model_name}"
        )
        hx_vals_json = json.dumps(
            {
                "model_name": model_name,
                "row_id": row_id,
                "condition_model": condition_model_str,
            }
        )

        return render(
            request,
            "partials/automation_field_select_response.html",
            {
                "field_name": field_name,
                "field_id": field_id,
                "row_id": row_id,
                "hx_get_url": reverse_lazy("generics:get_field_value_widget"),
                "hx_vals_json": hx_vals_json,
                "field_choices": field_choices,
            },
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "automations.view_horillaautomation",
            "automations.add_horillaautomation",
        ],
    ),
    name="dispatch",
)
class MailToChoicesView(LoginRequiredMixin, View):
    """
    Class-based view to return the delivery channel's recipient choices for the mail_to field via HTMX.
    """

    def get(self, request, *args, **kwargs):
        """
        Handle GET request to return a <select multiple> element with the recipient
        choices of the delivery channels given (mail by default). A multi-select
        sends delivery_channel once per selected key, hence getlist().
        """
        model_id = request.GET.get("model")
        model = None
        if model_id and model_id.isdigit():
            content_type = HorillaContentType.objects.filter(pk=model_id).first()
            model = get_model_class(content_type.model) if content_type else None
        user_fields = get_recipient_choices(
            request.GET.getlist("delivery_channel"), model
        )

        # Get current selected values if editing
        selected_values = []
        automation_id = request.GET.get("automation_id")
        if automation_id:
            try:
                automation = HorillaAutomation.objects.get(pk=automation_id)
                if automation.mail_to:
                    selected_values = [
                        v.strip() for v in automation.mail_to.split(",") if v.strip()
                    ]
            except HorillaAutomation.DoesNotExist:
                pass

        return render(
            request,
            "partials/mail_to_select_response.html",
            {
                "user_fields": user_fields,
                "selected_values": selected_values,
                "include_select2_script": model is None,
            },
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("automations.delete_horillaautomation", modal=True),
    name="dispatch",
)
class HorillaAutomationDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete view for HorillaAutomation
    """

    model = HorillaAutomation

    def get_post_delete_response(self):
        """Return response after successful deletion"""
        return ScriptResponse(reload=True)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "automations.view_horillaautomation",
            "automations.add_horillaautomation",
        ],
    ),
    name="dispatch",
)
class TemplateFieldsView(LoginRequiredMixin, View):
    """
    HTMX view to return template fields based on the selected delivery channels.

    A block shows when any selected channel asks for it: mail template and
    mail server (``shows_mail_fields()``), notification template
    (``shows_notification_fields()``). Mail and notification together show
    both blocks; an unregistered key adds none. The recipient picker
    (mail_to) is refreshed with the union of the channels' recipient choices.
    """

    def get(self, request, *args, **kwargs):
        """
        Handle GET request to return template field HTML based on delivery_channel
        """
        # A multi-select sends delivery_channel once per selected key; a
        # hidden field sends the stored comma-separated value. No parameter
        # means nothing is selected (the user cleared the picker): no
        # channel-specific fields.
        delivery_channels = split_delivery_channels(
            ",".join(request.GET.getlist("delivery_channel"))
        )
        automation_id = request.GET.get("automation_id")
        model_id = request.GET.get("model")

        # Pass through form errors when load is triggered after failed submit (so OOB swap keeps them)
        mail_template_errors = []
        notification_template_errors = []
        mail_server_errors = []
        raw_mail = request.GET.get("mail_template_errors")
        raw_notif = request.GET.get("notification_template_errors")
        raw_mail_server = request.GET.get("mail_server_errors")
        if raw_mail is not None:
            if isinstance(raw_mail, str) and raw_mail.startswith("["):
                try:
                    mail_template_errors = json.loads(raw_mail)
                except (ValueError, TypeError):
                    mail_template_errors = [raw_mail]
            else:
                mail_template_errors = request.GET.getlist("mail_template_errors") or [
                    raw_mail
                ]
        if raw_notif is not None:
            if isinstance(raw_notif, str) and raw_notif.startswith("["):
                try:
                    notification_template_errors = json.loads(raw_notif)
                except (ValueError, TypeError):
                    notification_template_errors = [raw_notif]
            else:
                notification_template_errors = request.GET.getlist(
                    "notification_template_errors"
                ) or [raw_notif]
        if raw_mail_server is not None:
            if isinstance(raw_mail_server, str) and raw_mail_server.startswith("["):
                try:
                    mail_server_errors = json.loads(raw_mail_server)
                except (ValueError, TypeError):
                    mail_server_errors = [raw_mail_server]
            else:
                mail_server_errors = request.GET.getlist("mail_server_errors") or [
                    raw_mail_server
                ]

        # Get content_type from model_id if provided
        content_type = None
        if model_id:
            try:
                content_type = HorillaContentType.objects.get(pk=model_id)
            except (HorillaContentType.DoesNotExist, ValueError):
                pass

        # Get current values if editing
        mail_template_id = None
        notification_template_id = None
        mail_server_id = None
        saved_mail_to = ""
        if automation_id:
            try:
                automation = HorillaAutomation.objects.get(pk=automation_id)
                saved_mail_to = automation.mail_to
                if automation.mail_template:
                    mail_template_id = automation.mail_template.pk
                if automation.notification_template:
                    notification_template_id = automation.notification_template.pk
                if automation.mail_server:
                    mail_server_id = automation.mail_server.pk
                # Get content_type from automation if not in request
                if not content_type and automation.model:
                    content_type = automation.model
            except HorillaAutomation.DoesNotExist:
                pass

        company = request.active_company

        if not company:
            company = request.user.company

        channels = [
            channel
            for channel in (get_delivery_channel(key) for key in delivery_channels)
            if channel is not None
        ]
        show_mail = any(channel.shows_mail_fields() for channel in channels)
        show_notification = any(
            channel.shows_notification_fields() for channel in channels
        )

        # Recipient picker: keep what is selected in the form, else the saved value.
        if "mail_to" in request.GET:
            mail_to_selected = [v for v in request.GET.getlist("mail_to") if v]
        else:
            mail_to_selected = [
                v.strip() for v in (saved_mail_to or "").split(",") if v.strip()
            ]
        mail_to_choices = get_recipient_choices(
            delivery_channels,
            get_model_class(content_type.model) if content_type else None,
        )

        mail_templates_qs = HorillaMailTemplate.objects.none()
        if show_mail:
            mail_templates_qs = HorillaMailTemplate.objects.all()
            if company:
                mail_templates_qs = mail_templates_qs.filter(company=company)
            if content_type:
                mail_templates_qs = mail_templates_qs.filter(
                    Q(content_type=content_type) | Q(content_type__isnull=True)
                )

        notification_templates_qs = NotificationTemplate.objects.none()
        if show_notification:
            notification_templates_qs = NotificationTemplate.objects.all()
            if company:
                notification_templates_qs = notification_templates_qs.filter(
                    company=company
                )
            if content_type:
                notification_templates_qs = notification_templates_qs.filter(
                    Q(content_type=content_type) | Q(content_type__isnull=True)
                )

        mail_servers_qs = HorillaMailConfiguration.objects.none()
        if show_mail:
            mail_servers_qs = HorillaMailConfiguration.objects.filter(
                mail_channel="outgoing"
            )
            if company:
                mail_servers_qs = mail_servers_qs.filter(company=company)

        # Use model field verbose_name for labels (consistent with form and i18n)
        mail_template_label = HorillaAutomation._meta.get_field(
            "mail_template"
        ).verbose_name
        notification_template_label = HorillaAutomation._meta.get_field(
            "notification_template"
        ).verbose_name
        mail_server_label = HorillaAutomation._meta.get_field(
            "mail_server"
        ).verbose_name

        return render(
            request,
            "partials/template_fields_response.html",
            {
                "show_mail_template": show_mail,
                "show_notification_template": show_notification,
                "show_mail_server": show_mail,
                "mail_templates": mail_templates_qs,
                "notification_templates": notification_templates_qs,
                "mail_servers": mail_servers_qs,
                "model_id": model_id if model_id and model_id.isdigit() else "",
                "mail_template_id": mail_template_id,
                "notification_template_id": notification_template_id,
                "mail_server_id": mail_server_id,
                "mail_template_label": mail_template_label,
                "notification_template_label": notification_template_label,
                "mail_server_label": mail_server_label,
                "mail_template_errors": mail_template_errors,
                "notification_template_errors": notification_template_errors,
                "mail_server_errors": mail_server_errors,
                "mail_to_choices": mail_to_choices,
                "mail_to_selected": mail_to_selected,
            },
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["automations.view_horillaautomation"]),
    name="dispatch",
)
class HorillaAutomationDetailView(LoginRequiredMixin, HorillaModalDetailView):
    """
    Modal detail view for a single automation.
    """

    model = HorillaAutomation
    _BASE_FIELDS = [
        "model",
        "trigger",
        "get_delivery_channel_display",
        "get_mail_to_display",
        "get_also_sent_to",
    ]
    _SCHEDULE_FIELDS = [
        "schedule_date_field",
        "schedule_offset_direction",
        "schedule_offset_amount",
        "schedule_offset_unit",
        "schedule_run_time",
    ]
    body = []

    def get_queryset(self):
        """Skip Big Deal Alert automations, which have their own detail view."""
        return super().get_queryset().exclude(additional_info__big_deal=True)

    def get_context_data(self, **kwargs):
        """Use the automation's own title as the modal heading."""
        context = super().get_context_data(**kwargs)
        if self.instance:
            context["title"] = self.instance.title
        return context

    def get_body_fields(self):
        """Show template/server fields per delivery channel, schedule fields only when scheduled."""
        fields = list(self._BASE_FIELDS)
        automation = self.instance
        if automation:
            channels = [
                channel
                for channel in (
                    get_delivery_channel(key)
                    for key in automation.get_delivery_channels()
                )
                if channel is not None
            ]
            for channel in channels:
                for name in channel.get_detail_fields():
                    if name not in fields:
                        fields.append(name)
            if automation.trigger == "scheduled":
                fields += self._SCHEDULE_FIELDS
        self.body = fields
        return super().get_body_fields()

    actions = [
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "svg-themed w-3 h-3",
            "permission": "automations.delete_horillaautomation",
            "attrs": """
                class="outline outline-1 outline-offset-[-1px] outline-primary-600 rounded-md hover:bg-primary-300 transition duration-300 text-primary-600 w-24 justify-center bg-[white] flex items-center gap-2 disabled:cursor-not-allowed cursor-pointer text-xs px-4 py-2"
                hx-get="{get_delete_url}"
                hx-target="#deleteModeBox"
                hx-vals='{{"check_dependencies": "false"}}'
                hx-trigger="click"
                onclick="openDeleteModeModal()"
            """,
        },
        {
            "action": "Edit",
            "src": "assets/icons/edit_white.svg",
            "img_class": "w-3 h-3 flex gap-4 filter brightness-0 invert",
            "permission": "automations.change_horillaautomation",
            "attrs": """
                class="w-24 justify-center px-4 py-2 bg-primary-600 text-white rounded-md text-xs flex items-center gap-2 hover:bg-primary-800 transition duration-300 disabled:cursor-not-allowed cursor-pointer"
                hx-get="{get_edit_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal();"
            """,
        },
    ]
