"""
Views for displaying related lists in Horilla's detail views, including dynamic discovery of related models and rendering using HorillaListView. This includes handling for both standard related fields.
"""

# Standard library imports
import functools
import logging
import re

from django.contrib import messages
from django.contrib.contenttypes.fields import GenericRelation

# Third-party imports (Django)
from django.template.loader import render_to_string

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin, login_redirect
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.utils.methods import get_section_info_for_model
from horilla.shortcuts import render
from horilla.urls import reverse
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.views.generic import DetailView
from horilla.web import HttpNotFound, HttpResponse

from .details import (
    check_record_access,
    check_record_change_access,
    check_record_delete_access,
)

# Local imports
from .list import HorillaListView

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
class HorillaRelatedListSectionView(DetailView):
    """View for displaying related objects in a list section within detail views."""

    template_name = "related_list.html"
    context_object_name = "object"

    related_list_config = {}
    max_items_per_list = None
    excluded_related_lists = []

    _view_registry = {}

    def __init_subclass__(cls, **kwargs):
        """
        Automatically register child classes with their models.
        This allows the parent to find the correct child class dynamically.
        """
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "model") and cls.model:
            HorillaRelatedListSectionView._view_registry[cls.model] = cls

    def dispatch(self, request, *args, **kwargs):
        """Verify the user can access the parent record before loading related lists."""
        if not request.user.is_authenticated:
            return login_redirect(request)
        try:
            # Fetch once; get_object() reuses self.object for the rest of the request.
            self.object = self.get_object()
        except Exception:
            return HttpResponse("Record not found", status=404)
        if not check_record_access(request.user, self.object):
            return render(request, "403.html", status=403)
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        """Return the parent record, reusing ``self.object`` when already loaded."""
        if getattr(self, "object", None) is not None:
            return self.object
        self.object = super().get_object(queryset=queryset)
        return self.object

    def _can_add_to_related(self):
        """True if the user can change the parent (gates related-list add UI)."""
        obj = getattr(self, "object", None)
        if obj is None:
            try:
                obj = self.get_object()
            except Exception:
                return False
        return check_record_change_access(self.request.user, obj)

    def get_related_lists_metadata(self):
        """
        Get metadata for related lists (for tab navigation), including custom related lists.
        """
        obj = self.get_object()
        related_lists = []

        related_config = getattr(self, "related_list_config", {})
        if isinstance(related_config, functools.cached_property):
            try:
                related_config = related_config.func(self)
            except Exception:
                related_config = {}
        related_config = related_config if isinstance(related_config, dict) else {}
        # Standard related fields
        for field in obj._meta.get_fields():
            if not self.is_valid_related_field(field):
                continue

            related_model = field.related_model
            config = related_config.get(field.name, {})
            default_title = related_model._meta.verbose_name_plural

            related_lists.append(
                {
                    "name": field.name,
                    "title": config.get("title", default_title),
                    "model_name": related_model.__name__,
                    "app_label": related_model._meta.app_label,
                    "parent_model_name": obj._meta.model_name,
                    "is_custom": False,
                    "config": config,
                }
            )

        for custom_name, custom_config in related_config.get(
            "custom_related_lists", {}
        ).items():
            try:
                related_model = apps.get_model(
                    custom_config["app_label"], custom_config["model_name"]
                )
                default_title = related_model._meta.verbose_name_plural

                related_lists.append(
                    {
                        "name": custom_name,
                        "title": custom_config.get("config").get(
                            "title", default_title
                        ),
                        "model_name": related_model.__name__,
                        "app_label": related_model._meta.app_label,
                        "parent_model_name": obj._meta.model_name,
                        "is_custom": True,
                        "custom_config": custom_config,
                    }
                )
            except LookupError:
                continue
        return related_lists

    def get_single_related_list(self, obj, field_name):
        """
        Get data for a single related list, handling both standard and custom related lists
        """
        related_config = getattr(self, "related_list_config", {})
        if isinstance(related_config, functools.cached_property):
            try:
                related_config = related_config.func(self)
            except Exception:
                related_config = {}
        elif not isinstance(related_config, dict):
            related_config = {}
        custom_related_lists = related_config.get("custom_related_lists", {})

        if field_name in custom_related_lists:
            return self.build_custom_related_list_data(
                obj, field_name, custom_related_lists[field_name]
            )

        for field in obj._meta.get_fields():
            if field.name == field_name and self.is_valid_related_field(field):
                return self.build_related_list_data(obj, field)
        return None

    def get_related_lists(self):
        """
        Dynamically discover all related models, including custom ones
        """
        obj = self.get_object()
        related_lists = []

        for field in obj._meta.get_fields():
            if self.is_valid_related_field(field):
                related_list_data = self.build_related_list_data(obj, field)
                if related_list_data:
                    related_lists.append(related_list_data)

        related_config = getattr(self, "related_list_config", {})

        if isinstance(related_config, functools.cached_property):
            try:
                related_config = related_config.func(self)
            except Exception:
                related_config = {}

        if not isinstance(related_config, dict):
            related_config = {}

        custom_related_lists = related_config.get("custom_related_lists", {})
        for custom_name, custom_config in custom_related_lists.items():
            related_list_data = self.build_custom_related_list_data(
                obj, custom_name, custom_config
            )
            if related_list_data:
                related_lists.append(related_list_data)

        return related_lists

    def is_valid_related_field(self, field):
        """
        Check if field should be included in related lists, respecting exclusions
        """
        excluded_fields = [
            "history",
            "logentry",
            "log_entries",
            "audit_log",
            "auditlog",
            "activity_log",
            "change_log",
            "revisions",
        ] + self.excluded_related_lists

        return (
            (
                field.one_to_many
                or field.many_to_many
                or isinstance(field, GenericRelation)
            )
            and not field.name.startswith("_")
            and field.name.lower() not in excluded_fields
        )

    def build_related_list_data(self, obj, field):
        """
        Build data structure for a standard related list using HorillaListView
        """
        try:
            related_manager = getattr(obj, field.name)
            if hasattr(related_manager, "all"):
                queryset = related_manager.all()
            else:
                return None
            total_count = queryset.count()
            related_model = field.related_model
            model_name = related_model.__name__
            config = self.related_list_config.get(field.name, {})
            dropdown_actions = config.get("dropdown_actions", [])
            custom_buttons = config.get("custom_buttons", [])
            default_title = related_model._meta.verbose_name_plural

            list_view = self.create_generic_list_view_instance(
                model=related_model,
                queryset=queryset[: self.max_items_per_list],
                config=config,
                view_id=field.name,
                parent_obj=obj,
            )

            rendered_html = self.render_generic_list_view(list_view)

            return {
                "name": field.name,
                "title": config.get("title", default_title),
                "model": related_model,
                "model_name": model_name,
                "app_label": related_model._meta.app_label,
                "total_count": total_count,
                "can_add": config.get("can_add", True),
                "add_url": config.get("add_url", ""),
                "button_name": config.get("button_name"),
                "description": config.get("description", ""),
                "field_obj": field,
                "rendered_content": rendered_html,
                "dropdown_actions": dropdown_actions,
                "custom_buttons": custom_buttons,
                "is_custom": False,
            }
        except Exception:
            return None

    def build_custom_related_list_data(self, obj, custom_name, custom_config):
        """
        Build data structure for a custom related list with proper company filtering.
        This method ensures CompanyFilteredManager is invoked by querying the related model directly.
        """
        try:
            related_model = apps.get_model(
                custom_config["app_label"], custom_config["model_name"]
            )
            default_title = related_model._meta.verbose_name_plural
            config = custom_config.get("config", {})
            dropdown_actions = config.get("dropdown_actions", [])

            queryset = None

            # Handle custom queryset function
            if "queryset" in custom_config:
                queryset = custom_config["queryset"](obj)

            # Handle intermediate model pattern
            elif "related_field" in custom_config:
                related_field = custom_config["related_field"]
                intermediate_field = custom_config["intermediate_field"]
                intermediate_model_name = custom_config.get("intermediate_model")

                if intermediate_model_name:
                    # Find the intermediate model across different app labels
                    intermediate_model = self._find_intermediate_model(
                        intermediate_model_name,
                        obj._meta.app_label,
                        custom_config["app_label"],
                    )

                    if intermediate_model:
                        # Step 1: Filter intermediate model by the parent object
                        intermediate_qs = intermediate_model.objects.filter(
                            **{related_field: obj}
                        )

                        # Step 2: Find the field in intermediate model that points to the related model
                        related_obj_field = self._get_related_field_from_intermediate(
                            intermediate_model,
                            related_model,
                            exclude_field=related_field,
                        )

                        if related_obj_field:
                            related_ids = list(
                                intermediate_qs.values_list(
                                    f"{related_obj_field}_id", flat=True
                                ).distinct()
                            )
                            queryset = related_model.objects.filter(pk__in=related_ids)

                            columns = config.get("columns", [])
                            annotations = self._build_intermediate_annotations(
                                intermediate_model,
                                intermediate_field,
                                related_field,
                                related_obj_field,
                                obj,
                                columns,
                            )

                            if annotations:
                                queryset = queryset.annotate(**annotations)
                        else:
                            # Fallback: couldn't find the field
                            queryset = related_model.objects.filter(
                                **{f"{intermediate_field}__{related_field}": obj}
                            )
                    else:
                        # Fallback: couldn't find intermediate model
                        queryset = related_model.objects.filter(
                            **{f"{intermediate_field}__{related_field}": obj}
                        )
                else:
                    # No intermediate_model specified, use direct relationship
                    queryset = related_model.objects.filter(
                        **{f"{intermediate_field}__{related_field}": obj}
                    )

            if queryset is None:
                return None

            total_count = queryset.count()

            list_view = self.create_generic_list_view_instance(
                model=related_model,
                queryset=queryset,
                config=config,
                view_id=custom_name,
                parent_obj=obj,
            )
            rendered_html = self.render_generic_list_view(list_view)

            return {
                "name": custom_name,
                "title": config.get("title", default_title),
                "model": related_model,
                "model_name": related_model.__name__,
                "app_label": related_model._meta.app_label,
                "total_count": total_count,
                "can_add": config.get("can_add", True),
                "add_url": config.get("add_url", ""),
                "button_name": config.get("button_name"),
                "description": config.get("description", ""),
                "field_obj": None,
                "rendered_content": rendered_html,
                "dropdown_actions": dropdown_actions,
                "custom_buttons": config.get("custom_buttons", ""),
                "is_custom": True,
            }
        except Exception as e:
            logger.error(
                "Error building custom related list %s: %s",
                custom_name,
                str(e),
                exc_info=True,
            )
            return None

    def _find_intermediate_model(
        self, intermediate_model_name, obj_app_label, related_app_label
    ):
        """Helper to find intermediate model across different app labels."""
        app_labels_to_try = [obj_app_label, related_app_label]

        # Add other app labels
        for app_config in apps.get_app_configs():
            if app_config.label not in app_labels_to_try:
                app_labels_to_try.append(app_config.label)

        for app_label in app_labels_to_try:
            try:
                return apps.get_model(app_label, intermediate_model_name)
            except LookupError:
                continue

        return None

    def _get_related_field_from_intermediate(
        self, intermediate_model, related_model, exclude_field=None
    ):
        """Find the field in intermediate model pointing to related model."""
        for field in intermediate_model._meta.get_fields():
            if (
                hasattr(field, "related_model")
                and field.related_model == related_model
                and field.name != exclude_field
            ):
                return field.name
        return None

    def _build_intermediate_annotations(
        self,
        intermediate_model,
        intermediate_field,
        related_field,
        related_obj_field,
        obj,
        columns,
    ):
        """Build annotations for fields from the intermediate model."""
        from horilla.db.models import OuterRef, Subquery

        annotations = {}

        for _, col_field in columns:
            if "__" in col_field and col_field.startswith(intermediate_field):
                field_parts = col_field.split("__", 1)

                if len(field_parts) >= 2:
                    intermediate_field_name = field_parts[1]

                    # Extract the actual field name (before any display methods)
                    if "__" in intermediate_field_name:
                        value_field = intermediate_field_name.split("__")[0]
                    else:
                        # Handle get_*_display methods
                        if intermediate_field_name.startswith(
                            "get_"
                        ) and intermediate_field_name.endswith("_display"):
                            # Extract field name: get_member_status_display -> member_status
                            value_field = intermediate_field_name.replace(
                                "get_", ""
                            ).replace("_display", "")
                        else:
                            value_field = intermediate_field_name

                    subquery = intermediate_model.objects.filter(
                        **{related_field: obj, related_obj_field: OuterRef("pk")}
                    ).values(value_field)[:1]

                    annotations[col_field] = Subquery(subquery)

        return annotations

    def _rewrite_actions_for_parent_permissions(self, actions, parent_obj):
        """
        Gate edit/delete row actions on the parent record's permissions.

        Edit actions:
          - Global change on parent → strip all child-permission keys, always show.
          - Own-only change on parent (owns record) → replace child permission keys
            with parent own_permission + "created_by" owner_field so the template
            tag checks whether the child row's creator is within the user's
            subordinate tree, without requiring any child-model permission.
          - No change access → remove.

        Delete actions:
          - Parent delete access → strip child-permission keys, always show.
          - No delete access → remove.
        """
        user = self.request.user
        app = parent_obj._meta.app_label
        model = parent_obj._meta.model_name
        has_global_change = user.is_superuser or user.has_perm(f"{app}.change_{model}")
        has_global_delete = user.is_superuser or user.has_perm(f"{app}.delete_{model}")
        can_change = has_global_change or check_record_change_access(user, parent_obj)
        can_delete = check_record_delete_access(user, parent_obj)

        _CHANGE_KEYWORDS = {"edit", "change", "update"}
        _DELETE_KEYWORDS = {"delete", "remove"}

        _STRIP_KEYS = {
            "permission",
            "own_permission",
            "owner_field",
            "owner_method",
            "intermediate_model",
            "intermediate_field",
            "parent_field",
        }

        from horilla.contrib.core.utils import get_allowed_user_ids

        allowed_ids = get_allowed_user_ids(user)

        def _make_disabled_if(im_name, i_field, p_field, p_pk, a_ids):
            def _disabled_if(related_obj):
                if not im_name or not i_field or not p_field:
                    return False
                try:
                    im = apps.get_model(related_obj._meta.app_label, im_name)
                except LookupError:
                    try:
                        for app_cfg in apps.get_app_configs():
                            try:
                                im = apps.get_model(app_cfg.label, im_name)
                                break
                            except LookupError:
                                continue
                        else:
                            return False
                    except Exception:
                        return False
                try:
                    member = im.objects.filter(
                        **{i_field: related_obj, f"{p_field}_id": p_pk}
                    ).first()
                    if not member:
                        return True
                    created_by = getattr(member, "created_by", None)
                    if not created_by:
                        return False
                    return created_by.pk not in a_ids
                except Exception:
                    return False

            return _disabled_if

        rewritten = []
        for action in actions:
            if isinstance(action, tuple):
                action = action[0] if action else None
            if not isinstance(action, dict):
                continue

            action_label = str(action.get("action", "")).lower()
            if any(k in action_label for k in _CHANGE_KEYWORDS):
                if not can_change:
                    continue  # no change access at all → hide action entirely
                if has_global_change:
                    action = {k: v for k, v in action.items() if k not in _STRIP_KEYS}
                else:
                    # Own-only: disable for rows created by superiors
                    im_name = action.get("intermediate_model")
                    i_field = action.get("intermediate_field")
                    p_field = action.get("parent_field")
                    action = {k: v for k, v in action.items() if k not in _STRIP_KEYS}
                    action["disabled_if"] = _make_disabled_if(
                        im_name,
                        i_field,
                        p_field,
                        parent_obj.pk,
                        allowed_ids,
                    )
            elif any(k in action_label for k in _DELETE_KEYWORDS):
                if not can_delete:
                    continue  # no delete access → hide action entirely
                if has_global_delete:
                    action = {k: v for k, v in action.items() if k not in _STRIP_KEYS}
                else:
                    # Own-only delete: disable for rows created by superiors
                    im_name = action.get("intermediate_model")
                    i_field = action.get("intermediate_field")
                    p_field = action.get("parent_field")
                    action = {k: v for k, v in action.items() if k not in _STRIP_KEYS}
                    action["disabled_if"] = _make_disabled_if(
                        im_name,
                        i_field,
                        p_field,
                        parent_obj.pk,
                        allowed_ids,
                    )
            rewritten.append(action)
        return rewritten

    def create_generic_list_view_instance(
        self, model, queryset, config, view_id=None, parent_obj=None
    ):
        """
        Create and configure HorillaListView instance
        """
        section_info = get_section_info_for_model(model)
        section = section_info.get("section", "")

        col_attrs = config.get("col_attrs", [])
        related_app = model._meta.app_label
        related_model_name = model._meta.model_name
        related_view_perm = f"{related_app}.view_{related_model_name}"
        related_view_own_perm = f"{related_app}.view_own_{related_model_name}"
        related_owner_fields = getattr(model, "OWNER_FIELDS", [])
        for col_attr in col_attrs:
            for _, attrs in col_attr.items():
                if not isinstance(attrs, dict):
                    continue
                for key, value in list(attrs.items()):
                    if key in ("hx-get", "hx-post", "hx-delete", "href") and isinstance(
                        value, str
                    ):
                        value = re.sub(r"([&?])section=[^&]*", "", value)
                        value = value.replace("?&", "?").rstrip("&").rstrip("?")
                        separator = "&" if "?" in value else "?"
                        attrs[key] = f"{value}{separator}section={section}"
                # Always set permission keys to the related model's view permission
                # so the template's col_attr_has_permission tag gates the link
                # per-row. Overwrite whatever the config had — the related model's
                # view permission is the correct gate for row navigation links.
                if (
                    "permission" in attrs
                    or "own_permission" in attrs
                    or "hx-get" in attrs
                    or "href" in attrs
                ):
                    attrs["permission"] = related_view_perm
                    attrs["own_permission"] = related_view_own_perm
                    if related_owner_fields:
                        attrs["owner_field"] = related_owner_fields[0]
                    else:
                        attrs.pop("owner_field", None)
                        attrs.pop("owner_method", None)

        list_view = HorillaListView()
        list_view.model = model
        list_view.request = self.request
        list_view.queryset = queryset
        columns = self.get_columns_for_model(model, config)
        list_view.columns = columns
        actions = config.get("actions", [])
        if parent_obj is not None:
            actions = self._rewrite_actions_for_parent_permissions(actions, parent_obj)
        actions_method = config.get("action_method")
        list_view.actions = actions
        list_view.action_method = actions_method
        list_view.col_attrs = col_attrs
        list_view.bulk_select_option = False
        list_view.filterset_class = None
        list_view.view_id = f"{view_id}-content" if view_id else None
        list_view.main_session_id = list_view.view_id
        if parent_obj is not None and view_id:
            class_name = self.request.GET.get("class_name", "")
            list_view.main_url = (
                f"{reverse('generics:related_list_content', kwargs={'pk': parent_obj.pk})}"
                f"?field_name={view_id}"
                f"&model_name={parent_obj.__class__.__name__}"
                f"&class_name={class_name}"
            )
        else:
            list_view.main_url = self.request.path
        list_view.search_url = self.request.path
        list_view.owner_filtration = False
        list_view.no_record_fit_height = False
        return list_view

    def render_generic_list_view(self, list_view):
        """
        Render HorillaListView and return HTML string
        """
        try:
            sorted_queryset = list_view.get_queryset()
            # Set object_list to the sorted QuerySet
            list_view.object_list = sorted_queryset
            context = list_view.get_context_data()

            return render_to_string(
                list_view.template_name, context, request=self.request
            )
        except Exception:
            return ""

    def get_columns_for_model(self, model, config):
        """
        Get columns to display for a model in the format [(verbose_name, field_name), ...]
        """
        if "columns" in config:
            return config["columns"]

        columns = []
        exclude_fields = config.get("exclude", [])
        default_exclude = [
            "id",
            "created_at",
            "additional_info",
            "updated_at",
            "history",
            "is_active",
            "created_by",
            "updated_by",
            "company",
        ]
        try:
            for field in model._meta.fields:
                if (
                    field.name not in default_exclude
                    and field.name not in exclude_fields
                ):
                    columns.append((field.verbose_name, field.name))
                    if len(columns) == 5:
                        break
        except Exception:
            return []

        return columns

    def get_context_data(self, **kwargs):
        """Add related_lists_metadata, object_id, and class_name to context."""
        context = super().get_context_data(**kwargs)
        context["related_lists_metadata"] = self.get_related_lists_metadata()
        context["object_id"] = self.object.pk
        context["class_name"] = self.__class__.__name__
        return context


