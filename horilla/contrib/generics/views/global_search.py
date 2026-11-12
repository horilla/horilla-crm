"""
Global search utilities for horilla.contrib.generics.

Provides a GlobalSearchView that performs cross-model searches and renders
search results and model-specific tabs for the generic global search UI.
"""

# Standard library imports
import logging
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

# Third-party imports (Django)
from django.template.loader import render_to_string

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin

# Local imports
from horilla.contrib.generics.search_support import (
    PRESET_FILTER_LABELS,
    apply_preset_filter,
    build_field_labels,
    resolve_lookup_label,
)
from horilla.contrib.utils.methods import get_section_info_for_model
from horilla.db.models import CharField, Q, TextField
from horilla.registry.feature import FEATURE_REGISTRY, get_feature_options
from horilla.shortcuts import redirect, render
from horilla.urls import reverse_lazy
from horilla.views.generic import View
from horilla.web import HttpResponse, safe_url

from .helpers.queryset_utils import filter_viewable_queryset
from .list import HorillaListView

logger = logging.getLogger(__name__)


class GlobalSearchView(LoginRequiredMixin, View):
    """View for performing cross-model global searches across registered models."""

    template_name = "global_search.html"

    @classmethod
    def get_include_models(cls):
        """
        Models registered for global search, read from the feature registry at call time.

        Must not be cached on the class: registration runs in AppConfig.ready() after
        URL/view imports, so reading FEATURE_REGISTRY at import time leaves an empty
        list and global search would always return no results.
        """
        return list(FEATURE_REGISTRY.get("global_search_models", []))

    # Standard fields to exclude from column display
    exclude_standard_fields = [
        "is_active",
        "additional_info",
        "company",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
        "history",
        "id",
        "password",
    ]

    default_icons = {
        "bg_color": "bg-blue-100",
        "text_color": "text-blue-600",
        "icon": "fas fa-table",
    }

    def get_first_5_text_columns(self, model):
        """Get FIRST 5 text-based columns (CharField and TextField) for a model."""
        columns = []

        for field in model._meta.fields:
            # Skip auto-created fields, excluded standard fields, and relations
            if (
                field.auto_created
                or field.name in self.exclude_standard_fields
                or field.is_relation
            ):
                continue

            # Only include CharField and TextField
            if isinstance(field, (CharField, TextField)):
                columns.append([str(field.verbose_name), field.name])

                # Limit to first 5 columns
                if len(columns) >= 5:
                    break

        return columns

    quick_filter_labels = PRESET_FILTER_LABELS

    def apply_quick_filter(self, model, queryset, request):
        """
        Narrow a queryset by the ``qf`` quick filter (see ``PRESET_FILTER_LABELS``).

        Models that cannot satisfy a filter return nothing so they drop out of the
        results.
        """
        return apply_preset_filter(model, queryset, request.user, request.GET.get("qf"))

    @staticmethod
    def build_search_q(config, query, field=None):
        """
        Build the OR query for a model's search fields.

        When ``field`` is one of the model's search fields, only that field is
        searched; otherwise every search field is used.
        """
        fields = (
            [field] if field in config["search_fields"] else config["search_fields"]
        )
        q_objects = Q()
        for name in fields:
            q_objects |= Q(**{f"{name}__icontains": query})
        return q_objects

    def get_configured_fields(self, model):
        """
        Search fields, result columns and field labels for a model.

        Uses the model's global_search feature options (``search_fields`` and
        ``columns``, see horilla.registry.feature) and falls back to the first 5 text fields for
        anything not configured. Invalid names are logged and skipped.
        """
        settings = get_feature_options("global_search", model)

        search_fields = []
        custom_labels = {}
        for entry in settings.get("search_fields") or []:
            # An entry is "lookup" or ("Label", "lookup").
            custom_label, lookup = (
                entry if isinstance(entry, (list, tuple)) else (None, entry)
            )
            if resolve_lookup_label(model, lookup) is None:
                logger.warning(
                    "Global search: '%s' is not a field of %s; ignored.",
                    lookup,
                    model.__name__,
                )
                continue
            search_fields.append(lookup)
            if custom_label:
                custom_labels[lookup] = str(custom_label)

        labels = build_field_labels(model, search_fields)
        labels.update(custom_labels)

        if not search_fields:
            for field in model._meta.fields:
                if (
                    isinstance(field, (CharField, TextField))
                    and field.name not in self.exclude_standard_fields
                    and not field.auto_created
                    and not field.is_relation
                ):
                    search_fields.append(field.name)
                    labels[field.name] = str(field.verbose_name)
                    if len(search_fields) >= 5:
                        break

        columns = []
        for entry in settings.get("columns") or []:
            label, name = entry if isinstance(entry, (list, tuple)) else (None, entry)
            try:
                field = model._meta.get_field(name)
            except Exception:
                logger.warning(
                    "Global search: column '%s' is not a field of %s; ignored.",
                    name,
                    model.__name__,
                )
                continue
            columns.append([label or str(field.verbose_name), name])

        if not columns:
            direct = [
                [labels[name], name] for name in search_fields if "__" not in name
            ]
            columns = direct[:5] or self.get_first_5_text_columns(model)

        return search_fields, columns, labels

    def get_dynamic_model_config(self):
        """
        Build configuration for included models used in global search.

        Scans installed models and returns a mapping containing searchable fields,
        display columns, icons and other metadata required for rendering model
        search tabs and results.
        """
        model_config = {}
        all_models = apps.get_models()

        include_models = self.get_include_models()
        include_models_lower = [
            model._meta.model_name.lower() for model in include_models
        ]

        for model in all_models:
            app_label = model._meta.app_label
            model_name = model._meta.model_name.capitalize()
            model_verbose_name = (
                model._meta.verbose_name_plural or model._meta.verbose_name
            )

            if model_name.lower() not in include_models_lower:
                continue

            search_fields, display_columns, field_labels = self.get_configured_fields(
                model
            )

            if not search_fields or not display_columns:
                continue

            model_config[model_name] = {
                "app_name": app_label,
                "search_fields": search_fields,
                "icons": self.default_icons,
                "columns": display_columns,
                "field_labels": field_labels,
                "verbose_name": model_verbose_name,
            }

        return model_config

    def get_tab_content(self, request, model_name, query):
        """Generate tab content for a specific model"""
        model_config = self.get_dynamic_model_config()

        if model_name not in model_config:
            return '<div class="p-4">Model not found.</div>'

        config = model_config[model_name]
        model = apps.get_model(config["app_name"], model_name)

        q_objects = self.build_search_q(config, query, request.GET.get("field"))

        results = model.objects.filter(q_objects)

        results = filter_viewable_queryset(request.user, model, results)
        results = self.apply_quick_filter(model, results, request)

        list_view = HorillaListView()
        list_view.request = request
        list_view.view_id = f"global-search-{model_name.lower()}"
        list_view.model = model
        list_view.queryset = results
        list_view.kwargs = {}
        list_view.paginate_by = 100
        list_view.object_list = results
        list_view.bulk_select_option = False
        list_view.search_url = reverse_lazy("generics:global_search")
        list_view.list_column_visibility = False
        list_view.columns = config["columns"]

        # Models expose their detail page as get_detail_url or get_detail_view_url.
        detail_attr = next(
            (
                name
                for name in ("get_detail_url", "get_detail_view_url")
                if hasattr(model, name)
            ),
            None,
        )
        if config["columns"] and detail_attr:
            first_column_field = config["columns"][0][1]
            htmx_attrs = self.get_col_attrs_for_model(model_name, request, detail_attr)
            list_view.col_attrs = [
                {
                    first_column_field: {
                        "style": "cursor:pointer",
                        "class": "hover:text-primary-600",
                        **htmx_attrs,
                    }
                }
            ]

        query_params = request.GET.copy()
        if "page" in query_params:
            del query_params["page"]

        table_context = list_view.get_context_data()
        table_context.update(
            {
                "search_params": query_params.urlencode(),
                "model_name": model_name,
                "icons": config["icons"],
                "view_id": f"global-search-{model_name.lower()}",
            }
        )

        return render_to_string("list_view.html", table_context, request)

    def get(self, request):
        """
        Handle GET requests to perform and route global search queries.

        Validates the incoming query, manages previous URL/session state, and
        either redirects back to previous page when no query is provided or
        renders the global search results.
        """
        query = request.GET.get("q", "").strip()
        filter_type = request.GET.get("filter", "all")
        previous_url = request.GET.get("prev_url", "/")
        search_url_path = str(reverse_lazy("generics:global_search"))

        if previous_url:
            try:
                previous_url = unquote(unquote(previous_url))
                previous_url = safe_url(request, previous_url, "/")

                if "?" in previous_url:
                    parsed = urlparse(previous_url)
                    query_params = parse_qs(parsed.query)

                    if "section" in query_params:
                        del query_params["section"]

                    new_query = urlencode(query_params, doseq=True)
                    previous_url = urlunparse(
                        (
                            parsed.scheme,
                            parsed.netloc,
                            parsed.path,
                            parsed.params,
                            new_query,
                            parsed.fragment,
                        )
                    )

                if (
                    previous_url.startswith(search_url_path)
                    or "global_search" in previous_url
                ):
                    previous_url = request.session.get("pre_search_url", "/")
                else:
                    request.session["pre_search_url"] = previous_url
            except Exception:
                previous_url = request.session.get("pre_search_url", "/")

        quick_filter = request.GET.get("qf")
        if quick_filter not in self.quick_filter_labels:
            quick_filter = ""

        if not query and not quick_filter:
            section = request.GET.get("section")
            if section:
                # Add section back to previous_url
                if "?" in previous_url:
                    previous_url += f"&section={section}"
                else:
                    previous_url += f"?section={section}"
            if request.headers.get("HX-Request"):
                response = HttpResponse()
                response["HX-Redirect"] = previous_url
                return response
            return redirect(previous_url)

        if request.headers.get("HX-Request"):
            tab_model = request.GET.get("tab_model")
            if tab_model and (query or quick_filter):
                return HttpResponse(self.get_tab_content(request, tab_model, query))

        model_config = self.get_dynamic_model_config()

        context = {
            "query": query,
            "quick_filter": quick_filter,
            "quick_filter_label": self.quick_filter_labels.get(quick_filter, ""),
            "total_results": 0,
            "model_config": model_config,
            "search_results": {},
            "first_tab_content": "",
            "previous_url": previous_url,
        }

        if query or quick_filter:
            result_counts = {}
            results_by_model = {}
            total_results = 0
            first_tab_content = ""
            first_model_name = None

            for model_name, config in model_config.items():
                model = apps.get_model(config["app_name"], model_name)

                q_objects = self.build_search_q(config, query, request.GET.get("field"))

                results = model.objects.filter(q_objects)

                results = filter_viewable_queryset(request.user, model, results)
                results = self.apply_quick_filter(model, results, request)

                count = results.count()
                if count > 0:
                    results_by_model[model_name] = results
                    result_counts[model_name] = count
                    total_results += count

            sorted_search_results_with_data = dict(
                sorted(
                    results_by_model.items(),
                    key=lambda item: result_counts[item[0]],
                    reverse=True,
                )
            )

            if sorted_search_results_with_data:
                first_model_name = list(sorted_search_results_with_data.keys())[0]
                first_tab_content = self.get_tab_content(
                    request, first_model_name, query
                )

            if filter_type != "all":
                model_name_filtered = filter_type.capitalize()
                if model_name_filtered in sorted_search_results_with_data:
                    sorted_search_results_with_data = {
                        model_name_filtered: sorted_search_results_with_data[
                            model_name_filtered
                        ]
                    }
                    first_model_name = model_name_filtered
                    first_tab_content = self.get_tab_content(
                        request, first_model_name, query
                    )
                else:
                    sorted_search_results_with_data = {}
                    first_tab_content = ""
                    first_model_name = None

            context.update(
                {
                    "search_results": sorted_search_results_with_data,
                    "total_results": total_results,
                    "first_tab_content": first_tab_content,
                }
            )

        return render(request, self.template_name, context)

    def get_col_attrs_for_model(
        self, model_name, request, detail_attr="get_detail_url"
    ):
        """Generate col_attrs for the first column of each model"""
        query_params = request.GET.dict()
        filtered_params = {}
        if "q" in query_params:
            filtered_params["q"] = query_params["q"]
        if "filter" in query_params:
            filtered_params["filter"] = query_params["filter"]
        # Always open the detail page inside its own section so the section's
        # side menu loads, even when the search was started without a section.
        section = get_section_info_for_model(model_name)
        if section.get("section"):
            filtered_params["section"] = section["section"]
        query_string = urlencode(filtered_params)

        htmx_attrs = {
            "hx-get": f"{{{detail_attr}}}?{query_string}",
            "hx-target": "#mainContent",
            "hx-swap": "outerHTML",
            "hx-push-url": "true",
            "hx-select": "#mainContent",
            "hx-select-oob": "#sideMenuContainer",
            "hx-on:click": "$('#header-search').val('')",
        }
        return htmx_attrs


