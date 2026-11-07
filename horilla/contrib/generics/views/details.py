"""
Generic detail view for displaying individual model instances, with support for dynamic field visibility, permissions,
pipeline stages, badges, and breadcrumbs. This view can be subclassed for specific models to customize the displayed fields, actions, and pipeline behavior.
"""

# Standard library imports
import logging
from functools import update_wrapper
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

# Third-party imports (Django)
from django.contrib import messages
from django.template.loader import get_template, render_to_string
from django.utils.encoding import force_str
from django.views.generic import DetailView

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import login_redirect
from horilla.contrib.core.utils import get_allowed_user_ids as _get_allowed_user_ids
from horilla.contrib.generics.history import is_record_locked
from horilla.contrib.utils.methods import closest_numbers, get_section_info_for_model
from horilla.core.exceptions import FieldDoesNotExist, ValidationError
from horilla.db.models import ForeignKey
from horilla.shortcuts import redirect, render
from horilla.urls import resolve, reverse, reverse_lazy
from horilla.utils.translation import gettext_lazy as _
from horilla.web import (
    Http404,
    HttpNotFound,
    HttpResponse,
    QueryDict,
    RefreshResponse,
    ScriptResponse,
)

# ``DetailFieldVisibility.url_name`` key storing the split-view field selection.
SPLIT_VISIBILITY_URL_NAME = "split_view"

logger = logging.getLogger(__name__)


def _check_record_permission(user, obj, action: str) -> bool:
    """
    Return True if user has ``action`` permission on ``obj``.

    Checks global ``{app}.{action}_{model}`` first, then falls back to
    ``{app}.{action}_own_{model}`` when the user owns the record (via OWNER_FIELDS).
    """
    if action in ("change", "delete") and getattr(obj, "is_record_locked", False):
        return False
    if user.is_superuser:
        return True
    app = obj._meta.app_label
    model = obj._meta.model_name
    if user.has_perm(f"{app}.{action}_{model}"):
        return True
    if user.has_perm(f"{app}.{action}_own_{model}"):
        allowed_ids = _get_allowed_user_ids(user)
        for field in getattr(obj.__class__, "OWNER_FIELDS", []):
            try:
                v = getattr(obj, field, None)
                if v:
                    if hasattr(v, "all"):
                        if any(m.pk in allowed_ids for m in v.all()):
                            return True
                    elif hasattr(v, "pk"):
                        if v.pk in allowed_ids:
                            return True
            except Exception:
                pass
        from .helpers.queryset_utils import user_has_granted_access

        if user_has_granted_access(obj, user, action):
            return True
    return False


def resolves_within_settings_shell(path: str) -> bool:
    """
    Return True if ``path`` resolves to a view whose template directly
    extends settings/settings.html, i.e. one that shares #settings-content
    rather than the app-wide #sideMenuContainer layout.

    Used to decide whether a detail view's back button can safely swap
    #mainContent via htmx, or must fall back to a full page navigation
    (the Settings shell has no #sideMenuContainer for htmx to swap into).
    """
    try:
        resolved = resolve(path)
    except Exception:
        return False
    view_class = getattr(resolved.func, "view_class", None)
    if view_class is None:
        return False
    template_name = getattr(view_class, "template_name", "") or ""
    if not template_name:
        return False
    try:
        template = get_template(template_name)
        with open(template.origin.name, encoding="utf-8") as fh:
            first_line = fh.readline()
    except Exception:
        return False
    return "settings/settings.html" in first_line


def check_record_access(user, obj) -> bool:
    """
    Return True if the user is allowed to view obj.

    A user may view a record if they:
      - have the unconditional view permission for the model, OR
      - are the record owner (via any OWNER_FIELDS) AND have the view_own permission.

    This is the shared access rule applied to the main record when deciding
    whether its related tabs (Activity, Notes, Attachments, Related Lists) are
    accessible.
    """
    return _check_record_permission(user, obj, "view")


def check_record_change_access(user, obj) -> bool:
    """
    Return True if the user can add/edit records in the related tabs of ``obj``.

    Allowed when:
      - user has global change permission for the model, OR
      - user has change_own permission AND owns the record (via OWNER_FIELDS).
    """
    return _check_record_permission(user, obj, "change")


def check_record_delete_access(user, obj) -> bool:
    """
    Return True if the user can delete records in the related tabs of ``obj``.

    Allowed when:
      - user has global delete permission for the model, OR
      - user has delete_own permission AND owns the record (via OWNER_FIELDS).
    """
    return _check_record_permission(user, obj, "delete")


