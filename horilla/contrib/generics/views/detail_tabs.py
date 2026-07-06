"""
Generic detail view with tabs for related content,
supporting dynamic field visibility and permissions.
"""

# Standard library imports
import logging
from functools import update_wrapper

# Third-party imports (Django)
from django.contrib import messages

from horilla.contrib.core.models import DetailFieldVisibility
from horilla.contrib.core.utils import get_field_permissions_for_model
from horilla.core.exceptions import FieldDoesNotExist

# First-party (Horilla)
from horilla.shortcuts import render
from horilla.urls import reverse, reverse_lazy
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import DetailView
from horilla.web import ScriptResponse

# Local imports
from .core import HorillaTabView
from .details import HorillaDetailView, check_record_access

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
class HorillaDetailTabView(HorillaTabView):
    """
    Generic for tabs in detail views
    """

    view_id = "generic-details-tab-view"
    is_detail_view = True
    object_id = None
    model = (
        None  # Subclasses must set this before calling super()._prepare_detail_tabs()
    )
    urls = {}
    tab_class = "h-[calc(_100vh_-_455px_)] overflow-hidden"

    def setup(self, request, *args, **kwargs):
        """Initialize detail tabs from configured URLs and object_id."""
        super().setup(request, *args, **kwargs)
        self._prepare_detail_tabs()

    def _can_access_record_tabs(self) -> bool:
        """
        Return True if the user is allowed to see the tab content for the current record.

        A user may access all tabs (Activity, Notes & Attachments, Related Lists)
        for a record if they have the unconditional view permission for the model,
        OR if they are the record owner and have the view_own permission.
        """
        user = self.request.user
        if user.is_superuser:
            return True
        if not self.model or not self.object_id:
            return True
        try:
            obj = self.model.objects.get(pk=self.object_id)
            return check_record_access(user, obj)
        except Exception:
            return False

    def _prepare_detail_tabs(self) -> None:
        """Fill ``self.tabs`` from ``self.urls`` and ``self.object_id`` (subclasses set those, then ``super()``)."""
        pipeline_field = self.request.GET.get("pipeline_field")
        if not pipeline_field:
            self.tab_class = "h-[calc(_100vh_-_370px_)] overflow-hidden"
        self.tabs = []
        if self.object_id:
            if "details" in self.urls:
                detail_url_name = self.request.GET.get("detail_url_name", "")
                details_url = reverse(
                    self.urls["details"], kwargs={"pk": self.object_id}
                )
                params = []
                if pipeline_field:
                    params.append(f"pipeline_field={pipeline_field}")
                if detail_url_name:
                    params.append(f"detail_url_name={detail_url_name}")
                if params:
                    details_url = f"{details_url}?{'&'.join(params)}"
                self.tabs.append(
                    {
                        "title": _("Details"),
                        "url": details_url,
                        "target": "tab-details-content",
                        "id": "details",
                    }
                )
            if "activity" in self.urls:
                self.tabs.append(
                    {
                        "title": _("Activity"),
                        "url": reverse_lazy(
                            self.urls["activity"], kwargs={"pk": self.object_id}
                        ),
                        "target": "tab-activity-content",
                        "id": "activity",
                    }
                )
            if "related_lists" in self.urls:
                self.tabs.append(
                    {
                        "title": _("Related Lists"),
                        "url": f"{reverse_lazy(self.urls['related_lists'], kwargs={'pk': self.object_id})}",
                        "target": "tab-related-lists-content",
                        "id": "related-lists",
                    }
                )

            if "notes_attachments" in self.urls and self._can_access_record_tabs():
                self.tabs.append(
                    {
                        "title": _("Notes & Attachments"),
                        "url": f"{reverse_lazy(self.urls['notes_attachments'], kwargs={'pk': self.object_id})}",
                        "target": "tab-notes-attachments-content",
                        "id": "notes-attachments",
                    }
                )

            if "history" in self.urls:
                self.tabs.append(
                    {
                        "title": _("History"),
                        "url": reverse_lazy(
                            self.urls["history"], kwargs={"pk": self.object_id}
                        ),
                        "target": "tab-history-content",
                        "id": "history",
                    }
                )