@method_decorator(htmx_required, name="dispatch")
class HorillaRelatedListContentView(LoginRequiredMixin, DetailView):
    """
    View to handle HTMX GenericSingleDetailedViewequests for individual related list content
    """

    template_name = "related_list_content.html"
    context_object_name = "object"

    def get_parent_view_class(self, model, class_name):
        """
        Dynamically resolve the parent view class for the given model
        """
        try:
            view_class = HorillaRelatedListSectionView._view_registry.get(model)
            if view_class:
                return view_class
        except (ImportError, AttributeError) as e:
            logger.error("Error resolving view %s in %s%s", class_name, model, str(e))

        return HorillaRelatedListSectionView

    def get_queryset(self):
        """Resolve parent model once per request (avoids duplicate ContentType hits)."""
        if getattr(self, "_cached_queryset", None) is not None:
            return self._cached_queryset

        model_name = self.request.GET.get("model_name")
        class_name = self.request.GET.get("class_name")
        model = None

        # Prefer registry lookup when class_name is present (no ContentType query).
        if class_name:
            for (
                reg_model,
                view_cls,
            ) in HorillaRelatedListSectionView._view_registry.items():
                if view_cls.__name__ == class_name:
                    model = reg_model
                    break

        if model is None:
            if not model_name:
                raise HttpNotFound("model_name parameter is required")
            try:
                content_type = HorillaContentType.objects.get(model=model_name.lower())
                model = apps.get_model(
                    app_label=content_type.app_label, model_name=model_name
                )
            except Exception as e:
                messages.error(self.request, e)
                raise HttpNotFound(e) from e

        self._cached_queryset = model.objects.all()
        return self._cached_queryset

    def get(self, request, *args, **kwargs):
        """Load and render related list content for the given field_name."""
        self.object = self.get_object()
        if not check_record_access(request.user, self.object):
            return render(request, "403.html", status=403)
        field_name = request.GET.get("field_name")
        class_name = request.GET.get("class_name")

        if not field_name:
            return HttpResponse("Field name required", status=400)

        model = self.object.__class__
        parent_view_class = self.get_parent_view_class(model, class_name)
        parent_view = parent_view_class()
        parent_view.request = request
        parent_view.kwargs = getattr(self, "kwargs", kwargs)
        parent_view.object = self.object
        parent_view.model = model
        parent_view.excluded_related_lists = getattr(
            parent_view_class, "excluded_related_lists", []
        )
        related_list_data = parent_view.get_single_related_list(self.object, field_name)
        if not related_list_data:
            return HttpResponse(
                f"No valid related field found for field_name: {field_name}", status=404
            )

        # "Add Column to List" is only shown to users with global view permission
        # on the related model. view_own is not sufficient — column layout changes
        # affect all users, so this is gated on the unrestricted view permission.
        related_model = related_list_data.get("model")
        can_add_column = False
        if related_model:
            r_app = related_model._meta.app_label
            r_model = related_model._meta.model_name
            user = request.user
            if user.is_superuser or user.has_perm(f"{r_app}.view_{r_model}"):
                can_add_column = True

        context = {
            "related_list": related_list_data,
            "object": self.object,
            "class_name": class_name,
            "can_add_column": can_add_column,
        }

        return render(request, self.template_name, context)
