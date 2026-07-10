"""
WhatsApp Flow views.
"""

# Standard library imports
from functools import cached_property

# Third-party imports (Django)
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin

from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)

# First party imports (Horilla)
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.web import HttpResponse

# Local imports
from ..filters import WhatsAppFlowFilter
from ..forms import WhatsAppFlowForm
from ..models import WhatsAppFlow


@method_decorator(
    permission_required_or_denied(["whatsapp.view_whatsappflow"]),
    name="dispatch",
)
class WhatsAppFlowView(LoginRequiredMixin, HorillaView):
    """
    Page shell for WhatsApp Flow management.
    """

    template_name = "whatsapp_flow/whatsapp_flow_view.html"
    nav_url = reverse_lazy("whatsapp:whatsapp_flow_navbar_view")
    list_url = reverse_lazy("whatsapp:whatsapp_flow_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["whatsapp.view_whatsappflow"]),
    name="dispatch",
)
class WhatsAppFlowNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar for WhatsApp Flow management.
    """

    nav_title = _("WhatsApp Flows")
    search_url = reverse_lazy("whatsapp:whatsapp_flow_list_view")
    filterset_class = WhatsAppFlowFilter
    main_url = reverse_lazy("whatsapp:whatsapp_flow_view")
    model_name = "WhatsAppFlow"
    model_app_label = "whatsapp"
    nav_width = False
    gap_enabled = False
    all_view_types = False
    one_view_only = True
    filter_option = False
    reload_option = False
    border_enabled = False

    @cached_property
    def new_button(self):
        """Return the new button configuration if the user has permission."""
        if self.request.user.has_perm("whatsapp.add_whatsappflow"):
            return {
                "url": f"""{reverse_lazy("whatsapp:whatsapp_flow_create_view")}""",
                "target": "#modalBox",
                "onclick": "openModal();",
                "attrs": {"id": "whatsapp-flow-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["whatsapp.view_whatsappflow"]),
    name="dispatch",
)
class WhatsAppFlowListView(LoginRequiredMixin, HorillaListView):
    """
    List view of WhatsApp Flows.
    """

    model = WhatsAppFlow
    view_id = "whatsapp-flow-list"
    search_url = reverse_lazy("whatsapp:whatsapp_flow_list_view")
    main_url = reverse_lazy("whatsapp:whatsapp_flow_view")
    table_width = False
    table_height_as_class = "h-[calc(_100vh_-_260px_)]"
    list_column_visibility = False
    filterset_class = WhatsAppFlowFilter

    columns = [
        "title",
        "flow_name",
        "cta_text",
        "account",
        "is_active",
    ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "whatsapp.change_whatsappflow",
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
            "permission": "whatsapp.delete_whatsappflow",
            "attrs": """
                hx-post="{get_delete_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                hx-trigger="click"
                hx-vals='{{"check_dependencies": "false"}}'
                onclick="openModal()"
            """,
        },
    ]

    def no_record_add_button(self):
        """Return the add button configuration when there are no records."""
        if self.request.user.has_perm("whatsapp.add_whatsappflow"):
            return {
                "url": f"""{reverse_lazy("whatsapp:whatsapp_flow_create_view")}""",
                "target": "#modalBox",
                "onclick": "openModal();",
                "attrs": {"id": "whatsapp-flow-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
class WhatsAppFlowFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Create and update form view for a WhatsApp Flow.
    """

    model = WhatsAppFlow
    form_class = WhatsAppFlowForm
    form_title = _("WhatsApp Flow")
    modal_height = False

    @cached_property
    def form_url(self):
        """Return the create or update URL for the flow form."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("whatsapp:whatsapp_flow_update_view", kwargs={"pk": pk})
        return reverse_lazy("whatsapp:whatsapp_flow_create_view")

    def get(self, request, *args, **kwargs):
        pk = kwargs.get("pk")
        if pk:
            try:
                self.model.all_objects.get(pk=pk)
            except self.model.DoesNotExist:
                messages.error(request, _("The requested data does not exist."))
                return HttpResponse("<script>$('#reloadButton').click();</script>")
        return super().get(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("whatsapp.delete_whatsappflow", modal=True),
    name="dispatch",
)
class WhatsAppFlowDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete view for a WhatsApp Flow.
    """

    model = WhatsAppFlow

    def get_post_delete_response(self):
        """Return HTMX script to reload the list after successful delete."""
        return HttpResponse("<script>$('#reloadButton').click();</script>")
