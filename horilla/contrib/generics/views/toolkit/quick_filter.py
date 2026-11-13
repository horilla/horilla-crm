"""
Standalone quick filter helpers for list views.
Use these functions from any view; no mixin inheritance required.
"""

# Standard library imports
import logging

from django.contrib import messages

# Third-party imports (Django)
from django.template.loader import render_to_string

from horilla.contrib.core.models import QuickFilter

# First party imports (Horilla)
from horilla.shortcuts import render
from horilla.utils.translation import gettext_lazy as _
from horilla.web import HttpResponse

logger = logging.getLogger(__name__)


def _quick_filters_enabled(view):
    """Quick filters are a plain-list-view feature - `supports_quick_filters`
    (False on Kanban/GroupBy/Card/Split/Chart/Timeline) overrides whatever
    `enable_quick_filters` a concrete view class sets.
    """
    return getattr(view, "enable_quick_filters", False) and getattr(
        view, "supports_quick_filters", True
    )


def get_available_quick_filter_fields(view):
    """Auto-detect fields suitable for quick filtering (ForeignKey, Choice, Boolean)."""
    if not _quick_filters_enabled(view):
        return []

    exclude = list(getattr(view, "exclude_quick_filter_fields", []) or [])
    if not view.request.session.get("show_all_companies", False):
        exclude.append("company")
    available_fields = []

    for field in view.model._meta.fields:
        if (
            field.name in exclude
            or field.auto_created
            or field.name == "id"
            or getattr(field, "editable", True) is False
        ):
            continue

        field_class_name = field.__class__.__name__
        field_info = None

        if field_class_name == "ForeignKey":
            field_info = {
                "name": field.name,
                "verbose_name": str(field.verbose_name),
                "type": "foreignkey",
            }
        elif field.choices:
            field_info = {
                "name": field.name,
                "verbose_name": str(field.verbose_name),
                "type": "choice",
            }
        elif field_class_name in ["BooleanField", "NullBooleanField"]:
            field_info = {
                "name": field.name,
                "verbose_name": str(field.verbose_name),
                "type": "boolean",
            }

        if field_info:
            available_fields.append(field_info)

    available_fields.extend(view.get_extra_quick_filter_fields())
    return available_fields


def get_quick_filters(view):
    """Get active quick filters for current user and model."""
    if not _quick_filters_enabled(view):
        return []

    quick_filters = QuickFilter.objects.filter(
        user=view.request.user,
        app_label=view.model._meta.app_label,
        model_name=view.model.__name__,
    )
    if not view.request.session.get("show_all_companies", False):
        quick_filters = quick_filters.exclude(field_name="company")
    return quick_filters


def get_quick_filter_choices(view, field_name):
    """Get choices for a quick filter field."""
    extra_choices = view.get_extra_quick_filter_choices(field_name)
    if extra_choices is not None:
        return extra_choices
    try:
        field = view.model._meta.get_field(field_name)
        if getattr(field, "editable", True) is False:
            return []

        field_class_name = field.__class__.__name__

        if field_class_name in ["BooleanField", "NullBooleanField"]:
            return [
                {"value": "true", "label": _("Yes")},
                {"value": "false", "label": _("No")},
            ]

        if field.choices:
            return [{"value": val, "label": label} for val, label in field.choices]

        if field_class_name == "ForeignKey":
            related_model = field.related_model
            queryset = related_model.objects.all()

            filterset_class = (
                view.get_filterset_class()
                if hasattr(view, "get_filterset_class")
                else getattr(view, "filterset_class", None)
            )
            if filterset_class and field_name:
                try:
                    temp_filterset = filterset_class(request=view.request, data={})
                    if field_name in temp_filterset.filters:
                        filter_obj = temp_filterset.filters[field_name]
                        if hasattr(filter_obj, "field") and hasattr(
                            filter_obj.field, "queryset"
                        ):
                            queryset = filter_obj.field.queryset
                        elif hasattr(filter_obj, "queryset"):
                            queryset = filter_obj.queryset
                except Exception:
                    pass

            queryset = queryset[:200]
            return [{"value": str(obj.pk), "label": str(obj)} for obj in queryset]

        return []

    except Exception as e:
        logger.error(
            "Error getting quick filter choices for %s:%s",
            field_name,
            str(e),
        )
        return []


