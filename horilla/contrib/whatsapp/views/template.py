"""
WhatsApp message template views.
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
from ..filters import WhatsAppTemplateFilter
from ..forms import WhatsAppTemplateForm
from ..models import WhatsAppTemplate


@method_decorator(
    permission_required_or_denied(["whatsapp.view_whatsapptemplate"]),
    name="dispatch",
)
class WhatsAppTemplateView(LoginRequiredMixin, HorillaView):
    """
    Page shell for WhatsApp template management.
    """

    template_name = "whatsapp_template/whatsapp_template_view.html"
    nav_url = reverse_lazy("whatsapp:whatsapp_template_navbar_view")
    list_url = reverse_lazy("whatsapp:whatsapp_template_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["whatsapp.view_whatsapptemplate"]),
    name="dispatch",
)
class WhatsAppTemplateNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar for WhatsApp template management.
    """

    nav_title = _("WhatsApp Templates")
    search_url = reverse_lazy("whatsapp:whatsapp_template_list_view")
    filterset_class = WhatsAppTemplateFilter
    main_url = reverse_lazy("whatsapp:whatsapp_template_view")
    model_name = "WhatsAppTemplate"
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
        if self.request.user.has_perm("whatsapp.add_whatsapptemplate"):
            return {
                "url": f"""{reverse_lazy("whatsapp:whatsapp_template_create_view")}""",
                "target": "#modalBox",
                "onclick": "openModal();",
                "attrs": {"id": "whatsapp-template-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["whatsapp.view_whatsapptemplate"]),
    name="dispatch",
)
class WhatsAppTemplateListView(LoginRequiredMixin, HorillaListView):
    """
    List view of WhatsApp message templates.
    """

    model = WhatsAppTemplate
    view_id = "whatsapp-template-list"
    search_url = reverse_lazy("whatsapp:whatsapp_template_list_view")
    main_url = reverse_lazy("whatsapp:whatsapp_template_view")
    table_width = False
    table_height_as_class = "h-[calc(_100vh_-_260px_)]"
    list_column_visibility = False
    filterset_class = WhatsAppTemplateFilter

    columns = [
        "title",
        "name",
        "language",
        "category",
        (_("Related Model"), "get_related_model"),
    ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "whatsapp.change_whatsapptemplate",
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
            "permission": "whatsapp.delete_whatsapptemplate",
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
        if self.request.user.has_perm("whatsapp.add_whatsapptemplate"):
            return {
                "url": f"""{reverse_lazy("whatsapp:whatsapp_template_create_view")}""",
                "target": "#modalBox",
                "onclick": "openModal();",
                "attrs": {"id": "whatsapp-template-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
class WhatsAppTemplateFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Create and update form view for a WhatsApp template.
    """

    model = WhatsAppTemplate
    form_class = WhatsAppTemplateForm
    form_title = _("WhatsApp Template")
    hidden_fields = ["is_active", "sample_body", "components"]
    modal_height = False

    @cached_property
    def form_url(self):
        """Return the create or update URL for the template form."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "whatsapp:whatsapp_template_update_view", kwargs={"pk": pk}
            )
        return reverse_lazy("whatsapp:whatsapp_template_create_view")

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
    permission_required_or_denied("whatsapp.delete_whatsapptemplate", modal=True),
    name="dispatch",
)
class WhatsAppTemplateDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete view for a WhatsApp template.
    """

    model = WhatsAppTemplate

    def get_post_delete_response(self):
        """Return HTMX script to reload the list after successful delete."""
        return HttpResponse("<script>$('#reloadButton').click();</script>")
