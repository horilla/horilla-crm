"""
Detail field visibility and selector views for horilla.contrib.generics.

HTMX views for detail field visibility and column selector modals.
"""

# Standard library imports
import logging

# Third-party imports (Django)
from django.db.models.fields import Field
from django.utils.encoding import force_str

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.models import DetailFieldVisibility
from horilla.contrib.core.utils import filter_hidden_fields
from horilla.shortcuts import render
from horilla.urls import resolve, reverse
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.views.generic import View
from horilla.web import HttpResponse, ScriptResponse

# Local imports
from ..details import SPLIT_VISIBILITY_URL_NAME, HorillaDetailView

logger = logging.getLogger(__name__)


def _ensure_json_serializable(fields_list):
    """Convert all values to plain str for JSON serialization (avoids lazy __proxy__)."""
    return [[str(v), str(n)] for v, n in fields_list]


def get_detail_field_defaults_no_request(model):
    """
    Get default header_fields and details_fields without request (for signals).
    When request is None, section view resolution may fall back to model fields.
    """
    return _get_detail_field_defaults(model, None)


def _get_detail_field_defaults(model, request):
    """Get default header_fields and details_fields for a model's detail view."""
    default_header = []
    default_details = []

    detail_view_class = HorillaDetailView._view_registry.get(model)
    if detail_view_class:
        # Use view's effective excluded fields (base_excluded_fields + excluded_fields)
        base = getattr(detail_view_class, "base_excluded_fields", None)
        extra = getattr(detail_view_class, "excluded_fields", [])
        if base is not None:
            excluded = set(base) | set(extra or [])
        else:
            excluded = (
                set(extra)
                if extra
                else {
                    "id",
                    "created_at",
                    "updated_at",
                    "history",
                    "is_active",
                    "additional_info",
                }
            )
        if request is not None and request.session.get("show_all_companies", False):
            excluded = set(excluded) - {"company"}
        # Automatically exclude pipeline_field from header and details
        pf = getattr(detail_view_class, "pipeline_field", None)
        if pf:
            excluded = excluded | {str(pf)}
        body = getattr(detail_view_class, "body", [])
        try:
            default_header = [
                [force_str(model._meta.get_field(f).verbose_name), str(f)]
                for f in body
                if f not in excluded
            ]
        except Exception:
            default_header = []
        details_url = getattr(detail_view_class, "details_section_url_name", None)
        if not details_url and request:
            details_url = request.GET.get("details_section_url") or None
        if details_url:
            try:
                resolved = resolve(reverse(details_url, kwargs={"pk": 1}))
                section_view = getattr(resolved.func, "view_class", None)
                if section_view:
                    view_inst = section_view()
                    view_inst.request = request
                    view_inst.model = model
                    raw_details = view_inst.get_default_body()
                    default_details = _ensure_json_serializable(raw_details)
                    # Automatically exclude pipeline_field (section view may not have it in GET)
                    if pf and default_details:
                        default_details = [
                            f
                            for f in default_details
                            if (
                                f[1]
                                if isinstance(f, (list, tuple)) and len(f) >= 2
                                else f
                            )
                            != str(pf)
                        ]
                else:
                    raise ValueError("No section view")
            except Exception:
                default_details = [
                    [force_str(f.verbose_name), str(f.name)]
                    for f in model._meta.get_fields()
                    if isinstance(f, Field)
                    and f.name not in excluded
                    and hasattr(f, "verbose_name")
                ]
        else:
            # Use detail view's effective excluded (already base + child excluded_fields); pipeline_field already in excluded
            default_details = [
                [force_str(f.verbose_name), str(f.name)]
                for f in model._meta.get_fields()
                if isinstance(f, Field)
                and f.name not in excluded
                and hasattr(f, "verbose_name")
            ]
    else:
        # No registered detail view; use HorillaDetailView base_excluded_fields
        excluded = set(HorillaDetailView.base_excluded_fields)
        default_header = default_details = [
            [force_str(f.verbose_name), str(f.name)]
            for f in model._meta.get_fields()
            if isinstance(f, Field)
            and f.name not in excluded
            and hasattr(f, "verbose_name")
        ]
    default_header = _ensure_json_serializable(default_header)
    return default_header, default_details