@method_decorator(htmx_required, name="dispatch")
class HorillaDetailSectionView(DetailView):
    """
    A generic detail view that supports multiple tabs for displaying related objects.
    """

    template_name = "details_tab.html"
    context_object_name = "obj"
    body = []
    edit_field = True
    non_editable_fields = []
    base_excluded_fields = HorillaDetailView.base_excluded_fields
    excluded_fields = []
    include_fields = []

    _view_registry = {}

    def __init_subclass__(cls, **kwargs):
        """
        Automatically register child classes with their models.
        This allows _inherit_detail_section discovery to find the concrete
        section view for a model, the same way HorillaDetailView._view_registry
        works for header/detail views.
        """
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "model") and cls.model:
            HorillaDetailSectionView._view_registry[cls.model] = cls

    @classmethod
    def as_view(cls, **initkwargs):
        """
        Wrap the view so _inherit_detail_section resolves on each request.

        Target apps register URLs in ``AppLauncher.ready()`` before extension apps
        import their view modules; resolving only at URL-import time would miss
        extensions. Mirrors HorillaDetailView.as_view() exactly.
        """
        if getattr(cls, "__horilla_detail_section_composed__", False):
            return super().as_view(**initkwargs)

        base_view = super().as_view(**initkwargs)

        def view(request, *args, **kwargs):
            from horilla.extension.detail_section.bootstrap import (
                registry_fingerprint as detail_section_fingerprint,
            )
            from horilla.extension.detail_section.resolve import (
                resolve_detail_section_view_class,
            )

            resolved = resolve_detail_section_view_class(cls)
            fingerprint = detail_section_fingerprint()

            if resolved is not cls:
                if (
                    getattr(view, "_extended_handler", None) is None
                    or getattr(view, "_extended_cls", None) is not resolved
                    or getattr(view, "_detail_section_ext_fingerprint", None)
                    != fingerprint
                ):
                    view._extended_cls = resolved
                    view._extended_handler = resolved.as_view(**initkwargs)
                    view._detail_section_ext_fingerprint = fingerprint
                return view._extended_handler(request, *args, **kwargs)
            return base_view(request, *args, **kwargs)

        update_wrapper(view, base_view)
        view.view_class = cls
        view.view_initkwargs = initkwargs
        return view

    def get_excluded_fields(self):
        """Return effective excluded fields: base list plus any extra from subclasses."""
        base = list(self.base_excluded_fields)
        extra = [f for f in (self.excluded_fields or []) if f not in base]
        request = getattr(self, "request", None)
        if request is not None and hasattr(request, "session"):
            excluded = base + extra
            if request.session.get("show_all_companies", False):
                # Company is shown only when "all companies" is enabled, even if
                # the view lists it in excluded_fields.
                return [f for f in excluded if f != "company"]
            if "company" not in excluded:
                return excluded + ["company"]
            return excluded
        return base + extra

    def check_object_permission(self, request, obj):
        """
        Check if user has permission to view the object.
        Override this method for custom permission logic.

        Returns True if permission granted, False otherwise.
        """
        user = request.user

        # Automatically generate permissions from model meta
        app_label = self.model._meta.app_label
        model_name = self.model._meta.model_name
        view_permission = f"{app_label}.view_{model_name}"
        view_own_permission = f"{app_label}.view_own_{model_name}"

        has_view_permission = user.has_perm(view_permission)
        if has_view_permission:
            return True

        # Check if user is the owner (including subordinate role members)
        owner_fields = getattr(self.model, "OWNER_FIELDS", [])

        if user.has_perm(view_own_permission):
            from horilla.contrib.core.utils import get_allowed_user_ids

            allowed_ids = get_allowed_user_ids(user)
            for owner_field in owner_fields:
                owner = getattr(obj, owner_field, None)
                if owner is not None:
                    if hasattr(owner, "all"):
                        if any(m.pk in allowed_ids for m in owner.all()):
                            return True
                    elif hasattr(owner, "pk"):
                        if owner.pk in allowed_ids:
                            return True
                    elif owner in allowed_ids:
                        return True

            from .helpers.queryset_utils import user_has_granted_access

            if user_has_granted_access(obj, user, "view"):
                return True

        return False

    def get(self, request, *args, **kwargs):
        """
        Override get method to handle object not found and permission check
        """
        try:
            self.object = self.get_object()
        except Exception as e:
            messages.error(self.request, e)
            return ScriptResponse(reload=True)

        # Permission check
        if not self.check_object_permission(request, self.object):
            return render(request, "403.html", status=403)

        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def get_default_body(self):
        """
        Dynamically generate body based on model fields.
        Exclude fields like 'id' or others you don't want to display.
        """
        excluded_fields = list(self.get_excluded_fields())
        pipeline_field = self.request.GET.get("pipeline_field")
        if pipeline_field:
            excluded_fields.append(pipeline_field)

        if self.include_fields:
            fields_by_name = {
                field.name: field
                for field in self.model._meta.get_fields()
                if hasattr(field, "verbose_name")
            }
            return [
                (fields_by_name[name].verbose_name, name)
                for name in self.include_fields
                if name in fields_by_name and name not in excluded_fields
            ]
        return [
            (field.verbose_name, field.name)
            for field in self.model._meta.get_fields()
            if field.name not in excluded_fields
            and hasattr(field, "verbose_name")
            and getattr(field, "editable", True)
        ]

    def prepare_include_fields(self):
        """
        Hook for subclasses to set ``self.include_fields`` from per-object state
        (e.g. Activity varying it by ``activity_type``) before ``get_default_body()``
        runs. Called both when rendering the Details tab and when building the
        "Edit Details" bulk-edit form, so both stay in sync.
        """

    def get_effective_body(self):
        """
        Return the (verbose_name, field_name) body to render: saved
        ``DetailFieldVisibility.details_fields`` for this ``detail_url_name`` if
        present, otherwise ``self.body`` or the type-aware default body.
        """
        self.prepare_include_fields()
        body = self.body or self.get_default_body()
        detail_url_name = self.request.GET.get("detail_url_name")
        if detail_url_name:
            visibility = DetailFieldVisibility.all_objects.filter(
                user=self.request.user,
                app_label=self.model._meta.app_label,
                model_name=self.model._meta.model_name,
                url_name=detail_url_name,
            ).first()
            if visibility and visibility.details_fields:
                body = []
                for f in visibility.details_fields:
                    fn = f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f
                    try:
                        mf = self.model._meta.get_field(str(fn))
                        body.append((mf.verbose_name, str(fn)))
                    except FieldDoesNotExist:
                        pass
        return body

    def get_context_data(self, **kwargs):
        """Add body (with detail field visibility), header_fields, and related list data to context."""
        context = super().get_context_data(**kwargs)
        context["body"] = self.get_effective_body()
        context["model_name"] = self.model._meta.model_name
        context["app_label"] = self.model._meta.app_label
        context["edit_field"] = self.edit_field
        context["non_editable_fields"] = self.non_editable_fields

        # field permissions context
        field_permissions = get_field_permissions_for_model(
            self.request.user, self.model
        )
        context["field_permissions"] = field_permissions
        context["can_update"] = HorillaDetailView.check_update_permission(self)
        pipeline_field = self.request.GET.get("pipeline_field")
        if pipeline_field:
            context["pipeline_field"] = pipeline_field
        detail_url_name = self.request.GET.get("detail_url_name")
        if detail_url_name:
            context["detail_url_name"] = detail_url_name
        return context
