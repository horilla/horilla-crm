"""
Mixins for horilla.contrib.generics.
Provides reusable view mixins used by horilla.contrib.generics views.
"""

# Standard library imports
import re
from urllib.parse import urlparse

# Third-party imports (Django)
from django.core.cache import cache
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.utils import translation

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.auth.models import User

# First party imports (Horilla)
from horilla.contrib.core.mixins import get_allowed_users_queryset_for_model
from horilla.contrib.core.models import ListColumnVisibility, RecentlyViewed
from horilla.contrib.core.utils import filter_hidden_fields
from horilla.core.exceptions import FieldDoesNotExist
from horilla.shortcuts import redirect, render
from horilla.urls import resolve
from horilla.utils.choices import FIELD_TYPE_MAP
from horilla.web import HttpResponse, QueryDict


class RecentlyViewedMixin(LoginRequiredMixin):
    """Mixin for automatically tracking recently viewed objects for authenticated users."""

    def dispatch(self, request, *args, **kwargs):
        """Dispatch request and record the viewed object in RecentlyViewed for the user."""
        response = super().dispatch(request, *args, **kwargs)
        if hasattr(self, "object") and self.object and request.user.is_authenticated:
            RecentlyViewed.objects.add_viewed_item(request.user, self.object)
        return response


