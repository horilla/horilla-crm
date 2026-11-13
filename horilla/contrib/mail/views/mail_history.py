"""
Mail History Views
"""

# Standard library imports
from functools import cached_property

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import HorillaListView, HorillaNavView, HorillaView
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _

# Local imports
from ..filters import HorillaMailHistoryFilter
from ..models import HorillaMail


@method_decorator(
    permission_required_or_denied(
        ["mail.view_horillamail"], wrapper_id="mail-history-view"
    ),
    name="dispatch",
)
class MailHistoryView(LoginRequiredMixin, HorillaView):
    """
    Settings page for mail history.
    """

    template_name = "settings/settings_list_shell.html"
    view_id = "mail-history-view"
    nav_url = reverse_lazy("mail:mail_history_navbar_view")
    list_url = reverse_lazy("mail:mail_history_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["mail.view_horillamail"]),
    name="dispatch",
)
class MailHistoryNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar for mail history.
    """

    nav_title = _("Outbox")
    nav_description = _("Review the emails sent from the system.")
    search_url = reverse_lazy("mail:mail_history_list_view")
    filterset_class = HorillaMailHistoryFilter
    main_url = reverse_lazy("mail:mail_history_view")
    nav_width = False
    all_view_types = False
    one_view_only = True
    filter_option = False
    reload_option = False
    border_enabled = False
    new_button = None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["mail.view_horillamail"]),
    name="dispatch",
)
class MailHistoryListView(LoginRequiredMixin, HorillaListView):
    """
    List view of all sent mails.
    """

    model = HorillaMail
    view_id = "mail-history-list"
    search_url = reverse_lazy("mail:mail_history_list_view")
    main_url = reverse_lazy("mail:mail_history_view")
    filterset_class = HorillaMailHistoryFilter
    list_column_visibility = False
    bulk_export_option = False

    columns = [
        "to",
        "subject",
        "mail_status",
        "sender",
        "send_by",
        "sent_at",
    ]

    actions = [
        {
            "action": "Send Email",
            "src": "assets/icons/email_black.svg",
            "img_class": "w-4 h-4",
            "permission": "mail.add_horillamail",
            "hidden_if": lambda obj: obj.mail_status != "draft",
            "attrs": """
                hx-get="{get_edit_url}"
                hx-target="#horillaModalBox"
                hx-swap="innerHTML"
                onclick="openhorillaModal()"
            """,
        },
        {
            "action": "Cancel",
            "src": "assets/icons/cancel.svg",
            "img_class": "w-4 h-4",
            "permission": "mail.add_horillamail",
            "hidden_if": lambda obj: obj.mail_status != "scheduled",
            "attrs": """
                hx-get="{get_edit_url}?cancel=true"
                hx-target="#horillaModalBox"
                hx-swap="innerHTML"
                hx-trigger="click"
                onclick="openhorillaModal()"
            """,
        },
        {
            "action": "Snooze",
            "src": "assets/icons/clock.svg",
            "img_class": "w-4 h-4",
            "permission": "mail.add_horillamail",
            "hidden_if": lambda obj: obj.mail_status != "scheduled",
            "attrs": """
                hx-get="{get_reschedule_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                hx-trigger="click"
                onclick="openModal()"
            """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "mail.delete_horillamail",
            "attrs": """
                hx-post="{get_delete_url}?from=mail_history"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                hx-trigger="click"
                hx-vals='{{"check_dependencies": "false"}}'
                onclick="openModal()"
            """,
        },
    ]

    @cached_property
    def col_attrs(self):
        """Open snapshot on subject click for non-draft mails."""
        if self.request.user.has_perm("mail.view_horillamail"):
            return [
                {
                    "subject": {
                        "hx-get": "{get_view_url}",
                        "hx-target": "#contentModalBox",
                        "hx-swap": "innerHTML",
                        "hx-push-url": "false",
                        "hx-on:click": "openContentModal();",
                        "style": "cursor:pointer",
                        "class": "hover:text-primary-600",
                    }
                }
            ]
        return []

    def get_queryset(self):
        return super().get_queryset().order_by("-sent_at", "-created_at")