@method_decorator(htmx_required, name="dispatch")
class DetailFieldSelectorView(LoginRequiredMixin, View):
    """View for selecting header and details fields in detail views."""

    template_name = "add_field_to_detail.html"

    def get(self, request, *args, **kwargs):
        """Load detail field selector form for the given model and url_name."""
        app_label = request.GET.get("app_label")
        model_name = request.GET.get("model_name")
        url_name = request.GET.get("url_name")
        model_name = model_name.strip('"') if model_name else model_name
        if model_name and "." in model_name:
            model_name = model_name.split(".")[-1]
        if not app_label or not model_name or not url_name:
            return HttpResponse(
                '<div id="error-message" class="p-4 text-red-600">Missing app_label, model_name or url_name</div>',
                status=200,
            )
        try:
            model = apps.get_model(app_label=app_label, model_name=model_name)
        except LookupError:
            return HttpResponse(
                '<div id="error-message" class="p-4 text-red-600">Invalid model or app label</div>',
                status=200,
            )

        model()
        base_excluded = {
            "id",
            "created_at",
            "updated_at",
            "history",
            "is_active",
            "additional_info",
            "created_by",
            "updated_by",
        }
        # The company field is only offered when "all companies" is enabled.
        if not request.session.get("show_all_companies", False):
            base_excluded.add("company")
        header_excluded = set(base_excluded)
        details_excluded = set(base_excluded)

        detail_view_class = HorillaDetailView._view_registry.get(model)

        allowed_field_names = None
        default_header = None
        default_details = None
        if detail_view_class and hasattr(
            detail_view_class, "get_available_fields_for_selector"
        ):
            result = detail_view_class.get_available_fields_for_selector(request, model)
            if result:
                default_header, default_details, allowed_field_names = result

        if detail_view_class:
            header_excluded.update(getattr(detail_view_class, "excluded_fields", []))
            pf = getattr(detail_view_class, "pipeline_field", None)
            if pf:
                pf_str = str(pf)
                header_excluded.add(pf_str)
                details_excluded.add(pf_str)
            details_url = getattr(detail_view_class, "details_section_url_name", None)
            if not details_url:
                details_url = request.GET.get("details_section_url") or None
            details_excluded_override = getattr(
                detail_view_class, "details_excluded_fields", None
            )
            if details_url:
                try:
                    resolved = resolve(reverse(details_url, kwargs={"pk": 1}))
                    section_view = getattr(resolved.func, "view_class", None)
                    if section_view:
                        view_inst = section_view()
                        view_inst.request = request
                        view_inst.model = model
                        details_excluded.update(
                            view_inst.get_excluded_fields()
                            if hasattr(view_inst, "get_excluded_fields")
                            else getattr(view_inst, "excluded_fields", [])
                        )
                except Exception:
                    details_excluded.update(header_excluded)
            elif details_excluded_override is not None:
                details_excluded.update(details_excluded_override)
            else:
                details_excluded.update(
                    getattr(detail_view_class, "excluded_fields", [])
                )

        if request.session.get("show_all_companies", False):
            header_excluded.discard("company")
            details_excluded.discard("company")

        all_model_fields = [
            [force_str(f.verbose_name or f.name.title()), f.name]
            for f in model._meta.get_fields()
            if isinstance(f, Field)
            and f.name not in ["history"]
            and f.name not in base_excluded
            and (allowed_field_names is None or f.name in allowed_field_names)
        ]

        field_names = [f[1] for f in all_model_fields]
        visible = filter_hidden_fields(request.user, model, field_names)
        all_model_fields = [f for f in all_model_fields if f[1] in visible]

        if default_header is None or default_details is None:
            default_header, default_details = _get_detail_field_defaults(model, request)

        visibility = DetailFieldVisibility.all_objects.filter(
            user=request.user,
            app_label=app_label,
            model_name=model_name,
            url_name=url_name,
        ).first()
        header_fields = (
            visibility.header_fields
            if visibility and visibility.header_fields
            else default_header
        )
        details_fields = (
            visibility.details_fields
            if visibility and visibility.details_fields
            else default_details
        )

        def resolve_verbose_names(fields_list):
            """Resolve verbose_name from model for current request language."""
            result = []
            for f in fields_list:
                fn = f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f
                try:
                    mf = model._meta.get_field(str(fn))
                    result.append([mf.verbose_name, str(fn)])
                except Exception:
                    result.append(
                        [f[0] if isinstance(f, (list, tuple)) else str(fn), str(fn)]
                    )
            return result

        header_fields = resolve_verbose_names(header_fields)
        details_fields = resolve_verbose_names(details_fields)
        header_fields = [f for f in header_fields if f[1] not in header_excluded]
        details_fields = [f for f in details_fields if f[1] not in details_excluded]
        header_field_names_list = [f[1] for f in header_fields]
        details_field_names_list = [f[1] for f in details_fields]
        visible_header_names = filter_hidden_fields(
            request.user, model, header_field_names_list
        )
        visible_details_names = filter_hidden_fields(
            request.user, model, details_field_names_list
        )
        header_fields = [f for f in header_fields if f[1] in visible_header_names]
        details_fields = [f for f in details_fields if f[1] in visible_details_names]

        if allowed_field_names is not None:
            header_fields = [f for f in header_fields if f[1] in allowed_field_names]
            details_fields = [f for f in details_fields if f[1] in allowed_field_names]

        header_field_names = {f[1] for f in header_fields}
        details_field_names = {f[1] for f in details_fields}
        header_available = []
        details_available = []
        for _, fn in all_model_fields:
            try:
                vn = model._meta.get_field(fn).verbose_name
                if fn not in header_field_names and fn not in header_excluded:
                    header_available.append([vn, fn])
                if fn not in details_field_names and fn not in details_excluded:
                    details_available.append([vn, fn])
            except Exception:
                pass

        has_custom = False
        if visibility and (visibility.header_fields or visibility.details_fields):

            def _field_names(fields):
                return [
                    f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else str(f)
                    for f in (fields or [])
                ]

            saved_header_names = _field_names(visibility.header_fields)
            saved_details_names = _field_names(visibility.details_fields)
            default_header_names = _field_names(default_header)
            default_details_names = _field_names(default_details)
            has_custom = (
                saved_header_names != default_header_names
                or saved_details_names != default_details_names
            )

        return render(
            request,
            self.template_name,
            {
                "app_label": app_label,
                "model_name": model_name,
                "url_name": url_name,
                "header_fields": header_fields,
                "header_available": header_available,
                "details_fields": details_fields,
                "details_available": details_available,
                "has_custom_visibility": has_custom,
            },
        )