class HorillaListColumnMixin:
    """
    Column resolution and company-column handling for HorillaListView.
    Expects self.columns, self.model, self.request,
    self.list_column_visibility, self.exclude_columns.
    """

    def _add_company_column_if_needed(self, columns):
        """Add or remove company column based on show_all_companies setting."""
        show_all_companies = self.request.session.get("show_all_companies", False)
        if not show_all_companies:
            columns = [
                col for col in columns if col[1] not in ("company", "company__name")
            ]
            return columns

        if show_all_companies and self.model:
            try:
                company_field = self.model._meta.get_field("company")
                if not any(
                    col[1] == "company" or col[1] == "company__name" for col in columns
                ):
                    company_verbose_name = getattr(
                        company_field, "verbose_name", "Company"
                    )
                    columns.append([str(company_verbose_name), "company__name"])
            except FieldDoesNotExist:
                pass
        return columns

    def _get_columns(self):
        """Get columns configuration based on model fields and methods."""
        if not self.list_column_visibility:
            columns = [[col[0], col[1]] for col in self.columns] if self.columns else []
            if columns and self.model:
                field_names = [col[1] for col in columns]
                visible_field_names = filter_hidden_fields(
                    self.request.user, self.model, field_names
                )
                columns = [col for col in columns if col[1] in visible_field_names]
            columns = self._add_company_column_if_needed(columns)
            return columns
        app_label = self.model._meta.app_label
        model_name = self.model.__name__
        hx_current = self.request.headers.get("HX-Current-URL", "")
        _referer_url = hx_current or self.request.META.get("HTTP_REFERER", "")
        context = re.sub(
            r"_\d+$",
            "",
            urlparse(_referer_url).path.strip("/").replace("/", "_"),
        )
        current_path = resolve(self.request.path_info).url_name
        cache_key = f"visible_columns_{self.request.user.id}_{app_label}_{model_name}_{context}_{current_path}"
        cached_columns = cache.get(cache_key)
        if cached_columns:
            if cached_columns and self.model:
                field_names = [
                    col[1]
                    for col in cached_columns
                    if isinstance(col, (list, tuple)) and len(col) >= 2
                ]
                visible_field_names = filter_hidden_fields(
                    self.request.user, self.model, field_names
                )
            else:
                visible_field_names = {
                    col[1]
                    for col in cached_columns
                    if isinstance(col, (list, tuple)) and len(col) >= 2
                }
            cached_columns = [
                col
                for col in cached_columns
                if isinstance(col, (list, tuple))
                and len(col) >= 2
                and col[1] in visible_field_names
            ]
            cached_columns = self._add_company_column_if_needed(cached_columns)
            return cached_columns

        visibility = ListColumnVisibility.all_objects.filter(
            user=self.request.user,
            model_name=model_name,
            app_label=app_label,
            context=context,
            url_name=current_path,
        ).first()

        if visibility:
            visible_fields = visibility.visible_fields
            model_fields = self.model._meta.get_fields()
            field_mapping = {}
            for field in model_fields:
                if hasattr(field, "verbose_name") and not field.is_relation:
                    field_mapping[str(field.verbose_name)] = field.name

            columns = []
            for visible_field in visible_fields:
                if isinstance(visible_field, list) and len(visible_field) >= 2:
                    columns.append([visible_field[0], visible_field[1]])
                else:
                    verbose_name = visible_field
                    for col_verbose_name, col_field_name in self.columns:
                        if str(col_verbose_name) == verbose_name:
                            columns.append([col_field_name, verbose_name])
                            break
                    else:
                        if verbose_name in field_mapping:
                            field_name = field_mapping[verbose_name]
                            field = next(
                                (f for f in model_fields if f.name == field_name), None
                            )
                            if field and getattr(field, "choices", None):
                                columns.append(
                                    [verbose_name, f"get_{field_name}_display"]
                                )
                            else:
                                columns.append([verbose_name, field_name])
                        else:
                            display_name = str(verbose_name.replace("_", " ").title())
                            columns.append(
                                [
                                    display_name,
                                    verbose_name.lower().replace(" ", "_"),
                                ]
                            )
            if columns and self.model:
                field_names = [col[1] for col in columns]
                visible_field_names = filter_hidden_fields(
                    self.request.user, self.model, field_names
                )
                columns = [col for col in columns if col[1] in visible_field_names]
            columns = self._add_company_column_if_needed(columns)
            cache.set(cache_key, columns)
            return columns

        if self.columns:
            with translation.override("en"):
                serializable_columns = []
                for col in self.columns:
                    if isinstance(col, (list, tuple)) and len(col) >= 2:
                        serializable_columns.append([str(col[0]), str(col[1])])
                    else:
                        serializable_columns.append([str(col[0]) if col else "", ""])

                if serializable_columns and self.model:
                    field_names = [
                        col[1] for col in serializable_columns if len(col) >= 2
                    ]
                    visible_field_names = filter_hidden_fields(
                        self.request.user, self.model, field_names
                    )
                    serializable_columns = [
                        col
                        for col in serializable_columns
                        if isinstance(col, (list, tuple))
                        and len(col) >= 2
                        and col[1] in visible_field_names
                    ]

                ListColumnVisibility.all_objects.create(
                    user=self.request.user,
                    app_label=self.model._meta.app_label,
                    model_name=self.model.__name__,
                    visible_fields=serializable_columns,
                    context=context,
                    url_name=current_path,
                )
                columns = [[col[0], col[1]] for col in serializable_columns]
                if columns and self.model:
                    field_names = [col[1] for col in columns]
                    visible_field_names = filter_hidden_fields(
                        self.request.user, self.model, field_names
                    )
                    columns = [col for col in columns if col[1] in visible_field_names]
                columns = self._add_company_column_if_needed(columns)
                cache.set(cache_key, columns)
                return columns

        auto_columns = []
        for field in self.model._meta.fields:
            if (
                not field.auto_created
                and field.name != "id"
                and field.name not in self.exclude_columns
            ):
                verbose = str(field.verbose_name)
                auto_columns.append([verbose, field.name])
        if auto_columns and self.model:
            field_names = [col[1] for col in auto_columns]
            visible_field_names = filter_hidden_fields(
                self.request.user, self.model, field_names
            )
            auto_columns = [
                col for col in auto_columns if col[1] in visible_field_names
            ]
        auto_columns = self._add_company_column_if_needed(auto_columns)
        return auto_columns


# ---------------------------------------------------------------------------
# Filter field metadata and field/operator change handlers
# ---------------------------------------------------------------------------