class GlobalSearchSuggestView(GlobalSearchView):
    """
    Live suggestions for the header search box.

    Returns an HTML fragment with one row per model that has matches (with a
    count). A model can be expanded to search a
    single field of that model. Visibility follows ``filter_viewable_queryset`` so
    users only see counts and records they are allowed to open.
    """

    template_name = "global_search_suggest.html"
    min_query_length = 2

    def get(self, request):
        """Render the suggestion dropdown for the current query."""
        query = request.GET.get("q", "").strip()
        if len(query) < self.min_query_length:
            return HttpResponse("")

        expand = request.GET.get("expand", "")
        model_config = self.get_dynamic_model_config()

        rows = []
        for model_name, config in model_config.items():
            model = apps.get_model(config["app_name"], model_name)
            queryset = filter_viewable_queryset(
                request.user,
                model,
                model.objects.filter(self.build_search_q(config, query)),
            )
            count = queryset.count()
            if not count:
                continue

            row = {
                "name": model_name,
                "filter": model_name.lower(),
                "verbose_name": config["verbose_name"],
                "count": count,
                "expanded": model_name == expand,
            }

            if row["expanded"]:
                row["fields"] = []
                for field_name in config["search_fields"]:
                    field_count = filter_viewable_queryset(
                        request.user,
                        model,
                        model.objects.filter(
                            self.build_search_q(config, query, field_name)
                        ),
                    ).count()
                    row["fields"].append(
                        {
                            "name": field_name,
                            "label": config["field_labels"].get(field_name, field_name),
                            "count": field_count,
                        }
                    )
            rows.append(row)

        rows.sort(key=lambda r: r["count"], reverse=True)
        context = {
            "query": query,
            "rows": rows,
            "total": sum(r["count"] for r in rows),
            "prev_url": request.GET.get("prev_url", "/"),
        }
        return render(request, self.template_name, context)