class HorillaDetailView(DetailView):
    """Generic detail view for displaying individual model instances."""

    template_name = "detail_view.html"
    context_object_name = "obj"
    body: list = []
    fieldsets = ()
    header_fields: list = (
        []
    )  # Fields shown in header (e.g. title). If empty, first body field is used.
    base_excluded_fields = [
        "id",
        "created_at",
        "additional_info",
        "updated_at",
        "history",
        "is_active",
        "created_by",
        "updated_by",
    ]
    excluded_fields = (
        []
    )  # Subclass: add more field names to exclude (extends base_excluded_fields).
    split_excluded_fields: list = (
        []
    )  # Optional extra fields to exclude only in split layout/detail section.
    pipeline_field = ""
    breadcrumbs = []
    actions = []
    tab_url: str = ""
    final_stage_action = {}
    badge: list = (
        []
    )  # List of badge configurations: [{"condition": callable, "label": str, "class": str}, ...]

    _view_registry = {}

    def __init_subclass__(cls, **kwargs):
        """
        Automatically register child classes with their models.
        This allows the parent to find the correct child class dynamically.
        """
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "model") and cls.model:
            HorillaDetailView._view_registry[cls.model] = cls

    def get_object(self, queryset=None):
        """Fetch the instance once per request and reuse it.

        Several methods on this view (permission checks, pipeline choices,
        badges, context data) each call ``get_object()`` independently;
        without caching, every call re-runs the same lookup query.
        """
        if queryset is not None:
            return super().get_object(queryset)
        if not hasattr(self, "_object_cache"):
            self._object_cache = super().get_object(queryset)
        return self._object_cache

    @classmethod
    def as_view(cls, **initkwargs):
        """
        Wrap the view so _inherit_detail resolves on each request.

        Target apps register URLs in ``AppLauncher.ready()`` before extension apps
        import ``details.py``; resolving only at URL-import time would miss extensions.
        """
        if getattr(cls, "__horilla_detail_composed__", False):
            return super().as_view(**initkwargs)

        base_view = super().as_view(**initkwargs)

        def view(request, *args, **kwargs):
            from horilla.extension.detail.bootstrap import (
                registry_fingerprint as detail_fingerprint,
            )
            from horilla.extension.detail.resolve import resolve_detail_view_class

            resolved = resolve_detail_view_class(cls)
            fingerprint = detail_fingerprint()

            if resolved is not cls:
                if (
                    getattr(view, "_extended_handler", None) is None
                    or getattr(view, "_extended_cls", None) is not resolved
                    or getattr(view, "_detail_ext_fingerprint", None) != fingerprint
                ):
                    view._extended_cls = resolved
                    view._extended_handler = resolved.as_view(**initkwargs)
                    view._detail_ext_fingerprint = fingerprint
                return view._extended_handler(request, *args, **kwargs)
            return base_view(request, *args, **kwargs)

        update_wrapper(view, base_view)
        view.view_class = cls
        view.view_initkwargs = initkwargs
        return view

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._run_detail_view_extension_setup()

    def _run_detail_view_extension_setup(self):
        """Call setup_detail_view_extension on extension mixins (composed views only)."""
        if not getattr(type(self), "__horilla_detail_composed__", False):
            return
        wrapped = getattr(type(self), "__wrapped_detail_view__", None)
        seen: set = set()
        for base in type(self).__mro__:
            if wrapped is not None and base is wrapped:
                break
            method = base.__dict__.get("setup_detail_view_extension")
            if method is None or method in seen:
                continue
            seen.add(method)
            method(self)

    def _is_owner(self, obj, user, action: str = "view") -> bool:
        """Return True if user owns obj via any OWNER_FIELDS, including subordinate role members,
        or has been separately granted ``action`` access (e.g. team/shared-access grants).
        """
        allowed_ids = _get_allowed_user_ids(user)
        for field in getattr(obj.__class__, "OWNER_FIELDS", []):
            try:
                v = getattr(obj, field, None)
                if v:
                    if hasattr(v, "all"):
                        if any(m.pk in allowed_ids for m in v.all()):
                            return True
                    elif hasattr(v, "pk"):
                        if v.pk in allowed_ids:
                            return True
            except Exception:
                pass

        from .helpers.queryset_utils import user_has_granted_access

        return user_has_granted_access(obj, user, action)

    def dispatch(self, request, *args, **kwargs):
        """Resolve model and object, check view/own permissions, then dispatch."""
        if not request.user.is_authenticated:
            return login_redirect(request)

        try:
            model_name = request.POST.get("model_name") or request.GET.get("model_name")
            app_label = request.POST.get("app_label") or request.GET.get("app_label")

            if model_name and app_label:
                self.model = apps.get_model(app_label=app_label, model_name=model_name)

            self.object = self.get_object()
        except Http404 as e:
            if self._is_same_page_htmx_refetch(request):
                # The record was just deleted from this very page (e.g. the
                # delete action's own reload button, or another element on
                # the page racing that delete), so retrying this same detail
                # URL via RefreshResponse's HX-Refresh would only 404 again.
                # Send the user to the model's list/section view instead.
                return self._redirect_to_model_list(request)
            # A fresh visit, bookmark, or plain browser reload of a record
            # that is simply gone (deleted earlier, by someone else, etc.):
            # behave like any other dead link and show Horilla's 404 page.
            raise HttpNotFound(e) from e
        except Exception as e:
            if request.headers.get("HX-Request") == "true":
                messages.error(request, e)
                return RefreshResponse(request)
            raise HttpNotFound(e) from e

        app = self.model._meta.app_label
        model = self.model._meta.model_name
        user = request.user
        obj = self.object

        view_perm = f"{app}.view_{model}"

        is_owner = self._is_owner(obj, user)

        own_view_perm = f"{app}.view_own_{model}"

        allowed = user.has_perm(view_perm) or (
            is_owner and user.has_perm(own_view_perm)
        )
        if not allowed:
            return render(request, "403.html")
        return super().dispatch(request, *args, **kwargs)

    def _is_same_page_htmx_refetch(self, request):
        """True if this htmx GET is re-fetching the detail page it was issued from.

        That pattern (``HX-Current-URL`` pointing at this same path) only
        happens for in-page refresh mechanisms like ``#reloadButton`` or a
        tab racing a delete — never for a fresh navigation, a bookmark, or a
        plain (non-htmx) browser reload, which carry no such header.
        """
        if request.headers.get("HX-Request") != "true":
            return False
        current_url = request.headers.get("HX-Current-URL")
        if not current_url:
            return False
        return urlparse(current_url).path == request.path

    def _redirect_to_model_list(self, request):
        """Send the user to this model's list/section view (record no longer exists)."""
        section_info = {}
        if self.model:
            try:
                section_info = get_section_info_for_model(self.model)
            except Exception:
                section_info = {}
        list_url = section_info.get("url") or reverse_lazy("core:home_view")
        if request.headers.get("HX-Request") == "true":
            response = HttpResponse(status=204)
            response["HX-Redirect"] = str(list_url)
            return response
        return redirect(list_url)

    def get(self, request, *args, **kwargs):
        """Redirect unauthenticated users to login; otherwise delegate to parent get."""
        if not self.request.user.is_authenticated:
            return login_redirect(request)
        return super().get(request, *args, **kwargs)

    def get_template_names(self):
        """Use fragment template when layout=split for split-view right panel."""
        if self.request.GET.get("layout") == "split":
            return ["detail_view_split_fragment.html"]
        return super().get_template_names()

    def get_queryset(self):
        """Return the queryset for the detail view; require model to be set."""
        if not self.model:
            raise HttpNotFound("Model not found")
        return super().get_queryset()

    def _normalize_field_list(self, field_list, exclude_set):
        """Normalize a list of fields to (verbose_name, field_name) and filter by permissions and excluded_fields.
        Always resolves verbose_name from the model so translations work in the current request language.
        """
        from horilla.contrib.core.utils import get_field_permissions_for_model

        if not field_list:
            return []
        field_permissions = get_field_permissions_for_model(
            self.request.user, self.model
        )
        instance = self.model()
        result = []
        for field in field_list:
            field_name = (
                field[1]
                if isinstance(field, (list, tuple)) and len(field) >= 2
                else field
            )
            if field_name in exclude_set:
                continue
            field_perm = field_permissions.get(field_name, "readwrite")
            if field_perm == "hidden":
                continue
            try:
                model_field = instance._meta.get_field(field_name)
                result.append((model_field.verbose_name, field_name))
            except FieldDoesNotExist:
                pass
        return result

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

    def get_header_fields(self):
        """Return normalized (verbose_name, field_name) list for header. Excluded fields are omitted."""
        excluded_set = set(self.get_excluded_fields())
        if self.header_fields:
            return self._normalize_field_list(self.header_fields, excluded_set)
        full_body = self._normalize_field_list(self.body, excluded_set)
        return [full_body[0]] if full_body else []

    def get_split_field_visibility(self):
        """Return the user's saved split-view ``DetailFieldVisibility`` or None."""
        from horilla.contrib.core.models import DetailFieldVisibility

        return DetailFieldVisibility.all_objects.filter(
            user=self.request.user,
            app_label=self.model._meta.app_label,
            model_name=self.model._meta.model_name,
            url_name=SPLIT_VISIBILITY_URL_NAME,
        ).first()

    def get_detail_section_body(self):
        """
        Return body list for split-view / detail section: all model fields
        excluding base_excluded_fields, excluded_fields, split_excluded_fields (for split layout),
        and pipeline_field
        (same logic as HorillaDetailSectionView.get_default_body).
        """
        excluded = list(self.get_excluded_fields())
        if self.request.GET.get("layout") == "split":
            for field in getattr(self, "split_excluded_fields", []) or []:
                if field not in excluded:
                    excluded.append(field)
        effective_pf = self._get_effective_pipeline_field()
        if effective_pf:
            excluded.append(effective_pf)
        include_fields = getattr(self, "include_fields", None)
        if include_fields:
            fields_by_name = {
                f.name: f
                for f in self.model._meta.get_fields()
                if hasattr(f, "verbose_name")
            }
            return [
                (fields_by_name[name].verbose_name, name)
                for name in include_fields
                if name in fields_by_name and name not in excluded
            ]
        split_visibility = self.get_split_field_visibility()
        if split_visibility and split_visibility.details_fields:
            return self._normalize_field_list(
                split_visibility.details_fields, set(excluded)
            )
        return [
            (f.verbose_name, f.name)
            for f in self.model._meta.get_fields()
            if f.name not in excluded
            and hasattr(f, "verbose_name")
            and getattr(f, "editable", True)
        ]

    def get_body(self):
        """Return normalized (verbose_name, field_name) list for details grid. Excluded fields are omitted."""
        from horilla.contrib.core.models import DetailFieldVisibility

        excluded_set = set(self.get_excluded_fields())
        url = resolve(self.request.path)
        url_name = url.url_name if url else ""
        visibility_scope = self.get_detail_field_visibility_scope(self.get_object())
        if visibility_scope:
            url_name = f"{url_name}:{visibility_scope}"
        visibility = DetailFieldVisibility.all_objects.filter(
            user=self.request.user,
            app_label=self.model._meta.app_label,
            model_name=self.model._meta.model_name,
            url_name=url_name,
        ).first()
        if visibility and visibility.header_fields:
            return self._normalize_field_list(visibility.header_fields, excluded_set)
        full_body = self._normalize_field_list(self.body, excluded_set)
        if self.header_fields:
            return full_body
        # Return full body so body[0]=title (heading), body[1:]=first_name,last_name... (grid)
        return full_body

    def get_fieldsets(self):
        """
        Return fieldsets as dicts with normalized (verbose_name, field_name) lists.

        Extension apps can inject fields via ``fieldsets_insert`` without editing
        HTML. When ``fieldsets`` is empty, falls back to a single untitled group
        from ``get_body()`` (excluding the first entry when it is used as title).
        """
        excluded_set = set(self.get_excluded_fields())
        declared = getattr(self, "fieldsets", None) or ()
        if not declared:
            body = self.get_body()
            if not body:
                return []
            # Match detail_view.html: body[0] is title, body[1:] is the grid.
            grid = body[1:] if len(body) > 1 and not self.header_fields else body
            return (
                [{"name": "", "fields": grid, "description": None, "icon": None}]
                if grid
                else []
            )

        result = []
        for name, options in declared:
            fields = self._normalize_field_list(options.get("fields", ()), excluded_set)
            if fields:
                result.append(
                    {
                        "name": name,
                        "fields": fields,
                        "description": options.get("description"),
                        "icon": options.get("icon"),
                    }
                )
        return result

    def check_update_permission(self):
        """
        Check if the current user has permission to update the pipeline field.
        Returns True if user has permission, False otherwise.
        """
        user = self.request.user
        current_obj = self.get_object()
        if is_record_locked(current_obj):
            return False
        model_name = self.model._meta.model_name
        app_label = self.model._meta.app_label

        is_owner = HorillaDetailView._is_owner(self, current_obj, user)

        # Check change_own permission if user is owner
        if is_owner:
            change_own_perm = f"{app_label}.change_own_{model_name}"
            if user.has_perm(change_own_perm):
                return True

        # Check regular change permission
        change_perm = f"{app_label}.change_{model_name}"
        if user.has_perm(change_perm):
            return True

        return False

    def _get_effective_pipeline_field(self):
        """
        Return pipeline_field only if the user has permission to see it (not "Don't Show").
        Returns None if the field is hidden for the current user.
        """
        from horilla.contrib.core.utils import filter_hidden_fields

        if not self.pipeline_field:
            return None
        visible = filter_hidden_fields(
            self.request.user, self.model, [self.pipeline_field]
        )
        return self.pipeline_field if self.pipeline_field in visible else None

    def _make_pipeline_choice(
        self,
        label,
        value,
        is_completed,
        is_current,
        related_obj=None,
        *,
        use_custom_colors=False,
    ):
        """Build one pipeline pill dict (generic; domain attrs stay on related_obj)."""
        return {
            "label": label,
            "value": value,
            "is_completed": is_completed,
            "is_current": is_current,
            "related_obj": related_obj,
            "use_custom_colors": use_custom_colors,
        }

    def get_pipeline_choices(self):
        """
        Generate pipeline data for the specified pipeline_field.

        Returns a list of dicts with keys:
        ``label``, ``value``, ``is_completed``, ``is_current``, ``related_obj``,
        ``use_custom_colors``.

        - Choice fields: no ``related_obj`` (always ``None``).
        - Foreign keys: ``related_obj`` is the stage/status instance already
          loaded for that column (subclasses can read domain attrs without
          re-querying).
        """
        if not self.pipeline_field:
            return []
        try:
            obj = self.get_object()
        except Http404:
            return render(self.request, "403.html")
        field = self.model._meta.get_field(self.pipeline_field)
        current_value = getattr(obj, self.pipeline_field)

        pipeline = []
        if hasattr(field, "choices") and field.choices:
            current_choice_index = None
            for i, (value, display_name) in enumerate(field.choices):
                if value == current_value:
                    current_choice_index = i
                    break

            for i, (value, display_name) in enumerate(field.choices):
                is_completed = (
                    current_choice_index is not None and i < current_choice_index
                )
                is_current = value == current_value
                pipeline.append(
                    self._make_pipeline_choice(
                        display_name,
                        value,
                        is_completed,
                        is_current,
                        related_obj=None,
                    )
                )

        elif isinstance(field, ForeignKey):
            related_model = field.related_model
            order_field = None
            try:
                order_field = related_model._meta.get_field("order")
            except Exception:
                pass
            queryset = related_model.objects.all()

            if (
                hasattr(related_model, "company")
                and hasattr(obj, "company")
                and obj.company
            ):
                queryset = queryset.filter(company=obj.company)

            if order_field:
                queryset = queryset.order_by("order")

            current_order = (
                getattr(current_value, "order", None) if current_value else None
            )
            current_id = current_value.id if current_value else None

            for related_obj in queryset:
                is_completed = False
                is_current = related_obj.id == current_id
                if current_order is not None:
                    related_order = getattr(related_obj, "order", None)
                    is_completed = (
                        related_order is not None and related_order < current_order
                    )
                pipeline.append(
                    self._make_pipeline_choice(
                        str(related_obj),
                        related_obj.id,
                        is_completed,
                        is_current,
                        related_obj=related_obj,
                    )
                )
        else:
            return []

        return pipeline

    def get_badges(self):
        """
        Get badges to display for the current object.
        Returns a list of badge dictionaries with 'label' and 'class' keys.
        Each badge in self.badge should have:
        - condition: A callable that takes the object and returns True if badge should show
        - label: The text to display on the badge
        - class: CSS classes for styling the badge
        - icon: (optional) FontAwesome icon class (e.g., "fa-solid fa-check")
        - icon_class: (optional) CSS classes for the icon
        - icon_bg_class: (optional) CSS classes for the icon background circle
        """
        badges = []
        if not self.badge:
            return badges

        obj = self.get_object()
        for badge_config in self.badge:
            try:
                condition = badge_config.get("condition")
                badge_data = {
                    "label": badge_config.get("label", ""),
                    "class": badge_config.get("class", ""),
                }
                # Include icon fields if present
                if "icon" in badge_config:
                    badge_data["icon"] = badge_config.get("icon")
                if "icon_class" in badge_config:
                    badge_data["icon_class"] = badge_config.get("icon_class")
                if "icon_bg_class" in badge_config:
                    badge_data["icon_bg_class"] = badge_config.get("icon_bg_class")

                if condition and callable(condition):
                    if condition(obj):
                        badges.append(badge_data)
                elif condition is None:
                    # If no condition, always show
                    badges.append(badge_data)
            except Exception as e:
                logger.warning("Error evaluating badge condition: %s", str(e))
                continue

        return badges

    def get_detail_field_visibility_scope(self, obj):
        """
        Hook: return a suffix to append to the ``url_name`` used as the
        ``DetailFieldVisibility``/column-selector key for ``obj``, or ``""``
        for no suffix.

        Override when a single model's detail view covers meaningfully
        different field sets depending on some attribute of the record (e.g.
        Activity's ``activity_type``: meeting vs. task vs. event), so each
        variant gets its own independently saved field selection instead of
        one shared customization applied inconsistently across all of them.
        """
        return ""

    def _get_details_section_url_for_fields(self, object_id):
        """
        Infer the details section URL name from the tab view (when tab_url is set)
        so the Fields modal uses the same visible/excluded fields as the Details tab.
        Returns the URL name (e.g. "activity:activity_details_tab") or None.
        """
        from types import SimpleNamespace

        tab_url = getattr(self, "tab_url", None)
        if not tab_url:
            return None
        try:
            path = str(tab_url)
            resolved = resolve(path)
            tab_view_class = getattr(resolved.func, "view_class", None)
            if not tab_view_class:
                return None
            q = QueryDict(mutable=True)
            q.setlist("object_id", [str(object_id)])
            req = SimpleNamespace(GET=q, user=getattr(self.request, "user", None))
            view_inst = tab_view_class()
            view_inst.setup(req)
            return (getattr(view_inst, "urls", None) or {}).get("details")
        except Exception:
            return None

    def _build_navigation_context(self, context, current_id):
        """Populate context with previous/next record IDs from session queryset."""
        session_key = f"list_view_queryset_ids_{self.model._meta.model_name}"
        queryset_ids = self.request.session.get(session_key, [])
        if not queryset_ids:
            # Local imports
            from .list import HorillaListView

            list_view = HorillaListView()
            list_view.request = self.request
            list_view.model = self.model
            queryset = list_view.get_queryset()
            queryset_ids = list(queryset.values_list("id", flat=True))
            self.request.session[session_key] = queryset_ids
        try:
            current_index = queryset_ids.index(current_id)
        except ValueError:
            current_index = -1
        context["has_previous"] = current_index > 0
        context["has_next"] = current_index < len(queryset_ids) - 1
        context["previous_id"] = (
            queryset_ids[current_index - 1] if context["has_previous"] else None
        )
        context["next_id"] = (
            queryset_ids[current_index + 1] if context["has_next"] else None
        )

    def _build_pipeline_context(self, context):
        """Populate context with pipeline_field and its verbose name if visible."""
        effective_pf = self._get_effective_pipeline_field()
        if effective_pf:
            context["pipeline_field"] = effective_pf
            context["pipeline_field_verbose_name"] = self.model._meta.get_field(
                effective_pf
            ).verbose_name

    def _get_model_from_view_class(self, view_class):
        """Resolve the Django model associated with a generic list/nav/shell view."""
        if view_class is None:
            return None

        model = getattr(view_class, "model", None)
        if model is not None:
            return model

        model_name = getattr(view_class, "model_name", None)
        model_app_label = getattr(view_class, "model_app_label", None)
        if model_name and model_app_label:
            for candidate in (model_name, model_name.lower()):
                try:
                    return apps.get_model(model_app_label, candidate)
                except LookupError:
                    continue
        return None

    def _serialize_breadcrumb_label(self, label):
        """Convert breadcrumb labels to strings so they can be stored in session."""
        if label is None:
            return None
        if hasattr(label, "_meta"):
            return str(label)
        return force_str(label)

    def _serialize_breadcrumb_items(self, items):
        """Return breadcrumb tuples with JSON-serializable labels."""
        serialized = []
        for label, bc_url in items:
            serialized.append((self._serialize_breadcrumb_label(label), bc_url))
        return serialized

    def _get_referer_breadcrumb_label(self, referer_view, resolved):
        """Return a translated breadcrumb label for a non-detail referer view."""
        if referer_view is None:
            return force_str(_("Back"))

        model = self._get_model_from_view_class(referer_view)
        if model is not None:
            return force_str(model._meta.verbose_name_plural)

        list_url = getattr(referer_view, "list_url", None)
        if list_url:
            try:
                list_path = urlparse(str(list_url)).path
                list_resolved = resolve(list_path)
                list_view_class = getattr(list_resolved.func, "view_class", None)
                model = self._get_model_from_view_class(list_view_class)
                if model is not None:
                    return force_str(model._meta.verbose_name_plural)
            except Exception:
                pass

        if resolved and resolved.url_name:
            label = resolved.url_name.replace("_", " ").replace("-", " ").title()
            for suffix in (
                " View",
                " Detail",
                " List",
                " Create",
                " Update",
                " Delete",
            ):
                if label.endswith(suffix):
                    return label[: -len(suffix)]
            return label
        return force_str(_("Back"))

    def _resolve_breadcrumb_label_from_url(self, url):
        """Re-resolve a breadcrumb label from a stored URL in the active locale."""
        if not url:
            return None
        try:
            referer_path = urlparse(url).path
            resolved = resolve(referer_path)
            referer_view = (
                resolved.func.view_class
                if hasattr(resolved.func, "view_class")
                else None
            )
            return self._get_referer_breadcrumb_label(referer_view, resolved)
        except Exception:
            return None

    def _is_current_path(self, url):
        """Return True if url points at this request's path (same-page reload)."""
        if not url:
            return False
        return urlparse(url).path == self.request.path

    def _referer_url_from_value(self, url):
        """Normalize an absolute or relative referer to path + query."""
        if not url:
            return None
        parsed = urlparse(url)
        if not parsed.path or parsed.path == self.request.path:
            return None
        return parsed.path + (f"?{parsed.query}" if parsed.query else "")

    def _get_model_list_breadcrumb(self):
        """Fallback crumb to the model's list/section view."""
        label = force_str(self.model._meta.verbose_name_plural)
        try:
            section_info = get_section_info_for_model(self.model)
        except Exception:
            section_info = {}
        url = section_info.get("url") or ""
        if not url or url == "#":
            return (label, None)
        parsed = urlparse(str(url))
        query_dict = parse_qs(parsed.query)
        section = self.request.GET.get("section") or section_info.get("section")
        if section:
            query_dict["section"] = [section]
        session_url_value = self.request.GET.get("session_url")
        if session_url_value:
            query_dict["session_url"] = [session_url_value]
        new_query = urlencode(query_dict, doseq=True)
        return (label, urlunparse(parsed._replace(query=new_query)))

    def _restore_stored_breadcrumbs(self, stored_breadcrumbs, current_obj):
        """Rebuild breadcrumb tuples from session, re-translating list labels."""
        crumbs = []
        for label, bc_url in stored_breadcrumbs[:-1]:
            if bc_url:
                resolved_label = self._resolve_breadcrumb_label_from_url(bc_url)
                if resolved_label is not None:
                    label = resolved_label
            crumbs.append((label, bc_url))
        if not crumbs:
            list_crumb = self._get_model_list_breadcrumb()
            if list_crumb:
                crumbs.append(list_crumb)
        crumbs.append((current_obj, None))
        return crumbs

    def _build_breadcrumb_context(
        self, context, current_obj, current_id, detail_actions, resolved_url
    ):
        """
        Populate context with breadcrumbs and actions.
        Returns True if an early return should be performed by the caller
        (i.e. the request is a reload of the same page and stored breadcrumbs exist).
        """
        breadcrumbs_session_key = (
            f"detail_view_breadcrumbs_{self.model._meta.model_name}_{current_id}"
        )
        referer_session_key = (
            f"detail_referer_{self.model._meta.model_name}_{current_id}"
        )

        hx_current_url = self.request.headers.get("HX-Current-URL")
        is_htmx_request = self.request.headers.get("HX-Request") == "true"
        http_referer = self.request.META.get("HTTP_REFERER")
        stored_referer = self.request.session.get(referer_session_key)
        stored_breadcrumbs = self.request.session.get(breadcrumbs_session_key)

        # HTMX refresh of the same detail URL, or a full browser refresh.
        # A plain (non-htmx) GET is either a browser reload or a fresh visit
        # (typed/pasted URL, external link, bookmark): since this app
        # navigates via htmx pushState, document.referrer on such a request
        # reflects the last real full page load, not the current page, so
        # Referer can't be trusted to detect a reload here. Prefer the
        # already-stored breadcrumbs for this exact record when available.
        is_reload = self._is_current_path(hx_current_url) or (
            not hx_current_url
            and bool(
                (not is_htmx_request and stored_breadcrumbs)
                or self._is_current_path(http_referer)
            )
        )

        if is_reload and stored_breadcrumbs:
            restored = self._restore_stored_breadcrumbs(stored_breadcrumbs, current_obj)
            context["breadcrumbs"] = restored
            context["actions"] = detail_actions
            context["model_name"] = self.model._meta.model_name
            self.request.session[breadcrumbs_session_key] = (
                self._serialize_breadcrumb_items(restored)
            )
            self._build_pipeline_context(context)
            return True

        breadcrumbs = []
        referer = self._referer_url_from_value(hx_current_url)
        if referer:
            self.request.session[referer_session_key] = referer
        else:
            referer = self._referer_url_from_value(http_referer)
            if referer:
                self.request.session[referer_session_key] = referer
            elif stored_referer and not self._is_current_path(stored_referer):
                referer = stored_referer

        if referer:
            referer_path = urlparse(referer).path
            if referer_path != self.request.path:
                try:
                    resolved = resolve(referer_path)
                    referer_view = (
                        resolved.func.view_class
                        if hasattr(resolved.func, "view_class")
                        else None
                    )
                    is_detail_view = referer_view and issubclass(
                        referer_view, HorillaDetailView
                    )
                    if is_detail_view:
                        session_breadcrumbs = self.request.session.get(
                            "detail_view_breadcrumbs", []
                        )
                        breadcrumbs.extend(session_breadcrumbs)
                    else:
                        label = self._get_referer_breadcrumb_label(
                            referer_view, resolved
                        )
                        breadcrumbs.append((label, referer))
                except Exception:
                    breadcrumbs.append((force_str(_("Back")), referer))

        # The inherited trail may already end at the record we're now on (e.g.
        # the user clicked this record's own breadcrumb link to jump back to
        # it). Drop that trailing entry so it isn't duplicated when current_obj
        # is appended below.
        if breadcrumbs and self._is_current_path(breadcrumbs[-1][1]):
            breadcrumbs.pop()

        if not breadcrumbs:
            list_crumb = self._get_model_list_breadcrumb()
            if list_crumb:
                breadcrumbs.append(list_crumb)

        dynamic_breadcrumbs = breadcrumbs.copy()

        referrer_app = self.request.GET.get("referrer_app")
        referrer_model = self.request.GET.get("referrer_model")
        referrer_id = self.request.GET.get("referrer_id")
        referrer_label = self.request.GET.get("referrer_label")
        referrer_url = self.request.GET.get("referrer_url")

        if referrer_app and referrer_model and referrer_id:
            if not (
                referrer_model == self.model._meta.model_name
                and str(referrer_id) == str(current_id)
            ):
                try:
                    model_class = apps.get_model(
                        app_label=referrer_app, model_name=referrer_model
                    )
                    obj = model_class.objects.get(pk=referrer_id)
                    obj_title = (
                        str(obj)
                        if hasattr(obj, "__str__")
                        else referrer_label or f"{referrer_model} {referrer_id}"
                    )
                    breadcrumb_url = None
                    if referrer_url:
                        try:
                            breadcrumb_url = reverse(
                                f"{referrer_app}:{referrer_url}",
                                kwargs={"pk": referrer_id},
                            )
                            parsed_url = urlparse(breadcrumb_url)
                            query_dict = parse_qs(parsed_url.query)

                            section_for_breadcrumb = None
                            try:
                                section_info = get_section_info_for_model(model_class)
                                section_for_breadcrumb = section_info.get("section")
                            except Exception:
                                pass
                            if not section_for_breadcrumb:
                                section_for_breadcrumb = self.request.GET.get("section")
                            if section_for_breadcrumb:
                                query_dict["section"] = [section_for_breadcrumb]

                            new_query = urlencode(query_dict, doseq=True)
                            breadcrumb_url = urlunparse(
                                parsed_url._replace(query=new_query)
                            )
                        except Exception:
                            breadcrumb_url = None
                    # The trail inherited above (from the generic session key)
                    # may already end with this same referrer object, e.g. when
                    # Next/Previous echoes the original referrer_* params back
                    # on every click. Skip the append so repeated clicks don't
                    # keep stacking duplicate copies of the same crumb.
                    if not (breadcrumbs and breadcrumbs[-1][0] == obj_title):
                        breadcrumbs.append((obj_title, breadcrumb_url))
                        dynamic_breadcrumbs = breadcrumbs.copy()
                except (LookupError, model_class.DoesNotExist, ValueError):
                    if (
                        referrer_label
                        and referrer_url
                        and not (breadcrumbs and breadcrumbs[-1][0] == referrer_label)
                    ):
                        breadcrumbs.append((referrer_label, referrer_url))
                        dynamic_breadcrumbs = breadcrumbs.copy()

        dynamic_breadcrumbs.append((current_obj, None))

        session_url_value = self.request.GET.get("session_url")
        if session_url_value:
            updated_breadcrumbs = []
            for label, bc_url in dynamic_breadcrumbs:
                if bc_url:
                    try:
                        parsed_url = urlparse(bc_url)
                        query_dict = parse_qs(parsed_url.query)
                        query_dict["session_url"] = [session_url_value]
                        new_query = urlencode(query_dict, doseq=True)
                        bc_url = urlunparse(parsed_url._replace(query=new_query))
                    except Exception:
                        pass
                updated_breadcrumbs.append((label, bc_url))
            dynamic_breadcrumbs = updated_breadcrumbs

        self.request.session["detail_view_breadcrumbs"] = (
            self._serialize_breadcrumb_items(breadcrumbs)
        )
        self.request.session[breadcrumbs_session_key] = (
            self._serialize_breadcrumb_items(dynamic_breadcrumbs)
        )

        context["breadcrumbs"] = dynamic_breadcrumbs
        context["actions"] = detail_actions
        context["model_name"] = self.model._meta.model_name
        return False

    def get_context_data(self, **kwargs):
        """Add header_fields, body, pipeline_choices, badges, and permissions to context."""
        context = super().get_context_data(**kwargs)
        context["header_fields"] = self.get_header_fields()
        current_obj = self.get_object()
        # Support split layout flag coming from both GET (initial load)
        # and POST (e.g. pipeline updates via HTMX hx-vals)
        is_split_layout = (
            self.request.GET.get("layout") == "split"
            or self.request.POST.get("layout") == "split"
        )
        if is_split_layout:
            context["body"] = self.get_detail_section_body()
            context["split_detail_url"] = (
                current_obj.get_detail_url()
                if hasattr(current_obj, "get_detail_url")
                else None
            )
        else:
            context["body"] = self.get_body()
        context["fieldsets"] = self.get_fieldsets()
        context["pipeline_choices"] = self.get_pipeline_choices()
        current_id = current_obj.id
        context["tab_url"] = self.tab_url
        context["badges"] = self.get_badges()
        from horilla.contrib.core.utils import get_field_permissions_for_model

        field_permissions = get_field_permissions_for_model(
            self.request.user, self.model
        )
        context["can_update"] = self.check_update_permission()
        context["field_permissions"] = field_permissions
        if hasattr(self, "final_stage_action"):
            final_stage = self.final_stage_action
            if callable(final_stage):
                context["final_stage_action"] = final_stage()
            else:
                context["final_stage_action"] = final_stage
        else:
            context["final_stage_action"] = self.final_stage_action

        # Get custom pipeline colors if method exists
        if hasattr(self, "get_pipeline_custom_colors"):
            custom_colors = self.get_pipeline_custom_colors()
            if custom_colors:
                context["pipeline_custom_bg_color"] = custom_colors.get("bg_color")
                context["pipeline_custom_text_color"] = custom_colors.get("text_color")
                context["pipeline_custom_hover_color"] = custom_colors.get(
                    "hover_color"
                )

        self._build_navigation_context(context, current_id)

        resolved_url = resolve(self.request.path)
        context["url_name"] = resolved_url.url_name
        context["app_label"] = self.model._meta.app_label

        detail_actions = list(self.actions) if self.actions else []
        if is_split_layout and context.get("split_detail_url"):
            detail_actions = [
                {
                    "action": _("View full detail"),
                    "src": "assets/icons/eye1.svg",
                    "img_class": "w-4 h-4",
                    "attrs": (
                        f'hx-get="{context["split_detail_url"]}" '
                        'hx-target="#mainContent" hx-select="#mainContent" '
                        'hx-swap="outerHTML" hx-push-url="true" '
                        'hx-indicator="#loading-indicator"'
                    ),
                }
            ] + detail_actions
        if self.tab_url:
            visibility_scope = self.get_detail_field_visibility_scope(current_obj)
            visibility_url_name = (
                f"{resolved_url.url_name}:{visibility_scope}"
                if visibility_scope
                else resolved_url.url_name
            )
            context["detail_field_visibility_url_name"] = visibility_url_name
            change_fields_url = (
                f"{reverse('generics:detail_field_selector')}"
                f"?app_label={self.model._meta.app_label}&model_name={self.model._meta.model_name}&url_name={visibility_url_name}&pk={current_id}"
            )
            details_section_url = self._get_details_section_url_for_fields(current_id)
            if details_section_url:
                change_fields_url += (
                    f"&details_section_url={quote(details_section_url)}"
                )
            context["change_fields_url"] = change_fields_url

        if self._build_breadcrumb_context(
            context, current_obj, current_id, detail_actions, resolved_url
        ):
            return context

        self._build_pipeline_context(context)
        return context

    def post(self, request, *args, **kwargs):
        """
        Handle POST requests for updating the pipeline field.
        """
        if request.POST.get("pipeline_update"):
            model_name = request.POST.get("model_name")
            app_label = request.POST.get("app_label")
            pipeline_field = request.POST.get("pipeline_field")

            try:
                model = apps.get_model(app_label, model_name)
            except Exception as e:
                messages.error(self.request, e)
                return ScriptResponse(reload=True)

            view_class = self._view_registry.get(model, self.__class__)

            if view_class != self.__class__:
                view_instance = view_class()
                view_instance.request = self.request
                view_instance.args = self.args
                view_instance.kwargs = self.kwargs
                view_instance.model = model
                view_instance.pipeline_field = pipeline_field
                return view_instance.update_pipeline(request, *args, **kwargs)

            self.model = model
            self.pipeline_field = pipeline_field
            return self.update_pipeline(request, *args, **kwargs)

        return HttpResponse(status=400)

    def update_pipeline(self, request, *args, **kwargs):
        """
        Handle HTMX POST request to update the pipeline field value.
        Re-render the Kanban choices template with updated data.
        """
        self.object = self.get_object()
        if is_record_locked(self.object):
            messages.error(request, _("This record is read-only."))
            return HttpResponse(status=403)

        pipeline_value = request.POST.get("pipeline_value")
        if not pipeline_value:
            return HttpResponse(status=400)

        try:
            # Permission check
            user = request.user
            model_name = self.model._meta.model_name
            app_label = self.model._meta.app_label

            # Check if user is the owner
            is_owner = self._is_owner(self.object, user)

            # Check permissions
            has_permission = False

            if user.is_superuser:
                has_permission = True
            elif is_owner:
                # Check if user has change_own permission
                change_own_perm = f"{app_label}.change_own_{model_name}"
                if user.has_perm(change_own_perm):
                    has_permission = True

            # Check regular change permission if not owner or doesn't have change_own
            if not has_permission:
                change_perm = f"{app_label}.change_{model_name}"
                if user.has_perm(change_perm):
                    has_permission = True

            if not has_permission:
                messages.error(
                    self.request, _("You don't have permission to update this record.")
                )
                return ScriptResponse(reload=True)

            # Proceed with pipeline update
            field = self.model._meta.get_field(self.pipeline_field)
            if hasattr(field, "choices") and field.choices:
                # Validate for choice fields
                if pipeline_value not in [choice[0] for choice in field.choices]:
                    raise ValidationError(_("Invalid choice"))
                setattr(self.object, self.pipeline_field, pipeline_value)
            elif isinstance(field, ForeignKey):
                # Validate for ForeignKey fields
                related_model = field.related_model
                try:
                    related_obj = related_model.objects.get(pk=pipeline_value)
                    setattr(self.object, self.pipeline_field, related_obj)
                except Exception as e:
                    logger.error(e)
            else:
                return HttpResponse(status=400)

            self.object.save()
            messages.success(
                self.request,
                _(f"{self.model._meta.verbose_name} Stage Updated Successfully"),
            )
            if request.POST.get("layout") == "split":
                context = self.get_context_data(object=self.object)
                context["body"] = self.get_detail_section_body()
                # Use detail view's url name and namespace for prev/next links (request.path
                # is update_pipeline here, which would break {% url app_label:url_name %}).
                if hasattr(self.object, "get_detail_url"):
                    try:
                        detail_path = str(self.object.get_detail_url())
                        if detail_path:
                            resolved = resolve(detail_path)
                            context["url_name"] = resolved.url_name
                            ns = getattr(resolved, "namespace", None) or getattr(
                                resolved, "app_name", None
                            )
                            if ns:
                                context["app_label"] = ns
                    except Exception:
                        pass
                html = render_to_string(
                    "detail_view_split_fragment.html",
                    context,
                    request=self.request,
                )
                return HttpResponse(html)
            context = self.get_context_data(object=self.object)
            context["pipeline_update"] = True
            kanban_html = render_to_string(
                "partials/pipeline_choices.html", context, request=self.request
            )
            return HttpResponse(kanban_html)
        except Exception as e:
            messages.error(self.request, e)
            return ScriptResponse(reload=True)


