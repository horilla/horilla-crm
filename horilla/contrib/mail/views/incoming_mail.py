"""
mail incoming mail views.
"""

# Standard library imports
from functools import cached_property

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView
from horilla.web import ScriptResponse

# Local imports
from ..filters import HorillaMailServerFilter
from ..forms import IncomingHorillaMailConfigurationForm
from ..models import HorillaMailConfiguration


@method_decorator(
    permission_required_or_denied(
        ["mail.view_horillamailconfiguration"], wrapper_id="mail-server-view"
    ),
    name="dispatch",
)
class IncomingMailServerView(LoginRequiredMixin, HorillaView):
    """
    TemplateView for mail server page.
    """

    template_name = "settings/settings_list_shell.html"
    view_id = "mail-server-view"
    nav_url = reverse_lazy("mail:incoming_mail_server_navbar_view")
    list_url = reverse_lazy("mail:incoming_mail_server_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["mail.view_horillamailconfiguration"]),
    name="dispatch",
)
class IncomingMailServerNavbar(LoginRequiredMixin, HorillaNavView):
    """
    navbar view for mail server
    """

    nav_title = _("Incoming Mail Configurations")
    nav_description = _("Configure the IMAP server used to receive incoming emails.")
    search_url = reverse_lazy("mail:incoming_mail_server_list_view")
    filterset_class = HorillaMailServerFilter
    main_url = reverse_lazy("mail:incoming_mail_server_view")
    nav_width = False
    all_view_types = False
    filter_option = False
    reload_option = False
    one_view_only = True
    border_enabled = False

    @cached_property
    def new_button(self):
        """New button configuration for the navbar."""
        if self.request.user.has_perm("mail.create_horillaemailconfiguration"):
            return {
                "url": f"""{reverse_lazy("mail:incoming_mail_server_type_selection")}?new=true""",
                "attrs": {"id": "mail-server-create"},
                "onclick": "openhorillaModal()",
                "target": "#horillaModalBox",
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["mail.view_horillamailconfiguration"]),
    name="dispatch",
)
class IncomingMailServerTypeSelectionView(LoginRequiredMixin, TemplateView):
    """
    View to show mail server type selection options
    """

    template_name = "incoming/incoming_mail_server_type_selection.html"


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["mail.view_horillamailconfiguration"]),
    name="dispatch",
)
class IncomingMailServerListView(LoginRequiredMixin, HorillaListView):
    """
    List view of mail server
    """

    model = HorillaMailConfiguration
    view_id = "mail-server-list"
    search_url = reverse_lazy("mail:incoming_mail_server_list_view")
    main_url = reverse_lazy("mail:incoming_mail_server_view")
    filterset_class = HorillaMailServerFilter
    bulk_update_two_column = True
    bulk_delete_enabled = False
    bulk_select_option = False
    list_column_visibility = False
    action_method = "custom_actions"
    store_ordered_ids = True

    @cached_property
    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        if self.request.user.has_perm("mail.create_horillaemailconfiguration"):
            return {
                "url": f"""{reverse_lazy("mail:incoming_mail_server_type_selection")}?new=true""",
                "attrs": 'id="mail-server-create"',
                "onclick": "openhorillaModal()",
                "target": "#horillaModalBox",
            }
        return None

    columns = ["username", "type"]

    @cached_property
    def col_attrs(self):
        """Open the detail modal when clicking the username column."""
        query_string = self.request.session.get(self.ordered_ids_key, [])
        attrs = {}
        if self.request.user.has_perm("mail.view_horillamailconfiguration"):
            attrs = {
                "hx-get": f"{{get_detail_url}}?instance_ids={query_string}",
                "hx-target": "#detailModalBox",
                "hx-swap": "innerHTML",
                "hx-push-url": "false",
                "hx-on:click": "openDetailModal();",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }
        return [{"username": {**attrs}}]

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(mail_channel="incoming")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "mail.view_horillamailconfiguration",
            "mail.add_horillamailconfiguration",
        ]
    ),
    name="dispatch",
)
class IncomingMailServerFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    create and update from view for mail server
    """

    model = HorillaMailConfiguration
    form_class = IncomingHorillaMailConfigurationForm
    modal_height = False
    hidden_fields = ["company", "type", "mail_channel"]
    save_and_new = False

    def get_initial(self):
        """Set initial form data for incoming mail configuration (IMAP defaults)."""
        initial = super().get_initial()
        pk = self.kwargs.get("pk")
        company = getattr(self.request, "active_company", None)
        if not pk:
            initial["company"] = company
            initial["type"] = "mail"
            initial["host"] = "imap.gmail.com"
            initial["port"] = 993
            initial["mail_channel"] = "incoming"
        return initial

    @cached_property
    def form_url(self):
        """Get the URL for the form view."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "mail:incoming_mail_server_update_view", kwargs={"pk": pk}
            )
        return reverse_lazy("mail:incoming_mail_server_form_view")

    def form_valid(self, form):
        super().form_valid(form)
        return ScriptResponse(reload=True, close=True, extra="closehorillaModal();")
