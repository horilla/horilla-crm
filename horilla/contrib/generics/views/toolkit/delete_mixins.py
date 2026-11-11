"""
Delete view toolkit: helpers and mixins for single-object delete with dependency handling.

Contains helper functions (excluded models, nullable check, FK name, context builder)
and mixins (dependency checking, pagination, bulk/individual reassign, main object deletion).
"""

# Standard library imports
import logging

# First-party (Horilla)
from horilla.apps import apps

# First party imports (Horilla)
from horilla.contrib.core.models import RecycleBin
from horilla.core.exceptions import ObjectDoesNotExist
from horilla.registry.feature import FEATURE_CONFIG, FEATURE_REGISTRY

logger = logging.getLogger(__name__)

# --- Helpers (used by mixins and by delete view) ---

# Feature apps register their own models for (see ``register_feature("delete_dependency")``
# in core). Registered models are ignored when listing delete dependencies, so they
# never show up in the dependency dialog or the reassign options.
DELETE_DEPENDENCY_FEATURE = "delete_dependency"

DEFAULT_EXCLUDED_DEPENDENCY_MODEL_LABELS = [
    "RecycleBinPolicy",
    "RecycleBin",
    "ActiveTab",
    "KanbanGroupBy",
    "TimelineSpanBy",
    "ListColumnVisibility",
    "RecentlyViewed",
    "SavedFilterList",
    "PinnedView",
    "LogEntry",
    "LoginHistory",
]


def get_excluded_models(excluded_model_labels=None):
    """
    Resolve the models to ignore as delete dependencies.

    Combines the model names in ``excluded_model_labels`` (looked up in all apps)
    with the models any app registered for the ``delete_dependency`` feature.
    """
    excluded_model_labels = (
        excluded_model_labels or DEFAULT_EXCLUDED_DEPENDENCY_MODEL_LABELS
    )
    excluded = []
    for model_name in excluded_model_labels:
        found_models = []
        for app_config in apps.get_app_configs():
            try:
                model = app_config.get_model(model_name)
                found_models.append(model)
            except LookupError:
                continue
        if len(found_models) >= 1:
            excluded.append(found_models[0])
        else:
            logger.warning("Model '%s' could not be resolved in any app.", model_name)

    registry_key = FEATURE_CONFIG.get(DELETE_DEPENDENCY_FEATURE)
    for model in FEATURE_REGISTRY.get(registry_key, []):
        if model not in excluded:
            excluded.append(model)
    return excluded


def is_field_nullable(related_model, main_model):
    """Check if the FK to main_model in related_model is nullable."""
    try:
        field_name = [
            f.name for f in related_model._meta.fields if f.related_model == main_model
        ][0]
        return related_model._meta.get_field(field_name).null
    except IndexError:
        return False


def get_fk_field_name(related_model, main_model):
    """Get the FK field name on related_model that points to main_model."""
    for f in related_model._meta.fields:
        if getattr(f, "related_model", None) == main_model:
            return f.name
    return None


def build_dependency_context(
    request,
    view,
    record_id,
    cannot_delete,
    can_delete,
    dependent_records,
    related_model,
    available_targets,
    is_nullable,
    has_more_individual_records,
    delete_mode,
    view_id=None,
):
    """Build common context dict for dependency modals/forms."""
    view_id = view_id or f"delete_{record_id}"
    return {
        "object": view.object,
        "cannot_delete": cannot_delete,
        "can_delete": can_delete,
        "cannot_delete_count": len(cannot_delete),
        "can_delete_count": len(can_delete),
        "model_verbose_name": view.model._meta.verbose_name_plural,
        "search_url": request.path,
        "view_id": view_id,
        "record_id": record_id,
        "related_model": related_model,
        "dependent_records": dependent_records,
        "available_targets": available_targets,
        "is_nullable": is_nullable,
        "has_more_individual_records": has_more_individual_records,
        "delete_mode": delete_mode,
        "reassign_all_visibility": getattr(view, "reassign_all_visibility", True),
        "reassign_individual_visibility": getattr(
            view, "reassign_individual_visibility", True
        ),
        "hx_target": getattr(view, "hx_target", None),
    }


