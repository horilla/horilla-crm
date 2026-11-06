"""
A highly customizable ListView for Horilla that supports dynamic column generation, filtering, searching, and action handling with infinite scrolling pagination.
This view can be extended to create specific list views for different models, and includes features like pinned views, recently viewed/created/modified filters, saved filter lists.
"""

# Standard library imports
import json
import logging
from functools import update_wrapper

# Third-party imports (Django)
from django.utils.dateparse import parse_time

from horilla.contrib.core.models import PinnedView, RecentlyViewed, SavedFilterList
from horilla.contrib.core.utils import filter_hidden_fields, get_editable_fields
from horilla.db.models import Case, ForeignKey, OneToOneField, Q, When
from horilla.db.models.fields import GenericForeignKey

# First party imports (Horilla)
from horilla.shortcuts import render
from horilla.utils import translation
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import ListView
from horilla.web import HttpResponse, QueryDict

from ..mixins import HorillaListViewMixin

# Local imports
from .toolkit import (
    HorillaBulkDeleteMixin,
    HorillaBulkExportMixin,
    HorillaBulkUpdateMixin,
    quick_filter,
)

logger = logging.getLogger(__name__)


class HorillaListView(HorillaListViewMixin, ListView):
    """
    A customizable ListView that provides automatic column generation,
    filtering, searching, and action handling with infinite scrolling pagination.
    """

    template_name = "list_view.html"
    context_object_name = "queryset"
    columns = []
    actions = []
    view_id = ""
    action_method = ""
    exclude_columns = []
    default_sort_field = None
    default_sort_direction = "asc"
    sort_by_mapping = []
    paginate_by = 100
    page_kwarg = "page"
    main_url: str = ""
    search_url: str = ""
    filterset_class = None
    filter_panel_option = True
    filter_url_push = True
    max_visible_actions = 4
    bulk_update_fields = []
    bulk_update_two_column = False
    raw_attrs: list = []
    number_of_recent_view = 20
    bulk_delete_enabled = True
    header_attrs = []
    col_attrs = []
    bulk_select_option = True
    no_record_section = True
    no_record_add_button: dict = None
    no_record_msg: str = None
    no_record_fit_height = True
    table_width = True
    table_class = True
    table_height_as_class = ""
    table_auto = False
    bulk_update_option = True
    store_ordered_ids = False
    track_list_navigation = True
    save_to_list_option = True
    apply_pinned_view_default = True
    enable_sorting = True
    custom_bulk_actions = []
    bulk_export_option = True
    additional_action_button = []
    list_column_visibility = True
    owner_filtration = True
    sorting_target = None
    exclude_columns_from_sorting = []
    no_found_img: str = ""
    enable_quick_filters = False  # Set to True in child classes to enable
    exclude_quick_filter_fields = []  # Fields to exclude from quick filters
    supports_quick_filters = True

    def get_filterset_class(self):
        """
        Return composed filterset when _inherit_filter extensions exist.

        Views keep ``filterset_class = UserFilter`` at class definition time;
        resolution runs here (same pattern as ``get_form_class()`` on form views).
        """
        base = type(self).filterset_class
        if base is None:
            return None
        from horilla.extension.filter.resolve import resolve_filterset_class

        return resolve_filterset_class(base)

    @classmethod
    def as_view(cls, **initkwargs):
        """
        Wrap the view so _inherit_list / _inherit_card / _inherit_kanban resolve on each request.

        Target apps register URLs in ``AppLauncher.ready()`` before extension apps
        import ``lists.py`` / ``cards.py`` / ``kanbans.py``; resolving only at
        URL-import time would miss extensions.
        """
        if getattr(cls, "__horilla_kanban_composed__", False):
            return super(HorillaListView, cls).as_view(**initkwargs)

        if getattr(cls, "__horilla_card_composed__", False):
            return super().as_view(**initkwargs)

        if getattr(cls, "__horilla_list_composed__", False):
            return super().as_view(**initkwargs)

        base_view = super().as_view(**initkwargs)

        def view(request, *args, **kwargs):
            from horilla.contrib.generics.views.card import HorillaCardView
            from horilla.contrib.generics.views.kanban import HorillaKanbanView

            if issubclass(cls, HorillaKanbanView):
                from horilla.extension.kanban.bootstrap import (
                    registry_fingerprint as kanban_fingerprint,
                )
                from horilla.extension.kanban.resolve import resolve_kanban_view_class

                resolved = resolve_kanban_view_class(cls)
                fingerprint = kanban_fingerprint()
                fp_attr = "_kanban_ext_fingerprint"
            elif issubclass(cls, HorillaCardView):
                from horilla.extension.card.bootstrap import (
                    registry_fingerprint as card_fingerprint,
                )
                from horilla.extension.card.resolve import resolve_card_view_class

                resolved = resolve_card_view_class(cls)
                fingerprint = card_fingerprint()
                fp_attr = "_card_ext_fingerprint"
            else:
                from horilla.extension.list.bootstrap import registry_fingerprint
                from horilla.extension.list.resolve import resolve_list_view_class

                resolved = resolve_list_view_class(cls)
                fingerprint = registry_fingerprint()
                fp_attr = "_list_ext_fingerprint"

            if resolved is not cls:
                if (
                    getattr(view, "_extended_handler", None) is None
                    or getattr(view, "_extended_cls", None) is not resolved
                    or getattr(view, fp_attr, None) != fingerprint
                ):
                    view._extended_cls = resolved
                    view._extended_handler = resolved.as_view(**initkwargs)
                    setattr(view, fp_attr, fingerprint)
                return view._extended_handler(request, *args, **kwargs)
            return base_view(request, *args, **kwargs)

        update_wrapper(view, base_view)
        view.view_class = cls
        view.view_initkwargs = initkwargs
        return view

    def __init__(self, **kwargs):
        self._model_fields_cache = None
        super().__init__(**kwargs)
        if self.store_ordered_ids:
            self.ordered_ids_key = f"ordered_ids_{self.model.__name__.lower()}"
        self.kwargs = kwargs
        if self.columns:
            resolved_columns = []
            instance = self.model()

            # Force English when resolving column names
            with translation.override("en"):
                for col in self.columns:
                    if isinstance(col, (tuple, list)) and len(col) >= 2:
                        label = col[0]
                        if isinstance(label, str):
                            try:
                                label = instance._meta.get_field(label).verbose_name
                            except Exception:
                                pass
                        resolved_columns.append((str(label), str(col[1])))
                    elif isinstance(col, str):
                        # Look up via the class (not the instance) so resolving a
                        # column name never triggers a related-object DB fetch,
                        # e.g. for a ForeignKey field with an invalid default.
                        class_attr = getattr(type(instance), col, None)
                        short_description = getattr(
                            class_attr, "short_description", None
                        )
                        if short_description:
                            resolved_columns.append((str(short_description), col))
                            continue

                        lookup_name = col
                        if lookup_name.startswith("get_") and lookup_name.endswith(
                            "_display"
                        ):
                            lookup_name = lookup_name[len("get_") : -len("_display")]
                        try:
                            field = instance._meta.get_field(lookup_name)
                            verbose_name = str(field.verbose_name)
                            resolved_columns.append((verbose_name, col))
                        except Exception:
                            resolved_columns.append(
                                (col.replace("_", " ").title(), col)
                            )
                    else:
                        resolved_columns.append((str(col), str(col)))

            self.columns = resolved_columns

        self._run_list_view_extension_setup()
        self._run_kanban_view_extension_setup()

    def _run_list_view_extension_setup(self):
        """Call setup_list_view_extension on extension mixins (composed views only)."""
        if not getattr(type(self), "__horilla_list_composed__", False):
            return
        wrapped = getattr(type(self), "__wrapped_list_view__", None)
        seen: set = set()
        for base in type(self).__mro__:
            if wrapped is not None and base is wrapped:
                break
            method = base.__dict__.get("setup_list_view_extension")
            if method is None or method in seen:
                continue
            seen.add(method)
            method(self)

    def _run_kanban_view_extension_setup(self):
        """Call setup_kanban_view_extension on extension mixins (composed kanban views only)."""
        if not getattr(type(self), "__horilla_kanban_composed__", False):
            return
        wrapped = getattr(type(self), "__wrapped_kanban_view__", None)
        seen: set = set()
        for base in type(self).__mro__:
            if wrapped is not None and base is wrapped:
                break
            method = base.__dict__.get("setup_kanban_view_extension")
            if method is None or method in seen:
                continue
            seen.add(method)
            method(self)

    def _is_embedded_list_context(self):
        """
        True for inline lists that are not the app's primary list.
        """
        req = getattr(self, "request", None)
        if not req:
            return False
        try:
            su = str(getattr(self, "search_url", "") or "").rstrip("/")
            mu = str(getattr(self, "main_url", "") or "").rstrip("/")
            path = req.path.rstrip("/")
            if not su or not mu:
                return False
            return su == mu == path
        except Exception:
            return False

    def _get_pinned_view(self):
        """Load the user's pinned view once per request and reuse it."""
        if hasattr(self, "_pinned_view_cache"):
            return self._pinned_view_cache
        if not self.model:
            self._pinned_view_cache = None
            return None
        self._pinned_view_cache = PinnedView.all_objects.filter(
            user=self.request.user, model_name=self.model.__name__
        ).first()
        return self._pinned_view_cache

    def get_group_field(self, field_name):
        """
        Return the field a grouped layout (kanban, group-by, chart) groups by.

        Extensions can override this to group by a value that isn't a model
        column; the object returned needs ``choices`` (or be a ForeignKey),
        ``verbose_name`` and ``null``.
        """
        return self.model._meta.get_field(field_name)

    def persist_group_value(self, item, group_by):
        """
        Hook called after a kanban card is moved and ``item`` is saved.

        The new column value is already set on ``item.<group_by>``; override to
        store it somewhere other than a model column.
        """

    def get_extra_quick_filter_fields(self):
        """
        Extra quick filter fields beyond the model's own choice / foreign key /
        boolean columns, as ``{"name", "verbose_name", "type"}`` dicts.
        """
        return []

    def get_extra_quick_filter_choices(self, field_name):
        """
        Choices (``{"value", "label"}`` dicts) for an extra quick filter field,
        or None when ``field_name`` isn't one of them.
        """
        return None

    def apply_extra_quick_filter(self, queryset, field_name, value):
        """
        Filter ``queryset`` by an extra quick filter field and return it, or
        return None when ``field_name`` isn't one of them.
        """
        return None

    def get_default_view_type(self):
        """Return the pinned view_type if available, else 'all'."""
        if not getattr(self, "apply_pinned_view_default", True):
            return "all"
        if self._is_embedded_list_context():
            return "all"
        pinned_view = self._get_pinned_view()
        return pinned_view.view_type if pinned_view else "all"

    def get_queryset(self):
        """Get filtered queryset based on search, filter, or view type parameters."""

        queryset = super().get_queryset()
        queryset = quick_filter.apply_quick_filters(queryset, self)

        is_bulk_operation = (
            (
                self.request.method == "POST"
                and self.request.POST.get("action")
                in [
                    "bulk_delete",
                    "delete_item_with_dependencies",
                    "delete_all_dependencies",
                ]
            )
            or self.request.POST.get("bulk_delete_form") == "true"
            or self.request.POST.get("soft_delete_form") == "true"
            or self.request.POST.get("delete_mode_form") == "true"
            or self.request.POST.get("bulk_update_form") == "true"
            or bool(
                self.request.method == "POST"
                and self.request.POST.get("record_ids")
                and any(k.startswith("bulk_update_value_") for k in self.request.POST)
            )
        )

        if is_bulk_operation:
            view_type = self.request.GET.get("view_type")
            if not view_type:
                view_type = "all"
        else:
            view_type = (
                self.request.GET.get("view_type") or self.get_default_view_type()
            )

        if view_type == "recently_viewed":
            recently_viewed_items = RecentlyViewed.objects.get_recently_viewed(
                user=self.request.user, model_class=self.model
            )
            pks = [item.pk for item in recently_viewed_items if item]
            queryset = queryset.filter(pk__in=pks)

        elif view_type in ("recently_created", "recently_modified"):
            sort_field = (
                "-created_at" if view_type == "recently_created" else "-updated_at"
            )
            recent_queryset = queryset.order_by(sort_field)[:20]
            recent_ids = list(recent_queryset.values_list("pk", flat=True))
            queryset = queryset.filter(pk__in=recent_ids)

        elif view_type == "oldest_first":
            queryset = queryset.order_by("created_at")

        elif view_type.startswith("saved_list_"):
            saved_list_id = view_type.replace("saved_list_", "")
            try:
                saved_list = (
                    SavedFilterList.all_objects.filter(id=saved_list_id)
                    .filter(Q(user=self.request.user) | Q(is_public=True))
                    .first()
                )
                if saved_list:
                    filter_params = saved_list.get_filter_params()
                    merged_params = QueryDict(mutable=True)
                    for key, values in filter_params.items():
                        for value in values:
                            merged_params.appendlist(key, value)

                    search_keys = [
                        "field",
                        "operator",
                        "value",
                        "start_value",
                        "end_value",
                        "logic",
                        "search",
                    ]
                    for key, values in self.request.GET.lists():
                        if key in search_keys:
                            for value in values:
                                merged_params.appendlist(key, value)

                    filterset_class = self.get_filterset_class()
                    if filterset_class:
                        self.filterset = filterset_class(
                            merged_params, queryset=queryset, request=self.request
                        )
                        queryset = self.filterset.filter_queryset(queryset)
            except Exception:
                pass

        filterset_class = self.get_filterset_class()
        if filterset_class and not (
            view_type.startswith("saved_list_") and getattr(self, "filterset", None)
        ):
            self.filterset = filterset_class(
                self.request.GET, queryset=queryset, request=self.request
            )
            try:
                queryset = self.filterset.filter_queryset(queryset)
            except Exception as e:
                logger.error(
                    "filter_queryset failed for %s (params=%s): %s",
                    self.model.__name__ if self.model else "<unknown model>",
                    self.request.GET.urlencode(),
                    str(e),
                )

        sort_keys_raw = self.request.GET.get("sort_keys", "")
        sort_field = self.request.GET.get("sort")
        sort_direction = self.request.GET.get("direction", self.default_sort_direction)

        # Parse multi-column sort_keys (e.g. "name:asc,date:desc")
        sort_pairs = []
        if sort_keys_raw:
            for token in sort_keys_raw.split(","):
                token = token.strip()
                if ":" in token:
                    f, d = token.rsplit(":", 1)
                    sort_pairs.append((f.strip(), d.strip()))
                elif token:
                    sort_pairs.append((token, self.default_sort_direction))

        if (
            view_type == "recently_viewed"
            and not sort_pairs
            and not sort_field
            and "pks" in locals()
        ):
            preserved_order = Case(
                *[When(pk=pk, then=pos) for pos, pk in enumerate(pks)]
            )
            queryset = queryset.order_by(preserved_order)
        elif sort_pairs:
            queryset = self._apply_multi_sorting(queryset, sort_pairs)
        elif sort_field:
            queryset = self._apply_sorting(queryset, sort_field, sort_direction)
        elif view_type == "recently_created":
            queryset = queryset.order_by("-created_at")
        elif view_type == "recently_modified":
            queryset = queryset.order_by("-updated_at")
        elif view_type == "oldest_first":
            queryset = queryset.order_by("created_at")
        elif self.default_sort_field:
            order_prefix = "-" if self.default_sort_direction == "desc" else ""
            queryset = queryset.order_by(f"{order_prefix}{self.default_sort_field}")
        else:
            queryset = queryset.order_by("-id")

        if self.store_ordered_ids:
            ordered_ids = list(queryset.values_list("pk", flat=True))
            self.request.session[self.ordered_ids_key] = ordered_ids

        # Join FK columns rendered per row (plus company for currency formatting)
        # so list display does not N+1 on getattr(obj, fk) / obj.company.
        queryset = self._apply_list_display_select_related(queryset)

        if self.owner_filtration:
            from .helpers.queryset_utils import get_viewable_queryset

            user = self.request.user
            model_meta = self.model._meta
            if user.has_perm(f"{model_meta.app_label}.view_{model_meta.model_name}"):
                return queryset
            viewable = get_viewable_queryset(user, self.model)
            return queryset.filter(pk__in=viewable.values("pk")).distinct()
        return queryset.distinct()

    def _apply_list_display_select_related(self, queryset):
        """Select-related FK columns used in list cells and row actions,
        plus ``company``.

        ``display_field_value`` / currency formatting touch related objects
        per row, and action permission checks (has_action_permission) read
        each action's ``owner_field`` off the row object -- without joins
        either becomes one query per row (N+1). This is the single, generic
        fix point: every HorillaListView subclass (Leads, Accounts,
        Contacts, Campaigns, Opportunities, ...) funnels through this
        method, so declaring an "owner_field" on an action is enough to get
        the join automatically, with no per-view get_queryset override.
        """
        if not self.model:
            return queryset

        related_fields = set()
        columns = None
        try:
            columns = self._get_columns()
        except Exception:
            columns = getattr(self, "columns", None) or []

        for col in columns or []:
            if isinstance(col, (tuple, list)) and len(col) >= 2:
                field_name = col[1]
            else:
                field_name = col
            if not isinstance(field_name, str) or not field_name:
                continue
            # company__name → join company; lead_owner → join lead_owner
            lookup = field_name.split("__")[0]
            try:
                field = self.model._meta.get_field(lookup)
            except Exception:
                continue
            if isinstance(field, (ForeignKey, OneToOneField)):
                related_fields.add(lookup)

        for owner_field in self._get_owner_field_candidates():
            lookup = owner_field.split("__")[0]
            try:
                field = self.model._meta.get_field(lookup)
            except Exception:
                continue
            if isinstance(field, (ForeignKey, OneToOneField)):
                related_fields.add(lookup)

        try:
            self.model._meta.get_field("company")
            related_fields.add("company")
        except Exception:
            pass

        if related_fields:
            queryset = queryset.select_related(*sorted(related_fields))
        return queryset

    def _get_owner_field_candidates(self):
        """Collect every ``owner_field`` name referenced by this view's
        actions/columns config, for use as select_related() lookups.

        ``owner_field`` may be a single field name or a list of names (see
        has_action_permission), and lives either on ``actions`` entries or
        on a ``col_attrs`` entry's per-column attrs dict -- both are plain
        lists/cached_properties by the time get_queryset() runs (after
        View.setup()), so accessing them here is always safe.
        """
        candidates = set()

        def _collect(attrs):
            if not isinstance(attrs, dict):
                return
            owner_field = attrs.get("owner_field")
            if not owner_field:
                return
            names = [owner_field] if isinstance(owner_field, str) else owner_field
            for name in names:
                if isinstance(name, str) and name:
                    candidates.add(name)

        for action in getattr(self, "actions", None) or []:
            _collect(action)

        for col_attr in getattr(self, "col_attrs", None) or []:
            if isinstance(col_attr, dict):
                for attrs in col_attr.values():
                    _collect(attrs)

        return candidates

    def _resolve_sort_field(self, field, model_class):
        """
        Resolve a column name to a sortable DB field name.
        Returns None if the field cannot be sorted.
        """
        # get_*_display → strip to underlying choice field
        if field.startswith("get_") and field.endswith("_display"):
            field = field[4:-8]

        # Check model-level SORT_FIELD_MAPPING (e.g. {"get_avatar_with_name": "first_name"})
        model_sort_map = getattr(model_class, "SORT_FIELD_MAPPING", {})
        if field in model_sort_map:
            return model_sort_map[field]

        # Check view-level sort_by_mapping
        mapped_field = next(
            (
                item[1]
                for item in getattr(self, "sort_by_mapping", [])
                if item[0] == field
            ),
            field,
        )

        if not hasattr(model_class, mapped_field):
            return None

        attr = getattr(model_class, mapped_field)
        if callable(attr) or isinstance(attr, property):
            return None

        return mapped_field

    def _apply_sorting(self, queryset, field, direction):
        """Fast sorting: uses DB fields or mapped aliases only."""

        if not field:
            return queryset

        model_class = queryset.model
        mapped_field = self._resolve_sort_field(field, model_class)
        if mapped_field is None:
            return queryset

        # Check if the field is a GenericForeignKey
        try:
            field_obj = model_class._meta.get_field(mapped_field)

            if isinstance(field_obj, GenericForeignKey):
                # Sort by content_type_id and then object_id
                ct_field = field_obj.ct_field + "_id"  # Usually 'content_type_id'
                fk_field = field_obj.fk_field  # Usually 'object_id'

                if direction == "desc":
                    return queryset.order_by(f"-{ct_field}", f"-{fk_field}")
                # else:
                return queryset.order_by(ct_field, fk_field)
        except Exception:
            pass

        order_field = f"-{mapped_field}" if direction == "desc" else mapped_field

        try:
            return queryset.order_by(order_field)
        except Exception as e:
            logger.warning("Could not sort by field '%s': %s", mapped_field, str(e))
            return queryset

    def _apply_multi_sorting(self, queryset, sort_pairs):
        """Apply multiple sort columns in order. sort_pairs is a list of (field, direction) tuples."""
        order_fields = []
        model_class = queryset.model
        for field, direction in sort_pairs:
            mapped_field = self._resolve_sort_field(field, model_class)
            if mapped_field is None:
                continue

            try:
                field_obj = model_class._meta.get_field(mapped_field)
                if isinstance(field_obj, GenericForeignKey):
                    ct_field = field_obj.ct_field + "_id"
                    fk_field = field_obj.fk_field
                    if direction == "desc":
                        order_fields.extend([f"-{ct_field}", f"-{fk_field}"])
                    else:
                        order_fields.extend([ct_field, fk_field])
                    continue
            except Exception:
                pass

            order_fields.append(
                f"-{mapped_field}" if direction == "desc" else mapped_field
            )

        if not order_fields:
            return queryset
        try:
            return queryset.order_by(*order_fields)
        except Exception as e:
            logger.warning("Could not apply multi-sort %s: %s", order_fields, str(e))
            return queryset

    def render_to_response(self, context, **response_kwargs):
        """Override to handle different types of requests appropriately."""
        is_htmx = self.request.headers.get("HX-Request") == "true"
        context["request_params"] = self.request.GET.copy()

        if is_htmx:
            return render(self.request, "list_view.html", context)

        return super().render_to_response(context, **response_kwargs)

    def handle_custom_bulk_action(self, action, record_ids):
        """Handle custom bulk actions based on their configuration."""
        try:
            if action.get("handler"):
                # Call custom handler function if provided
                handler = getattr(self, action["handler"], None)
                if callable(handler):
                    return handler(record_ids, self.request)
                # else:
                return HttpResponse(
                    f"Handler {action['handler']} not found.", status=500
                )

            # Default behavior: HTMX POST request
            url = action.get("url")
            if not url:
                return HttpResponse(
                    f"No URL provided for action {action['name']}.", status=400
                )

            context = self.get_context_data()
            context.update(
                {
                    "selected_ids": record_ids,
                    "selected_ids_json": json.dumps(record_ids),
                    "action_name": action["name"],
                }
            )

            # Prepare HTMX attributes
            hx_attrs = {
                (
                    "hx-post"
                    if action.get("method", "POST").upper() == "POST"
                    else "hx-get"
                ): url,
                "hx-target": action.get("target", "#modalBox"),
                "hx-swap": action.get("swap", "innerHTML"),
                "hx-vals": f'js:{{"selected_ids": JSON.stringify(selectedRecordIds("{self.view_id}")), "action": "{action["name"]}"}}',
            }
            if action.get("after_request"):
                hx_attrs["hx-on::after-request"] = action["after_request"]

            context["hx_attrs"] = hx_attrs
            return render(self.request, "list_view.html", context)

        except Exception as e:
            logger.error("Custom  action %s failed: %s", action["name"], str(e))
            return HttpResponse(f"Action {action['name']} failed: {str(e)}", status=500)

    def post(self, request, *args, **kwargs):
        """
        Handle POST requests for exporting data.
        """

        record_ids = request.POST.get("record_ids")
        columns = [
            value
            for key, value in request.POST.items()
            if key.startswith("expo_avail_") or key.startswith("expo_add_")
        ]
        action = request.POST.get("action")
        # columns = request.POST.getlist("export_columns")
        export_format = request.POST.get("export_format")
        delete_type = request.POST.get("delete_type")

        # Handle custom bulk actions
        if action in [bulk["name"] for bulk in self.custom_bulk_actions]:
            try:
                record_ids = json.loads(record_ids) if record_ids else []
                bulk_action = next(
                    bulk for bulk in self.custom_bulk_actions if bulk["name"] == action
                )
                return self.handle_custom_bulk_action(bulk_action, record_ids)
            except json.JSONDecodeError as e:
                logger.error("Error decoding record_ids JSON: %s", str(e))
                return HttpResponse("Invalid JSON data for record_ids", status=400)

        if action in [
            additional["name"] for additional in self.additional_action_button
        ]:
            try:
                record_ids = json.loads(record_ids) if record_ids else []
                bulk_action = next(
                    additional
                    for additional in self.additional_action_button
                    if additional["name"] == action
                )
                return self.handle_custom_bulk_action(bulk_action, record_ids)
            except json.JSONDecodeError as e:
                logger.error("Error decoding record_ids JSON: %s", str(e))
                return HttpResponse("Invalid JSON data for record_ids", status=400)

        # Delegate bulk delete–related handling to helper
        bulk_delete_response = HorillaBulkDeleteMixin.handle_bulk_delete_post(
            self,
            request=request,
            action=action,
            record_ids=record_ids,
            delete_type=delete_type,
        )
        if bulk_delete_response is not None:
            return bulk_delete_response

        bulk_update_response = HorillaBulkUpdateMixin.handle_bulk_update_post(
            self,
            request=request,
            record_ids=record_ids,
            columns=columns,
        )
        if bulk_update_response is not None:
            return bulk_update_response

        export_response = HorillaBulkExportMixin.handle_bulk_export_post(
            self,
            record_ids=record_ids,
            columns=columns,
            export_format=export_format,
        )
        if export_response is not None:
            return export_response

        # Delegate quick filter add/remove actions to helper
        quick_filter_response = quick_filter.handle_quick_filter_post(
            request, action, self
        )
        if quick_filter_response is not None:
            return quick_filter_response

        return HttpResponse("Invalid request: Missing required fields", status=400)

    def get(self, request, *args, **kwargs):
        """
        Handle GET requests and ensure an HttpResponse is returned.
        """

        self.object_list = self.get_queryset()
        context = self.get_context_data()

        # Handle filter row addition
        if request.GET.get("add_filter_row") == "true":
            curr_row_id = int(request.GET.get("row_id"))
            new_row_id = curr_row_id + 1
            filter_rows = [{"row_id": new_row_id, "logic": "AND"}]
            context["filter_rows"] = filter_rows
            context["is_appended_row"] = True
            return render(request, "partials/filter_row.html", context)

        # Return pre-filled filter rows partial (used by save_filter_form modal)
        if request.GET.get("render_filter_rows") == "true":
            row_id_offset = int(request.GET.get("row_id_offset", 0))
            if row_id_offset:
                for row in context.get("filter_rows", []):
                    row["row_id"] = row["row_id"] + row_id_offset
            return render(request, "partials/filter_row.html", context)

        if "remove_filter" in request.GET:
            return self.handle_remove_filter(request)

        if request.GET.get("clear_all_filters") == "true":
            has_search = request.GET.get("search", "").strip()
            has_other_ops = request.GET.get("apply_filter") or request.GET.get(
                "remove_filter"
            )
            if not has_search and not has_other_ops:
                return self.handle_clear_all_filters(request)

        if request.GET.get("remove_filter_field") == "true":
            return HttpResponse("")

        if request.headers.get("HX-Request") == "true":
            # Delegate quick filter-related HTMX requests to helper
            quick_filter_response = quick_filter.handle_quick_filter_get(request, self)
            if quick_filter_response is not None:
                return quick_filter_response

            if request.GET.get("field_change") and not request.GET.get(
                "operator_change"
            ):
                field_name = request.GET.get("field")
                row_id = request.GET.get("row_id")
                return self.handle_field_change(request, field_name, row_id)

            if request.GET.get("operator_change"):
                field_name = request.GET.get("field")
                operator = request.GET.get("operator")
                row_id = request.GET.get("row_id")
                return self.handle_operator_change(
                    request, field_name, operator, row_id
                )

            return render(request, self.template_name, context)

        return self.render_to_response(context)

    def parse_filter_date_value(self, val, user=None):
        """Parse a filter date string via composed DateTimeFormatter."""
        user = user if user is not None else getattr(self.request, "user", None)
        from horilla.extension.formatting.resolve import get_datetime_formatter

        return get_datetime_formatter().parse_date(val, user=user)

    def parse_filter_datetime_value(self, val, user=None):
        """Parse a filter datetime string via composed DateTimeFormatter."""
        user = user if user is not None else getattr(self.request, "user", None)
        from horilla.extension.formatting.resolve import get_datetime_formatter

        return get_datetime_formatter().parse_datetime(val, user=user)

    def _build_filter_context(self, context, filter_fields, query_params):
        """Populate context with filter rows, operators, field types, and filterset info."""
        field_operators = {}
        field_types = {}
        choices = {}

        operator_display = {
            "exact": _("Equals"),
            "iexact": _("Equals (case insensitive)"),
            "icontains": _("Contains"),
            "ne": _("Not Equals"),
            "gt": _("Greater than"),
            "lt": _("Less than"),
            "gte": _("Greater than or equal to"),
            "lte": _("Less than or equal to"),
            "startswith": _("Starts with"),
            "istartswith": _("Starts with"),
            "endswith": _("Ends with"),
            "iendswith": _("Ends with"),
            "date_range": _("Between"),
            "between": _("Between"),
            "today": _("Today"),
            "yesterday": _("Yesterday"),
            "this_week": _("This Week"),
            "this_month": _("This Month"),
            "this_year": _("This Year"),
            "this_fiscal_period": _("This FP"),
            "this_fiscal_quarter": _("This FQ"),
            "this_fiscal_year": _("This FY"),
            "isnull": _("Is Empty"),
            "isnotnull": _("Is Not Empty"),
        }
        context["operator_display"] = operator_display

        field_verbose_names = {}
        for field in filter_fields:
            field_operators[field["name"]] = field.get("operators", [])
            field_types[field["name"]] = field.get("type", [])
            choices[field["name"]] = field.get("choices", [])
            field_verbose_names[field["name"]] = field.get("verbose_name", "")
        context["field_verbose_names"] = field_verbose_names

        context["filter_push_url"] = "true" if self.filter_url_push else "false"

        filter_rows = []
        if (
            query_params.get("field")
            and self.request.GET.get("add_filter_row") != "true"
        ):

            def _parse_filter_value(val, ftype):
                if not val or ftype not in ("date", "datetime", "time"):
                    return None
                if ftype in ("date", "datetime"):
                    # Datetime fields are filtered by date only (plain date input).
                    return self.parse_filter_date_value(val)
                if ftype == "time":
                    return parse_time(val)
                return None

            for i, field in enumerate(query_params["field"]):
                field_info = next(
                    (f for f in filter_fields if f["name"] == field), None
                )
                field_is_valid = field_info is not None
                field_info = field_info or {}
                raw_value = (
                    query_params.get("value", [None])[i]
                    if i < len(query_params.get("value", []))
                    else None
                )

                # Convert ForeignKey ID(s) / choice value(s) to display value(s).
                # foreignkey/choice fields support multi-select, so raw_value
                # may be a comma-joined list of selected values.
                display_value = raw_value
                value_list = [v for v in raw_value.split(",") if v] if raw_value else []
                display_value_list = []
                if field_info.get("type") == "foreignkey" and value_list:
                    try:
                        model_field = self.model._meta.get_field(field)
                        related_model = model_field.related_model
                        related_objs = related_model.objects.filter(pk__in=value_list)
                        related_by_pk = {str(obj.pk): str(obj) for obj in related_objs}
                        display_value_list = [
                            related_by_pk.get(v, v) for v in value_list
                        ]
                    except Exception:
                        display_value_list = value_list
                    display_value = ", ".join(display_value_list)
                elif field_info.get("type") == "choice" and value_list:
                    try:
                        field_obj = self.model._meta.get_field(field)
                        choices_dict = (
                            dict(field_obj.choices) if field_obj.choices else {}
                        )
                        display_value_list = [
                            str(choices_dict.get(v, v)) for v in value_list
                        ]
                    except Exception:
                        display_value_list = value_list
                    display_value = ", ".join(display_value_list)

                start_value = (
                    query_params.get("start_value", [None])[i]
                    if i < len(query_params.get("start_value", []))
                    else None
                )
                end_value = (
                    query_params.get("end_value", [None])[i]
                    if i < len(query_params.get("end_value", []))
                    else None
                )
                field_type = field_info.get("type")
                operator = (
                    query_params.get("operator", [None])[i]
                    if i < len(query_params.get("operator", []))
                    else None
                )
                logic = (
                    query_params.get("logic", [None])[i]
                    if i < len(query_params.get("logic", []))
                    else None
                )
                if logic not in ("AND", "OR"):
                    logic = "AND"

                row = {
                    "row_id": i,
                    "field": field,
                    "operator": operator,
                    "value": raw_value,
                    "value_list": value_list,
                    "raw_value": display_value,
                    "start_value": start_value,
                    "end_value": end_value,
                    "value_obj": _parse_filter_value(raw_value, field_type),
                    "start_value_obj": _parse_filter_value(start_value, field_type),
                    "end_value_obj": _parse_filter_value(end_value, field_type),
                    "operators": field_operators.get(field, []),
                    "type": field_types.get(field, []),
                    "choices": choices.get(field, []),
                    "model": field_info.get("model", None),
                    "app_label": field_info.get("app_label", None),
                    "verbose_name": field_verbose_names.get(field, field),
                    "operator_display": operator_display.get(operator, operator),
                    "logic": logic,
                    "field_is_valid": field_is_valid,
                }
                if field and operator:
                    filter_rows.append(row)

        # Rows for the Filters modal form: only fields still registered in
        # filter_fields can be rendered (their Select Field/Operator options
        # exist), so a stale/unregistered field (e.g. company filtering
        # toggled off) is dropped here but keeps its "Applied Filters" chip.
        form_filter_rows = [row for row in filter_rows if row.get("field_is_valid")]
        if not form_filter_rows:
            form_filter_rows = [
                {
                    "row_id": 0,
                    "field": None,
                    "operator": None,
                    "value": None,
                    "operators": [],
                    "logic": "AND",
                }
            ]

        # Mark each row that has a rendered "Applied Filters" chip with whether
        # a prior chip already exists, so the template can show the AND/OR pill
        # between chips without relying on forloop.first.
        for index, row in enumerate(filter_rows):
            row["has_prior_chip"] = index > 0

        context["filter_rows"] = form_filter_rows
        context["applied_filter_rows"] = filter_rows
        context["last_row_id"] = max(row["row_id"] for row in form_filter_rows)

        filterset_class = self.get_filterset_class()
        if filterset_class:
            context["filter_class_path"] = (
                f"{filterset_class.__module__}.{filterset_class.__name__}"
            )
            context["parent_model_path"] = (
                f"{self.model._meta.app_label}.{self.model._meta.model_name}"
            )
        else:
            context["filter_class_path"] = None
            context["parent_model_path"] = None

        if hasattr(self, "filterset"):
            context["filterset"] = self.filterset

    def _build_action_context(self, context):
        """Populate context with visible/dropdown actions and bulk action lists."""
        if self.actions and len(self.actions) > self.max_visible_actions:
            context["visible_actions"] = self.actions[: self.max_visible_actions]
            context["dropdown_actions"] = self.actions[self.max_visible_actions :]
            context["use_dropdown"] = True
        else:
            context["visible_actions"] = self.actions
            context["dropdown_actions"] = []
            context["use_dropdown"] = False

        context["custom_bulk_actions"] = self.custom_bulk_actions
        context["additional_action_button"] = self.additional_action_button

    def _build_bulk_context(self, context, filter_fields):
        """Populate context with bulk operation fields, counts, and session state."""
        from horilla.contrib.core.views.export_data import get_export_queryset

        qs = self.object_list
        context["total_records_count"] = qs.count()
        context["selected_ids"] = list(qs.values_list("id", flat=True))
        context["selected_ids_json"] = json.dumps(context["selected_ids"])

        editable_bulk_field_names = get_editable_fields(
            self.request.user, self.model, self.bulk_update_fields
        )
        context["bulk_update_fields"] = [
            field
            for field in filter_fields
            if field["name"] in editable_bulk_field_names
        ]
        user = self.request.user
        app_label = self.model._meta.app_label
        model_name = self.model._meta.model_name

        context["bulk_export_option"] = self.bulk_export_option and (
            get_export_queryset(user, self.model) is not None
        )
        context["bulk_update_option"] = self.bulk_update_option
        context["bulk_delete_enabled"] = self.bulk_delete_enabled

        can_bulk_update = bool(
            self.bulk_update_option
            and context["bulk_update_fields"]
            and (
                user.has_perm(f"{app_label}.change_{model_name}")
                or user.has_perm(f"{app_label}.change_own_{model_name}")
            )
        )
        can_bulk_delete = bool(
            self.bulk_delete_enabled
            and (
                (
                    user.has_perm(f"{app_label}.view_{model_name}")
                    and user.has_perm(f"{app_label}.delete_{model_name}")
                )
                or (
                    user.has_perm(f"{app_label}.delete_own_{model_name}")
                    and user.has_perm(f"{app_label}.view_own_{model_name}")
                )
            )
        )
        has_any_bulk_action = (
            context["bulk_export_option"]
            or can_bulk_update
            or can_bulk_delete
            or bool(self.custom_bulk_actions)
        )
        context["bulk_select_option"] = self.bulk_select_option and has_any_bulk_action

        if self.track_list_navigation:
            session_key = f"list_view_queryset_ids_{self.model._meta.model_name}"
            self.request.session[session_key] = context["selected_ids"]

    def _build_sort_context(self, context):
        """Populate context with sort field, direction, and sorting configuration."""
        context["current_sort"] = self.request.GET.get("sort", self.default_sort_field)
        context["current_direction"] = self.request.GET.get(
            "direction", self.default_sort_direction
        )
        context["enable_sorting"] = self.enable_sorting
        context["sorting_target"] = self.sorting_target
        context["exclude_columns_from_sorting"] = self.exclude_columns_from_sorting

        # Multi-column sort: parse sort_keys into a dict {field: direction} preserving order
        sort_keys_raw = self.request.GET.get("sort_keys", "")
        sort_keys_map = {}
        sort_keys_order = []
        if sort_keys_raw:
            for token in sort_keys_raw.split(","):
                token = token.strip()
                if ":" in token:
                    f, d = token.rsplit(":", 1)
                    f = f.strip()
                    if f not in sort_keys_map:
                        sort_keys_order.append(f)
                    sort_keys_map[f] = d.strip()
                elif token and token not in sort_keys_map:
                    sort_keys_map[token] = self.default_sort_direction
                    sort_keys_order.append(token)
        context["sort_keys_map"] = sort_keys_map
        context["sort_keys_raw"] = sort_keys_raw

    def _has_active_filters(self):
        """Whether search, advanced filters, or quick filters are narrowing the results."""
        get_params = self.request.GET
        if get_params.get("search", "").strip():
            return True
        if any(key.startswith("qf_") and get_params.get(key) for key in get_params):
            return True
        filter_keys = ("field", "operator", "value", "start_value", "end_value")
        if any(get_params.get(key) for key in filter_keys):
            return True
        return False

    def get_context_data(self, **kwargs):
        """Enhance context with column and filtering information."""
        context = super().get_context_data(**kwargs)
        if self.store_ordered_ids:
            context["ordered_ids_key"] = self.ordered_ids_key
            context["ordered_ids"] = self.request.session.get(self.ordered_ids_key, [])

        filter_fields = self._get_model_fields(include_properties=False)
        export_additional_fields = self._get_model_fields(
            include_properties=True, for_export=True
        )

        available_column_names = {col[1] for col in self._get_columns()}
        export_additional_fields = [
            f
            for f in export_additional_fields
            if f["name"] not in available_column_names
        ]

        additional_field_names = [f["name"] for f in export_additional_fields]
        visible_additional_names = filter_hidden_fields(
            self.request.user, self.model, additional_field_names
        )
        export_additional_fields = [
            f for f in export_additional_fields if f["name"] in visible_additional_names
        ]
        view_type = self.request.GET.get("view_type") or self.get_default_view_type()
        context["saved_list_name"] = None  # default

        if view_type and view_type.startswith("saved_list_"):
            try:
                saved_list_id = int(view_type.split("_")[2])
                saved_list = (
                    SavedFilterList.all_objects.filter(id=saved_list_id)
                    .filter(Q(user=self.request.user) | Q(is_public=True))
                    .first()
                )
                if saved_list:
                    context["saved_list_name"] = saved_list.name
                    context["saved_list_is_owner"] = (
                        saved_list.user_id == self.request.user.id
                    )
            except (IndexError, ValueError):
                pass
        context["view_type"] = view_type
        context["filter_fields"] = filter_fields
        context["export_additional_fields"] = export_additional_fields
        context["model_verbose_name"] = self.model._meta.verbose_name_plural
        context["model_name"] = self.model.__name__
        context["no_record_add_button"] = self.no_record_add_button or {}
        context["no_record_section"] = self.no_record_section
        context["no_record_msg"] = self.no_record_msg
        context["no_found_img"] = self.no_found_img
        context["bulk_update_two_column"] = self.bulk_update_two_column
        context["has_active_filters"] = self._has_active_filters()
        header_attrs_dict = {}
        for item in self.header_attrs:
            for col_name, attrs in item.items():
                header_attrs_dict[col_name] = attrs

        col_attrs_dict = {}
        visible_columns = self._get_columns()

        if not visible_columns and self.columns:
            # Filter hidden fields even in fallback case
            field_names = [
                col[1] if isinstance(col, (tuple, list)) and len(col) >= 2 else col
                for col in self.columns
            ]
            visible_field_names = filter_hidden_fields(
                self.request.user, self.model, field_names
            )
            visible_columns = [
                [col[0], col[1]]
                for col in self.columns
                if (col[1] if isinstance(col, (tuple, list)) and len(col) >= 2 else col)
                in visible_field_names
            ]

        if self.col_attrs and visible_columns:
            first_column_field = visible_columns[0][1]
            for item in self.col_attrs:
                for col_name, attrs in item.items():
                    col_attrs_dict[first_column_field] = attrs
                    break
                break

        context["header_attrs"] = header_attrs_dict
        context["col_attrs"] = col_attrs_dict
        context["columns"] = self._get_columns()
        context["raw_attrs"] = self.raw_attrs
        context["view_id"] = self.view_id
        context["action_method"] = self.action_method
        context["current_query"] = self.request.GET.urlencode()
        context["is_htmx_request"] = self.request.headers.get("HX-Request") == "true"
        context["has_next"] = False
        context["next_page"] = None
        if "page_obj" in context and context["page_obj"] is not None:
            context["has_next"] = context["page_obj"].has_next()
            if context["has_next"]:
                context["next_page"] = context["page_obj"].next_page_number()
        context["search_url"] = self.search_url or self.request.path
        context["main_url"] = self.main_url or self.request.path
        from horilla.urls import resolve as _resolve

        try:
            context["list_view_url_name"] = _resolve(self.request.path_info).url_name
        except Exception:
            context["list_view_url_name"] = ""
        context["main_session_id"] = getattr(self, "main_session_id", "mainSession")
        query_params = {
            item: self.request.GET.getlist(item) for item in self.request.GET
        }
        context["query_params"] = query_params
        context["pinned_view"] = self._get_pinned_view()
        context["model_name"] = self.model.__name__
        context["app_label"] = self.model._meta.app_label
        search_params = self.request.GET.copy()
        if "page" in search_params:
            del search_params["page"]
        context["search_params"] = search_params.urlencode()
        context["filter_set_class"] = self.get_filterset_class()
        # The navbar(s) searching this list decide whether it gets a filter panel
        from .navbar import HorillaNavView

        navs = HorillaNavView.for_list_url(self.request.path)
        context["filter_panel_option"] = self.filter_panel_option and all(
            nav.filter_option for nav in navs
        )
        context["table_width"] = self.table_width
        context["no_record_fit_height"] = self.no_record_fit_height
        context["table_class"] = self.table_class
        context["table_height_as_class"] = self.table_height_as_class
        context["table_auto"] = self.table_auto
        # Saved lists are view types, so a navbar without view types can't offer them
        context["save_to_list_option"] = self.save_to_list_option and all(
            nav.all_view_types for nav in navs
        )

        self._build_sort_context(context)
        self._build_filter_context(context, filter_fields, query_params)
        self._build_action_context(context)
        self._build_bulk_context(context, filter_fields)

        # Let helper inject quick filter-related context
        quick_filter.update_quick_filter_context(context, self)
        return context