class HorillaListFilterFieldsMixin:
    """
    _get_model_fields and filter UI handlers (handle_field_change,
    handle_operator_change) for HorillaListView.
    Expects self.model, self.request, and get_filterset_class() (or filterset_class).
    """

    def _get_model_fields(self, include_properties=False, for_export=False):
        """Extract model fields with metadata for filtering UI."""
        cache_key = f"_model_fields_cache_{include_properties}_{for_export}"
        if hasattr(self, cache_key) and getattr(self, cache_key) is not None:
            return getattr(self, cache_key)

        BOOLEAN_CHOICES = [
            {"value": "True", "label": "Yes"},
            {"value": "False", "label": "No"},
        ]
        filterset_class = self.get_filterset_class()
        exclude_fields = []
        if filterset_class:
            exclude_fields = list(getattr(filterset_class.Meta, "exclude", []) or [])
        if not self.request.session.get("show_all_companies", False):
            exclude_fields = exclude_fields + ["company"]
        exclude_from_export = ["histories", "full_histories"]
        if for_export:
            view_export_exclude = getattr(self, "export_exclude", [])
            exclude_from_export = list(exclude_from_export) + list(view_export_exclude)
        model_fields = []
        is_bulk_update_trigger = self.request.POST.get(
            "bulk_update_form"
        ) == "true" or (
            self.request.META.get("HTTP_HX_TRIGGER")
            and str(self.request.META.get("HTTP_HX_TRIGGER", "")).startswith(
                "bulk-update-btn"
            )
        )
        trigger_name = self.request.headers.get("Hx-Trigger-Name")
        is_operator_trigger = trigger_name == "operator"
        trigger = self.request.GET.get("hx_trigger")
        is_filter_form_trigger = trigger == "filter-form"
        has_filterset = bool(filterset_class)
        value_field = self.request.GET.get("value", "")
        use_full_queryset_for_choices = False

        for field in self.model._meta.fields:
            if field.name in exclude_from_export:
                continue
            if filterset_class and not for_export:
                if field.name in exclude_fields:
                    continue

            field_class_name = field.__class__.__name__
            choices = []
            related_model = None
            related_app_label = None
            related_model_name = None

            if field.choices:
                field_type = "choice"
                choices = [
                    {"value": val, "label": label} for val, label in field.choices
                ]
            elif field_class_name == "ForeignKey":
                related_model = field.related_model
                related_app_label = related_model._meta.app_label
                related_model_name = related_model.__name__
                user_model = User
                field_type = "foreignkey"
                if (
                    is_operator_trigger
                    or is_bulk_update_trigger
                    or is_filter_form_trigger
                    or value_field
                ):
                    related_objects_queryset = None
                    if related_model == user_model or issubclass(
                        related_model, user_model
                    ):
                        related_objects_queryset = get_allowed_users_queryset_for_model(
                            self.request.user, self.model
                        )

                    if (
                        related_objects_queryset is None
                        and filterset_class
                        and field.name
                    ):
                        try:
                            temp_filterset = filterset_class(
                                request=self.request, data={}
                            )
                            if field.name in temp_filterset.filters:
                                filter_obj = temp_filterset.filters[field.name]
                                if hasattr(filter_obj, "field") and hasattr(
                                    filter_obj.field, "queryset"
                                ):
                                    related_objects_queryset = filter_obj.field.queryset
                                elif hasattr(filter_obj, "queryset"):
                                    related_objects_queryset = filter_obj.queryset
                        except Exception:
                            pass

                    if related_objects_queryset is None:
                        related_objects_queryset = field.related_model.objects.all()

                    related_objects = related_objects_queryset.order_by("id")
                    use_full_queryset_for_choices = is_bulk_update_trigger and (
                        related_model == user_model
                        or issubclass(related_model, user_model)
                    )
                    if use_full_queryset_for_choices:
                        choices = [
                            {"value": str(obj.pk), "label": str(obj)}
                            for obj in related_objects
                        ]
                    else:
                        paginator = Paginator(related_objects, 10)
                        try:
                            paginated_objects = paginator.page(1)
                        except PageNotAnInteger:
                            paginated_objects = paginator.page(1)
                        except EmptyPage:
                            paginated_objects = paginator.page(paginator.num_pages)
                        choices = [
                            {"value": str(obj.pk), "label": str(obj)}
                            for obj in paginated_objects
                        ]

                    if value_field:
                        try:
                            value_obj = related_objects_queryset.get(pk=value_field)
                            value_choice = {
                                "value": str(value_obj.pk),
                                "label": str(value_obj),
                            }
                            if value_choice not in choices:
                                choices.append(value_choice)
                        except (field.related_model.DoesNotExist, ValueError):
                            pass
            elif field_class_name == "DateTimeField":
                field_type = "datetime"
            elif field_class_name == "DateField":
                field_type = "date"
            else:
                field_type = FIELD_TYPE_MAP.get(field_class_name, "other")
                if field_type == "boolean":
                    choices = BOOLEAN_CHOICES

            operators = []
            if has_filterset:
                operators = filterset_class.get_operators_for_field(field_type)

            field_dict = {
                "name": field.name,
                "type": field_type,
                "verbose_name": field.verbose_name,
                "choices": choices,
                "operators": operators,
                "model": related_model_name,
                "app_label": related_app_label,
            }
            if field_class_name == "ForeignKey" and use_full_queryset_for_choices:
                field_dict["use_static_options"] = True
            model_fields.append(field_dict)

        if include_properties:
            property_labels = getattr(self.model, "PROPERTY_LABELS", None)
            if property_labels:
                for name in property_labels:
                    member = getattr(self.model, name, None)
                    if member is None:
                        continue
                    if isinstance(member, property) or callable(member):
                        label_key = (
                            name.replace("get_", "", 1)
                            if name.startswith("get_")
                            else name
                        )
                        if name in ["histories", "full_histories"] or label_key in [
                            "histories",
                            "full_histories",
                        ]:
                            continue
                        model_fields.append(
                            {
                                "name": name,
                                "type": "text",
                                "verbose_name": property_labels[name],
                                "choices": [],
                                "operators": [],
                                "is_property": True,
                            }
                        )

        setattr(self, cache_key, model_fields)
        return model_fields

    def handle_field_change(self, request, field_name, row_id):
        """Handle field change to update operators dropdown."""
        field_info = next(
            (
                field
                for field in self._get_model_fields()
                if field["name"] == field_name
            ),
            None,
        )
        if not field_info:
            return HttpResponse("Field not found", status=404)
        filterset_class = self.get_filterset_class()
        if not filterset_class:
            return HttpResponse("Filterset not configured", status=404)
        operators = filterset_class.get_operators_for_field(field_info["type"])
        context = {
            "operators": operators,
            "field_name": field_name,
            "row_id": row_id,
            "search_url": self.search_url,
        }
        return render(request, "partials/operator_select.html", context)

    def handle_operator_change(self, request, field_name, operator, row_id):
        """Handle operator change to update value field."""
        field_info = next(
            (
                field
                for field in self._get_model_fields()
                if field["name"] == field_name
            ),
            None,
        )
        if not field_info:
            return HttpResponse("Field not found", status=404)
        filter_class_path = None
        parent_model_path = None
        filterset_class = self.get_filterset_class()
        if filterset_class:
            filter_class_path = (
                f"{filterset_class.__module__}.{filterset_class.__name__}"
            )
            parent_model_path = (
                f"{self.model._meta.app_label}.{self.model._meta.model_name}"
            )
        context = {
            "field_info": field_info,
            "operator": operator,
            "row_id": row_id,
            "filter_class_path": filter_class_path,
            "parent_model_path": parent_model_path,
        }
        return render(request, "partials/value_field.html", context)