@method_decorator(htmx_required, name="dispatch")
class ResetDetailFieldsView(LoginRequiredMixin, View):
    """Reset detail view fields to default."""

    def post(self, request, *args, **kwargs):
        """Delete saved detail field visibility for the given model/url_name and return reload script."""
        app_label = request.POST.get("app_label")
        model_name = request.POST.get("model_name")
        url_name = request.POST.get("url_name")
        if model_name and "." in model_name:
            model_name = model_name.split(".")[-1]
        if app_label and model_name and url_name:
            DetailFieldVisibility.all_objects.filter(
                user=request.user,
                app_label=app_label,
                model_name=model_name,
                url_name=url_name,
            ).delete()
        return ScriptResponse(extra="closeContentModal();", reload=True)


@method_decorator(htmx_required, name="dispatch")
class SaveDetailFieldsView(LoginRequiredMixin, View):
    """Save header and details field order in one request (no per-move requests)."""

    def post(self, request, *args, **kwargs):
        """Save header and details field order and return reload script."""
        app_label = request.POST.get("app_label")
        model_name = request.POST.get("model_name")
        url_name = request.POST.get("url_name")
        header_field_names = request.POST.getlist("header_fields")
        details_field_names = request.POST.getlist("details_fields")
        if model_name and "." in model_name:
            model_name = model_name.split(".")[-1]
        if not app_label or not model_name or not url_name:
            return HttpResponse(status=400)
        try:
            model = apps.get_model(app_label=app_label, model_name=model_name)
        except LookupError:
            return HttpResponse(status=400)
        header_field_names = filter_hidden_fields(
            request.user, model, header_field_names
        )
        details_field_names = filter_hidden_fields(
            request.user, model, details_field_names
        )
        all_model_fields = {
            f.name: force_str(f.verbose_name or f.name.title())
            for f in model._meta.get_fields()
            if isinstance(f, Field) and f.name not in ["history"]
        }
        header_fields = [
            [all_model_fields.get(fn, fn.replace("_", " ").title()), fn]
            for fn in header_field_names
        ]
        details_fields = [
            [all_model_fields.get(fn, fn.replace("_", " ").title()), fn]
            for fn in details_field_names
        ]
        default_header, default_details = _get_detail_field_defaults(model, request)
        visibility, _ = DetailFieldVisibility.all_objects.get_or_create(
            user=request.user,
            app_label=app_label,
            model_name=model_name,
            url_name=url_name,
            defaults={
                "header_fields": default_header,
                "details_fields": default_details,
            },
        )
        visibility.header_fields = _ensure_json_serializable(header_fields)
        visibility.details_fields = _ensure_json_serializable(details_fields)
        visibility.save()
        return ScriptResponse(extra="closeContentModal();", reload=True)