def is_valid_quick_filter_value(view, field_name, filter_value):
    """Return True if filter_value is a valid choice for this quick filter field."""
    if not filter_value:
        return False
    choices = get_quick_filter_choices(view, field_name)
    if not choices:
        return False
    valid_values = [str(c["value"]) for c in choices]
    return str(filter_value).strip() in valid_values


def apply_quick_filters(queryset, view):
    """Apply active quick filters to queryset. Invalid choice values are ignored (show All)."""
    if not _quick_filters_enabled(view):
        return queryset

    for qf in get_quick_filters(view):
        filter_value = view.request.GET.get(f"qf_{qf.field_name}")
        if not filter_value or not is_valid_quick_filter_value(
            view, qf.field_name, filter_value
        ):
            continue
        extra_queryset = view.apply_extra_quick_filter(
            queryset, qf.field_name, filter_value
        )
        if extra_queryset is not None:
            queryset = extra_queryset
            continue
        try:
            field = view.model._meta.get_field(qf.field_name)
            field_class_name = field.__class__.__name__

            if field_class_name in ["BooleanField", "NullBooleanField"]:
                bool_value = filter_value.lower() == "true"
                queryset = queryset.filter(**{qf.field_name: bool_value})
            elif field_class_name == "ForeignKey":
                queryset = queryset.filter(**{f"{qf.field_name}_id": filter_value})
            else:
                queryset = queryset.filter(**{qf.field_name: filter_value})
        except Exception as e:
            logger.error("Error applying quick filter %s: %s", qf.field_name, str(e))

    return queryset


def handle_quick_filter_post(request, action, view):
    """
    Handle POST actions related to quick filters (add/remove).
    Returns an HttpResponse when handled, or None to continue normal processing.
    """
    if action == "add_quick_filter":
        field_names = request.POST.getlist("field_name")
        available_names = {f["name"] for f in get_available_quick_filter_fields(view)}
        valid_field_names = [fn for fn in field_names if fn in available_names]

        if not valid_field_names:
            existing_names = set(
                get_quick_filters(view).values_list("field_name", flat=True)
            )
            available_fields_list = [
                f
                for f in get_available_quick_filter_fields(view)
                if f["name"] not in existing_names
            ]
            context = {
                "available_fields": available_fields_list,
                "search_url": getattr(view, "search_url", None) or request.path,
                "view_id": getattr(view, "view_id", ""),
                "error_message": "Please select at least one valid field.",
            }
            response = render(request, "partials/add_quick_filter_form.html", context)
            response["HX-Reswap"] = "innerHTML"
            response["HX-Retarget"] = "#modalBox"
            response["HX-Reselect"] = "#add-quick-filter-container"
            return response

        base_count = QuickFilter.objects.filter(
            user=request.user,
            app_label=view.model._meta.app_label,
            model_name=view.model.__name__,
        ).count()

        existing = set(
            QuickFilter.objects.filter(
                user=request.user,
                app_label=view.model._meta.app_label,
                model_name=view.model.__name__,
                field_name__in=valid_field_names,
            ).values_list("field_name", flat=True)
        )

        new_filters = [
            QuickFilter(
                user=request.user,
                app_label=view.model._meta.app_label,
                model_name=view.model.__name__,
                field_name=field_name,
                display_order=base_count + idx,
            )
            for idx, field_name in enumerate(valid_field_names)
            if field_name not in existing
        ]

        if new_filters:
            QuickFilter.objects.bulk_create(new_filters)

        view.object_list = view.get_queryset()
        context = view.get_context_data(object_list=view.object_list)
        list_view_html = render_to_string(view.template_name, context, request=request)
        view_id = getattr(view, "view_id", "")
        response = HttpResponse(list_view_html)
        response["HX-Retarget"] = f"#{view_id}"
        response["HX-Reswap"] = "outerHTML"
        response["HX-Reselect"] = f"#{view_id}"
        return response

    if action == "remove_quick_filter":
        filter_id = request.POST.get("filter_id")
        if not filter_id:
            return HttpResponse(status=400)

        try:
            quick_filter = QuickFilter.objects.only("field_name").get(
                id=filter_id, user=request.user
            )
            field_name = quick_filter.field_name
            quick_filter.delete()
        except Exception as e:
            messages.error(request, str(e))
            response = HttpResponse(
                "<div id='reload'><script>$('#reloadButton').click();</script></div>"
            )
            response["HX-Retarget"] = f"#tableview-{getattr(view, 'view_id', '')}"
            response["HX-Reswap"] = "innerHTML"
            response["HX-Reselect"] = "#reload"
            return response

        clean_params = request.GET.copy()
        clean_params.pop(f"qf_{field_name}", None)
        original_get = request.GET
        request.GET = clean_params

        try:
            view.object_list = view.get_queryset()
            context = view.get_context_data(object_list=view.object_list)
            list_view_html = render_to_string(
                view.template_name, context, request=request
            )
        finally:
            request.GET = original_get

        view_id = getattr(view, "view_id", "")
        response = HttpResponse(list_view_html)
        response["HX-Retarget"] = f"#{view_id}"
        response["HX-Reswap"] = "outerHTML"
        response["HX-Reselect"] = f"#{view_id}"

        if getattr(view, "filter_url_push", True):
            clean_url = (
                f"{getattr(view, 'main_url', None) or request.path}?{clean_params.urlencode()}"
                if clean_params
                else (getattr(view, "main_url", None) or request.path)
            )
            response["HX-Push-Url"] = clean_url
            response["HX-Replace-Url"] = clean_url
        else:
            response["HX-Push-Url"] = "false"

        return response

    return None