# ---------------------------------------------------------------------------
# Filter remove/clear handlers
# ---------------------------------------------------------------------------


class HorillaListFilterHandlersMixin:
    """
    handle_remove_filter and handle_clear_all_filters for HorillaListView.
    Expects self.main_url, self.template_name, self.filter_url_push,
    get_queryset(), get_context_data().
    """

    def handle_remove_filter(self, request):
        """Handle removing a specific filter or the search parameter."""
        remove_filter = request.GET.get("remove_filter", "")
        query_params = request.GET.copy()

        new_fields = []
        new_operators = []
        new_values = []
        new_start_values = []
        new_end_values = []
        new_logics = []
        search_value = query_params.get("search", "")

        if remove_filter == "search":
            fields = [f for f in query_params.getlist("field") if f.strip()]
            operators = [o for o in query_params.getlist("operator") if o.strip()]
            values = [v for v in query_params.getlist("value") if v.strip()]
            start_values = [
                sv for sv in query_params.getlist("start_value") if sv.strip()
            ]
            end_values = [ev for ev in query_params.getlist("end_value") if ev.strip()]
            logics = [l for l in query_params.getlist("logic") if l.strip()]
            new_fields = fields
            new_operators = operators
            new_values = values
            new_start_values = start_values
            new_end_values = end_values
            new_logics = logics
            search_value = ""
        else:
            filter_index = int(remove_filter) if remove_filter.isdigit() else -1
            fields = query_params.getlist("field")
            operators = query_params.getlist("operator")
            values = query_params.getlist("value")
            start_values = query_params.getlist("start_value")
            end_values = query_params.getlist("end_value")
            logics = query_params.getlist("logic")
            for i, field in enumerate(fields):
                if i != filter_index and field.strip():
                    new_fields.append(field)
                    if i < len(operators) and operators[i].strip():
                        new_operators.append(operators[i])
                    if i < len(values) and values[i].strip():
                        new_values.append(values[i])
                    if i < len(start_values) and start_values[i].strip():
                        new_start_values.append(start_values[i])
                    if i < len(end_values) and end_values[i].strip():
                        new_end_values.append(end_values[i])
                    if i < len(logics) and logics[i].strip():
                        new_logics.append(logics[i])

        # With no filter rows left, leftover operator/value/logic params (e.g. the
        # always-present logic=AND) are meaningless, so don't keep them in the URL.
        if not new_fields:
            new_operators = []
            new_values = []
            new_start_values = []
            new_end_values = []
            new_logics = []

        new_query_params = QueryDict("", mutable=True)
        for key, values_list in query_params.lists():
            if key not in [
                "field",
                "operator",
                "value",
                "start_value",
                "end_value",
                "logic",
                "remove_filter",
                "page",
                "apply_filter",
                "hx_trigger",
                "search",
            ]:
                for value in values_list:
                    if value.strip():
                        new_query_params.appendlist(key, value)
        for field in new_fields:
            new_query_params.appendlist("field", field)
        for operator in new_operators:
            new_query_params.appendlist("operator", operator)
        for value in new_values:
            new_query_params.appendlist("value", value)
        for start_value in new_start_values:
            new_query_params.appendlist("start_value", start_value)
        for end_value in new_end_values:
            new_query_params.appendlist("end_value", end_value)
        for logic in new_logics:
            new_query_params.appendlist("logic", logic)
        if search_value:
            new_query_params["search"] = search_value
        if new_fields:
            new_query_params["apply_filter"] = "true"

        new_query_string = new_query_params.urlencode()
        current_path = self.main_url
        url = f"{current_path}?{new_query_string}" if new_query_string else current_path

        if request.headers.get("HX-Request") == "true":
            return self._render_with_params(request, new_query_params, url)
        return redirect(url)

    def handle_clear_all_filters(self, request):
        """Handle clearing all applied filters."""
        query_params = request.GET.copy()
        filter_params = [
            "field",
            "operator",
            "value",
            "start_value",
            "end_value",
            "logic",
            "apply_filter",
            "clear_all_filters",
            "page",
            "search",
        ]
        new_query_params = QueryDict(mutable=True)
        for key, values in query_params.lists():
            if key not in filter_params:
                for value in values:
                    new_query_params.appendlist(key, value)
        new_query_params._mutable = False

        new_query_string = new_query_params.urlencode()
        url = f"{self.main_url}" + (f"?{new_query_string}" if new_query_string else "")
        return self._render_with_params(request, new_query_params, url)

    def _render_with_params(self, request, new_query_params, url):
        """Render the list as if request.GET were new_query_params (no full reload)."""
        new_query_string = new_query_params.urlencode()
        original_get = request.GET
        original_query_string = request.META.get("QUERY_STRING", "")
        if hasattr(request, "_get"):
            delattr(request, "_get")
        request.__dict__["GET"] = new_query_params
        request.META["QUERY_STRING"] = new_query_string

        self.object_list = self.get_queryset()
        context = self.get_context_data()
        context["filter_reload_url"] = url
        response = render(request, self.template_name, context)

        request.__dict__["GET"] = original_get
        request.META["QUERY_STRING"] = original_query_string

        if self.filter_url_push:
            response["HX-Push-Url"] = url
            response["HX-Replace-Url"] = url
        else:
            response["HX-Push-Url"] = "false"
        response["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        return response


class HorillaListViewMixin(
    HorillaListColumnMixin,
    HorillaListFilterFieldsMixin,
    HorillaListFilterHandlersMixin,
):
    """
    Combined mixin for HorillaListView: columns, filter field metadata,
    and filter remove/clear handlers. Use this as the single list-view mixin.
    """
