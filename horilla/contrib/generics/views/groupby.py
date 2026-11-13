"""
Generic view for displaying data in a grouped list layout.
Groups rows by a selected field (ChoiceField or ForeignKey) and displays.
"""

# Standard library imports
import json
import logging

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator

# Third-party imports (Django)
from django.db.models import Count
from django.template.loader import render_to_string

from horilla.contrib.core.models import KanbanGroupBy
from horilla.contrib.core.utils import get_user_field_permission
from horilla.core.exceptions import FieldError
from horilla.db.models import ForeignKey
from horilla.shortcuts import render

# First-party (Horilla)
from horilla.urls import reverse
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.text import slugify
from horilla.utils.translation import gettext_lazy as _
from horilla.web import HttpResponse

# Local imports
from ..methods import group_label_with_company, group_order_by
from .list import HorillaListView

logger = logging.getLogger(__name__)

# House palette only (see tailwind.config.js `primary` scale). All levels stay
# plain white so the table reads as data, not stacked colored cards - matches
# the plain list view's row background exactly.
GROUP_LEVEL_BG_CLASSES = ["bg-white", "bg-white", "bg-white", "bg-white"]


@method_decorator(htmx_required, name="dispatch")
class HorillaGroupByView(HorillaListView):
    """
    Generic view for displaying data in a grouped list layout.
    Groups rows by a selected field (ChoiceField or ForeignKey) and displays
    them as collapsible sections. Uses same group-by preference as Kanban.
    """

    template_name = "group_by_view.html"
    supports_quick_filters = False
    group_by_field = None
    group_by_param = "group_by"
    filterset_module = "filters"
    bulk_select_option = True
    table_class = True
    paginate_by = 20

    _view_registry = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "model") and cls.model:
            HorillaGroupByView._view_registry[cls.model] = cls

    def _get_kanban_exclude_include_fields(self, view_type="group_by"):
        """Return (exclude_fields, include_fields) used by Kanban/GroupBy settings for this view."""
        exclude_str = getattr(self, "exclude_kanban_fields", "") or ""
        exclude_fields = [f.strip() for f in exclude_str.split(",") if f.strip()]
        include_fields = getattr(self, "include_kanban_fields", None)
        return exclude_fields, include_fields

    def _get_allowed_group_by_fields(self, view_type="group_by"):
        """Return list of field names the user is allowed to group by (respects field permissions
        and exclude_kanban_fields so we only consider fields shown in settings).
        """
        model_name = self.model.__name__
        app_label = self.model._meta.app_label
        exclude_fields, include_fields = self._get_kanban_exclude_include_fields(
            view_type
        )
        temp = KanbanGroupBy(model_name=model_name, app_label=app_label)
        choices = temp.get_model_groupby_fields(
            user=self.request.user,
            exclude_fields=exclude_fields,
            include_fields=include_fields,
        )
        return [c[0] for c in choices]

    def _is_field_visible_for_group_by(self, field_name):
        """Check if a field is visible (not hidden) for the current user."""
        if not field_name:
            return False
        perm = get_user_field_permission(self.request.user, self.model, field_name)
        return perm != "hidden"

    def get_group_by_field_choices(self):
        """Return (value, label) choices for the group-by field selector."""
        model_name = self.model.__name__
        app_label = self.model._meta.app_label
        exclude_fields, include_fields = self._get_kanban_exclude_include_fields(
            "group_by"
        )
        temp = KanbanGroupBy(model_name=model_name, app_label=app_label)
        choices = temp.get_model_groupby_fields(
            user=self.request.user,
            exclude_fields=exclude_fields,
            include_fields=include_fields,
        )
        return [
            (value, label)
            for value, label in choices
            if self._is_field_visible_for_group_by(value)
        ]

    def get_group_by_fields(self):
        """Return the ordered list of fields to nest rows by.

        Priority: `group_by` GET param (comma-separated, ordered) if it has at
        least one valid+visible field, else the saved Kanban/GroupBy
        preference as a single-field list, else the first allowed field.
        Nothing is cached in the session: the page URL carries the choice.
        Invalid/hidden/duplicate field names in the GET param are dropped
        rather than rejecting the whole list.
        """
        allowed = self._get_allowed_group_by_fields(view_type="group_by")

        def _clean(raw_names):
            seen = set()
            cleaned = []
            for name in raw_names:
                name = (name or "").strip()
                if (
                    name
                    and name not in seen
                    and name in allowed
                    and self._is_field_visible_for_group_by(name)
                ):
                    seen.add(name)
                    cleaned.append(name)
            return cleaned

        requested_raw = self.request.GET.get(self.group_by_param)
        if requested_raw:
            requested = _clean(requested_raw.split(","))
            if requested:
                # With "all companies" on, group by company first so each
                # company's own records (e.g. its lead stages) nest under it.
                if "company" in requested and self.request.session.get(
                    "show_all_companies", False
                ):
                    requested.remove("company")
                    requested.insert(0, "company")
                return requested

        model_name = self.model.__name__
        app_label = self.model._meta.app_label
        default_group = KanbanGroupBy.all_objects.filter(
            model_name=model_name,
            app_label=app_label,
            user=self.request.user,
            view_type="group_by",
        ).first()
        preferred = default_group.field_name if default_group else self.group_by_field
        if (
            preferred
            and preferred in allowed
            and self._is_field_visible_for_group_by(preferred)
        ):
            return [preferred]
        for field_name in allowed:
            if self._is_field_visible_for_group_by(field_name):
                return [field_name]
        return []

    def get_group_by_field(self):
        """Return the first (primary) field used to group rows.

        Kept for callers that only care about a single grouping field.
        """
        fields = self.get_group_by_fields()
        return fields[0] if fields else None

    def _validate_group_by_field(self, field_name):
        """Return the model field for `field_name` if it's groupable, else raise FieldError."""
        field = self.get_group_field(field_name)
        if not (
            (hasattr(field, "choices") and field.choices)
            or isinstance(field, ForeignKey)
        ):
            raise FieldError(
                str(
                    _("Field '%(field)s' is not a Choice field or ForeignKey field.")
                    % {"field": field_name}
                )
            )
        return field

    def _group_label(self, field, field_name, key):
        """Return the display label for a single group key, without building
        the full ordered group list (used when a group's identity is already
        known, e.g. from a `group_path`, and only its label is needed).
        """
        if hasattr(field, "choices") and field.choices:
            choices = dict(field.choices)
            if key in choices:
                return choices[key]
            return f"Unknown ({key})"

        if key is None:
            return str(_("None"))
        related_model = field.related_model
        related_item = related_model.objects.filter(pk=key).first()
        return (
            group_label_with_company(
                self.request,
                related_item,
                show_company="company" not in self.get_group_by_fields(),
            )
            if related_item is not None
            else f"Unknown ({key})"
        )

    def _ordered_group_values(self, field, field_name, queryset):
        """Return an ordered list of (key, label, sub_queryset) for one grouping level."""
        groups = {}
        if hasattr(field, "choices") and field.choices:
            for value, label in field.choices:
                groups[value] = (label, queryset.filter(**{field_name: value}))
            existing_values = set(queryset.values_list(field_name, flat=True))
            for value in existing_values:
                if value not in groups:
                    groups[value] = (
                        f"Unknown ({value})",
                        queryset.filter(**{field_name: value}),
                    )
            ordered_keys = [value for value, __ in field.choices if value in groups]
            ordered_keys += [key for key in groups if key not in ordered_keys]
            return [(key, groups[key][0], groups[key][1]) for key in ordered_keys]

        related_model = field.related_model
        related_qs = related_model.objects.all()
        active_company = getattr(self.request, "active_company", None)
        if (
            active_company is not None
            and not self.request.session.get("show_all_companies", False)
            and any(f.name == "company" for f in related_model._meta.fields)
        ):
            related_qs = related_qs.filter(company=active_company)
        related_items = related_qs.order_by(
            *group_order_by(self.request, related_model)
        )

        show_company = "company" not in self.get_group_by_fields()
        for related_item in related_items:
            groups[related_item.pk] = (
                group_label_with_company(
                    self.request, related_item, show_company=show_company
                ),
                queryset.filter(**{f"{field_name}__pk": related_item.pk}),
            )

        if field.null:
            none_qs = queryset.filter(**{f"{field_name}__isnull": True})
            if none_qs.exists():
                groups[None] = (str(_("None")), none_qs)

        ordered_keys = [item.pk for item in related_items if item.pk in groups]
        if None in groups:
            ordered_keys.append(None)
        return [(key, groups[key][0], groups[key][1]) for key in ordered_keys]

    def _group_counts(self, field, field_name, queryset):
        """Return {key: count} for every value of `field_name` in `queryset`,
        computed with one GROUP BY query instead of one .count() per group.
        """
        lookup = (
            field_name
            if hasattr(field, "choices") and field.choices
            else f"{field_name}__pk"
        )
        rows = queryset.values(lookup).annotate(_group_total=Count("pk")).order_by()
        return {row[lookup]: row["_group_total"] for row in rows}

    def _build_group_load_more_url(self, group_path):
        """Build the load-more URL for the leaf group identified by `group_path`."""
        app_label = self.model._meta.app_label
        model_name = self.model.__name__
        load_more_params = self.request.GET.copy()
        load_more_params["group_path"] = "|".join(
            "" if key is None else str(key) for key in group_path
        )
        load_more_params["page"] = 1
        load_more_base = reverse(
            "generics:group_by_load_more",
            kwargs={"app_label": app_label, "model_name": model_name},
        )
        return f"{load_more_base}?{load_more_params.urlencode()}"

    def _build_group_expand_url(self, group_path):
        """Build the lazy-expand URL for the (branch or leaf) group at `group_path`."""
        app_label = self.model._meta.app_label
        model_name = self.model.__name__
        expand_params = self.request.GET.copy()
        expand_params["group_path"] = "|".join(
            "" if key is None else str(key) for key in group_path
        )
        expand_base = reverse(
            "generics:group_by_expand",
            kwargs={"app_label": app_label, "model_name": model_name},
        )
        return f"{expand_base}?{expand_params.urlencode()}"

    @staticmethod
    def _group_ids_json(qs):
        """JSON list of record ids in a group, used by the group-level select checkbox."""
        return json.dumps(list(qs.values_list("id", flat=True)))

    def _company_scoped_group_pks(self, field, path):
        """For a foreign-key group level nested under a Company group, return the
        pks of the related records that belong to that company (so a company only
        lists its own stages); None when no restriction applies."""
        related_model = getattr(field, "related_model", None)
        if (
            related_model is None
            or not self.request.session.get("show_all_companies", False)
            or not any(f.name == "company" for f in related_model._meta.fields)
        ):
            return None
        full_fields = self.get_group_by_fields()
        for fname, pkey in zip(full_fields[: len(path)], path):
            if fname == "company" and pkey is not None:
                return set(
                    related_model._default_manager.filter(company_id=pkey).values_list(
                        "pk", flat=True
                    )
                )
        return None

    def _build_group_tree(self, queryset, fields, path=(), max_depth=None):
        """Recursively group `queryset` by `fields` (in order), returning an
        ordered dict of key -> node. A node is a leaf (paginated `items`) when
        it's the last field, else it has `sub_groups` (another such dict).

        `max_depth` caps how many levels get built/rendered right now (counted
        from this call's `path`, i.e. `1` builds only the level being iterated
        here). Any node beyond that depth still gets an accurate `total_count`
        (one aggregate query per level, same as always) but no descendants -
        it's marked `needs_fetch: True` with its own `group_path` so the
        client can fetch that subtree on demand instead of the whole tree
        being built/rendered eagerly regardless of what's actually expanded.
        """
        field_name = fields[0]
        field = self.get_group_field(field_name)
        is_leaf = len(fields) == 1
        at_depth_limit = max_depth is not None and max_depth <= 0
        paginate_by = getattr(self, "paginate_by", 20)
        nodes = {}
        counts = self._group_counts(field, field_name, queryset)
        scoped_pks = (
            self._company_scoped_group_pks(field, path)
            if field_name != "company"
            else None
        )

        for key, label, sub_qs in self._ordered_group_values(
            field, field_name, queryset
        ):
            if scoped_pks is not None and key is not None and key not in scoped_pks:
                continue
            total_count = counts.get(key, 0)
            group_path = path + (key,)
            group_id = f"{self.view_id}-{slugify('-'.join(str(k) for k in group_path))}"

            if at_depth_limit:
                nodes[key] = {
                    "label": label,
                    "field_label": str(field.verbose_name).title(),
                    "level": len(path),
                    "level_class": GROUP_LEVEL_BG_CLASSES[
                        len(path) % len(GROUP_LEVEL_BG_CLASSES)
                    ],
                    "is_leaf": is_leaf,
                    "group_id": group_id,
                    "total_count": total_count,
                    "needs_fetch": True,
                    "record_ids_json": self._group_ids_json(sub_qs),
                    "expand_url": self._build_group_expand_url(group_path),
                    "data_container_id": group_id,
                }
                continue

            if is_leaf:
                ordered_items = sub_qs.order_by("id")
                paginator = Paginator(ordered_items, paginate_by)
                # We already know the count from the aggregate query above -
                # pre-seed Paginator's cached_property so it skips its own
                # COUNT(*) (one fewer query per leaf group; with many leaf
                # groups this was a large share of total query volume).
                paginator.count = total_count
                page = self.request.GET.get(f"page_{key}", 1)
                try:
                    page_obj = paginator.page(page)
                except PageNotAnInteger:
                    page_obj = paginator.page(1)
                except EmptyPage:
                    page_obj = paginator.page(paginator.num_pages)
                nodes[key] = {
                    "label": label,
                    "field_label": str(field.verbose_name).title(),
                    "level": len(path),
                    "level_class": GROUP_LEVEL_BG_CLASSES[
                        len(path) % len(GROUP_LEVEL_BG_CLASSES)
                    ],
                    "is_leaf": True,
                    "group_id": group_id,
                    "items": page_obj.object_list,
                    "page_obj": page_obj,
                    "has_next": page_obj.has_next(),
                    "next_page": (
                        page_obj.next_page_number() if page_obj.has_next() else None
                    ),
                    "total_count": total_count,
                    "record_ids_json": self._group_ids_json(sub_qs),
                    "load_more_url": self._build_group_load_more_url(group_path),
                    "data_container_id": group_id,
                }
            else:
                next_max_depth = None if max_depth is None else max_depth - 1
                sub_groups = self._build_group_tree(
                    sub_qs, fields[1:], group_path, max_depth=next_max_depth
                )
                nodes[key] = {
                    "label": label,
                    "field_label": str(field.verbose_name).title(),
                    "level": len(path),
                    "level_class": GROUP_LEVEL_BG_CLASSES[
                        len(path) % len(GROUP_LEVEL_BG_CLASSES)
                    ],
                    "is_leaf": False,
                    "group_id": group_id,
                    "total_count": total_count,
                    "record_ids_json": self._group_ids_json(sub_qs),
                    "sub_groups": sub_groups,
                }
        return nodes

    def get_context_data(self, **kwargs):
        """Populate context with grouped items for list display."""
        if not hasattr(self, "object_list"):
            self.object_list = self.get_queryset()

        context = super().get_context_data(**kwargs)
        queryset = self.object_list
        group_by_fields = self.get_group_by_fields()

        app_label = self.model._meta.app_label if self.model else ""
        model_name = self.model.__name__ if self.model else ""
        context["app_label"] = app_label
        context["model_name"] = model_name
        context["group_by_param"] = self.group_by_param
        context["group_by_field_choices"] = self.get_group_by_field_choices()

        if not group_by_fields:
            context["error"] = _(
                "No grouping field specified or you don't have permission to view any grouping fields."
            )
            return context

        try:
            for field_name in group_by_fields:
                self._validate_group_by_field(field_name)

            grouped_items = self._build_group_tree(
                queryset, group_by_fields, max_depth=1
            )

            context["grouped_items"] = grouped_items
            context["group_by_fields"] = group_by_fields
            context["group_by_field"] = group_by_fields[0]
            context["group_by_label"] = self.get_group_field(
                group_by_fields[0]
            ).verbose_name
            context["queryset"] = queryset
            context["total_records_count"] = queryset.count()

        except FieldError as e:
            context["error"] = _("Invalid grouping field: %(err)s") % {"err": str(e)}
        except Exception as e:
            context["error"] = _("Error grouping data: %(err)s") % {"err": str(e)}
        return context

    def load_more_items(self, request, *args, **kwargs):
        """
        Load more items for a specific (possibly nested) group with filters
        and search applied. Returns table rows (tr elements) for the next
        page of the leaf group identified by `group_path`.
        """
        group_path_raw = request.GET.get("group_path")
        page = request.GET.get("page")
        group_by_fields = self.get_group_by_fields()

        if not page or not group_by_fields or group_path_raw is None:
            return HttpResponse(status=400, content="Missing required parameters")

        group_path = group_path_raw.split("|") if group_path_raw else []
        if len(group_path) != len(group_by_fields):
            return HttpResponse(status=400, content="Invalid group path")

        try:
            queryset = self.get_queryset()
            typed_group_path = []
            for field_name, raw_key in zip(group_by_fields, group_path):
                field = self.get_group_field(field_name)
                key = raw_key if raw_key != "" else None
                if isinstance(field, ForeignKey):
                    if key is None:
                        queryset = queryset.filter(**{f"{field_name}__isnull": True})
                    else:
                        if key.isdigit():
                            key = int(key)
                        queryset = queryset.filter(**{f"{field_name}__pk": key})
                else:
                    queryset = queryset.filter(**{field_name: key})
                typed_group_path.append(key)

            items = queryset.order_by("id")
            paginate_by = getattr(self, "paginate_by", 20)
            paginator = Paginator(items, paginate_by)
            try:
                page_obj = paginator.page(page)
            except PageNotAnInteger:
                page_obj = paginator.page(1)
            except EmptyPage:
                return HttpResponse("")

            # Only the base list-view context (columns, permissions, header
            # attrs, etc.) is needed to render rows here - NOT a full rebuild
            # of the group-by tree via HorillaGroupByView.get_context_data(),
            # which this used to call just to throw away everything except
            # the few keys overwritten right after. The base get_context_data
            # (MultipleObjectMixin) requires self.object_list to be set.
            if not hasattr(self, "object_list"):
                self.object_list = self.get_queryset()
            context = super().get_context_data()
            context["queryset"] = page_obj.object_list
            context["has_next"] = page_obj.has_next()
            context["next_page"] = (
                page_obj.next_page_number() if page_obj.has_next() else None
            )
            context["data_container_id"] = (
                f"{self.get_view_id()}-"
                f"{slugify('-'.join(str(k) for k in typed_group_path))}"
            )
            load_more_params = request.GET.copy()
            load_more_params["group_path"] = group_path_raw
            load_more_params["page"] = (
                page_obj.next_page_number() if page_obj.has_next() else 1
            )
            app_label = self.model._meta.app_label
            model_name = self.model.__name__
            load_more_base = reverse(
                "generics:group_by_load_more",
                kwargs={"app_label": app_label, "model_name": model_name},
            )
            context["group_by_load_more_url"] = (
                f"{load_more_base}?{load_more_params.urlencode()}"
            )
            context["search_params"] = request.GET.urlencode()

            return HttpResponse(
                render_to_string(
                    "partials/group_by_load_more_rows.html", context, request=request
                )
            )
        except Exception as e:
            logger.error("Group by load more failed: %s", str(e))
            return HttpResponse(status=500, content=f"Error: {str(e)}")

    def expand_group(self, request, *args, **kwargs):
        """
        Lazily build and render whatever is one level below the (branch or
        leaf) group at `group_path` - the group-by tree is only built one
        level deep up front (see `_build_group_tree`'s `max_depth`), so the
        first time a user expands any group beyond that, this fetches just
        that group's own children (more sub-groups, or its first page of
        rows) instead of the whole tree having been built/rendered eagerly.
        """
        group_path_raw = request.GET.get("group_path")
        group_by_fields = self.get_group_by_fields()

        if not group_by_fields or group_path_raw is None:
            return HttpResponse(status=400, content="Missing required parameters")

        group_path = group_path_raw.split("|") if group_path_raw else []
        if len(group_path) > len(group_by_fields):
            return HttpResponse(status=400, content="Invalid group path")

        try:
            queryset = self.get_queryset()
            typed_group_path = []
            for field_name, raw_key in zip(group_by_fields, group_path):
                field = self.get_group_field(field_name)
                key = raw_key if raw_key != "" else None
                if isinstance(field, ForeignKey):
                    if key is None:
                        queryset = queryset.filter(**{f"{field_name}__isnull": True})
                    else:
                        if key.isdigit():
                            key = int(key)
                        queryset = queryset.filter(**{f"{field_name}__pk": key})
                else:
                    queryset = queryset.filter(**{field_name: key})
                typed_group_path.append(key)

            remaining_fields = group_by_fields[len(group_path) :]
            if remaining_fields:
                group_tree = self._build_group_tree(
                    queryset,
                    remaining_fields,
                    path=tuple(typed_group_path),
                    max_depth=1,
                )
                level = len(typed_group_path)
                parent_path = typed_group_path
            else:
                # group_path already names the leaf group itself (it's the last
                # field's value, not a branch to sub-group further) - build its
                # one row-paginated node directly instead of recursing into
                # _build_group_tree with an empty fields list, which has
                # nothing to group by.
                leaf_key = typed_group_path[-1]
                leaf_field_name = group_by_fields[-1]
                leaf_field = self.get_group_field(leaf_field_name)
                leaf_label = self._group_label(leaf_field, leaf_field_name, leaf_key)
                total_count = queryset.count()
                items = queryset.order_by("id")
                paginate_by = getattr(self, "paginate_by", 20)
                paginator = Paginator(items, paginate_by)
                paginator.count = total_count
                page = request.GET.get(f"page_{leaf_key}", 1)
                try:
                    page_obj = paginator.page(page)
                except PageNotAnInteger:
                    page_obj = paginator.page(1)
                except EmptyPage:
                    page_obj = paginator.page(paginator.num_pages)
                group_id = (
                    f"{self.view_id}-"
                    f"{slugify('-'.join(str(k) for k in typed_group_path))}"
                )
                group_tree = {
                    leaf_key: {
                        "label": leaf_label,
                        "field_label": str(leaf_field.verbose_name).title(),
                        "level": len(typed_group_path) - 1,
                        "level_class": GROUP_LEVEL_BG_CLASSES[
                            (len(typed_group_path) - 1) % len(GROUP_LEVEL_BG_CLASSES)
                        ],
                        "is_leaf": True,
                        "group_id": group_id,
                        "items": page_obj.object_list,
                        "page_obj": page_obj,
                        "has_next": page_obj.has_next(),
                        "next_page": (
                            page_obj.next_page_number() if page_obj.has_next() else None
                        ),
                        "total_count": total_count,
                        "record_ids_json": self._group_ids_json(queryset),
                        "load_more_url": self._build_group_load_more_url(
                            tuple(typed_group_path)
                        ),
                        "data_container_id": group_id,
                    }
                }
                level = len(typed_group_path) - 1
                parent_path = typed_group_path[:-1]

            if not hasattr(self, "object_list"):
                self.object_list = self.get_queryset()
            context = super().get_context_data()
            context["group_tree"] = group_tree
            context["level"] = level
            context["colspan"] = 99
            # The leaf group's header row is already on the page (it is the
            # row that was clicked); only its rows must be rendered.
            context["skip_divider"] = not remaining_fields
            context["parent_row_id"] = (
                f"{self.view_id}-" f"{slugify('-'.join(str(k) for k in parent_path))}"
            )

            return HttpResponse(
                render_to_string(
                    "partials/group_by_node.html", context, request=request
                )
            )
        except Exception as e:
            logger.error("Group by expand failed: %s", str(e))
            return HttpResponse(status=500, content=f"Error: {str(e)}")

    def get_view_id(self):
        """Return the view_id for this view."""
        return getattr(self, "view_id", "group-by-view")

    def render_to_response(self, context, **response_kwargs):
        """Override to ensure HTMX requests get the group_by template."""
        is_htmx = self.request.headers.get("HX-Request") == "true"
        context["request_params"] = self.request.GET.copy()
        if is_htmx:
            return render(self.request, self.template_name, context)
        return super().render_to_response(context, **response_kwargs)