class HorillaModalDetailView(DetailView):
    """
    HorillDetailedView
    """

    title = _("Detailed View")
    template_name = "single_detail_view.html"
    # No profile header unless the view sets one ({"title", "subtitle", "avatar"}).
    header: dict = {}
    body: list = []

    action_method: list = []
    actions: list = []
    cols: dict = {}
    instance = None
    empty_template = None

    ids_key: str = "instance_ids"

    def get_queryset(self):
        """
        Filter queryset based on instance_ids from session.
        """
        queryset = super().get_queryset()
        instance_ids = self.request.session.get(self.ordered_ids_key, [])
        if instance_ids:
            queryset = queryset.filter(pk__in=instance_ids)
        return queryset

    def get_object(self, queryset=None):
        """Resolve the current object from queryset and store on self.instance."""
        if queryset is None:
            queryset = self.get_queryset()
        try:
            self.instance = super().get_object(queryset)
        except Exception as e:
            logger.error("Error getting object: %s", e)
        return self.instance

    def get(self, request, *args, **kwargs):
        """Initialize session ordered_ids if needed; render empty template or error when no instance."""
        if not self.request.GET.get(self.ids_key) and not self.request.session.get(
            self.ordered_ids_key
        ):
            self.request.session[self.ordered_ids_key] = []
        response = super().get(request, *args, **kwargs)
        if not self.instance and self.empty_template:
            return render(request, self.empty_template, context=self.get_context_data())
        if not self.instance:
            messages.error(request, _("The requested record does not exist."))
            return ScriptResponse(extra="closeDetailModal();", reload=True)
        return response

    def setup(self, request, *args, **kwargs):
        """Bind request (Django) and session key for ordered instance navigation."""
        super().setup(request, *args, **kwargs)
        if self.model is not None:
            self.ordered_ids_key = f"ordered_ids_{self.model.__name__.lower()}"

    def get_context_data(self, **kwargs: Any):
        """Add ordered instance_ids and navigation data for prev/next to context."""
        context = super().get_context_data(**kwargs)
        obj = context.get("object")

        if not obj:
            return context

        pk = obj.pk
        instance_ids = self.request.session.get(self.ordered_ids_key, [])
        url_info = resolve(self.request.path)
        url_name = url_info.url_name
        key = next(iter(url_info.kwargs), "pk")

        context["instance"] = obj
        context["title"] = self.title
        context["header"] = self.header
        context["body"] = self.get_body_fields()
        context["actions"] = self.actions
        context["action_method"] = self.action_method
        context["cols"] = self.cols

        if instance_ids:
            prev_id, next_id = closest_numbers(instance_ids, pk)

            full_url_name = (
                f"{url_info.namespaces[0]}:{url_name}"
                if url_info.namespaces
                else url_name
            )
            context.update(
                {
                    "instance_ids": str(instance_ids),
                    "ids_key": self.ids_key,
                    "has_previous": pk in instance_ids and instance_ids.index(pk) > 0,
                    "has_next": pk in instance_ids
                    and instance_ids.index(pk) < len(instance_ids) - 1,
                    "next_url": reverse_lazy(full_url_name, kwargs={key: next_id}),
                    "previous_url": reverse_lazy(full_url_name, kwargs={key: prev_id}),
                }
            )

            # Filter out instance_ids key from GET params
            get_params = self.request.GET.copy()
            get_params.pop(self.ids_key, None)
            context["extra_query"] = get_params.urlencode()
        else:
            context["extra_query"] = ""

        return context

    def get_body_fields(self):
        """
        Normalize modal body fields.
        - If an entry is (label, field_name), keep provided label, unless
          label is itself a model field name, in which case resolve and
          use that field's verbose_name.
        - If an entry is "field_name", resolve and use model verbose_name.
        - If an entry is "get_<field_name>_display", resolve the verbose
          name from the underlying <field_name>.
        - If an entry names a method/property with a `short_description`
          attribute (Django admin convention), use that as the label.
        """
        normalized = []
        instance = self.model()

        for field in self.body:
            if isinstance(field, (list, tuple)) and len(field) >= 2:
                label = field[0]
                field_name = field[1]
                extra = tuple(field[2:]) if len(field) > 2 else ()
                if isinstance(label, str):
                    try:
                        label = instance._meta.get_field(label).verbose_name
                    except FieldDoesNotExist:
                        pass
                normalized.append((label, field_name, *extra))
                continue

            field_name = field
            short_description = getattr(
                getattr(instance, field_name, None), "short_description", None
            )
            if short_description:
                normalized.append((str(short_description), field_name))
                continue

            lookup_name = field_name
            if lookup_name.startswith("get_") and lookup_name.endswith("_display"):
                lookup_name = lookup_name[len("get_") : -len("_display")]

            try:
                model_field = instance._meta.get_field(lookup_name)
                label = model_field.verbose_name
            except FieldDoesNotExist:
                label = str(field_name).replace("_", " ").title()

            normalized.append((label, field_name))

        return normalized
