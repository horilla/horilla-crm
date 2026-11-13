"""
Mail Inbox Views.

Lists fetched IncomingMail rows and lets a user run whichever actions other
apps (e.g. leads, contacts) have registered against them via
horilla.contrib.mail.actions. This module never imports horilla_crm or any
other app's models directly - it only ever iterates whatever
get_incoming_mail_actions() returns.
"""

# Standard library imports
from functools import cached_property

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaView,
)
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import Http404, HxTriggerResponse, ScriptResponse

# Local imports
from ..actions import get_incoming_mail_action, get_incoming_mail_actions
from ..filters import IncomingMailFilter
from ..models import IncomingMail


def _is_converted(action, obj):
    """True if this exact action already ran against this exact row."""
    return action["key"] in obj.get_converted_actions()


def _is_action_blocked(action, obj, request, _cache=None):
    """True if this action is unavailable for obj (already converted on this
    row, or the registering app's already_exists_check says this sender
    already has a record from some other message).

    _cache, when passed, memoizes the (possibly DB-querying)
    already_exists_check result per (action key, obj pk) for the lifetime of
    one request - disabled_if is called once per action per row, so without
    memoizing, a page of N rows x M actions could run up to N x M duplicate
    queries.
    """
    if _is_converted(action, obj):
        return True
    check = action.get("already_exists_check")
    if not check:
        return False
    if _cache is None:
        return bool(check(obj, request))
    cache_key = (action["key"], obj.pk)
    if cache_key not in _cache:
        _cache[cache_key] = bool(check(obj, request))
    return _cache[cache_key]


def _build_inbox_actions(request):
    """
    Build the list of available incoming-mail actions (one per entry
    registered via horilla.contrib.mail.actions), shared by the list view's
    row actions and the preview modal's action buttons so both stay in sync.

    Per row: every registered action always shows, disabled (never hidden)
    once it's blocked - already converted on this row, or the registering
    app's already_exists_check says this sender already has a record from
    some other message - so the Actions cell always lists every action
    consistently and a disabled button's tooltip still says why.
    """
    all_actions = get_incoming_mail_actions()
    # Shared across every action/row rendered from this call, so a given
    # (action, row) already_exists_check only ever runs once per page render
    # instead of once per disabled_if call.
    blocked_cache = {}
    row_actions = []
    for action in all_actions:
        key = action["key"]
        # {pk} is substituted per-row by render_action_button's
        # _format_string (every model instance has a pk attribute).
        url = str(
            reverse_lazy("mail:inbox_run_action_view", kwargs={"pk": 0, "key": key})
        ).replace("/0/", "/{pk}/", 1)

        def disabled_if(obj, this_action=action):
            return _is_action_blocked(this_action, obj, request, blocked_cache)

        row_actions.append(
            {
                "action": action["label"],
                "src": action.get("icon") or "assets/icons/email_black.svg",
                "img_class": "w-4 h-4",
                "permission": action.get("permission"),
                "disabled_if": disabled_if,
                # Per-action noun (not the full "Add as X" label, which would
                # read "Already added as Add as Contact") so the tooltip says
                # specifically which conversion is unavailable, e.g. "Already
                # added as Contact" vs "Already added as Lead".
                # The noun ("Lead", "Contact") is looked up in the catalogs
                # too, or the tooltip would mix languages.
                "disabled_title": _("Already added as %(noun)s")
                % {"noun": _(key.capitalize())},
                "attrs": f"""
                    hx-get="{url}"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    hx-trigger="click"
                    onclick="openModal()"
                """,
            }
        )
    return row_actions


@method_decorator(
    permission_required_or_denied(["mail.view_incomingmail"], wrapper_id="inbox-view"),
    name="dispatch",
)
class InboxView(LoginRequiredMixin, HorillaView):
    """
    Settings page for the mail inbox.
    """

    template_name = "settings/settings_list_shell.html"
    view_id = "inbox-view"
    nav_url = reverse_lazy("mail:inbox_navbar_view")
    list_url = reverse_lazy("mail:inbox_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["mail.view_incomingmail"]),
    name="dispatch",
)
class InboxNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar for the mail inbox.
    """

    nav_title = _("Inbox")
    nav_description = _("Review emails fetched from your incoming mailboxes.")
    search_url = reverse_lazy("mail:inbox_list_view")
    filterset_class = IncomingMailFilter
    main_url = reverse_lazy("mail:inbox_view")
    nav_width = False
    all_view_types = False
    one_view_only = True
    filter_option = True
    reload_option = False
    border_enabled = False
    new_button = None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["mail.view_incomingmail"]),
    name="dispatch",
)
class InboxListView(LoginRequiredMixin, HorillaListView):
    """
    List view of fetched incoming mails.
    """

    model = IncomingMail
    view_id = "inbox-list"
    search_url = reverse_lazy("mail:inbox_list_view")
    main_url = reverse_lazy("mail:inbox_view")
    filterset_class = IncomingMailFilter
    list_column_visibility = False
    bulk_select_option = False

    columns = [
        "sender_name",
        "sender_email",
        "mail",
        "subject",
        "received_at",
    ]

    @cached_property
    def actions(self):
        """
        Row actions = the dynamically-registered CRM actions (e.g. "Add as
        Contact"/"Add as Lead" - this view never hardcodes any specific
        app's action, it only ever iterates whatever
        get_incoming_mail_actions() returns) plus a fixed "Delete" action,
        which is generic mail infrastructure, not a pluggable CRM action.
        """
        return _build_inbox_actions(self.request) + [
            {
                "action": _("Delete"),
                "src": "assets/icons/a4.svg",
                "img_class": "w-4 h-4",
                "permission": "mail.delete_incomingmail",
                "attrs": """
                    hx-post="{get_delete_url}?from=inbox"
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
        """Open the full email preview on subject click, like Outbox does."""
        if self.request.user.has_perm("mail.view_incomingmail"):
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
        return super().get_queryset().order_by("-received_at")


