"""Notification Template Views"""

# Standard library imports
import logging
from functools import cached_property

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin, login_redirect
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaView,
)
from horilla.contrib.utils.middlewares import _thread_local
from horilla.core.exceptions import ValidationError
from horilla.shortcuts import get_object_or_404
from horilla.urls import reverse, reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import DetailView, FormView
from horilla.web import HttpNotFound, RefreshResponse, ScriptResponse

from ..filters import NotificationTemplateFilter
from ..forms import NotificationTemplateForm

# Local imports
from ..models import NotificationTemplate

logger = logging.getLogger(__name__)


@method_decorator(
    permission_required_or_denied(
        "notifications.view_notificationtemplate",
        wrapper_id="notification-template-view",
    ),
    name="dispatch",
)
class NotificationTemplateView(LoginRequiredMixin, HorillaView):
    """
    TemplateView for notification template view
    """

    template_name = "settings/settings_list_shell.html"
    view_id = "notification-template-view"
    nav_url = reverse_lazy("notifications:notification_template_nav_view")
    list_url = reverse_lazy("notifications:notification_template_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["notifications.view_notificationtemplate"]),
    name="dispatch",
)
class NotificationTemplateNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar for Notification Template"""

    nav_description = _("Customize the content of notifications sent to your users.")
    search_url = reverse_lazy("notifications:notification_template_list_view")
    main_url = reverse_lazy("notifications:notification_template_view")
    model_name = "NotificationTemplate"
    model_app_label = "notifications"
    filterset_class = NotificationTemplateFilter
    nav_width = False
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False

    @cached_property
    def new_button(self):
        """New button configuration"""
        if self.request.user.has_perm("notifications.add_notificationtemplate"):
            return {
                "url": f"""{reverse_lazy("notifications:notification_template_create_view")}?new=true""",
                "attrs": 'id="notification-template-create"',
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["notifications.view_notificationtemplate"]),
    name="dispatch",
)
class NotificationTemplateListView(LoginRequiredMixin, HorillaListView):
    """
    Notification Template List view
    """

    model = NotificationTemplate
    view_id = "notification-template-list"
    search_url = reverse_lazy("notifications:notification_template_list_view")
    main_url = reverse_lazy("notifications:notification_template_view")
    save_to_list_option = False
    bulk_select_option = False
    enable_sorting = False
    filterset_class = NotificationTemplateFilter

    columns = ["title", ("content_type", "get_related_model")]

    def no_record_add_button(self):
        """Button to show when no records exist"""
        if self.request.user.has_perm("notifications.add_notificationtemplate"):
            return {
                "url": f"""{reverse_lazy("notifications:notification_template_create_view")}?new=true""",
                "attrs": 'id="notification-template-create"',
            }
        return None

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "notifications.change_notificationtemplate",
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
            "permission": "notifications.delete_notificationtemplate",
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

    @cached_property
    def raw_attrs(self):
        """Get row attributes for HTMX detail view loading"""
        if self.request.user.has_perm("notifications.view_notificationtemplate"):
            return {
                "hx-get": "{get_detail_view_url}",
                "hx-target": "#contentModalBox",
                "hx-swap": "innerHTML",
                "hx-on:click": "openContentModal();",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }
        return ""


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["notifications.add_notificationtemplate"]),
    name="dispatch",
)
class NotificationTemplateCreateUpdateView(LoginRequiredMixin, FormView):
    """
    FormView for creating and updating Horilla Notification Template
    """

    form_class = NotificationTemplateForm
    template_name = "notification_template/template_form.html"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.template_id = None
        self.object = None

    def dispatch(self, request, *args, **kwargs):
        """Resolve template by pk and set self.object; handle errors with modal close."""
        self.template_id = kwargs.get("pk")
        if self.template_id:
            try:
                self.object = get_object_or_404(
                    NotificationTemplate, pk=self.template_id
                )
            except Exception as e:
                messages.error(
                    request,
                    e,
                )
                return ScriptResponse(reload=True, close=True)
        else:
            self.object = None
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        """Pass current template instance to the form when editing."""
        kwargs = super().get_form_kwargs()
        if self.object:
            kwargs["instance"] = self.object
        return kwargs

    def get_context_data(self, **kwargs):
        """Add form title, submit text, and action URL for create/update template form."""
        context = super().get_context_data(**kwargs)
        if self.object:
            context["form_title"] = _("Edit Notification Template")
            context["submit_text"] = _("Edit Template")

        else:
            context["form_title"] = _("Create Notification Template")
            context["submit_text"] = _("Save Template")

        context["action_url"] = self.get_form_action_url()
        return context

    def get_form_action_url(self):
        """Get the appropriate URL for form submission"""
        if self.object:
            return reverse(
                "notifications:notification_template_update_view",
                kwargs={"pk": self.object.pk},
            )
        return reverse("notifications:notification_template_create_view")

    def form_valid(self, form):
        """Save template with company, show success message, and return modal-close script."""
        try:
            mail_template = form.save(commit=False)
            mail_template.company = (
                getattr(_thread_local, "request", None).active_company
                if hasattr(_thread_local, "request")
                else self.request.user.company
            )
            if not self.object:
                mail_template.created_by = self.request.user
            mail_template.updated_by = self.request.user
            mail_template.save()
            if self.object:
                messages.success(
                    self.request,
                    _('Notification template "{}" updated successfully.').format(
                        mail_template.title
                    ),
                )
            else:
                messages.success(
                    self.request,
                    _('Notification template "{}" created successfully.').format(
                        mail_template.title
                    ),
                )

            return ScriptResponse(reload=True, close=True)

        except ValidationError as e:
            messages.error(self.request, str(e))
            return self.form_invalid(form)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        "notifications.delete_notificationtemplate", modal=True
    ),
    name="dispatch",
)
class NotificationTemplateDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View to delete a notification template"""

    model = NotificationTemplate

    def get_post_delete_response(self):
        """Return script to reload and close modal after template deletion."""
        return ScriptResponse(reload=True)


@method_decorator(
    permission_required_or_denied(["notifications.view_notificationtemplate"]),
    name="dispatch",
)
class NotificationTemplateDetailView(DetailView):
    """ " View to display mail template details"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.object = None

    def dispatch(self, request, *args, **kwargs):
        """Ensure user is authenticated, load object, and handle HTMX errors with refresh."""
        if not request.user.is_authenticated:
            return login_redirect(request)
        try:
            self.object = self.get_object()
        except Exception as e:
            if request.headers.get("HX-Request") == "true":
                messages.error(self.request, e)
                return RefreshResponse(request)
            raise HttpNotFound(e) from e
        return super().dispatch(request, *args, **kwargs)

    model = NotificationTemplate
    template_name = "notification_template/template_detail.html"
    context_object_name = "notification_template"