@method_decorator(htmx_required, name="dispatch")
class SplitColumnSelectorView(LoginRequiredMixin, View):
    """Add/remove/reorder the fields shown in the split view's detail panel."""

    template_name = "add_column_to_split.html"

    def _get_model(self, data):
        app_label = data.get("app_label")
        model_name = data.get("model_name")
        model_name = model_name.strip('"') if model_name else model_name
        if model_name and "." in model_name:
            model_name = model_name.split(".")[-1]
        if not app_label or not model_name:
            return None
        try:
            return apps.get_model(app_label=app_label, model_name=model_name)
        except (LookupError, ValueError):
            return None

    def _selectable_fields(self, request, model):
        """Return [[verbose_name, field_name], ...] mirroring the split panel's defaults."""
        excluded = {
            "id",
            "created_at",
            "updated_at",
            "history",
            "is_active",
            "additional_info",
            "created_by",
            "updated_by",
        }
        if not request.session.get("show_all_companies", False):
            excluded.add("company")
        view_class = HorillaDetailView._view_registry.get(model)
        if view_class:
            for attr in (
                "base_excluded_fields",
                "excluded_fields",
                "split_excluded_fields",
            ):
                excluded.update(getattr(view_class, attr, None) or [])
            pipeline_field = getattr(view_class, "pipeline_field", None)
            if pipeline_field:
                excluded.add(str(pipeline_field))
        if request.session.get("show_all_companies", False):
            excluded.discard("company")
        fields = [
            [force_str(f.verbose_name or f.name.title()), f.name]
            for f in model._meta.get_fields()
            if isinstance(f, Field)
            and hasattr(f, "verbose_name")
            and getattr(f, "editable", True)
            and f.name not in excluded
        ]
        visible = filter_hidden_fields(request.user, model, [f[1] for f in fields])
        fields = [f for f in fields if f[1] in visible]
        try:
            from horilla.contrib.field_management.utils.custom_fields import (
                custom_field_form_name,
                get_custom_field_definitions,
                safe_custom_field_label,
            )

            fields += [
                [force_str(safe_custom_field_label(defn)), custom_field_form_name(defn)]
                for defn in get_custom_field_definitions(model)
            ]
        except Exception:  # field_management unavailable or model without custom fields
            logger.debug("No custom fields for %s", model, exc_info=True)
        return fields

    def get(self, request, *args, **kwargs):
        """Render the column selector for the split view."""
        model = self._get_model(request.GET)
        if model is None:
            return HttpResponse(
                '<div id="error-message" class="p-4 text-red-600">Invalid model or app label</div>',
                status=200,
            )
        all_fields = self._selectable_fields(request, model)
        labels = {name: label for label, name in all_fields}
        visibility = DetailFieldVisibility.all_objects.filter(
            user=request.user,
            app_label=model._meta.app_label,
            model_name=model._meta.model_name,
            url_name=SPLIT_VISIBILITY_URL_NAME,
        ).first()
        saved = visibility.details_fields if visibility else []
        saved_names = [
            str(f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f)
            for f in saved or []
        ]
        has_custom = bool(saved_names)
        visible_names = [n for n in saved_names if n in labels] or [
            name for _label, name in all_fields
        ]
        visible_fields = [[labels[n], n] for n in visible_names]
        available_fields = [f for f in all_fields if f[1] not in set(visible_names)]
        return render(
            request,
            self.template_name,
            {
                "app_label": model._meta.app_label,
                "model_name": model._meta.model_name,
                "url_name": SPLIT_VISIBILITY_URL_NAME,
                "visible_fields": visible_fields,
                "available_fields": available_fields,
                "has_custom_visibility": has_custom,
            },
        )

    def post(self, request, *args, **kwargs):
        """Save the chosen split-view fields (order preserved) and reload."""
        model = self._get_model(request.POST)
        if model is None:
            return HttpResponse(status=400)
        if request.POST.get("reset"):
            DetailFieldVisibility.all_objects.filter(
                user=request.user,
                app_label=model._meta.app_label,
                model_name=model._meta.model_name,
                url_name=SPLIT_VISIBILITY_URL_NAME,
            ).delete()
            return ScriptResponse(close=True, reload=True)
        allowed = {
            name: label for label, name in self._selectable_fields(request, model)
        }
        fields = [
            [allowed[name], name]
            for name in request.POST.getlist("visible_fields")
            if name in allowed
        ]
        visibility, _created = DetailFieldVisibility.all_objects.get_or_create(
            user=request.user,
            app_label=model._meta.app_label,
            model_name=model._meta.model_name,
            url_name=SPLIT_VISIBILITY_URL_NAME,
        )
        visibility.details_fields = _ensure_json_serializable(fields)
        visibility.save()
        return ScriptResponse(extra="closeModal();", reload=True)
