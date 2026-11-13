"""
List column visibility and selector views for horilla.contrib.generics.

Utilities and views for resolving default columns and column visibility selection.
"""

# Standard library imports
import inspect
import logging
import re
from urllib.parse import urlparse

# Third-party imports (Django)
from django.contrib import messages
from django.core.cache import cache
from django.core.exceptions import FieldDoesNotExist
from django.db.models.fields import Field
from django.template import Context, Template
from django.utils import translation
from django.utils.encoding import force_str

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.models import ListColumnVisibility
from horilla.contrib.core.utils import filter_hidden_fields
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import FormView, View
from horilla.web import HttpResponse, JsonResponse, ScriptResponse

from ...forms import ColumnSelectionForm

# Local imports
from ..list import HorillaListView

logger = logging.getLogger(__name__)


def _get_path_context(request):
    """Return the path context string used as a key for column visibility lookups.

    Prefers HX-Current-URL (the real browser URL during HTMX requests) over
    HTTP_REFERER so that modals opened from navbar/sub-views still resolve to
    the correct page context.
    """
    hx_current = request.headers.get("HX-Current-URL", "")
    url = hx_current or request.META.get("HTTP_REFERER", "")
    path_context = urlparse(url).path.strip("/").replace("/", "_")
    return re.sub(r"_\d+$", "", path_context)


def _get_generic_fk_component_fields(model):
    """Return the ct_field/fk_field names backing any GenericForeignKey on model.

    These (e.g. content_type/object_id) are implementation details of a GFK
    like related_object and shouldn't be offered as separate columns when the
    GFK itself is already a selectable field.
    """
    component_fields = set()
    for f in model._meta.get_fields():
        ct_field = getattr(f, "ct_field", None)
        fk_field = getattr(f, "fk_field", None)
        if ct_field and fk_field:
            component_fields.add(ct_field)
            component_fields.add(fk_field)
    return component_fields


def get_default_columns_from_view(url_name, app_label, model_name, request):
    """
    Get default columns from the view class based on URL name.

    Args:
        url_name: The URL name
        app_label: The app label
        model_name: The model name
        request: The request object (for getting URL resolver)

    Returns:
        List of default column field names, or None if view cannot be resolved
    """
    try:
        from horilla.urls import get_resolver

        # Get the URL resolver
        resolver = get_resolver()
        view_func = None

        # Try to find the URL pattern by name
        # URL name might be in format 'app:name' or just 'name'
        if ":" in url_name:
            app_name, pattern_name = url_name.split(":", 1)
        else:
            pattern_name = url_name
            app_name = None

        def find_pattern_by_name(patterns, target_name, target_app=None):
            """Recursively search for URL pattern by name"""
            for pattern in patterns:
                # Check if this pattern matches
                pattern_app = getattr(pattern, "app_name", None)
                pattern_name_attr = getattr(pattern, "name", None)

                if pattern_name_attr == target_name:
                    if target_app is None or pattern_app == target_app:
                        return getattr(pattern, "callback", None)

                # Recursively search nested patterns
                if hasattr(pattern, "url_patterns"):
                    result = find_pattern_by_name(
                        pattern.url_patterns, target_name, target_app
                    )
                    if result:
                        return result
            return None

        view_func = find_pattern_by_name(resolver.url_patterns, pattern_name, app_name)

        if not view_func:
            return None

        # Get the view class
        if hasattr(view_func, "view_class"):
            view_class = view_func.view_class
        elif hasattr(view_func, "cls"):
            view_class = view_func.cls
        elif inspect.isclass(view_func):
            view_class = view_func
        else:
            return None

        # Check if it's a HorillaListView and has columns defined
        if issubclass(view_class, HorillaListView):
            try:
                apps.get_model(app_label=app_label, model_name=model_name)

                if hasattr(view_class, "columns") and view_class.columns:
                    columns = view_class.columns
                    default_field_names = []
                    for col in columns:
                        if isinstance(col, (list, tuple)) and len(col) >= 2:
                            default_field_names.append(col[1])
                        elif isinstance(col, str):
                            default_field_names.append(col)
                    return default_field_names
            except Exception as e:
                logger.debug("Error getting columns from view: %s", str(e))
                return None
    except Exception as e:
        logger.debug("Error resolving URL name %s: %s", url_name, str(e))
        return None