def handle_quick_filter_get(request, view):
    """
    Handle HTMX GET requests related to quick filters (show add quick filter form).
    Returns an HttpResponse when handled, or None to continue normal processing.
    """
    if request.GET.get("show_add_quick_filter") == "true":
        available_fields = get_available_quick_filter_fields(view)
        existing_filters = get_quick_filters(view)
        existing_field_names = [qf.field_name for qf in existing_filters]
        available_fields = [
            f for f in available_fields if f["name"] not in existing_field_names
        ]
        search_params = request.GET.copy()
        search_params.pop("show_add_quick_filter", None)
        search_params.pop("page", None)
        context = {
            "available_fields": available_fields,
            "search_url": getattr(view, "search_url", None) or request.path,
            "view_id": getattr(view, "view_id", ""),
            "search_params": search_params.urlencode(),
        }
        return render(request, "partials/add_quick_filter_form.html", context)
    return None


def update_quick_filter_context(context, view):
    """Inject quick filter data into the template context."""
    if not _quick_filters_enabled(view):
        context["enable_quick_filters"] = False
        context["quick_filters"] = []
        context["available_quick_filter_fields"] = []
        context["quick_filters_height_adjustment"] = 0
        return

    quick_filters = []
    for qf in get_quick_filters(view):
        choices = get_quick_filter_choices(view, qf.field_name)
        field_info = next(
            (
                f
                for f in get_available_quick_filter_fields(view)
                if f["name"] == qf.field_name
            ),
            {
                "verbose_name": qf.field_name.replace("_", " ").title(),
                "type": "text",
            },
        )
        quick_filters.append(
            {
                "id": qf.id,
                "field_name": qf.field_name,
                "verbose_name": field_info.get("verbose_name", qf.field_name),
                "type": field_info.get("type", "text"),
                "choices": choices,
                "selected_value": view.request.GET.get(f"qf_{qf.field_name}", ""),
            }
        )

    active_field_names = [qf["field_name"] for qf in quick_filters]
    available_fields = [
        f
        for f in get_available_quick_filter_fields(view)
        if f["name"] not in active_field_names
    ]

    context["quick_filters"] = quick_filters
    context["enable_quick_filters"] = True
    context["available_quick_filter_fields"] = available_fields

    num_filters = len(quick_filters)
    if num_filters > 0:
        if num_filters <= 4:
            context["quick_filters_height_adjustment"] = 265
        else:
            rows_lg = (num_filters + 3) // 4
            base_height = 265
            height_per_row = 50
            additional_rows = rows_lg - 1
            total_height_reduction = base_height + (additional_rows * height_per_row)
            context["quick_filters_height_adjustment"] = total_height_reduction
    else:
        context["quick_filters_height_adjustment"] = 225
