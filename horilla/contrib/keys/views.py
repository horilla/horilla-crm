"""
Views for the keys app
"""

# Standard library imports
import logging
from functools import cached_property

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import HxTriggerResponse, JsonResponse, ScriptResponse

# Local imports
from .filters import ShortKeyFilter
from .forms import ShortcutKeyForm
from .models import ShortcutKey

logger = logging.getLogger(__name__)


@method_decorator(
    permission_required_or_denied(
        ["keys.view_shortcutkey", "keys.view_own_shortcutkey"],
        wrapper_id="short-key-view",
    ),
    name="dispatch",
)
class ShortKeyView(LoginRequiredMixin, HorillaView):
    """
    TemplateView for short key view.
    """

    template_name = "settings/my_settings_list_shell.html"
    view_id = "short-key-view"
    nav_url = reverse_lazy("keys:short_key_nav")
    list_url = reverse_lazy("keys:short_key_list")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required(["keys.view_shortcutkey", "keys.view_own_shortcutkey"]),
    name="dispatch",
)
class ShortKeyNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar for short key
    """

    nav_title = _("Short Keys")
    nav_description = _("Create keyboard shortcuts for quick access to actions.")
    search_url = reverse_lazy("keys:short_key_list")
    main_url = reverse_lazy("keys:short_key_view")
    filterset_class = ShortKeyFilter
    one_view_only = True
    all_view_types = False
    filter_option = False
    reload_option = False
    model_name = "ShortcutKey"
    model_app_label = "keys"
    nav_width = False

    @cached_property
    def new_button(self):
        """Return configuration for the create new shortcut key button."""
        if self.request.user.has_perm(
            "keys.add_own_shortcutkey"
        ) or self.request.user.has_perm("keys.create_shortcutkey"):
            return {
                "url": f"""{reverse_lazy("keys:short_key_create")}?new=true""",
                "attrs": {"id": "short-key-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required(["keys.view_shortcutkey", "keys.view_own_shortcutkey"]),
    name="dispatch",
)
class ShortKeyListView(LoginRequiredMixin, HorillaListView):
    """
    List view of user short key
    """

    model = ShortcutKey
    view_id = "short_key_list"
    filterset_class = ShortKeyFilter
    search_url = reverse_lazy("keys:short_key_list")
    main_url = reverse_lazy("keys:short_key_view")
    bulk_update_option = False
    bulk_export_option = False
    store_ordered_ids = True
    list_column_visibility = False

    @cached_property
    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        if self.request.user.has_perm(
            "keys.add_own_shortcutkey"
        ) or self.request.user.has_perm("keys.create_shortcutkey"):
            return {
                "url": f"""{reverse_lazy("keys:short_key_create")}?new=true""",
                "attrs": 'id="short-key-create"',
            }
        return None

    columns = [("page", "page_display"), ("key", "custom_key_col")]

    def get_queryset(self):
        """Return shortcut keys filtered by the logged-in user across all companies."""
        user = self.request.user
        if not user:
            return self.model.all_objects.none()
        return self.model.all_objects.filter(user=user)

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permissions": "keys.change_shortcutkey",
            "owner_field": "user",
            "own_permission": "keys.change_own_shortcutkey",
            "attrs": """
                    hx-get="{get_edit_url}?new=true"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    onclick="openModal()"
                    """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permissions": "keys.delete_shortcutkey",
            "owner_field": "user",
            "own_permission": "keys.delete_own_shortcutkey",
            "attrs": """
                    hx-post="{get_delete_url}"
                    hx-target="#deleteModeBox"
                    hx-swap="innerHTML"
                    hx-trigger="click"
                    hx-vals='{{"check_dependencies": "true"}}'
                    onclick="openDeleteModeModal()"
                """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
class ShortKeyFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    create and update from view for short key
    """

    model = ShortcutKey
    form_class = ShortcutKeyForm
    modal_height = False
    full_width_fields = ["page"]
    hidden_fields = ["is_active", "user", "company"]

    @cached_property
    def form_url(self):
        """Return the create or update URL for the shortcut key form."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("keys:short_key_update", kwargs={"pk": pk})
        return reverse_lazy("keys:short_key_create")

    def get_initial(self):
        """Set initial form data with current user and their assigned company."""
        initial = super().get_initial()
        initial["user"] = self.request.user
        initial["company"] = getattr(self.request.user, "company", None)
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def get(self, request, *args, **kwargs):
        pk = kwargs.get("pk")
        if pk:
            try:
                self.model.all_objects.get(pk=pk)
            except self.model.DoesNotExist:
                messages.error(request, _("The requested data does not exist."))
                return ScriptResponse(reload=True)

        return super().get(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["keys.delete_shortcutkey", "keys.delete_own_shortcutkey"], modal=True
    ),
    name="dispatch",
)
class ShortcutKeyDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View to handle deletion of shortcut keys."""

    model = ShortcutKey

    def get_post_delete_response(self):
        """Return HTMX response to reload shortcut key list after deletion."""
        return HxTriggerResponse()


class ShortKeyDataView(LoginRequiredMixin, View):
    """
    View to return shortcut data as JSON for the current user.
    """

    def get(self, request, *args, **kwargs):
        """Return all shortcut keys for the logged-in user as JSON."""
        shortcuts = [
            {
                "key": sk.key,
                "page": sk.page,
                "command": sk.command.lower(),
                "section": sk.get_section(),
                "title": sk.get_page_title(),
            }
            for sk in ShortcutKey.all_objects.filter(user=request.user)
        ]

        return JsonResponse({"shortcuts": shortcuts})