def _resolve_list_view_class(url_name):
    """Resolve a url_name to its HorillaListView subclass, or None."""
    try:
        from horilla.urls import get_resolver

        resolver = get_resolver()
        if ":" in url_name:
            app_name, pattern_name = url_name.split(":", 1)
        else:
            pattern_name = url_name
            app_name = None

        def _find(patterns, name, app):
            for p in patterns:
                if getattr(p, "name", None) == name:
                    if app is None or getattr(p, "app_name", None) == app:
                        return getattr(p, "callback", None)
                if hasattr(p, "url_patterns"):
                    r = _find(p.url_patterns, name, app)
                    if r:
                        return r
            return None

        view_func = _find(resolver.url_patterns, pattern_name, app_name)
        if not view_func:
            return None
        view_class = getattr(view_func, "view_class", None) or getattr(
            view_func, "cls", None
        )
        if not view_class or not issubclass(view_class, HorillaListView):
            return None
        return view_class
    except Exception as e:
        logger.debug("Error resolving view class for %s: %s", url_name, str(e))
        return None


def get_view_exclude_columns(url_name):
    """Return the resolved view's declared ``exclude_columns``, or an empty list.

    Lets any HorillaListView scope down the model-field fallback in the column
    selector (e.g. a shared model backing several distinct sub-types) using the
    same ``exclude_columns`` attribute it already uses for auto-generated columns.
    """
    view_class = _resolve_list_view_class(url_name)
    if view_class is None:
        return []
    return list(getattr(view_class, "exclude_columns", None) or [])


def get_view_columns(url_name, app_label, model_name):
    """Return the full [[label, field_name], ...] column list from a view class.

    Used to populate the column selector with the view-defined columns (including
    method-based columns like status_col, related_object) that don't exist on the
    model's _meta field list.
    """
    try:
        view_class = _resolve_list_view_class(url_name)
        if view_class is None:
            return None
        columns = getattr(view_class, "columns", None)
        if not columns:
            return None

        model = None
        try:
            model = apps.get_model(app_label=app_label, model_name=model_name)
        except Exception:
            model = None

        def _resolve_verbose_name(name):
            """Look up a field's verbose_name, unwrapping get_x_display first."""
            if model is None:
                return None
            lookup_name = name
            if lookup_name.startswith("get_") and lookup_name.endswith("_display"):
                lookup_name = lookup_name[len("get_") : -len("_display")]
            try:
                field = model._meta.get_field(lookup_name)
                return force_str(field.verbose_name)
            except Exception:
                return None

        result = []
        # Force English so the stored label is the stable key {% trans %}
        # re-translates at render time, not whatever language is active now.
        with translation.override("en"):
            for col in columns:
                if isinstance(col, (list, tuple)) and len(col) >= 2:
                    # col[0] is often the underlying field name (snake_case),
                    # not a real display label (e.g. ("status", "status_col")).
                    # Resolve it to the model field's verbose_name when it
                    # matches one; otherwise keep the tuple's own label as-is.
                    label = col[0]
                    if isinstance(label, str) and label == label.lower():
                        verbose_name = _resolve_verbose_name(label)
                        if verbose_name is not None:
                            label = verbose_name
                    result.append([force_str(label), col[1]])
                elif isinstance(col, str):
                    verbose_name = _resolve_verbose_name(col)
                    if verbose_name is None:
                        verbose_name = col.replace("_", " ").title()
                    result.append([verbose_name, col])
        return result
    except Exception as e:
        logger.debug("Error in get_view_columns for %s: %s", url_name, str(e))
        return None

    return None