# --- Mixins ---


class DeleteDependencyMixin:
    """Mixin for dependency checking and pagination of related records."""

    def _get_excluded_models(self):
        """Resolve excluded model labels to model classes using helpers."""
        labels = getattr(
            self,
            "excluded_dependency_model_labels",
            None,
        )
        return get_excluded_models(labels)

    def _is_field_nullable(self, related_model):
        """Check if the FK from related_model to self.model is nullable."""
        return is_field_nullable(related_model, self.model)

    def _get_paginated_individual_records(self, record_id, page=1, per_page=8):
        """Get paginated individual records for infinite scrolling in individual reassign form."""
        try:
            obj = self.model.objects.get(id=record_id)
            related_objects = self.model._meta.related_objects
            all_records = []
            available_targets = self.model.objects.exclude(id=record_id)
            is_nullable = False

            for related in related_objects:
                related_model = related.related_model
                related_name = related.get_accessor_name()
                if related_name:
                    if hasattr(related_model, "all_objects"):
                        related_records = related_model.all_objects.filter(
                            **{related.field.name: obj}
                        )
                    else:
                        related_records = related_model.objects.filter(
                            **{related.field.name: obj}
                        )
                    all_records.extend(related_records)
                    is_nullable = self._is_field_nullable(related_model)

            total_count = len(all_records)
            offset = (page - 1) * per_page
            paginated_records = all_records[offset : offset + per_page]
            has_more = offset + per_page < total_count

            return {
                "records": paginated_records,
                "has_more": has_more,
                "next_page": page + 1 if has_more else None,
                "total_count": total_count,
                "available_targets": available_targets,
                "is_nullable": is_nullable,
            }

        except Exception as e:
            logger.error("Error getting paginated individual records: %s", str(e))
            return {
                "records": [],
                "has_more": False,
                "next_page": None,
                "total_count": 0,
                "available_targets": self.model.objects.exclude(id=record_id),
                "is_nullable": False,
            }

    def _check_dependencies(self, record_id, get_all=False):
        """
        Check for dependencies in related models for the given record ID.
        Returns: cannot_delete (list), can_delete (list), dependency_details (dict).
        """
        cannot_delete = []
        can_delete = []
        dependency_details = {}

        try:
            obj = self.model.all_objects.filter(id=record_id).only("id").first()
            if not obj:
                logger.warning(
                    "No record found with id %s for model %s",
                    record_id,
                    self.model.__name__,
                )
                return cannot_delete, can_delete, dependency_details

            related_objects = self.model._meta.related_objects
            if not related_objects:
                can_delete.append({"id": obj.id, "name": str(obj)})
                return cannot_delete, can_delete, dependency_details

            dependencies = []
            total_individual_records = 0
            excluded_models = self._get_excluded_models()

            for related in related_objects:
                related_model = related.related_model
                if related_model in excluded_models:
                    continue

                related_name = related.get_accessor_name()
                if related_name:
                    if hasattr(related_model, "all_objects"):
                        fk_field_name = related.field.name
                        all_related_records = related_model.all_objects.filter(
                            **{fk_field_name: obj}
                        )
                        total_count = all_related_records.count()
                        related_records = (
                            list(all_related_records)
                            if get_all
                            else list(all_related_records[:10])
                        )
                    else:
                        fk_field_name = related.field.name
                        related_records_qs = related_model.objects.filter(
                            **{fk_field_name: obj}
                        )
                        total_count = related_records_qs.count()
                        related_records = (
                            list(related_records_qs)
                            if get_all
                            else list(related_records_qs[:10])
                        )

                    total_individual_records += total_count

                    if related_records or total_count > 0:
                        dependencies.append(
                            {
                                "model_name": related_model._meta.verbose_name_plural,
                                "count": total_count,
                                "records": [str(rec) for rec in related_records],
                                "related_model": related_model,
                                "related_name": related_name,
                                "related_records": related_records,
                                "has_more": (
                                    total_count > len(related_records)
                                    if not get_all
                                    else False
                                ),
                            }
                        )

            if dependencies:
                cannot_delete.append(
                    {
                        "id": obj.id,
                        "name": str(obj),
                        "dependencies": dependencies,
                        "total_individual_records": total_individual_records,
                    }
                )
            else:
                can_delete.append({"id": obj.id, "name": str(obj)})

            dependency_details = {
                item["id"]: item["dependencies"] for item in cannot_delete
            }
            return cannot_delete, can_delete, dependency_details
        except Exception as e:
            logger.error("Error checking dependencies: %s", str(e))
            return cannot_delete, can_delete, dependency_details

    def _get_paginated_dependencies(self, record_id, related_name, page=1, per_page=8):
        """Get paginated dependencies for infinite scrolling."""
        try:
            obj = self.model.objects.get(id=record_id)
            related_objects = self.model._meta.related_objects
            excluded_models = self._get_excluded_models()

            for related in related_objects:
                related_model = related.related_model
                if related_model in excluded_models:
                    continue

                if related.get_accessor_name() == related_name:
                    if hasattr(related_model, "all_objects"):
                        queryset = related_model.all_objects.filter(
                            **{related.field.name: obj}
                        )
                    else:
                        queryset = getattr(obj, related_name).all()

                    total_count = queryset.count()
                    offset = (page - 1) * per_page
                    records = queryset[offset : offset + per_page]
                    has_more = offset + per_page < total_count

                    return {
                        "records": records,
                        "has_more": has_more,
                        "next_page": page + 1 if has_more else None,
                        "total_count": total_count,
                        "related_model": related_model,
                    }

            return {
                "records": [],
                "has_more": False,
                "next_page": None,
                "total_count": 0,
            }
        except Exception as e:
            logger.error("Error getting paginated dependencies: %s", str(e))
            return {
                "records": [],
                "has_more": False,
                "next_page": None,
                "total_count": 0,
            }

    def _dependent_records_from_cannot_delete(self, cannot_delete, limit=8):
        """Build dependent_records, related_model, is_nullable, has_more from cannot_delete.
        Pass limit=None to return all dependent records (no slicing)."""
        dependent_records = []
        related_model = None
        is_nullable = False
        has_more = False
        if cannot_delete:
            all_dependent_records = []
            for dep in cannot_delete[0]["dependencies"]:
                related_model = dep["related_model"]
                all_dependent_records.extend(dep["related_records"])
                is_nullable = self._is_field_nullable(related_model)
            if limit is not None:
                dependent_records = all_dependent_records[:limit]
                has_more = len(all_dependent_records) > limit
            else:
                dependent_records = all_dependent_records
        return dependent_records, related_model, is_nullable, has_more