@method_decorator(htmx_required, name="dispatch")
class InboxRunActionView(LoginRequiredMixin, View):
    """
    Generic endpoint to run a single registered incoming-mail action against
    one IncomingMail row. GET renders a confirm step, POST runs the handler.

    This single view replaces what would otherwise be a hardcoded
    InboxAddAsContactView/InboxAddAsLeadView pair - it stays generic no
    matter how many apps register actions.
    """

    def _get_action_or_404(self, key):
        action = get_incoming_mail_action(key)
        if action is None:
            raise Http404(f"No incoming mail action registered for key '{key}'.")
        return action

    def get_action_form(self, action, incoming_mail, data=None):
        """
        Extension point: the form shown in the confirm step, or None for a
        plain confirm. Apps extend this view (ViewExtension) to ask for extra
        input, e.g. an owner, for their own action key.
        """
        return None

    def run_action(self, action, incoming_mail, form=None):
        """Extension point: perform the action; ``form`` is its validated form."""
        return action["handler"](incoming_mail, self.request)

    def get(self, request, pk, key, *args, **kwargs):
        incoming_mail = get_object_or_404(IncomingMail, pk=pk)
        action = self._get_action_or_404(key)

        if _is_converted(action, incoming_mail):
            return HxTriggerResponse(extra="closeModal();")

        if action.get("permission") and not request.user.has_perm(action["permission"]):
            return render(request, "403.html", {"modal": True})

        warning_check = action.get("warning_check")
        warning = warning_check(incoming_mail, request) if warning_check else None

        context = {
            "incoming_mail": incoming_mail,
            "action": action,
            "warning": warning,
            "form": self.get_action_form(action, incoming_mail),
        }
        return render(request, "incoming/inbox_run_action_confirm.html", context)

    def post(self, request, pk, key, *args, **kwargs):
        incoming_mail = get_object_or_404(IncomingMail, pk=pk)
        action = self._get_action_or_404(key)

        if _is_converted(action, incoming_mail):
            return HxTriggerResponse(extra="closeModal();")

        if action.get("permission") and not request.user.has_perm(action["permission"]):
            return render(request, "403.html", {"modal": True})

        form = self.get_action_form(action, incoming_mail, request.POST)
        if form is not None and not form.is_valid():
            context = {"incoming_mail": incoming_mail, "action": action, "form": form}
            return render(request, "incoming/inbox_run_action_confirm.html", context)
        self.run_action(action, incoming_mail, form)
        incoming_mail.mark_action_converted(key)

        return HxTriggerResponse(extra="closeModal();")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["mail.delete_incomingmail"]),
    name="dispatch",
)
class InboxDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete a single incoming mail via the generic single-delete flow
    (confirmation modal, etc.) - matches EmailToLeadConfigDeleteView's own
    use of the same base view elsewhere in the codebase.

    This is a genuine hard delete: the row (and its attachments, via
    cascade) are actually removed, so nothing accumulates indefinitely.
    What stops the fetch task from recreating it is a separate, tiny
    DeletedIncomingMessageId tombstone row, written by signals.py's
    remember_deleted_message_id pre_delete receiver before this delete
    actually destroys the IncomingMail row - that receiver fires regardless
    of which code path deletes the row (this view, Django admin, a shell
    command), so "delete" stays permanent everywhere, not just here.
    """

    model = IncomingMail

    def get_post_delete_response(self):
        return ScriptResponse(reload=True)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["mail.view_incomingmail"]),
    name="dispatch",
)
class InboxPreviewView(LoginRequiredMixin, View):
    """
    Full detail preview of a single incoming mail - sender, subject, body -
    with the same registered actions
    available directly from the preview, like Outbox's snapshot view.
    """

    def get(self, request, pk, *args, **kwargs):
        incoming_mail = get_object_or_404(IncomingMail, pk=pk)

        permitted_actions = [
            action
            for action in get_incoming_mail_actions()
            if not action.get("permission")
            or request.user.has_perm(action["permission"])
        ]
        blocked_cache = {}
        # An action that is already done (or blocked) is left out, not greyed.
        actions = [
            action
            for action in permitted_actions
            if not _is_action_blocked(action, incoming_mail, request, blocked_cache)
        ]

        attachments = list(incoming_mail.attachments.all())
        body = incoming_mail.body or ""

        def _was_embedded_in_body(attachment):
            return (
                attachment.is_inline and attachment.file and attachment.file.url in body
            )

        visible_attachments = [a for a in attachments if not _was_embedded_in_body(a)]
        image_attachments = [
            a for a in visible_attachments if (a.mime_type or "").startswith("image/")
        ]
        file_attachments = [
            a for a in visible_attachments if a not in image_attachments
        ]

        context = {
            "incoming_mail": incoming_mail,
            "actions": actions,
            "image_attachments": image_attachments,
            "file_attachments": file_attachments,
        }
        return render(request, "incoming/inbox_preview_modal.html", context)