@method_decorator(htmx_required, name="dispatch")
class ListColumnSelectFormView(LoginRequiredMixin, FormView):
    """View for selecting and adding columns to list views."""

    template_name = "add_column_to_list.html"
    form_class = ColumnSelectionForm

    def dispatch(self, request, *args, **kwargs):
        """Require view permission before configuring related-list columns."""
        url_name = request.POST.get("url_name", request.GET.get("url_name"))
        if url_name == "related_list_content":
            app_label = request.POST.get("app_label", request.GET.get("app_label"))
            model_name = request.POST.get("model_name", request.GET.get("model_name"))
            if app_label and model_name:
                user = request.user
                if not user.is_superuser and not user.has_perm(
                    f"{app_label}.view_{model_name.lower()}"
                ):
                    messages.error(
                        request,
                        _(
                            "You don't have permission to configure columns for this list."
                        ),
                    )
                    return ScriptResponse(msgs=True, reload=True, close=True)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        """Pass model, app_label, path_context, user, and url_name to the column selection form."""
        kwargs = super().get_form_kwargs()
        app_label = self.request.POST.get(
            "app_label", self.request.GET.get("app_label")
        )
        model_name = self.request.POST.get(
            "model_name", self.request.GET.get("model_name")
        )
        url_name = self.request.POST.get("url_name", self.request.GET.get("url_name"))
        model_name = model_name.strip('"') if model_name else model_name
        if model_name and "." in model_name:
            model_name = model_name.split(".")[-1]

        path_context = _get_path_context(self.request)
        user = self.request.user

        if app_label and model_name and url_name:
            try:
                model = apps.get_model(app_label=app_label, model_name=model_name)
                kwargs["model"] = model
                kwargs["app_label"] = app_label
                kwargs["path_context"] = path_context
                kwargs["user"] = user
                kwargs["model_name"] = model_name
                kwargs["url_name"] = url_name
            except LookupError:
                self.form_error = "Invalid model specified."
        return kwargs

    def get_context_data(self, **kwargs):
        """Add app_label, model_name, url_name, path_context, and column visibility data to context."""
        context = super().get_context_data(**kwargs)
        app_label = self.request.GET.get(
            "app_label", self.request.POST.get("app_label")
        )
        model_name = self.request.GET.get(
            "model_name", self.request.POST.get("model_name")
        )
        url_name = self.request.GET.get("url_name", self.request.POST.get("url_name"))

        model_name = model_name.strip('"') if model_name else model_name
        if model_name and "." in model_name:
            model_name = model_name.split(".")[-1]
        path_context = _get_path_context(self.request)
        context["app_label"] = app_label
        context["model_name"] = model_name
        context["url_name"] = url_name

        visible_fields = []
        all_fields = []
        removed_custom_field_lists = []
        visibility = None
        model = None
        view_exclude_columns = set()

        if app_label and model_name:
            try:
                model = apps.get_model(app_label=app_label, model_name=model_name)
                instance = model()
                generic_fk_component_fields = _get_generic_fk_component_fields(model)
                # A view's exclude_columns scopes down the model-field fallback
                # below, so a model shared by several distinct list views (e.g.
                # one view per sub-type) only offers the fields relevant to it.
                view_exclude_columns = (
                    set(get_view_exclude_columns(url_name)) if url_name else set()
                )
                model_fields = [
                    [
                        force_str(f.verbose_name or f.name.title()),
                        (
                            f.name
                            if not getattr(f, "choices", None)
                            else f"get_{f.name}_display"
                        ),
                    ]
                    for f in model._meta.get_fields()
                    if isinstance(f, Field)
                    and f.name not in ["history"]
                    and f.name not in generic_fk_component_fields
                    and f.name not in view_exclude_columns
                ]
                all_fields = (
                    getattr(instance, "columns", model_fields)
                    if hasattr(instance, "columns")
                    else model_fields
                )

                # When a url_name is provided, put the view's declared columns
                # first (they're the ones the list is currently built around),
                # but still fall back to the full model field list so fields
                # outside the view's default columns remain selectable as
                # "Available Fields".
                if url_name:
                    view_cols = get_view_columns(url_name, app_label, model_name)
                    if view_cols:
                        seen_field_names = {
                            f[1]
                            for f in view_cols
                            if isinstance(f, (list, tuple)) and len(f) >= 2
                        }
                        # A view column (e.g. status_col) can carry the same
                        # label as the model field it customizes (e.g. Status
                        # from a get_x_display fallback). The view's column
                        # is authoritative for display, so drop the
                        # model-derived entry instead of listing both.
                        seen_labels = {
                            force_str(f[0]).strip().casefold()
                            for f in view_cols
                            if isinstance(f, (list, tuple)) and len(f) >= 2
                        }
                        all_fields = list(view_cols) + [
                            f
                            for f in model_fields
                            if isinstance(f, (list, tuple))
                            and len(f) >= 2
                            and f[1] not in seen_field_names
                            and force_str(f[0]).strip().casefold() not in seen_labels
                        ]

                # Filter out hidden fields based on field permissions
                if all_fields:
                    field_names = [
                        f[1]
                        for f in all_fields
                        if isinstance(f, (list, tuple)) and len(f) >= 2
                    ]

                    # filter_hidden_fields now handles display methods internally
                    visible_field_names_from_perms = filter_hidden_fields(
                        self.request.user, model, field_names
                    )

                    # Filter all_fields - only keep fields that are visible
                    filtered_all_fields = []
                    for f in all_fields:
                        field_name = (
                            f[1]
                            if isinstance(f, (list, tuple)) and len(f) >= 2
                            else None
                        )
                        if field_name and field_name in visible_field_names_from_perms:
                            filtered_all_fields.append(f)

                    all_fields = filtered_all_fields

                session_key = (
                    f"visible_fields_{app_label}_{model_name}_{path_context}_{url_name}"
                )
                visibility = ListColumnVisibility.all_objects.filter(
                    user=self.request.user,
                    app_label=app_label,
                    model_name=model_name,
                    context=path_context,
                    url_name=url_name,
                ).first()
                if visibility:
                    visible_fields = visibility.visible_fields
                    # Filter out hidden fields from visible_fields as well
                    if visible_fields:
                        visible_field_names_list = [
                            f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f
                            for f in visible_fields
                        ]
                        visible_field_names_from_perms = filter_hidden_fields(
                            self.request.user, model, visible_field_names_list
                        )
                        visible_fields = [
                            f
                            for f in visible_fields
                            if (
                                f[1]
                                if isinstance(f, (list, tuple)) and len(f) >= 2
                                else f
                            )
                            in visible_field_names_from_perms
                        ]

                    # Get removed_custom_field_lists and filter hidden fields
                    removed_custom_field_lists = visibility.removed_custom_fields or []
                else:
                    # No saved record — populate visible_fields from the view's default columns
                    if url_name:
                        default_field_names = get_default_columns_from_view(
                            url_name, app_label, model_name, self.request
                        )
                        if default_field_names:
                            all_fields_map = {
                                f[1]: f[0]
                                for f in all_fields
                                if isinstance(f, (list, tuple)) and len(f) >= 2
                            }
                            visible_fields = [
                                [
                                    all_fields_map.get(
                                        fn, fn.replace("_", " ").title()
                                    ),
                                    fn,
                                ]
                                for fn in default_field_names
                                if fn in all_fields_map
                            ]
                    # Filter out hidden fields from removed_custom_field_lists
                    if removed_custom_field_lists:
                        removed_field_names = [
                            f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f
                            for f in removed_custom_field_lists
                        ]
                        visible_removed_field_names = filter_hidden_fields(
                            self.request.user, model, removed_field_names
                        )
                        removed_custom_field_lists = [
                            f
                            for f in removed_custom_field_lists
                            if (
                                f[1]
                                if isinstance(f, (list, tuple)) and len(f) >= 2
                                else f
                            )
                            in visible_removed_field_names
                        ]

                self.request.session[session_key] = [
                    f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f
                    for f in visible_fields
                ]
                self.request.session.modified = True
            except LookupError:
                context["error"] = "Invalid model specified."

        # Keep the selector in sync with the list view's company-column handling
        # (see HorillaListColumnMixin._add_company_column_if_needed): the company
        # column is only shown when "all companies" is enabled.
        company_names = ("company", "company__name")
        if model:
            if self.request.session.get("show_all_companies", False):
                try:
                    company_field = model._meta.get_field("company")
                except FieldDoesNotExist:
                    company_field = None
                if company_field is not None and url_name:
                    has_company = any(
                        isinstance(f, (list, tuple))
                        and len(f) >= 2
                        and f[1] in company_names
                        for f in visible_fields
                    )
                    company_removed = any(
                        isinstance(f, (list, tuple))
                        and len(f) >= 2
                        and f[1] == "company__name"
                        for f in removed_custom_field_lists
                    )
                    if (
                        not has_company
                        and not company_removed
                        and "company" not in view_exclude_columns
                    ):
                        visible_fields = list(visible_fields) + [
                            [
                                force_str(
                                    getattr(company_field, "verbose_name", "Company")
                                ),
                                "company__name",
                            ]
                        ]
            else:
                visible_fields = [
                    f
                    for f in visible_fields
                    if not (
                        isinstance(f, (list, tuple))
                        and len(f) >= 2
                        and f[1] in company_names
                    )
                ]
                all_fields = [
                    f
                    for f in all_fields
                    if not (
                        isinstance(f, (list, tuple))
                        and len(f) >= 2
                        and f[1] in company_names
                    )
                ]
                removed_custom_field_lists = [
                    f
                    for f in removed_custom_field_lists
                    if not (
                        isinstance(f, (list, tuple))
                        and len(f) >= 2
                        and f[1] in company_names
                    )
                ]

        context["visible_fields"] = visible_fields

        visible_field_names = [
            f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f
            for f in visible_fields
        ]
        # For choice fields: view/store uses raw name (e.g. role) but all_fields
        # uses get_x_display; treat both as visible so the field does not appear in both panels
        visible_field_names_set = set(visible_field_names)
        for name in visible_field_names:
            visible_field_names_set.add(f"get_{name}_display")
        for name in list(visible_field_names_set):
            if name.startswith("get_") and name.endswith("_display"):
                raw = name[4:-8]  # strip get_ and _display
                visible_field_names_set.add(raw)

        related_field_parents = set()
        for _, field_name in visible_fields + removed_custom_field_lists:
            if isinstance(field_name, (list, tuple)) and len(field_name) >= 2:
                field_name = field_name[1]
            if "__" in str(field_name):
                parent_field = str(field_name).split("__", maxsplit=1)[0]
                related_field_parents.add(parent_field)
        exclude_fields = self.request.GET.get("exclude")
        exclude_fields_list = exclude_fields.split(",") if exclude_fields else []
        context["exclude_fields"] = exclude_fields
        sensitive_fields = ["id", "additional_info"]

        # Build available_fields - all_fields and removed_custom_field_lists are already filtered for hidden fields
        # But do one final check to ensure no hidden fields slip through.
        # A removed view column (e.g. status_col) is also in all_fields; list it once.
        all_field_names = {
            f[1] for f in all_fields if isinstance(f, (list, tuple)) and len(f) >= 2
        }
        combined_fields = all_fields + [
            f
            for f in removed_custom_field_lists
            if (f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f)
            not in all_field_names
        ]

        if model and combined_fields:
            # Final safety check: filter hidden fields one more time
            combined_field_names = [
                f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f
                for f in combined_fields
            ]

            # filter_hidden_fields now handles display methods internally
            visible_combined_field_names = filter_hidden_fields(
                self.request.user, model, combined_field_names
            )

            # Only include fields that passed the permission check
            filtered_combined_fields = []
            for f in combined_fields:
                field_name = f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f
                if field_name in visible_combined_field_names:
                    filtered_combined_fields.append(f)

            combined_fields = filtered_combined_fields

        context["available_fields"] = [
            [verbose_name, field_name]
            for verbose_name, field_name in combined_fields
            if field_name not in visible_field_names_set
            and field_name not in related_field_parents
            and field_name not in exclude_fields_list
            and field_name not in sensitive_fields
        ]

        has_custom_visibility = False
        if app_label and model_name and model and url_name:
            view_default_field_names = get_default_columns_from_view(
                url_name, app_label, model_name, self.request
            )

            if view_default_field_names is None:
                view_default_field_names = []
                for f in all_fields:
                    if isinstance(f, (list, tuple)) and len(f) >= 2:
                        view_default_field_names.append(f[1])

            session_key = (
                f"visible_fields_{app_label}_{model_name}_{path_context}_{url_name}"
            )
            session_field_names = self.request.session.get(session_key, [])

            if session_field_names:
                current_field_names = session_field_names
            else:
                current_field_names = []
                for f in visible_fields:
                    if isinstance(f, (list, tuple)) and len(f) >= 2:
                        current_field_names.append(f[1])
                    elif isinstance(f, str):
                        current_field_names.append(f)

            has_removed_fields = bool(removed_custom_field_lists)

            default_set = set(view_default_field_names)
            current_set = set(current_field_names)

            has_added_fields = bool(current_set - default_set)
            has_removed_default_fields = bool(default_set - current_set)
            # Same fields but different order counts as custom (so "Reset to Default" shows)
            default_list = (
                list(view_default_field_names) if view_default_field_names else []
            )
            has_order_changed = (
                default_set == current_set
                and len(current_field_names) == len(default_list)
                and current_field_names != default_list
            )

            has_custom_visibility = (
                has_removed_fields
                or has_added_fields
                or has_removed_default_fields
                or has_order_changed
            )

        context["has_custom_visibility"] = has_custom_visibility

        if hasattr(self, "form_error"):
            context["error"] = self.form_error
        return context

    def form_valid(self, form):
        """Save selected visible columns and return JSON/HTMX response."""
        with translation.override("en"):
            app_label = self.request.POST.get("app_label")
            model_name = self.request.POST.get("model_name")
            url_name = self.request.POST.get("url_name")
            if model_name and "." in model_name:
                model_name = model_name.split(".")[-1]
            field_names = self.request.POST.getlist("visible_fields")

            if not app_label or not model_name:
                return JsonResponse(
                    {
                        "status": "error",
                        "message": "Missing app_label or model_name",
                        "htmx": '<div id="error-message">Missing app_label or model_name</div>',
                    }
                )

            path_context = _get_path_context(self.request)
            try:
                model = apps.get_model(app_label=app_label, model_name=model_name)

                # Filter out hidden fields from field_names before processing
                if field_names:
                    field_names = filter_hidden_fields(
                        self.request.user, model, field_names
                    )
                instance = model()
                generic_fk_component_fields = _get_generic_fk_component_fields(model)
                # A view's exclude_columns scopes down the model-field fallback
                # below, so a model shared by several distinct list views (e.g.
                # one view per sub-type) only offers the fields relevant to it.
                view_exclude_columns = (
                    set(get_view_exclude_columns(url_name)) if url_name else set()
                )
                model_fields = [
                    [
                        force_str(f.verbose_name or f.name.title()),
                        (
                            f.name
                            if not getattr(f, "choices", None)
                            else f"get_{f.name}_display"
                        ),
                    ]
                    for f in model._meta.get_fields()
                    if isinstance(f, Field)
                    and f.name not in ["history"]
                    and f.name not in generic_fk_component_fields
                    and f.name not in view_exclude_columns
                ]
                all_fields = (
                    getattr(instance, "columns", model_fields)
                    if hasattr(instance, "columns")
                    else model_fields
                )

                # Put the view's declared columns first, but still fall back
                # to the full model field list so fields outside the view's
                # default columns resolve to a correct verbose name.
                if url_name:
                    view_cols = get_view_columns(url_name, app_label, model_name)
                    if view_cols:
                        seen_field_names = {
                            f[1]
                            for f in view_cols
                            if isinstance(f, (list, tuple)) and len(f) >= 2
                        }
                        # A view column (e.g. status_col) can carry the same
                        # label as the model field it customizes (e.g. Status
                        # from a get_x_display fallback). The view's column
                        # is authoritative for display, so drop the
                        # model-derived entry instead of listing both.
                        seen_labels = {
                            force_str(f[0]).strip().casefold()
                            for f in view_cols
                            if isinstance(f, (list, tuple)) and len(f) >= 2
                        }
                        all_fields = list(view_cols) + [
                            f
                            for f in model_fields
                            if isinstance(f, (list, tuple))
                            and len(f) >= 2
                            and f[1] not in seen_field_names
                            and force_str(f[0]).strip().casefold() not in seen_labels
                        ]

                # Filter out hidden fields based on field permissions
                if all_fields:
                    field_names_list = [
                        f[1]
                        for f in all_fields
                        if isinstance(f, (list, tuple)) and len(f) >= 2
                    ]
                    visible_field_names_from_perms = filter_hidden_fields(
                        self.request.user, model, field_names_list
                    )
                    all_fields = [
                        f
                        for f in all_fields
                        if (
                            f[1]
                            if isinstance(f, (list, tuple)) and len(f) >= 2
                            else None
                        )
                        in visible_field_names_from_perms
                    ]

                all_field_names = {item[1] for item in all_fields}
                visibility = ListColumnVisibility.all_objects.filter(
                    user=self.request.user,
                    app_label=app_label,
                    model_name=model_name,
                    context=path_context,
                    url_name=url_name,
                ).first()
                custom_fields = []
                if visibility:
                    visible_fields_from_db = visibility.visible_fields
                    # Filter visible_fields from DB to exclude hidden fields
                    if visible_fields_from_db:
                        visible_field_names_list = [
                            f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f
                            for f in visible_fields_from_db
                        ]
                        visible_field_names_from_perms = filter_hidden_fields(
                            self.request.user, model, visible_field_names_list
                        )
                        visible_fields_from_db = [
                            f
                            for f in visible_fields_from_db
                            if (
                                f[1]
                                if isinstance(f, (list, tuple)) and len(f) >= 2
                                else f
                            )
                            in visible_field_names_from_perms
                        ]

                    for display_name, field_name in visible_fields_from_db:
                        if field_name not in all_field_names and field_name not in [
                            f[1]
                            for f in model_fields
                            if isinstance(f, (list, tuple)) and len(f) >= 2
                        ]:
                            custom_fields.append([display_name, field_name])
                all_fields = all_fields + custom_fields
                verbose_name_map = {f[1]: f[0] for f in all_fields}

                # Include removed custom fields in the verbose name map to preserve original display names
                removed_custom_field_lists = (
                    visibility.removed_custom_fields if visibility else []
                )
                # Filter out hidden fields from removed_custom_field_lists
                if removed_custom_field_lists:
                    removed_field_names = [
                        f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f
                        for f in removed_custom_field_lists
                    ]
                    visible_removed_field_names = filter_hidden_fields(
                        self.request.user, model, removed_field_names
                    )
                    removed_custom_field_lists = [
                        f
                        for f in removed_custom_field_lists
                        if (f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f)
                        in visible_removed_field_names
                    ]

                for display_name, field_name in removed_custom_field_lists:
                    verbose_name_map[field_name] = display_name

                model_field_names = {
                    f.name for f in model._meta.get_fields() if isinstance(f, Field)
                }

                visible_fields = [
                    [force_str(verbose_name_map.get(f, f.replace("_", " ").title())), f]
                    for f in field_names
                ]

                previous_visible_fields = (
                    visibility.visible_fields if visibility else []
                )
                previous_non_model_fields = [
                    f[1]
                    for f in previous_visible_fields
                    if f[1] not in model_field_names and not f[1].startswith("get_")
                ]
                removed_non_model_fields = [
                    [force_str(verbose_name_map.get(f, f.replace("_", " ").title())), f]
                    for f in previous_non_model_fields
                    if f not in field_names
                ]

                existing_removed = (
                    visibility.removed_custom_fields if visibility else []
                )
                # Only add to removed_custom_fields if not already there
                for removed_field in removed_non_model_fields:
                    if not any(
                        existing[1] == removed_field[1] for existing in existing_removed
                    ):
                        existing_removed.append(removed_field)

                # The company column is auto-added when "all companies" is on;
                # remember an explicit removal so it is not added back.
                if (
                    self.request.session.get("show_all_companies", False)
                    and "company" not in field_names
                    and "company__name" not in field_names
                    and "company" in model_field_names
                    and not any(e[1] == "company__name" for e in existing_removed)
                ):
                    existing_removed.append(["Company", "company__name"])

                # Remove fields from removed_custom_fields if they're being added back
                updated_removed_custom_fields = [
                    field for field in existing_removed if field[1] not in field_names
                ]

                session_key = (
                    f"visible_fields_{app_label}_{model_name}_{path_context}_{url_name}"
                )
                self.request.session[session_key] = field_names
                self.request.session.modified = True

                ListColumnVisibility.all_objects.filter(
                    user=self.request.user,
                    app_label=app_label,
                    model_name=model_name,
                    context=path_context,
                    url_name=url_name,
                ).delete()
                ListColumnVisibility.all_objects.create(
                    user=self.request.user,
                    app_label=app_label,
                    model_name=model_name,
                    visible_fields=visible_fields,
                    removed_custom_fields=updated_removed_custom_fields,
                    context=path_context,
                    url_name=url_name,
                )

                cache_key = f"visible_columns_{self.request.user.id}_{app_label}_{model_name}_{path_context}_{url_name}"
                cache.delete(cache_key)

                return ScriptResponse(reload=True, close=True)
            except LookupError:
                return JsonResponse(
                    {
                        "status": "error",
                        "message": "Invalid model",
                        "htmx": '<div id="error-message">Invalid model</div>',
                    }
                )

    def form_invalid(self, form):
        """Render form with error message when column selection is invalid."""
        context = self.get_context_data(form=form)
        context["error"] = "Form submission failed. Please review the selected fields."
        return self.render_to_response(context)


