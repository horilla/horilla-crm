"""
mail outgoing mail views
"""

# Standard library imports
import re
from functools import cached_property

# Third-party imports (Django)
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla.contrib.utils.middlewares import _thread_local
from horilla.shortcuts import get_object_or_404
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.html import strip_tags
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import FormView, TemplateView
from horilla.web import HttpResponse, ScriptResponse

from ..backends import HorillaDefaultMailBackend

# Local imports
from ..filters import HorillaMailServerFilter
from ..forms import DynamicMailTestForm, HorillaMailConfigurationForm
from ..models import HorillaMailConfiguration


@method_decorator(
    permission_required_or_denied(
        ["mail.view_horillamailconfiguration"], wrapper_id="mail-server-view"
    ),
    name="dispatch",
)
class MailServerView(LoginRequiredMixin, HorillaView):
    """
    TemplateView for mail server page.
    """

    template_name = "settings/settings_list_shell.html"
    view_id = "mail-server-view"
    nav_url = reverse_lazy("mail:mail_server_navbar_view")
    list_url = reverse_lazy("mail:mail_server_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["mail.view_horillamailconfiguration"]),
    name="dispatch",
)
class MailServerNavbar(LoginRequiredMixin, HorillaNavView):
    """
    navbar view for mail server
    """

    nav_title = _("Outgoing Mail Configurations")
    nav_description = _("Configure the SMTP server used to send outgoing emails.")
    search_url = reverse_lazy("mail:mail_server_list_view")
    filterset_class = HorillaMailServerFilter
    main_url = reverse_lazy("mail:mail_server_view")
    nav_width = False
    all_view_types = False
    one_view_only = True
    filter_option = False
    reload_option = False
    border_enabled = False

    @cached_property
    def new_button(self):
        """Return new button configuration if user has permission"""
        if self.request.user.has_perm("mail.create_horillaemailconfiguration"):
            return {
                "url": f"""{reverse_lazy("mail:mail_server_type_selection")}?new=true""",
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
class MailServerTypeSelectionView(LoginRequiredMixin, TemplateView):
    """
    View to show mail server type selection options
    """

    template_name = "mail_server_type_selection.html"


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["mail.view_horillamailconfiguration"]),
    name="dispatch",
)
class MailServerListView(LoginRequiredMixin, HorillaListView):
    """
    List view of mail server
    """

    model = HorillaMailConfiguration
    view_id = "mail-server-list"
    search_url = reverse_lazy("mail:mail_server_list_view")
    main_url = reverse_lazy("mail:mail_server_view")
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
                "url": f"""{reverse_lazy("mail:mail_server_type_selection")}?new=true""",
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
        return queryset.filter(mail_channel="outgoing")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["mail.add_horillamailconfiguration"]),
    name="dispatch",
)
class OutgoingMailServerFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    create and update from view for mail server
    """

    model = HorillaMailConfiguration
    form_class = HorillaMailConfigurationForm
    form_title = _("Outgoing Mail Server Configuration")
    modal_height = False
    hidden_fields = ["company", "type", "mail_channel"]
    save_and_new = False

    def get_initial(self):
        """Set initial form data for outgoing mail configuration (company and channel)."""
        initial = super().get_initial()
        pk = self.kwargs.get("pk")
        company = getattr(self.request, "active_company", None)
        if not pk:
            initial["company"] = company
            initial["type"] = "mail"
            initial["mail_channel"] = "outgoing"
        return initial

    @cached_property
    def form_url(self):
        """url for form submission"""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("mail:mail_server_update_view", kwargs={"pk": pk})
        return reverse_lazy("mail:mail_server_form_view")

    def form_valid(self, form):
        super().form_valid(form)
        return ScriptResponse(reload=True, close=True, extra="closehorillaModal();")


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
class MailServerTestEmailView(LoginRequiredMixin, FormView):
    """
    View to send test email from mail server configuration"""

    template_name = "form_email_test.html"
    form_class = DynamicMailTestForm

    def get_object_or_error_response(self, request):
        """
        Return an error response (message, reload and close) when the mail
        server was deleted, otherwise None.
        """
        try:
            get_object_or_404(
                HorillaMailConfiguration, pk=request.GET.get("instance_id")
            )
        except Exception as e:
            messages.error(request, str(e))
            return ScriptResponse(reload=True, close=True)
        return None

    def get(self, request, *args, **kwargs):
        """Open the test mail form only if the mail server still exists"""
        return self.get_object_or_error_response(request) or super().get(
            request, *args, **kwargs
        )

    def post(self, request, *args, **kwargs):
        """Send the test mail only if the mail server still exists"""
        return self.get_object_or_error_response(request) or super().post(
            request, *args, **kwargs
        )

    def get_html_content(self, company):
        """Generate HTML email content from template"""
        user = self.request.user.get_full_name()
        button_url = f"{self.request.scheme}://{self.request.get_host()}"

        context = {
            "user": user,
            "company": company,
            "button_url": button_url,
        }

        html_content = render_to_string("mail_server_success.html", context)
        return html_content

    def get_email_backend(self):
        """Get configured email backend with specific instance"""
        instance_id = self.request.GET.get("instance_id")
        setattr(_thread_local, "from_mail_id", instance_id)
        email_backend = HorillaDefaultMailBackend()

        if getattr(_thread_local, "invalid_config", False):
            try:
                delattr(_thread_local, "invalid_config")
            except Exception:
                pass
            return ScriptResponse(reload=True, close=True)

        return email_backend

    def send_test_email(self, form):
        """Send the test email with inline images"""
        email_to = form.cleaned_data["to_email"]
        company = self.request.active_company
        subject = f"Test mail from {company}"

        html_content = self.get_html_content(company)
        text_content = strip_tags(html_content)

        email_backend = self.get_email_backend()
        if isinstance(email_backend, HttpResponse):
            return None, email_backend

        try:
            msg = EmailMultiAlternatives(
                subject,
                text_content,
                email_backend.dynamic_from_email_with_display_name,
                [email_to],
                connection=email_backend,
            )
            msg.attach_alternative(html_content, "text/html")
            sent_count = msg.send()
            if not sent_count:
                return False, str(_("Mail server did not send the message."))
            return True, None

        except Exception as e:
            return False, str(e)

    def parse_error_message(self, error_str):
        """Extract human-readable part from error messages"""
        error_str = str(error_str)

        # Pattern 1: Handle tuple errors like (535, b'5.7.8 Username and Password not accepted...')
        tuple_pattern = r'\(\d+,\s*b?[\'"]([^\'"]*).*?\'\)'
        tuple_match = re.search(tuple_pattern, error_str)
        if tuple_match:
            message = tuple_match.group(1)
            message = re.sub(r"^\d+\.\d+\.\d+\s+", "", message)
            message = re.sub(r"\\n", " ", message)
            message = re.sub(r"\s+", " ", message).strip()
            message = re.split(r"(?i)(for more information|learn more|go to)", message)[
                0
            ].strip()
            return message

        # Pattern 2: Handle [Errno X] messages
        errno_pattern = r"\[Errno -?\d+\]\s*(.+?)(?:\s*\((?!.*\))|$)"
        errno_match = re.search(errno_pattern, error_str)
        if errno_match:
            message = errno_match.group(1).strip()
            # Clean up any trailing punctuation or extra info
            message = re.sub(r"\s*[\(\[].*$", "", message).strip()
            return message

        # Pattern 3: Handle OSError and similar exceptions
        os_error_pattern = (
            r"(?:OSError|ConnectionError|TimeoutError):\s*(.+?)(?:\s*\(|$)"
        )
        os_error_match = re.search(os_error_pattern, error_str)
        if os_error_match:
            return os_error_match.group(1).strip()

        # Pattern 4: Handle authentication errors
        auth_patterns = [
            r"(?i)(authentication\s+failed?)",
            r"(?i)(invalid\s+credentials?)",
            r"(?i)(username\s+and\s+password\s+not\s+accepted)",
            r"(?i)(access\s+denied)",
            r"(?i)(login\s+failed?)",
        ]
        for pattern in auth_patterns:
            auth_match = re.search(pattern, error_str)
            if auth_match:
                return auth_match.group(1)

        # Pattern 5: Handle connection errors
        connection_patterns = [
            r"(?i)(connection\s+refused)",
            r"(?i)(network\s+is\s+unreachable)",
            r"(?i)(timeout\s+error)",
            r"(?i)(host\s+not\s+found)",
            r"(?i)(dns\s+resolution\s+failed)",
        ]
        for pattern in connection_patterns:
            conn_match = re.search(pattern, error_str)
            if conn_match:
                return conn_match.group(1)

        cleaned = re.sub(r"^(Exception|Error):\s*", "", error_str, flags=re.IGNORECASE)
        sentences = re.split(r"[.!?]\s+", cleaned)
        if sentences:
            first_sentence = sentences[0].strip()
            if len(first_sentence) > 100:
                first_sentence = first_sentence[:97] + "..."
            return (
                first_sentence if first_sentence else str(_("Unknown error occurred"))
            )

        return str(_("Unknown error occurred"))

    def form_valid(self, form):
        """Handle valid form submission"""
        success, error = self.send_test_email(form)

        if success is None and isinstance(error, HttpResponse):
            return error

        if success:
            messages.success(self.request, _("Mail sent successfully"))
        else:
            parsed_error = self.parse_error_message(error)
            messages.error(self.request, f"{_('Something went wrong:')} {parsed_error}")

        return ScriptResponse(close=True, reload=True)

    def get_context_data(self, **kwargs):
        """Add instance_id to context"""
        context = super().get_context_data(**kwargs)
        context["instance_id"] = self.request.GET.get("instance_id")
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("mail.delete_horillamailconfiguration", modal=True),
    name="dispatch",
)
class MailServerDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete view for mail server configuration
    """

    model = HorillaMailConfiguration

    def get_post_delete_response(self):
        return ScriptResponse(reload=True)
