"""
Generic delete view for single object deletion with dependency handling, including bulk reassign and individual record management before deletion.
This view checks for related records in other models and provides options to reassign, set null, or delete those records before allowing the main record to be deleted.
"""

# Standard library imports
import json
import logging

from django.contrib import messages
from django.utils.encoding import force_str

# Third-party imports (Django)
from django.views.generic import DeleteView

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import login_redirect
from horilla.contrib.core.models import RecycleBin
from horilla.contrib.core.utils import get_allowed_user_ids
from horilla.core.exceptions import (
    ImproperlyConfigured,
    ObjectDoesNotExist,
    PermissionDenied,
)
from horilla.db import transaction
from horilla.shortcuts import redirect, render
from horilla.utils.translation import gettext_lazy as _
from horilla.web import Http404, HttpResponse, HxTriggerResponse, ScriptResponse

# Local imports
from .toolkit.delete_mixins import (
    DEFAULT_EXCLUDED_DEPENDENCY_MODEL_LABELS,
    DeleteDependencyMixin,
    DeleteReassignMixin,
    build_dependency_context,
    get_fk_field_name,
)

logger = logging.getLogger(__name__)


class HorillaSingleDeleteView(DeleteDependencyMixin, DeleteReassignMixin, DeleteView):
    """Generic delete view for single object deletion with dependency handling."""

    template_name = None
    success_url = None
    success_message = _("The record was deleted successfully.")
    reassign_all_visibility = True
    check_delete_permission = True
    reassign_individual_visibility = True
    hx_target = None
    excluded_dependency_model_labels = DEFAULT_EXCLUDED_DEPENDENCY_MODEL_LABELS

    def get_queryset(self):
        """Dynamically get queryset based on app_label and model_name from URL."""
        if not getattr(self, "model", None):
            app_label = self.kwargs.get("app_label")
            model_name = self.kwargs.get("model_name")
            if not app_label or not model_name:
                raise ImproperlyConfigured(
                    "HorillaSingleDeleteView requires either a 'model' attribute "
                    "or 'app_label' and 'model_name' in URL kwargs."
                )
            try:
                self.model = apps.get_model(app_label, model_name)
            except LookupError:
                return render(self.request, "403.html", {"modal": True})
        # Use the default (company-scoped) manager so a record that belongs to
        # another company can never be resolved from a URL pk (cross-tenant IDOR).
        return self.model.objects.all()

    def get(self, request, *args, **kwargs):
        """Handle GET requests for delete view, including dependency check and form rendering."""
        if not self.request.user.is_authenticated:
            return login_redirect(request)
        try:
            self.object = self.get_object()
            record_id = self.object.id
            action = request.GET.get("action")
            view_id = request.GET.get("view_id", f"delete_{record_id}")
            delete_mode = request.GET.get("delete_mode", "hard")

            if action == "load_more_dependencies":
                related_name = request.GET.get("related_name")
                page = int(request.GET.get("page", 1))
                per_page = int(request.GET.get("per_page", 8))
                pagination_data = self._get_paginated_dependencies(
                    record_id, related_name, page, per_page
                )
                context = {
                    "records": pagination_data["records"],
                    "has_more": pagination_data["has_more"],
                    "next_page": pagination_data["next_page"],
                    "related_name": related_name,
                    "record_id": record_id,
                    "per_page": per_page,
                    "delete_mode": delete_mode,
                }
                return render(
                    request,
                    "partials/single_delete/delete_dependency_partial.html",
                    context,
                )

            if action == "load_more_individual_records":
                page = int(request.GET.get("page", 1))
                per_page = int(request.GET.get("per_page", 8))
                pagination_data = self._get_paginated_individual_records(
                    record_id, page, per_page
                )
                context = {
                    "records": pagination_data["records"],
                    "has_more": pagination_data["has_more"],
                    "next_page": pagination_data["next_page"],
                    "main_record_id": record_id,
                    "per_page": per_page,
                    "available_targets": pagination_data["available_targets"],
                    "is_nullable": pagination_data["is_nullable"],
                    "search_url": request.path,
                    "delete_mode": delete_mode,
                }
                return render(
                    request,
                    "partials/single_delete/individual_reassign_partial.html",
                    context,
                )

            cannot_delete, can_delete, _dependency_details = self._check_dependencies(
                record_id
            )
            available_targets = self.model.objects.exclude(id=record_id)
            dep_records, related_model, is_nullable, has_more_individual = (
                self._dependent_records_from_cannot_delete(cannot_delete)
            )

            context = build_dependency_context(
                request,
                self,
                record_id,
                cannot_delete,
                can_delete,
                dep_records,
                related_model,
                available_targets,
                is_nullable,
                has_more_individual,
                delete_mode,
                view_id,
            )

            if action == "show_individual_reassign":
                # Load all dependent records for bulk actions (table view)
                cannot_delete_all, _can_delete_all, _dependency_details = (
                    self._check_dependencies(record_id, get_all=True)
                )
                (
                    all_dep_records,
                    _related_model,
                    _is_nullable,
                    _has_more,
                ) = self._dependent_records_from_cannot_delete(
                    cannot_delete_all, limit=None
                )
                context["dependent_records"] = all_dep_records
                context["has_more_individual_records"] = False
                context["selected_ids_json"] = json.dumps(
                    [r.id for r in all_dep_records]
                )

            if action == "show_bulk_reassign":
                return render(
                    request, "partials/single_delete/bulk_reassign_form.html", context
                )
            if action == "show_individual_reassign":
                return render(
                    request,
                    "partials/single_delete/individual_reassign_form.html",
                    context,
                )
            if action == "show_delete_confirmation":
                # Use actual dependency types from cannot_delete, not the last related_objects entry
                related_verbose_name_plural = "records"
                related_model = None
                if cannot_delete and cannot_delete[0].get("dependencies"):
                    dep_names = [
                        str(d["model_name"]) for d in cannot_delete[0]["dependencies"]
                    ]
                    related_verbose_name_plural = ", ".join(dep_names)
                    related_model = cannot_delete[0]["dependencies"][0].get(
                        "related_model"
                    )
                context["model_verbose_name"] = self.model._meta.verbose_name
                context["related_model"] = related_model if cannot_delete else None
                context["related_verbose_name_plural"] = related_verbose_name_plural
                context["hx_target"] = self.hx_target
                return render(
                    request, "partials/single_delete/delete_all_confirm.html", context
                )

            if not request.GET.get("delete_mode"):
                return render(
                    request, "partials/single_delete/delete_mode_modal.html", context
                )
            return render(
                request,
                "partials/single_delete/delete_dependency_modal.html",
                context,
            )

        except Exception as e:
            logger.error("Error in get method: %s", str(e))
            messages.error(self.request, str(e))
            return ScriptResponse(
                reload=True, extra="closeDeleteModeModal();", close=True
            )

    @staticmethod
    def _is_owned_by_user_or_subordinate(obj, user):
        """
        Return True if any OWNER_FIELDS value on ``obj`` (ForeignKey or
        ManyToMany) is the user or a user in a subordinate role. Same rule the
        list, detail and related-tab views use for ``*_own`` permissions.
        """
        owner_fields = getattr(obj.__class__, "OWNER_FIELDS", None)
        if not owner_fields:
            return False
        allowed_ids = get_allowed_user_ids(user)
        for field_name in owner_fields:
            value = getattr(obj, field_name, None)
            if value is None:
                continue
            if hasattr(value, "all"):
                if any(member.pk in allowed_ids for member in value.all()):
                    return True
            elif getattr(value, "pk", None) in allowed_ids:
                return True
        return False

    def get_object(self, queryset=None):
        """Override to check delete permissions on the specific object."""
        if queryset is None:
            queryset = self.get_queryset()
        try:
            obj = super().get_object(queryset)
        except Http404 as exc:
            raise Http404(
                f"{self.model._meta.object_name} matching query does not exist."
            ) from exc
        if self.check_delete_permission:
            user = self.request.user
            app_label = self.model._meta.app_label
            model_name = self.model._meta.model_name
            delete_perm = f"{app_label}.delete_{model_name}"
            delete_own_perm = f"{app_label}.delete_own_{model_name}"
            has_delete_all = user.has_perm(delete_perm)
            has_delete_own = user.has_perm(delete_own_perm)
            if has_delete_all:
                return obj
            if has_delete_own:
                if self._is_owned_by_user_or_subordinate(obj, user):
                    return obj

                from .helpers.queryset_utils import user_has_granted_access

                if user_has_granted_access(obj, user, "delete"):
                    return obj
                raise PermissionDenied(
                    _("You don't have permission to delete this %(model)s.")
                    % {"model": force_str(self.model._meta.verbose_name)}
                )
            raise PermissionDenied(
                _("You don't have permission to delete %(model)s.")
                % {"model": force_str(self.model._meta.verbose_name_plural)}
            )
        return obj

    def post(self, request, *args, **kwargs):
        """Resolve object and delegate to parent post; on error return reload/close script."""
        try:
            self.object = self.get_object()
            return self.delete(request, *args, **kwargs)
        except Exception as e:
            messages.error(self.request, _(str(e)))
            return ScriptResponse(
                reload=True, extra="closeDeleteModeModal();", close=True
            )

    def delete(self, request, *args, **kwargs):
        """Handle POST requests for delete actions with dependency handling."""
        try:
            record_id = self.object.id
            delete_mode = request.POST.get("delete_mode")
            action = request.POST.get("action")
            check_dependencies = request.POST.get("check_dependencies", "true")

            if not delete_mode and action != "check_dependencies_with_mode":
                result = self._handle_missing_delete_mode(
                    request, record_id, check_dependencies
                )
            elif check_dependencies == "false" and delete_mode:
                result = self._handle_direct_delete(request, record_id, delete_mode)
            elif action == "check_dependencies_with_mode":
                result = self._handle_check_dependencies_with_mode(
                    request, record_id, delete_mode
                )
            elif action == "bulk_reassign" and request.POST.get("new_target_id"):
                result = self._handle_bulk_reassign(request, record_id, delete_mode)
            elif action == "individual_action":
                result = self._handle_individual_action(request, record_id, delete_mode)
            elif action == "soft_delete_record":
                result = self._handle_soft_delete_record(request)
            elif action == "delete_single_record":
                result = self._handle_delete_single_record(request)
            elif action == "bulk_delete":
                result = self._handle_bulk_delete(request, delete_mode)
            elif action == "simple_delete":
                result = self._handle_simple_delete(request, record_id, delete_mode)
            elif action == "set_null_action":
                result = self._handle_set_null_action(request, delete_mode)
            else:
                result = self._handle_delete_fallback(request, record_id, delete_mode)

            return result

        except Exception as e:
            logger.error("Error in delete method: %s", str(e))
            messages.error(
                self.request,
                _("Error in delete method: %(error)s") % {"error": str(e)},
            )
            return ScriptResponse(reload=True, extra="closeDeleteModeModal();")

    def _handle_missing_delete_mode(self, request, record_id, check_dependencies):
        """Render the delete mode modal when no delete mode has been chosen yet."""
        context = {
            "object": self.object,
            "model_verbose_name": self.model._meta.verbose_name,
            "search_url": request.path,
            "view_id": request.GET.get("view_id", f"delete_{record_id}"),
            "record_id": record_id,
            "check_dependencies": check_dependencies,
        }
        return render(request, "partials/single_delete/delete_mode_modal.html", context)

    def _handle_direct_delete(self, request, record_id, delete_mode):
        """Delete the main object directly without checking dependencies."""
        try:
            with transaction.atomic():
                self._delete_main_object(
                    delete_mode,
                    request.user if hasattr(request, "user") else None,
                )
            messages.success(request, self.get_success_message())
            return self.get_post_delete_response()
        except Exception as e:
            logger.error(
                "Simple delete error for %s id %s: %s",
                self.model.__name__,
                record_id,
                str(e),
            )
            messages.info(
                self.request,
                _(
                    "Selected record is not associated with any company. Activate a company to proceed with deletion."
                ),
            )
            return ScriptResponse(reload=True, extra="closeDeleteModeModal();")

    def _handle_check_dependencies_with_mode(self, request, record_id, delete_mode):
        """Render the dependency modal for the chosen delete mode."""
        cannot_delete, can_delete, _dependency_details = self._check_dependencies(
            record_id
        )
        dep_records, related_model, is_nullable, has_more_individual = (
            self._dependent_records_from_cannot_delete(cannot_delete)
        )
        available_targets = self.model.objects.exclude(id=record_id)
        context = build_dependency_context(
            request,
            self,
            record_id,
            cannot_delete,
            can_delete,
            dep_records,
            related_model,
            available_targets,
            is_nullable,
            has_more_individual,
            delete_mode,
            request.GET.get("view_id", f"delete_{record_id}"),
        )
        return render(
            request,
            "partials/single_delete/delete_dependency_modal.html",
            context,
        )

    def _handle_bulk_reassign(self, request, record_id, delete_mode):
        """Reassign dependent records in bulk and delete the main object."""
        try:
            with transaction.atomic():
                new_target_id = int(request.POST.get("new_target_id"))
                reassigned_count = self._perform_bulk_reassign(record_id, new_target_id)
                self._delete_main_object(
                    delete_mode,
                    request.user if hasattr(request, "user") else None,
                )
            messages.success(
                request,
                _(
                    "Successfully reassigned %(count)d records and deleted the %(model)s."
                )
                % {
                    "count": reassigned_count,
                    "model": force_str(self.model._meta.verbose_name),
                },
            )
            return self.get_post_delete_response()
        except Exception as e:
            logger.error("Bulk reassign error: %s", str(e))
            messages.error(self.request, str(e))
            return ScriptResponse(
                msgs=True,
                reload=True,
                extra="closeDeleteModeModal();",
                status=500,
            )

    def _build_individual_actions(self, request):
        """Build the per-record actions mapping for individual_action handling."""
        actions = {}
        reassigned_count = 0
        selected_ids_raw = request.POST.get("selected_ids", "[]")
        try:
            selected_ids_list = json.loads(selected_ids_raw)
        except (TypeError, ValueError):
            selected_ids_list = []

        bulk_action = request.POST.get("bulk_action")
        bulk_target_id = request.POST.get("bulk_target_id", "").strip()

        if bulk_action in ("set_null", "delete") and selected_ids_list:
            for sid in selected_ids_list:
                actions[str(sid)] = {
                    "action": bulk_action,
                    "new_target_id": None,
                }
            return actions, reassigned_count, None

        for key, value in request.POST.items():
            if key.startswith("action_"):
                record_id_key = key.replace("action_", "")
                action_type = value
                new_target_id = request.POST.get(f"new_target_{record_id_key}")
                if action_type in [
                    "reassign",
                    "set_null",
                    "delete",
                ]:
                    actions[record_id_key] = {
                        "action": action_type,
                        "new_target_id": (
                            new_target_id
                            if action_type == "reassign" and new_target_id
                            else None
                        ),
                    }
                    if action_type == "reassign" and new_target_id:
                        try:
                            self.model.objects.get(id=new_target_id)
                            reassigned_count += 1
                        except ObjectDoesNotExist:
                            messages.error(self.request, _("Invalid target ID"))
                            return (
                                actions,
                                reassigned_count,
                                ScriptResponse(
                                    msgs=True,
                                    reload=True,
                                    extra="closeDeleteModeModal();",
                                    status=500,
                                ),
                            )
        if not actions and selected_ids_list:
            for sid in selected_ids_list:
                per_row_target = (request.POST.get(f"new_target_{sid}") or "").strip()
                target_id = per_row_target or bulk_target_id
                if target_id:
                    actions[str(sid)] = {
                        "action": "reassign",
                        "new_target_id": target_id,
                    }
                    try:
                        self.model.objects.get(id=target_id)
                        reassigned_count += 1
                    except ObjectDoesNotExist:
                        messages.error(self.request, _("Invalid target ID"))
                        return (
                            actions,
                            reassigned_count,
                            ScriptResponse(
                                msgs=True,
                                reload=True,
                                extra="closeDeleteModeModal();",
                                status=500,
                            ),
                        )
        return actions, reassigned_count, None

    def _finalize_individual_action(
        self, request, record_id, delete_mode, actions, reassigned_count
    ):
        """Apply the built actions and report the outcome messages."""
        processed_count = self._perform_individual_action(
            record_id, actions, delete_mode
        )
        remaining_cannot_delete, _can_delete, _dependency_details = (
            self._check_dependencies(record_id)
        )
        if not remaining_cannot_delete:
            self._delete_main_object(
                delete_mode,
                request.user if hasattr(request, "user") else None,
            )
            if reassigned_count > 0:
                messages.success(
                    request,
                    _("Reassigned %(count)d records and deleted %(record)s")
                    % {
                        "count": reassigned_count,
                        "record": str(self.object),
                    },
                )
            else:
                messages.success(
                    request,
                    _("Processed dependency records and deleted %(record)s")
                    % {"record": str(self.object)},
                )
        elif processed_count > 0:
            if reassigned_count > 0:
                messages.success(
                    request,
                    _("Reassigned %(count)d records") % {"count": reassigned_count},
                )
            else:
                messages.success(
                    request,
                    _("Processed dependency records"),
                )

    def _handle_individual_action(self, request, record_id, delete_mode):
        """Process individual per-record reassign/set_null/delete actions."""
        try:
            with transaction.atomic():
                actions, reassigned_count, early_response = (
                    self._build_individual_actions(request)
                )
                if early_response is not None:
                    return early_response
                self._finalize_individual_action(
                    request, record_id, delete_mode, actions, reassigned_count
                )
            return HxTriggerResponse(
                extra="closeModal();closeDeleteModal();closeDeleteModeModal();",
            )
        except Exception as e:
            messages.error(self.request, str(e))
            return ScriptResponse(
                msgs=True,
                reload=True,
                extra="closeDeleteModeModal();",
                status=500,
            )

    def _handle_soft_delete_record(self, request):
        """Soft delete a single dependent record via the recycle bin."""
        record_id_to_delete = request.POST.get("record_id")
        main_record_id = request.POST.get("main_record_id")
        if not record_id_to_delete or not main_record_id:
            return HttpResponse("No record ID or main record ID provided", status=400)
        try:
            with transaction.atomic():
                record_to_delete = self._find_related_record_by_id(record_id_to_delete)
                if record_to_delete:
                    RecycleBin.create_from_instance(
                        record_to_delete,
                        user=request.user if hasattr(request, "user") else None,
                    )
                    record_to_delete.delete()
                    messages.success(
                        request,
                        _("Successfully soft deleted %(record)s.")
                        % {"record": str(record_to_delete)},
                    )
                    return ScriptResponse(msgs=True)
            return HttpResponse("Record not found", status=404)
        except Exception as e:
            logger.error("Soft delete error: %s", str(e))
            messages.error(self.request, str(e))
            return ScriptResponse(
                msgs=True,
                reload=True,
                extra="closeDeleteModeModal();",
                status=500,
            )

    def _handle_delete_single_record(self, request):
        """Hard delete a single dependent record."""
        record_id_to_delete = request.POST.get("record_id")
        main_record_id = request.POST.get("main_record_id")
        if not record_id_to_delete or not main_record_id:
            return HttpResponse("No record ID or main record ID provided", status=400)
        try:
            with transaction.atomic():
                record_to_delete = self._find_related_record_by_id(record_id_to_delete)
                if record_to_delete:
                    record_to_delete.delete()
                    messages.success(
                        request,
                        _("Successfully deleted %(record)s.")
                        % {"record": str(record_to_delete)},
                    )
                    return ScriptResponse(msgs=True)
            return HttpResponse("Record not found", status=404)
        except Exception as e:
            messages.error(self.request, str(e))
            return ScriptResponse(
                msgs=True,
                reload=True,
                extra="closeDeleteModeModal();",
                status=500,
            )

    def _handle_bulk_delete(self, request, delete_mode):
        """Delete all dependent records and the main object."""
        try:
            with transaction.atomic():
                self._bulk_delete_related()
                self._delete_main_object(
                    delete_mode,
                    request.user if hasattr(request, "user") else None,
                )
            messages.success(
                request,
                _("Successfully deleted the %(model)s and all its related records.")
                % {"model": force_str(self.model._meta.verbose_name)},
            )
            return self.get_post_delete_response()
        except Exception as e:
            logger.error("Bulk delete error: %s", str(e))
            messages.error(self.request, str(e))
            return ScriptResponse(
                msgs=True,
                reload=True,
                extra="closeDeleteModeModal();",
                status=500,
            )

    def _handle_simple_delete(self, request, record_id, delete_mode):
        """Delete the main object without touching dependent records."""
        try:
            with transaction.atomic():
                self._delete_main_object(
                    delete_mode,
                    request.user if hasattr(request, "user") else None,
                )
            messages.success(request, self.get_success_message())
            return self.get_post_delete_response()
        except Exception as e:
            logger.error(
                "Simple delete error for %s id %s: %s",
                self.model.__name__,
                record_id,
                str(e),
            )
            messages.info(
                self.request,
                _(
                    "Selected record is not associated with any company. Activate a company to proceed with deletion."
                ),
            )
            return ScriptResponse(reload=True, extra="closeDeleteModeModal();")

    def _set_null_related_record(self, record_id_to_update, excluded_models):
        """Find a related record referencing the main object and null its FK."""
        related_objects = self.model._meta.related_objects
        updated = False
        for related in related_objects:
            related_model = related.related_model
            if related_model in excluded_models:
                continue
            related_name = related.get_accessor_name()
            if related_name and self._is_field_nullable(related_model):
                try:
                    fk_name = related.field.name
                    record_to_update = related_model.objects.get(
                        id=record_id_to_update, **{fk_name: self.object}
                    )
                    field_name = get_fk_field_name(related_model, self.model)
                    if field_name:
                        if getattr(record_to_update, field_name, None):
                            setattr(record_to_update, field_name, None)
                            record_to_update.save()
                            updated = True
                            logger.info(
                                "Set %s to null for %s id %s",
                                field_name,
                                related_model.__name__,
                                record_id_to_update,
                            )
                    break
                except ObjectDoesNotExist:
                    continue
        return updated

    def _render_set_null_response(self, request, main_record_id, delete_mode):
        """Build dependency context after a set-null update and render it."""
        cannot_delete, can_delete, _dependency_details = self._check_dependencies(
            main_record_id
        )
        dep_records, related_model, is_nullable, _has_more_individual = (
            self._dependent_records_from_cannot_delete(cannot_delete)
        )
        available_targets = self.model.objects.exclude(id=main_record_id)
        context = build_dependency_context(
            request,
            self,
            main_record_id,
            cannot_delete,
            can_delete,
            dep_records,
            related_model,
            available_targets,
            is_nullable,
            len(dep_records) > 8 if cannot_delete else False,
            delete_mode,
            request.GET.get("view_id", f"delete_{main_record_id}"),
        )
        if cannot_delete:
            cannot_delete_all, _can_delete_all, _dependency_details = (
                self._check_dependencies(main_record_id, get_all=True)
            )
            (
                all_dep_records,
                _related_model,
                _is_nullable,
                _has_more,
            ) = self._dependent_records_from_cannot_delete(
                cannot_delete_all, limit=None
            )
            context["dependent_records"] = all_dep_records
            context["has_more_individual_records"] = False
            context["selected_ids_json"] = json.dumps([r.id for r in all_dep_records])
            return render(
                request,
                "partials/single_delete/individual_reassign_form.html",
                context,
            )
        return render(
            request,
            "partials/single_delete/delete_dependency_modal.html",
            context,
        )

    def _handle_set_null_action(self, request, delete_mode):
        """Set a dependent record's FK to null and re-render the dependency modal."""
        record_id_to_update = request.POST.get("record_id")
        main_record_id = request.POST.get("main_record_id")
        if not record_id_to_update or not main_record_id:
            return HttpResponse("No record ID provided", status=400)
        try:
            with transaction.atomic():
                self.model.all_objects.get(id=main_record_id)
                excluded_models = self._get_excluded_models()
                updated = self._set_null_related_record(
                    record_id_to_update, excluded_models
                )

                if updated:
                    messages.success(request, _("Successfully set record to null."))

                return self._render_set_null_response(
                    request, main_record_id, delete_mode
                )
        except Exception as e:
            logger.error("Set null action error: %s", str(e))
            messages.error(self.request, str(e))
            return ScriptResponse(
                msgs=True,
                reload=True,
                extra="closeDeleteModeModal();",
                status=500,
            )

    def _handle_delete_fallback(self, request, record_id, delete_mode):
        """Fallback path when no action branch matched: re-check dependencies."""
        cannot_delete, can_delete, _dependency_details = self._check_dependencies(
            record_id
        )
        if not cannot_delete:
            dep_records, related_model = [], None
            available_targets = self.model.objects.exclude(id=record_id)
            context = build_dependency_context(
                request,
                self,
                record_id,
                cannot_delete,
                can_delete,
                dep_records,
                related_model,
                available_targets,
                False,
                False,
                delete_mode,
                request.GET.get("view_id", f"delete_{record_id}"),
            )
            return render(
                request,
                "partials/single_delete/delete_dependency_modal.html",
                context,
            )

        messages.error(self.request, _("Error in delete method"))
        return ScriptResponse(reload=True, extra="closeDeleteModeModal();", close=True)

    def get_post_delete_response(self):
        """Default post-delete behavior."""
        try:
            resolved_url = self.success_url or self.get_success_url()
            if resolved_url:
                return redirect(resolved_url)
        except Exception as e:
            logger.error("Error getting success URL: %s", str(e))
            messages.error(self.request, str(e))
            return ScriptResponse(
                msgs=True, reload=True, extra="closeDeleteModeModal();", status=500
            )
        return HxTriggerResponse(extra="closeDeleteModeModal();")

    def form_valid(self, form):
        """Handle form submission by calling the delete method."""
        return self.delete(self.request, *self.args, **self.kwargs)

    def get_success_message(self):
        """Return the success message for deletion."""
        return self.success_message