@method_decorator(htmx_required, name="dispatch")
class ResetColumnToDefaultView(LoginRequiredMixin, View):
    """View for resetting column visibility to default settings."""

    def post(self, request, *args, **kwargs):
        """
        Reset column visibility to default by deleting ListColumnVisibility record.

        Expects query parameters: app_label, model_name, url_name
        """
        app_label = request.POST.get("app_label") or request.GET.get("app_label")
        model_name = request.POST.get("model_name") or request.GET.get("model_name")
        url_name = request.POST.get("url_name") or request.GET.get("url_name")

        if not app_label or not model_name:
            return HttpResponse(
                "<div id='error-message'>Missing app_label or model_name</div>",
                status=400,
            )

        # Clean model_name if it contains app_label
        model_name = model_name.strip('"') if model_name else model_name
        if model_name and "." in model_name:
            model_name = model_name.split(".")[-1]

        path_context = _get_path_context(request)

        try:
            ListColumnVisibility.all_objects.filter(
                user=request.user,
                app_label=app_label,
                model_name=model_name,
                context=path_context,
                url_name=url_name,
            ).delete()

            session_key = (
                f"visible_fields_{app_label}_{model_name}_{path_context}_{url_name}"
            )
            if session_key in request.session:
                del request.session[session_key]
                request.session.modified = True

            cache_key = (
                f"visible_columns_{request.user.id}_{app_label}_{model_name}_"
                f"{path_context}_{url_name}"
            )
            cache.delete(cache_key)

            # Return response that reloads the page
            return ScriptResponse(reload=True, close=True)
        except Exception as e:
            logger.error("Error resetting columns to default: %s", str(e))
            msg = Template(
                "<div id='error-message'>Error resetting columns: {{ message }}</div>"
            ).render(Context({"message": str(e)}))
            return HttpResponse(msg, status=500)
