"""
WhatsApp account settings views.
"""

# Standard library imports
from functools import cached_property

# Third-party imports (Django)
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, render
from django.views import View

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
from horilla.web import HttpResponse, RedirectResponse, ScriptResponse

# Local imports
from ..filters import WhatsAppAccountFilter
from ..forms import WhatsAppAccountForm
from ..models import WhatsAppAccount, normalize_whatsapp_number
from ..services import WhatsAppAPIError, WhatsAppCloudAPIClient


@method_decorator(
    permission_required_or_denied(["whatsapp.view_whatsappaccount"]),
    name="dispatch",
)
class WhatsAppAccountView(LoginRequiredMixin, HorillaView):
    """
    Page shell for WhatsApp account settings.
    """

    template_name = "whatsapp_account/whatsapp_account_view.html"
    nav_url = reverse_lazy("whatsapp:whatsapp_account_navbar_view")
    list_url = reverse_lazy("whatsapp:whatsapp_account_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["whatsapp.view_whatsappaccount"]),
    name="dispatch",
)
class WhatsAppAccountNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar for WhatsApp account settings.
    """

    nav_title = _("WhatsApp Accounts")
    search_url = reverse_lazy("whatsapp:whatsapp_account_list_view")
    filterset_class = WhatsAppAccountFilter
    main_url = reverse_lazy("whatsapp:whatsapp_account_view")
    model_name = "WhatsAppAccount"
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
        if self.request.user.has_perm("whatsapp.add_whatsappaccount"):
            return {
                "url": f"""{reverse_lazy("whatsapp:whatsapp_account_create_view")}""",
                "target": "#modalBox",
                "onclick": "openModal();",
                "attrs": {"id": "whatsapp-account-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["whatsapp.view_whatsappaccount"]),
    name="dispatch",
)
class WhatsAppAccountListView(LoginRequiredMixin, HorillaListView):
    """
    List view of connected WhatsApp accounts.
    """

    model = WhatsAppAccount
    view_id = "whatsapp-account-list"
    search_url = reverse_lazy("whatsapp:whatsapp_account_list_view")
    main_url = reverse_lazy("whatsapp:whatsapp_account_view")
    table_width = False
    table_height_as_class = "h-[calc(_100vh_-_260px_)]"
    list_column_visibility = False
    filterset_class = WhatsAppAccountFilter

    columns = [
        "display_name",
        "display_phone_number",
        "is_primary",
        "bot_enabled",
        "is_active",
    ]

    actions = [
        {
            "action": "Test Connection",
            "src": "whatsapp/assets/icons/test_connection.svg",
            "img_class": "w-4 h-4",
            "permission": "whatsapp.view_whatsappaccount",
            "attrs": """
                hx-get="{get_test_connection_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal()"
            """,
        },
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "whatsapp.change_whatsappaccount",
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
            "permission": "whatsapp.delete_whatsappaccount",
            "attrs": """
                hx-post="{get_delete_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                hx-trigger="click"
                hx-vals='{{"check_dependencies": "true"}}'
                onclick="openModal()"
            """,
        },
    ]

    def no_record_add_button(self):
        """Return the add button configuration when there are no records."""
        if self.request.user.has_perm("whatsapp.add_whatsappaccount"):
            return {
                "url": f"""{reverse_lazy("whatsapp:whatsapp_account_create_view")}""",
                "target": "#modalBox",
                "onclick": "openModal();",
                "attrs": {"id": "whatsapp-account-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
class WhatsAppAccountFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Create and update form view for a WhatsApp account.
    """

    model = WhatsAppAccount
    form_class = WhatsAppAccountForm
    form_title = _("WhatsApp Account")
    hidden_fields = ["is_active", "is_primary"]
    modal_height = False

    @property
    def return_response(self):
        """After adding an account, refresh the list and open its connection test."""
        account = getattr(self, "object", None)
        if account is None or not account.pk or self.kwargs.get("pk"):
            return None
        url = reverse_lazy(
            "whatsapp:whatsapp_account_test_connection_view", kwargs={"pk": account.pk}
        )
        return HttpResponse(
            "<script>$('#reloadButton').click();"
            f"htmx.ajax('GET', '{url}', {{target: '#modalBox', swap: 'innerHTML'}});</script>"
        )

    @cached_property
    def form_url(self):
        """Return the create or update URL for the account form."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "whatsapp:whatsapp_account_update_view", kwargs={"pk": pk}
            )
        return reverse_lazy("whatsapp:whatsapp_account_create_view")

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
    permission_required_or_denied("whatsapp.delete_whatsappaccount", modal=True),
    name="dispatch",
)
class WhatsAppAccountDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete view for a WhatsApp account.
    """

    model = WhatsAppAccount

    def get_post_delete_response(self):
        """Return HTMX script to reload the list after successful delete."""
        return HttpResponse("<script>$('#reloadButton').click();</script>")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("whatsapp.view_whatsappaccount", modal=True),
    name="dispatch",
)
class WhatsAppAccountTestConnectionView(LoginRequiredMixin, View):
    """
    Test an account's connection to Meta in a modal, like the mail server test.
    GET runs the live checks. When nothing has failed, the modal also offers to
    send a test message (Meta's approved `hello_world` template) to a number.
    """

    template_name = "whatsapp_account/connection_test.html"
    TEST_TEMPLATE = "hello_world"
    TEST_LANGUAGE = "en_US"

    @staticmethod
    def test_text(account, request):
        """Fixed test message, signed with the company's own name."""
        company = (
            account.company
            or getattr(request, "active_company", None)
            or getattr(request.user, "company", None)
        )
        name = str(company) if company else str(_("your CRM"))
        return str(
            _("Test message from %(company)s. Your WhatsApp connection is working.")
            % {"company": name}
        )

    def get(self, request, pk):
        account = get_object_or_404(WhatsAppAccount, pk=pk)
        checks = WhatsAppCloudAPIClient(account).test_connection()
        statuses = {check["status"] for check in checks}
        overall = (
            "fail" if "fail" in statuses else "warn" if "warn" in statuses else "ok"
        )
        return render(
            request,
            self.template_name,
            {
                "account": account,
                "checks": checks,
                "overall": overall,
                "can_send": bool(checks) and checks[0]["status"] != "fail",
            },
        )

    def post(self, request, pk):
        """
        Send the fixed test message. Success: toast + close the modal. Failure:
        error toast, modal stays open so the number can be corrected.
        """
        account = get_object_or_404(WhatsAppAccount, pk=pk)
        number = normalize_whatsapp_number(request.POST.get("to_number", ""))

        if not number or not 8 <= len(number) <= 15:
            messages.error(
                request,
                _("Enter the full number with country code, e.g. 919876543210."),
            )
            return ScriptResponse(msgs=True)

        client = WhatsAppCloudAPIClient(account)
        try:
            # A plain text message works when the number messaged us in the last
            # 24 hours; otherwise WhatsApp refuses it, so fall back to the
            # approved hello_world template, which can start a conversation.
            try:
                client.send_text(number, self.test_text(account, request))
            except WhatsAppAPIError as text_exc:
                try:
                    client.send_template(number, self.TEST_TEMPLATE, self.TEST_LANGUAGE)
                except WhatsAppAPIError as template_exc:
                    messages.error(
                        request,
                        _(
                            "Test message failed: %(error)s (the text message also failed: %(text_error)s)"
                        )
                        % {
                            "error": WhatsAppCloudAPIClient._error_text(template_exc),
                            "text_error": WhatsAppCloudAPIClient._error_text(text_exc),
                        },
                    )
                    return ScriptResponse(msgs=True)
        except WhatsAppAPIError as exc:  # pragma: no cover - defensive
            messages.error(request, WhatsAppCloudAPIClient._error_text(exc))
            return ScriptResponse(msgs=True)

        messages.success(
            request,
            _("Test message sent to +%(number)s. Check that it arrives on WhatsApp.")
            % {"number": number},
        )
        return ScriptResponse(close=True, msgs=True)
