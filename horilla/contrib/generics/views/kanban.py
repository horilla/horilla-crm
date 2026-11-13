"""
View for displaying data in a kanban board layout with group-by functionality.
"""

# Standard library imports
import json
import logging

# Third-party imports (Django)
from django.contrib import messages
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import IntegrityError
from django.template.loader import render_to_string

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import login_redirect
from horilla.contrib.core.models import KanbanGroupBy
from horilla.contrib.core.utils import get_user_field_permission
from horilla.core.exceptions import FieldDoesNotExist, FieldError, ImproperlyConfigured
from horilla.db import transaction
from horilla.db.models import ForeignKey, Max
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.translation import gettext_lazy as _
from horilla.web import HttpNotFound, HttpResponse, QueryDict, ScriptResponse

# Local imports
from ..methods import group_label_with_company, group_order_by
from .list import HorillaListView

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
class HorillaKanbanView(HorillaListView):
    """View for displaying data in a kanban board layout with group-by functionality."""

    template_name = "kanban_view.html"
    supports_quick_filters = False
    group_by_field = None
    paginate_by = 30
    filterset_module = "filters"
    kanban_attrs: str = None
    height_kanban = None
    # Order items within each column: "-updated_at" (newest updated first) or override with tuple/list
    kanban_order_by = "-updated_at"

    _view_registry = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "model") and cls.model:
            HorillaKanbanView._view_registry[cls.model] = cls

    def dispatch(self, request, *args, **kwargs):
        """Ensure user is authenticated and resolve model from URL/POST; then dispatch."""
        if not self.request.user.is_authenticated:
            return login_redirect(request)
        app_label = kwargs.get("app_label")
        app_label = app_label.split(".")[-1] if app_label else ""
        model_name = kwargs.get("model_name") or request.POST.get("model_name")
        if model_name:
            try:
                self.model = apps.get_model(app_label=app_label, model_name=model_name)
            except Exception as e:
                logger.error("Error fetching model: %s", str(e))
                raise HttpNotFound(
                    f"Invalid app_label/model_name: {app_label}/{model_name}"
                ) from e

        if self.model is None:
            raise ImproperlyConfigured("Model must be specified via URL or POST data.")

        return super().dispatch(request, *args, **kwargs)

    def get_kanban_order_by(self):
        """Return order_by value for items within each kanban column (e.g. by updated)."""
        order = getattr(self, "kanban_order_by", "-updated_at")
        if isinstance(order, (list, tuple)):
            return order
        # If model has no updated_at, fall back to -id
        if order == "-updated_at" and self.model:
            try:
                self.model._meta.get_field("updated_at")
            except Exception:
                return "-id"
        return order

    def can_user_modify_item(self, item):
        """
        Check if the user has permission to modify the item.
        Returns True if user can modify, False otherwise.
        """
        user = self.request.user
        model = self.model
        app_label = model._meta.app_label
        model_name = model._meta.model_name

        # Check if user has global change permission
        change_perm = f"{app_label}.change_{model_name}"
        if user.has_perm(change_perm):
            return True

        # Check for change_own permission
        change_own_perm = f"{app_label}.change_own_{model_name}"
        if user.has_perm(change_own_perm):
            # Get owner fields from model
            owner_fields = getattr(model, "OWNER_FIELDS", [])

            # Check if user owns this item
            for owner_field in owner_fields:
                try:
                    owner_value = getattr(item, owner_field, None)
                    if owner_value == user:
                        return True
                except AttributeError:
                    continue

            from .helpers.queryset_utils import user_has_granted_access

            if user_has_granted_access(item, user, "change"):
                return True

        return False

    def post(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        if request.POST.get("item_id") and request.POST.get("new_column"):
            return self.update_kanban_item(request)
        if request.POST.get("column_order"):
            return self.update_kanban_column_order(request)
        return super().post(request, *args, **kwargs)

    def update_kanban_item(self, request):
        """Move a Kanban item to a new column and render the updated content."""
        item_id = request.POST.get("item_id")
        new_column = request.POST.get("new_column")
        app_label = request.POST.get("app_label")
        model_name = request.POST.get("model_name")
        class_name = request.POST.get("class_name")

        if not all([item_id, new_column, app_label, model_name, class_name]):
            return HttpResponse(status=400, content="Missing required parameters")

        try:
            view_class = HorillaKanbanView._view_registry.get(self.model)
            if not view_class:
                return HttpResponse(
                    status=404, content=f"View class {class_name} not found"
                )

            # Instantiate the view class and ensure it has attributes set by dispatch
            view = view_class()
            view.request = request
            view.kwargs = getattr(view, "kwargs", {})

            # If the registered view class has overridden update_kanban_item, delegate to it.
            if (
                type(view).update_kanban_item
                is not HorillaKanbanView.update_kanban_item
            ):
                try:
                    view.model = apps.get_model(
                        app_label=app_label.split(".")[-1], model_name=model_name
                    )
                except LookupError:
                    messages.error(
                        request,
                        f"Invalid app_label/model_name: {app_label}/{model_name}",
                    )
                    return ScriptResponse(reload=True)
                view.object_list = view.get_queryset()
                return view.update_kanban_item(request)

            # Initialize model
            try:
                view.model = apps.get_model(
                    app_label=app_label.split(".")[-1], model_name=model_name
                )
            except LookupError:
                messages.error(
                    request, f"Invalid app_label/model_name: {app_label}/{model_name}"
                )
                return ScriptResponse(reload=True)

            group_by = view.get_group_by_field()
            try:
                item = view.model.objects.get(pk=item_id)
                if not view.can_user_modify_item(item):
                    messages.error(
                        request, "You don't have permission to modify this item"
                    )
                    return ScriptResponse(reload=True)

                field = view.get_group_field(group_by)

                if hasattr(field, "choices") and field.choices:
                    valid_choices = dict(field.choices)
                    reverse_choices = {v: k for k, v in valid_choices.items()}
                    if new_column in reverse_choices:
                        setattr(item, group_by, reverse_choices[new_column])
                    elif new_column in valid_choices:
                        setattr(item, group_by, new_column)
                    else:
                        return HttpResponse(
                            status=400, content=f"Invalid column value: {new_column}"
                        )

                elif isinstance(field, ForeignKey):
                    if new_column.lower() == "none":
                        setattr(item, group_by, None)
                    else:
                        related_model = field.related_model
                        try:
                            related_obj = related_model.objects.get(pk=new_column)
                            item_company_id = getattr(item, "company_id", None)
                            related_company_id = getattr(
                                related_obj, "company_id", None
                            )
                            if (
                                item_company_id
                                and related_company_id
                                and item_company_id != related_company_id
                            ):
                                messages.error(
                                    request,
                                    "This item belongs to a different company than "
                                    "the selected column, so it cannot be moved there.",
                                )
                                return ScriptResponse(reload=True)
                            setattr(item, group_by, related_obj)
                        except related_model.DoesNotExist:
                            return HttpResponse(
                                status=400,
                                content=f"Invalid related object: {new_column}",
                            )

                item.save()
                view.persist_group_value(item, group_by)

            except view.model.DoesNotExist:
                messages.error(request, "Item Not found")
                return ScriptResponse(reload=True)

            # Reconstruct query parameters
            query_params = QueryDict(mutable=True)
            for key, values in request.POST.lists():
                if key not in [
                    "item_id",
                    "new_column",
                    "app_label",
                    "model_name",
                    "class_name",
                    "csrfmiddlewaretoken",
                ]:
                    for value in values:
                        query_params.appendlist(key, value)

            # FIXED: Use the complete get_queryset logic instead of basic filtering
            view.request.GET = query_params

            # Apply the full queryset logic from HorillaListView
            view.object_list = view.get_queryset()

            # Get context
            context = view.get_context_data()
            context["app_label"] = app_label
            context["model_name"] = model_name
            context["class_name"] = class_name

            rendered_content = render_to_string(
                "partials/kanban_blocks.html", context, request=request
            )

            main_url = getattr(
                view, "main_url", f"/generics/kanban/{app_label}/{model_name}/"
            )
            response = HttpResponse(rendered_content)
            new_query_string = query_params.urlencode()
            url = main_url + (f"?{new_query_string}" if new_query_string else "")
            response["HX-Push-Url"] = url
            return response

        except Exception as e:
            logger.exception(
                "update_kanban_item failed for %s.%s: %s",
                app_label,
                model_name,
                e,
            )
            return HttpResponse(status=500, content=f"Error: {str(e)}")

    def update_kanban_column_order(self, request):
        """Update stored Kanban column ordering for a model and return updated view."""
        app_label = request.POST.get("app_label")
        model_name = request.POST.get("model_name")
        class_name = request.POST.get("class_name")
        column_order = request.POST.get("column_order")

        # Validate required parameters

        try:
            # Dynamically import the view class
            view_class = HorillaKanbanView._view_registry.get(self.model)
            if not view_class:
                return HttpResponse(
                    status=404, content=f"View class {class_name} not found"
                )

            # Instantiate the view class
            view = view_class()
            view.request = request
            view.model = apps.get_model(
                app_label=app_label.split(".")[-1], model_name=model_name
            )
            main_url = getattr(view, "main_url")

            group_by = view.get_group_by_field()
            try:
                field = view.get_group_field(group_by)
                if not isinstance(field, ForeignKey):
                    return HttpResponse(
                        status=400,
                        content="Column ordering is only supported for ForeignKey fields.",
                    )

                related_model = field.related_model
                if "order" not in [f.name for f in related_model._meta.get_fields()]:
                    return HttpResponse(
                        status=400,
                        content=f"Related model {related_model.__name__} does not support ordering",
                    )
            except Exception as e:
                logger.error("Error fetching group_by field: %s", str(e))
                return HttpResponse(
                    status=400,
                    content=f"Invalid group_by field: {group_by}",
                )

            try:
                column_order = json.loads(column_order)
                if not isinstance(column_order, list):
                    raise ValueError("column_order must be a list")
            except json.JSONDecodeError:
                return HttpResponse(status=400, content="Invalid column_order format")

            try:
                with transaction.atomic():
                    max_order = (
                        related_model.objects.aggregate(Max("order"))["order__max"] or 0
                    )
                    temp_offset = max_order + 1000
                    valid_pks = []
                    for index, column_key in enumerate(column_order):
                        if column_key == "None":
                            continue
                        try:
                            related_obj = related_model.objects.get(pk=column_key)
                            related_obj.order = temp_offset + index
                            related_obj.save()
                            valid_pks.append(column_key)
                        except related_model.DoesNotExist:
                            continue

                    for index, column_key in enumerate(valid_pks):
                        related_obj = related_model.objects.get(pk=column_key)
                        related_obj.order = index
                        related_obj.save()

            except IntegrityError:
                return HttpResponse(
                    status=400,
                    content="Failed to update column order due to a unique constraint violation.",
                )
            except Exception as e:
                return HttpResponse(status=500, content=f"Error: {str(e)}")

            # Reconstruct query parameters
            query_params = QueryDict(mutable=True)
            for key, values in request.POST.lists():
                if key not in [
                    "column_order",
                    "app_label",
                    "model_name",
                    "class_name",
                    "csrfmiddlewaretoken",
                ]:
                    for value in values:
                        query_params.appendlist(key, value)

            view.request.GET = query_params
            view.object_list = view.get_queryset()

            context = view.get_context_data()
            context["app_label"] = app_label
            context["apps_label"] = app_label.split(".")[-1] if app_label else ""
            context["model_name"] = model_name
            context["class_name"] = class_name

            # Render response
            rendered_content = render_to_string(
                "partials/kanban_blocks.html", context, request=request
            )
            if not rendered_content.strip():
                return HttpResponse(
                    status=500, content="Error: Empty template response"
                )

            response = HttpResponse(rendered_content)
            new_query_string = query_params.urlencode()
            url = main_url + (f"?{new_query_string}" if new_query_string else "")
            response["HX-Push-Url"] = url
            return response

        except Exception as e:
            return HttpResponse(status=500, content=f"Error: {str(e)}")

    def _get_kanban_exclude_include_fields(self, view_type="kanban"):
        """Return (exclude_fields, include_fields) used by Kanban/GroupBy settings for this view."""
        exclude_str = getattr(self, "exclude_kanban_fields", "") or ""
        exclude_fields = [f.strip() for f in exclude_str.split(",") if f.strip()]
        include_fields = getattr(self, "include_kanban_fields", None)
        return exclude_fields, include_fields

    def _get_allowed_group_by_fields(self, view_type="kanban"):
        """Return list of field names the user is allowed to group by (respects field permissions
        and exclude_kanban_fields/include_kanban_fields so we only consider fields shown in settings).
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

    def get_group_by_field(self):
        """Return the field used to group Kanban columns for this view's model.
        Falls back to an allowed field when the preferred field has 'hidden' permission.
        Never returns a field with 'hidden' permission.
        """
        if hasattr(self, "_group_by_field_cache"):
            return self._group_by_field_cache

        model_name = self.model.__name__
        app_label = self.model._meta.app_label
        default_group = KanbanGroupBy.all_objects.filter(
            model_name=model_name,
            app_label=app_label,
            user=self.request.user,
            view_type="kanban",
        ).first()
        preferred = default_group.field_name if default_group else self.group_by_field
        allowed = self._get_allowed_group_by_fields(view_type="kanban")
        result = None
        if (
            preferred
            and preferred in allowed
            and self._is_field_visible_for_group_by(preferred)
        ):
            result = preferred
        else:
            for field_name in allowed:
                if self._is_field_visible_for_group_by(field_name):
                    result = field_name
                    break
        self._group_by_field_cache = result
        return result

    def _page_for_column(self, ordered_items, total_count, page_key):
        """
        Paginate a column queryset using a precomputed total_count.

        Django's Paginator would otherwise issue a COUNT(*) per column even when
        we already know the totals from a bulk GROUP BY.
        """
        paginator = Paginator(ordered_items, self.paginate_by)
        paginator.count = total_count
        page = self.request.GET.get(f"page_{page_key}", 1)
        try:
            return paginator.page(page)
        except PageNotAnInteger:
            return paginator.page(1)
        except EmptyPage:
            return paginator.page(paginator.num_pages)

    def get_context_data(self, **kwargs):
        """Populate Kanban view context including grouping, columns and items."""
        context = super().get_context_data(**kwargs)
        if not hasattr(self, "object_list"):
            self.object_list = self.get_queryset()

        queryset = self.object_list
        group_by = self.get_group_by_field()

        app_label = self.model._meta.app_label if self.model else ""
        model_name = self.model.__name__ if self.model else ""
        context["app_label"] = app_label
        context["apps_label"] = app_label
        context["model_name"] = model_name
        context["kanban_attrs"] = self.kanban_attrs
        context["class_name"] = self.__class__.__name__
        context["height_kanban"] = self.height_kanban
        if not group_by:
            context["error"] = _(
                "No grouping field specified or you don't have permission to view any grouping fields."
            )
            return context

        try:
            field = self.get_group_field(group_by)
            if not (
                (hasattr(field, "choices") and field.choices)
                or isinstance(field, ForeignKey)
            ):
                context["error"] = _(
                    "Field '%(field)s' is not a Choice field or ForeignKey field."
                ) % {"field": group_by}
                return context

            allow_column_reorder = False
            has_colour_field = False
            if isinstance(field, ForeignKey):
                related_model = field.related_model
                related_fields = [f.name for f in related_model._meta.fields]
                allow_column_reorder = "order" in related_fields
                has_colour_field = "color" in related_fields

            context["group_by_field"] = group_by
            context["group_by_label"] = field.verbose_name
            context["allow_column_reorder"] = allow_column_reorder

            grouped_items = {}
            paginated_groups = {}

            if hasattr(field, "choices") and field.choices:
                num_columns = len(field.choices)
                for value, label in field.choices:
                    grouped_items[value] = {
                        "label": label,
                        "items": queryset.filter(**{group_by: value}),
                    }
                existing_values = set(queryset.values_list(group_by, flat=True))
                for value in existing_values:
                    if value not in grouped_items:
                        grouped_items[value] = {
                            "label": f"Unknown ({value})",
                            "items": queryset.filter(**{group_by: value}),
                        }

                sorted_items = {}
                for value, __ in field.choices:
                    if value in grouped_items:
                        sorted_items[value] = grouped_items[value]
                for key, group in grouped_items.items():
                    if key not in sorted_items:
                        sorted_items[key] = group

                order_by = self.get_kanban_order_by()
                order_by_tuple = (
                    order_by if isinstance(order_by, (list, tuple)) else (order_by,)
                )
                for key, group in sorted_items.items():
                    total_count = group["items"].count()
                    ordered_items = group["items"].order_by(*order_by_tuple)
                    page_obj = self._page_for_column(
                        ordered_items, total_count, page_key=key
                    )
                    paginated_groups[key] = {
                        "label": group["label"],
                        "items": page_obj.object_list,
                        "page_obj": page_obj,
                        "has_next": page_obj.has_next(),
                        "next_page": (
                            page_obj.next_page_number() if page_obj.has_next() else None
                        ),
                        "total_count": total_count,
                    }

            elif isinstance(field, ForeignKey):
                related_model = field.related_model
                related_items = list(
                    related_model.objects.all().order_by(
                        *group_order_by(self.request, related_model)
                    )
                )

                # Fetch all counts in one query. Use a subquery-based count to avoid
                # the DISTINCT from get_queryset() collapsing GROUP BY counts to 1.
                from django.db.models import Count as _Count

                fk_field = f"{group_by}_id"
                count_qs = (
                    queryset.order_by()
                    .values(fk_field)
                    .annotate(_c=_Count("pk", distinct=True))
                )
                counts_map = dict(count_qs.values_list(fk_field, "_c"))
                null_count = (
                    queryset.filter(**{f"{group_by}__isnull": True}).count()
                    if field.null
                    else 0
                )

                _default_hex_use_primary = "#f39022"
                for related_item in related_items:
                    raw_color = (
                        getattr(related_item, "color", None)
                        if has_colour_field
                        else None
                    )
                    if raw_color in (None, "", _default_hex_use_primary):
                        raw_color = "primary-600"
                    grouped_items[related_item.pk] = {
                        "label": group_label_with_company(self.request, related_item),
                        "items": queryset.filter(
                            **{f"{group_by}__pk": related_item.pk}
                        ),
                        "color": raw_color,
                        "_total_count": counts_map.get(related_item.pk, 0),
                        # Already-loaded column model; subclasses can read attrs
                        # without re-querying.
                        "related_obj": related_item,
                    }

                if field.null:
                    grouped_items[None] = {
                        "label": "None",
                        "items": queryset.filter(**{f"{group_by}__isnull": True}),
                        "color": None,
                        "_total_count": null_count,
                        "related_obj": None,
                    }
                    num_columns = len(related_items) + 1
                else:
                    num_columns = len(related_items)

                if None in grouped_items and grouped_items[None]["_total_count"] == 0:
                    del grouped_items[None]
                    if field.null:
                        num_columns -= 1

                sorted_items = {}
                for related_item in related_items:
                    if related_item.pk in grouped_items:
                        sorted_items[related_item.pk] = grouped_items[related_item.pk]
                if None in grouped_items:
                    sorted_items[None] = grouped_items[None]

                order_by = self.get_kanban_order_by()
                order_by_tuple = (
                    order_by if isinstance(order_by, (list, tuple)) else (order_by,)
                )
                for key, group in sorted_items.items():
                    total_count = group["_total_count"]
                    ordered_items = group["items"].order_by(*order_by_tuple)
                    page_obj = self._page_for_column(
                        ordered_items, total_count, page_key=key
                    )
                    paginated_groups[key] = {
                        "label": group["label"],
                        "items": page_obj.object_list,
                        "page_obj": page_obj,
                        "has_next": page_obj.has_next(),
                        "next_page": (
                            page_obj.next_page_number() if page_obj.has_next() else None
                        ),
                        "total_count": total_count,
                        "colour": group["color"],
                        "related_obj": group.get("related_obj"),
                    }

            # Get filtered columns (already filtered by field permissions in _get_columns)
            filtered_columns = self._get_columns()
            display_columns = []
            for verbose_name, field_name in filtered_columns:
                if field_name != group_by:
                    display_columns.append({"name": field_name, "label": verbose_name})
            for key, group in paginated_groups.items():
                group["count"] = len(group["items"])
                for item in group["items"]:
                    item.can_drag = self.can_user_modify_item(item)
                    item.display_columns = []
                    for column in display_columns:
                        field_name = column["name"]
                        value = None
                        # Check if field_name is a display method (get_*_display)
                        if field_name.startswith("get_") and field_name.endswith(
                            "_display"
                        ):
                            # It's already a display method, call it directly
                            if hasattr(item, field_name):
                                display_method = getattr(item, field_name)
                                if callable(display_method):
                                    value = display_method()
                        else:
                            # Check if it's a choice field and use display method
                            try:
                                from django.db.models import (
                                    ManyToManyField,
                                    ManyToManyRel,
                                    ManyToOneRel,
                                )

                                field = self.model._meta.get_field(field_name)
                                if isinstance(
                                    field,
                                    (ManyToManyField, ManyToManyRel, ManyToOneRel),
                                ):
                                    # M2M / reverse-relation: join all related objects as strings
                                    m2m_qs = getattr(item, field_name, None)
                                    if m2m_qs is not None:
                                        try:
                                            value = ", ".join(
                                                str(obj) for obj in m2m_qs.all()
                                            )
                                        except Exception:
                                            value = None
                                elif hasattr(field, "choices") and field.choices:
                                    # Use the display method for choice fields
                                    display_method_name = f"get_{field_name}_display"
                                    if hasattr(item, display_method_name):
                                        display_method = getattr(
                                            item, display_method_name
                                        )
                                        if callable(display_method):
                                            value = display_method()
                                    else:
                                        # Fallback to raw value if display method doesn't exist
                                        value = getattr(item, field_name, None)
                                else:
                                    # Not a choice field, get value normally
                                    if hasattr(item, field_name):
                                        value = getattr(item, field_name)
                                        if callable(value):
                                            value = value()
                            except (FieldDoesNotExist, AttributeError):
                                # Field doesn't exist or can't be accessed, try direct attribute
                                if hasattr(item, field_name):
                                    value = getattr(item, field_name)
                                    if callable(value):
                                        value = value()

                        item.display_columns.append(
                            {
                                "name": field_name,
                                "label": column["label"],
                                "value": str(value) if value is not None else "–",
                            }
                        )

            context.update(
                {
                    "grouped_items": paginated_groups,
                    "display_columns": display_columns,
                    "num_columns": num_columns,
                    "model_name": model_name,
                    "app_label": app_label,
                    "apps_label": app_label.split(".")[-1] if app_label else "",
                    "columns": filtered_columns,
                    "actions": self.actions,
                    "filter_class": (
                        self.get_filterset_class().__name__
                        if self.get_filterset_class()
                        else ""
                    ),
                    "group_by_field": group_by,
                    "kanban_attrs": self.kanban_attrs,
                }
            )
        except FieldError as e:
            context["error"] = f"Invalid grouping field '{group_by}': {str(e)}"
        except Exception as e:
            context["error"] = f"Error grouping by field '{group_by}': {str(e)}"
        return context

    def load_more_items(self, request, *args, **kwargs):
        """
        Load more items for a specific Kanban column with filters and search applied.
        """
        column_key = request.GET.get("column_key")
        page = request.GET.get("page")
        group_by = self.get_group_by_field()

        if not page or not group_by:
            return HttpResponse(status=400, content="Missing required parameters")

        try:
            field = self.get_group_field(group_by)
            if column_key == "None":
                column_key = None
            elif isinstance(field, ForeignKey) and column_key and column_key.isdigit():
                column_key = int(column_key)

            # CRITICAL FIX: Use get_queryset() which applies ALL filters from HorillaListView
            # This ensures search and filterset are properly applied
            queryset = self.get_queryset()

            # Filter by the specific column after applying all other filters
            order_by = self.get_kanban_order_by()
            order_by_tuple = (
                order_by if isinstance(order_by, (list, tuple)) else (order_by,)
            )
            if hasattr(field, "choices") and field.choices:
                items = queryset.filter(**{group_by: column_key}).order_by(
                    *order_by_tuple
                )
            elif isinstance(field, ForeignKey):
                if column_key is None:
                    items = queryset.filter(**{f"{group_by}__isnull": True}).order_by(
                        *order_by_tuple
                    )
                else:
                    items = queryset.filter(**{f"{group_by}__pk": column_key}).order_by(
                        *order_by_tuple
                    )

            paginate_by = getattr(self, "paginate_by", 10)
            paginator = Paginator(items, paginate_by)
            try:
                page_obj = paginator.page(page)
            except PageNotAnInteger:
                page_obj = paginator.page(1)
            except EmptyPage:
                return HttpResponse("")  # Return empty response for no more items

            # Get filtered columns (already filtered by field permissions in _get_columns)
            filtered_columns = self._get_columns()
            display_columns = []
            for verbose_name, field_name in filtered_columns:
                if field_name != group_by:
                    display_columns.append({"name": field_name, "label": verbose_name})

            for item in page_obj.object_list:
                item.can_drag = self.can_user_modify_item(item)
                item.display_columns = []
                for column in display_columns:
                    field_name = column["name"]
                    value = None
                    try:
                        # Check if field_name is a display method (get_*_display)
                        if field_name.startswith("get_") and field_name.endswith(
                            "_display"
                        ):
                            # It's already a display method, call it directly
                            if hasattr(item, field_name):
                                display_method = getattr(item, field_name)
                                if callable(display_method):
                                    value = display_method()
                        else:
                            # Check if it's a choice field and use display method
                            try:
                                from django.db.models import (
                                    ManyToManyField,
                                    ManyToManyRel,
                                    ManyToOneRel,
                                )

                                field = self.model._meta.get_field(field_name)
                                if isinstance(
                                    field,
                                    (ManyToManyField, ManyToManyRel, ManyToOneRel),
                                ):
                                    # M2M / reverse-relation: join all related objects as strings
                                    m2m_qs = getattr(item, field_name, None)
                                    if m2m_qs is not None:
                                        try:
                                            value = ", ".join(
                                                str(obj) for obj in m2m_qs.all()
                                            )
                                        except Exception:
                                            value = None
                                elif hasattr(field, "choices") and field.choices:
                                    # Use the display method for choice fields
                                    display_method_name = f"get_{field_name}_display"
                                    if hasattr(item, display_method_name):
                                        display_method = getattr(
                                            item, display_method_name
                                        )
                                        if callable(display_method):
                                            value = display_method()
                                    else:
                                        # Fallback to raw value if display method doesn't exist
                                        value = getattr(item, field_name, None)
                                else:
                                    # Not a choice field, get value normally
                                    if hasattr(item, field_name):
                                        value = getattr(item, field_name)
                                        if callable(value):
                                            value = value()
                            except (FieldDoesNotExist, AttributeError):
                                # Field doesn't exist or can't be accessed, try direct attribute
                                if hasattr(item, field_name):
                                    value = getattr(item, field_name)
                                    if callable(value):
                                        value = value()
                    except AttributeError:
                        value = None
                    item.display_columns.append(
                        {
                            "name": field_name,
                            "label": column["label"],
                            "value": str(value) if value is not None else "–",
                        }
                    )

            context = {
                "group": {
                    "items": page_obj.object_list,
                    "has_next": page_obj.has_next(),
                    "next_page": (
                        page_obj.next_page_number() if page_obj.has_next() else None
                    ),
                    "label": str(column_key) if column_key else "None",
                },
                "actions": getattr(self, "actions", []),
                "column_key": column_key,
                "class_name": self.__class__.__name__,
                "app_label": (self.model._meta.app_label if self.model else ""),
                "apps_label": self.model._meta.app_label if self.model else "",
                "model_name": self.model.__name__ if self.model else "",
                "key": column_key,
                "kanban_attrs": self.kanban_attrs,
            }

            return HttpResponse(
                render_to_string("partials/kanban_items.html", context, request=request)
            )
        except Exception as e:
            logger.error("Load more items failed: %s", str(e))
            return HttpResponse(status=500, content=f"Error: {str(e)}")