class DeleteReassignMixin:
    """Mixin for bulk reassign, individual actions, and main object deletion."""

    def _perform_bulk_reassign(self, record_id, new_target_id):
        """Reassign all dependent records to a new target. Returns the number of reassigned records."""
        try:
            obj = self.model.all_objects.get(id=record_id)
            new_target = self.model.objects.get(id=new_target_id)
            related_objects = self.model._meta.related_objects
            reassigned_count = 0
            excluded_models = self._get_excluded_models()

            for related in related_objects:
                related_model = related.related_model
                if related_model in excluded_models:
                    continue

                related_name = related.get_accessor_name()
                if related_name:
                    if hasattr(related_model, "all_objects"):
                        fk_field_name = related.field.name
                        related_records = related_model.all_objects.filter(
                            **{fk_field_name: obj}
                        )
                    else:
                        fk_field_name = related.field.name
                        related_records = related_model.objects.filter(
                            **{fk_field_name: obj}
                        )

                    field_name = get_fk_field_name(related_model, self.model)
                    if field_name:
                        for rec in related_records:
                            setattr(rec, field_name, new_target)
                            rec.save()
                            reassigned_count += 1
            return reassigned_count
        except ObjectDoesNotExist as exe:
            raise ValueError(f"Target with id {new_target_id} does not exist") from exe

    def _perform_individual_action(self, record_id, actions, delete_mode=None):
        """
        Handle individual reassign, set null, or delete actions for dependent records.

        actions:
            dict with record IDs as keys and
            {
                action: 'reassign' | 'set_null' | 'delete',
                new_target_id: ID
            }
            as values.

        delete_mode:
            When 'main_soft', dependent deletes are performed as soft-deletes
            (RecycleBin entry created) to match the main record delete mode.

        Returns the number of processed records.
        """
        try:
            obj = self.model.all_objects.get(id=record_id)
            related_objects = self.model._meta.related_objects
            processed_count = 0
            excluded_models = self._get_excluded_models()

            for related in related_objects:
                related_model = related.related_model
                if related_model in excluded_models:
                    continue

                related_name = related.get_accessor_name()
                if related_name:
                    if hasattr(related_model, "all_objects"):
                        fk_field_name = related.field.name
                        related_records = related_model.objects.filter(
                            **{fk_field_name: obj}
                        )
                    else:
                        fk_field_name = related.field.name
                        related_records = related_model.objects.filter(
                            **{fk_field_name: obj}
                        )

                    field_name = get_fk_field_name(related_model, self.model)
                    for rec in related_records:
                        if str(rec.id) not in actions:
                            continue
                        action = actions[str(rec.id)]
                        if action["action"] == "reassign" and action.get(
                            "new_target_id"
                        ):
                            try:
                                new_target = self.model.objects.get(
                                    id=action["new_target_id"]
                                )
                                setattr(rec, field_name, new_target)
                                rec.save()
                                processed_count += 1
                            except ObjectDoesNotExist:
                                continue
                        elif action["action"] == "set_null" and self._is_field_nullable(
                            related_model
                        ):
                            setattr(rec, field_name, None)
                            rec.save()
                            processed_count += 1
                        elif action["action"] == "delete":
                            # Match dependent delete behavior with selected delete_mode
                            if delete_mode == "main_soft":
                                try:
                                    user = (
                                        getattr(self.request, "user", None)
                                        if hasattr(self, "request")
                                        else None
                                    )
                                except Exception:
                                    user = None
                                RecycleBin.create_from_instance(rec, user=user)
                            rec.delete()
                            processed_count += 1
            return processed_count
        except ObjectDoesNotExist as exe:
            raise ValueError(
                "Invalid target ID provided in individual actions"
            ) from exe

    def _delete_main_object(self, delete_mode, user=None):
        """Delete the main object based on the delete mode (main_soft vs hard)."""
        if delete_mode == "main_soft":
            RecycleBin.create_from_instance(self.object, user=user if user else None)
        self.object.delete()

    def _bulk_delete_related(self):
        """Delete all related records for self.object (excluding excluded models), then delete main object is caller's job."""
        related_objects = self.model._meta.related_objects
        excluded_models = self._get_excluded_models()
        for related in related_objects:
            if related.many_to_many:
                continue
            related_model = related.related_model
            if related_model in excluded_models:
                continue
            related_name = related.get_accessor_name()
            if related_name:
                if hasattr(related_model, "all_objects"):
                    fk_field_name = related.field.name
                    related_model.all_objects.filter(
                        **{fk_field_name: self.object}
                    ).delete()
                else:
                    fk_field_name = related.field.name
                    related_model.objects.filter(
                        **{fk_field_name: self.object}
                    ).delete()

    def _find_related_record_by_id(self, record_id_to_find):
        """Find a related record by id in any related model. Returns record or None."""
        excluded_models = self._get_excluded_models()
        related_objects = self.model._meta.related_objects
        for related in related_objects:
            related_model = related.related_model
            if related_model in excluded_models:
                continue
            try:
                # Company-scoped manager, and only records that actually
                # reference the main object, so arbitrary ids can't be deleted.
                return related_model.objects.get(
                    id=record_id_to_find, **{related.field.name: self.object}
                )
            except ObjectDoesNotExist:
                continue
        return None
